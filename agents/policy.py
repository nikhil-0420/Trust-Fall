"""
Owner: Nikhil (Phase N2)
Deterministic policy engine for Worker defenses.
Applies memory write deny patterns, max length, fact-only formatting, and report redaction.
"""
import logging
import multiprocessing
import re
from typing import Any

from contracts.models import Patch

logger = logging.getLogger(__name__)

INSTRUCTION_PHRASES = [
    "always",
    "from now on",
    "ignore",
    "you must",
    "do not",
    "never",
    "remember to",
    "system:",
    "disregard",
    "override",
]

IMPERATIVE_START_REGEX = re.compile(
    r"^(always|ignore|disregard|forget|remember|set|override|do|never|from now on)\b",
    re.IGNORECASE,
)


NESTED_QUANTIFIER_REGEX = re.compile(r"(\([^)]*[\+\*][^)]*\))[\+\*]")


def _worker_search(pat_str: str, text: str, q: Any) -> None:
    try:
        compiled = re.compile(pat_str, re.IGNORECASE)
        m = compiled.search(text)
        q.put(bool(m))
    except Exception as e:
        q.put(e)


def _worker_sub(pat_str: str, repl: str, text: str, q: Any) -> None:
    try:
        compiled = re.compile(pat_str, re.IGNORECASE)
        res = compiled.sub(repl, text)
        q.put(res)
    except Exception as e:
        q.put(e)


def safe_regex_search(pat_str: str, text: str, timeout: float = 0.05) -> bool:
    """Executes a regex search guarded by a timeout (default 50 ms)."""
    # If pattern does not have nested quantifiers, execute directly with timing
    if not NESTED_QUANTIFIER_REGEX.search(pat_str):
        try:
            return bool(re.search(pat_str, text, re.IGNORECASE))
        except Exception:
            return False

    q: multiprocessing.Queue = multiprocessing.Queue()
    p = multiprocessing.Process(target=_worker_search, args=(pat_str, text, q))
    p.start()
    p.join(timeout=timeout)
    if p.is_alive():
        p.terminate()
        p.join()
        logger.warning(f"Regex pattern '{pat_str}' exceeded {timeout*1000}ms timeout guard and was skipped.")
        return False
    if not q.empty():
        res = q.get()
        if isinstance(res, Exception):
            return False
        return bool(res)
    return False


def safe_regex_sub(pat_str: str, repl: str, text: str, timeout: float = 0.05) -> str:
    """Executes regex substitution guarded by a timeout."""
    if not NESTED_QUANTIFIER_REGEX.search(pat_str):
        try:
            return re.sub(pat_str, repl, text, flags=re.IGNORECASE)
        except Exception:
            return text

    q: multiprocessing.Queue = multiprocessing.Queue()
    p = multiprocessing.Process(target=_worker_sub, args=(pat_str, repl, text, q))
    p.start()
    p.join(timeout=timeout)
    if p.is_alive():
        p.terminate()
        p.join()
        logger.warning(f"Regex pattern '{pat_str}' in redaction exceeded {timeout*1000}ms timeout guard.")
        return text
    if not q.empty():
        res = q.get()
        if isinstance(res, str):
            return res
    return text


class Policy:
    def __init__(self, patch: dict[str, Any] | Patch | None = None):
        self.raw_patch = patch
        self.deny_patterns: list[str] = []
        self.max_len: int | None = None
        self.note_format: str | None = None
        self.redact_patterns: list[str] = []
        self.screen_memory_reads: bool = False
        self.screen_tool_outputs: bool = False
        self.threshold: float = 0.3

        if patch is not None:
            if isinstance(patch, Patch):
                patch_dict = patch.model_dump()
            elif isinstance(patch, dict):
                patch_dict = patch
            else:
                patch_dict = {}

            mem_rules = patch_dict.get("memory_write_rules") or {}
            self.deny_patterns = mem_rules.get("deny_patterns", []) or []
            self.max_len = mem_rules.get("max_len")
            self.note_format = mem_rules.get("note_format")

            tool_policy = patch_dict.get("tool_policy") or {}
            send_rep = tool_policy.get("send_report") or {}
            self.redact_patterns = send_rep.get("redact_patterns", []) or []

            gate_cfg = patch_dict.get("gate") or {}
            self.screen_memory_reads = bool(gate_cfg.get("screen_memory_reads", False))
            self.screen_tool_outputs = bool(gate_cfg.get("screen_tool_outputs", False))
            self.threshold = float(gate_cfg.get("threshold", 0.3))

    def allow_memory_write(self, text: str) -> tuple[bool, str]:
        """
        Determines if a memory note write is permitted.
        Returns (allowed: bool, reason: str).
        """
        if self.raw_patch is None:
            return True, ""

        # Check max length
        if self.max_len is not None and len(text) > self.max_len:
            return False, f"Length {len(text)} exceeds limit {self.max_len}"

        # Check note_format == 'fact_only'
        if self.note_format == "fact_only":
            lower_text = text.lower().strip()
            # Imperative start check
            if IMPERATIVE_START_REGEX.search(lower_text):
                return False, "Imperative note rejected under fact_only policy"

            for phrase in INSTRUCTION_PHRASES:
                if phrase in lower_text:
                    return False, f"Instruction phrase '{phrase}' prohibited under fact_only policy"

        # Check deny patterns
        for pattern in self.deny_patterns:
            if not pattern:
                continue
            if safe_regex_search(pattern, text, timeout=0.05):
                return False, f"Matched deny pattern: {pattern}"

        return True, ""

    def redact_report(self, text: str) -> str:
        """Applies configured redact patterns to outgoing report text."""
        if self.raw_patch is None:
            return text

        result = text
        for pattern in self.redact_patterns:
            if not pattern:
                continue
            result = safe_regex_sub(pattern, "[REDACTED]", result, timeout=0.05)
        return result
