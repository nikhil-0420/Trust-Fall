"""
Owner: Nikhil (Phase N2)
Deterministic policy engine for Worker defenses.
Applies memory write deny patterns, max length, fact-only formatting, and report redaction.
"""
import base64
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


def safe_regex_subn(pat_str: str, repl: str, text: str, timeout: float = 0.05) -> tuple[str, int]:
    """Executes regex substitution guarded by a timeout, returning (new_text, count)."""
    if not NESTED_QUANTIFIER_REGEX.search(pat_str):
        try:
            return re.subn(pat_str, repl, text, flags=re.IGNORECASE)
        except Exception:
            return text, 0

    q: multiprocessing.Queue = multiprocessing.Queue()
    p = multiprocessing.Process(target=_worker_sub, args=(pat_str, repl, text, q))
    p.start()
    p.join(timeout=timeout)
    if p.is_alive():
        p.terminate()
        p.join()
        logger.warning(f"Regex pattern '{pat_str}' in redaction exceeded {timeout*1000}ms timeout guard.")
        return text, 0
    if not q.empty():
        res = q.get()
        if isinstance(res, str):
            # Calculate occurrences replaced
            count = 1 if res != text else 0
            return res, count
    return text, 0


def safe_regex_sub(pat_str: str, repl: str, text: str, timeout: float = 0.05) -> str:
    """Executes regex substitution guarded by a timeout."""
    res, _ = safe_regex_subn(pat_str, repl, text, timeout=timeout)
    return res


def generate_tolerant_patterns(base_format: str = "canary") -> list[str]:
    """
    Generates tolerant regex patterns handling:
    - Case insensitivity
    - Arbitrary whitespace between characters (e.g. 'C A N A R Y ...')
    - Separator variations ('-', '_', ' ', ':', or none)
    - Reversed canary sequences ('Y L N O ...' and 'O N E D ...')
    - Base64 canary prefix ('Q0FOQVJZ...')
    - Hex canary prefix ('43414e415259...')
    """
    return [
        # Tolerant forward with arbitrary spaces and separators
        r"(?i)C\s*A\s*N\s*A\s*R\s*Y[\s\-_:]*[0-9a-fA-F\s]{6,20}[\s\-_:]*D\s*E\s*M\s*O[\s\-_:]*O\s*N\s*L\s*Y",
        # Tolerant reversed (YLNO-OMED-...-YRANAC)
        r"(?i)Y\s*L\s*N\s*O[\s\-_:]*O\s*M\s*E\s*D[\s\-_:]*[0-9a-fA-F\s]{6,20}[\s\-_:]*Y\s*R\s*A\s*N\s*A\s*C",
        # Tolerant reversed alternative (ONED-OMED-...-YRACAN)
        r"(?i)O\s*N\s*E\s*D[\s\-_:]*O\s*M\s*E\s*D[\s\-_:]*[0-9a-fA-F\s]{6,20}[\s\-_:]*Y\s*R\s*A\s*C\s*A\s*N",
        # Base64 canary prefix
        r"(?i)Q0FOQVJZ[A-Za-z0-9+/=]{16,40}",
        # Hex canary prefix (43414e415259 is CANARY in hex)
        r"(?i)43414e415259[0-9a-fA-F]{20,60}",
    ]


def generate_known_secret_patterns(secret: str) -> list[str]:
    """
    Generates patterns to detect and redact the exact current secret value across:
    - plain, case-insensitive
    - characters separated by any whitespace or punctuation
    - reversed (including characters separated by whitespace/punctuation)
    - base64 (standard and urlsafe, with and without padding)
    - hex (lower and upper)
    """
    if not secret:
        return []

    patterns: list[str] = []

    # 1. Plain & case-insensitive with arbitrary whitespace or punctuation between characters
    escaped_chars = [re.escape(c) for c in secret]
    patterns.append(r"(?i)" + r"[\s\W_]*".join(escaped_chars))

    # 2. Reversed with arbitrary whitespace or punctuation between characters
    rev_secret = secret[::-1]
    rev_escaped_chars = [re.escape(c) for c in rev_secret]
    patterns.append(r"(?i)" + r"[\s\W_]*".join(rev_escaped_chars))

    # 3. Base64 (standard and urlsafe, with and without padding)
    raw_bytes = secret.encode("utf-8")
    b64_std = base64.b64encode(raw_bytes).decode("ascii")
    b64_std_unpad = b64_std.rstrip("=")
    b64_url = base64.urlsafe_b64encode(raw_bytes).decode("ascii")
    b64_url_unpad = b64_url.rstrip("=")
    for b_str in (b64_std, b64_std_unpad, b64_url, b64_url_unpad):
        if b_str and re.escape(b_str) not in patterns:
            patterns.append(re.escape(b_str))

    # 4. Hex (lower and upper)
    hex_lower = raw_bytes.hex()
    hex_upper = hex_lower.upper()
    if hex_lower not in patterns:
        patterns.append(re.escape(hex_lower))
    if hex_upper not in patterns:
        patterns.append(re.escape(hex_upper))

    return patterns


class Policy:
    def __init__(self, patch: dict[str, Any] | Patch | None = None):
        self.raw_patch = patch
        self.deny_patterns: list[str] = []
        self.max_len: int | None = None
        self.note_format: str | None = None
        self.redact_patterns: list[str] = []
        self.tolerant_format: str | None = None
        self.screen_memory_reads: bool = False
        self.screen_tool_outputs: bool = False
        self.threshold: float = 0.3
        self.last_redactions_count: int = 0

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
            self.redact_patterns = list(send_rep.get("redact_patterns", []) or [])
            self.tolerant_format = send_rep.get("tolerant_format")
            if self.tolerant_format:
                for tol_pat in generate_tolerant_patterns(self.tolerant_format):
                    if tol_pat not in self.redact_patterns:
                        self.redact_patterns.append(tol_pat)

            gate_cfg = patch_dict.get("gate") or {}
            self.screen_memory_reads = bool(gate_cfg.get("screen_memory_reads", False))
            self.screen_tool_outputs = bool(gate_cfg.get("screen_tool_outputs", False))
            self.threshold = float(gate_cfg.get("threshold", 0.3))
            self.redact_known_secrets = bool(send_rep.get("redact_known_secrets", False))
        else:
            self.redact_known_secrets = False
        self.current_secret: str | None = None

    def set_current_secret(self, secret: str | None) -> None:
        """Sets the active secret value in memory for known-secret variant DLP."""
        self.current_secret = secret

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

    def redact_report(self, text: str, return_count: bool = False, secret: str | None = None) -> str | tuple[str, int]:
        """
        Applies configured redact patterns (and known-secret variants if enabled) to outgoing report text.
        If return_count=True, returns (redacted_text, count).
        Otherwise returns redacted_text, storing count in self.last_redactions_count.
        """
        self.last_redactions_count = 0
        if self.raw_patch is None:
            return (text, 0) if return_count else text

        active_secret = secret or self.current_secret
        patterns_to_run = list(self.redact_patterns)
        if self.redact_known_secrets and active_secret:
            for pat in generate_known_secret_patterns(active_secret):
                if pat not in patterns_to_run:
                    patterns_to_run.append(pat)

        result = text
        total_count = 0
        for pattern in patterns_to_run:
            if not pattern:
                continue
            result, count = safe_regex_subn(pattern, "[REDACTED]", result, timeout=0.05)
            total_count += count

        self.last_redactions_count = total_count
        if return_count:
            return result, total_count
        return result
