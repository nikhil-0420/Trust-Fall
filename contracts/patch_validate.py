"""
Owner: Nikhil (Phase N5)
Patch validation and safety engine.
Validates patch dictionaries against strict safety rules, schemas, and regex performance guards.
Pure function, offline, no network.
"""
import re
from typing import Any

from agents.policy import NESTED_QUANTIFIER_REGEX, safe_regex_search
from contracts.models import Patch

ALLOWED_TOP_KEYS = {
    "version",
    "memory_write_rules",
    "tool_policy",
    "gate",
    "notes",
}

CATASTROPHIC_TEST_STRING = ("a" * 2048) + "X"
TRIVIAL_WILDCARDS = {".*", ".+", "^.*$", "^.+$", ".*?", ".+?", ""}


def validate_patch(patch: Any) -> tuple[bool, list[str], Patch | None]:
    """
    Validates a patch dictionary according to safety rules:
    - Must be a dictionary.
    - Only known keys permitted.
    - Version must be integer >= 1.
    - Regex patterns must compile, run in under 50ms on a 2KB adversarial test string,
      and cannot be trivial wildcards matching everything.
    - memory_write_rules: max_len in [20, 500], note_format in {"fact_only"}.
    - tool_policy: redact_patterns max 20 entries, each under 200 chars.
    - gate: threshold in [0.05, 0.95].
    Returns (ok: bool, errors: list[str], normalized: Optional[Patch]).
    """
    errors: list[str] = []

    if not isinstance(patch, dict):
        return False, ["Patch must be a JSON dictionary"], None

    # Check for unknown keys
    unknown_keys = set(patch.keys()) - ALLOWED_TOP_KEYS
    if unknown_keys:
        errors.append(f"Unknown top-level keys in patch: {sorted(list(unknown_keys))}")

    # Version check
    version = patch.get("version")
    if version is None or not isinstance(version, int) or version < 1:
        errors.append("Patch 'version' must be an integer >= 1")

    # Gate checks
    gate = patch.get("gate")
    if gate is not None:
        if not isinstance(gate, dict):
            errors.append("'gate' must be a dictionary")
        else:
            threshold = gate.get("threshold")
            if threshold is not None:
                if not isinstance(threshold, (int, float)) or not (0.05 <= float(threshold) <= 0.95):
                    errors.append(f"gate.threshold {threshold} must be between 0.05 and 0.95")

    # Memory write rules checks
    mem_rules = patch.get("memory_write_rules")
    if mem_rules is not None:
        if not isinstance(mem_rules, dict):
            errors.append("'memory_write_rules' must be a dictionary")
        else:
            max_len = mem_rules.get("max_len")
            if max_len is not None:
                if not isinstance(max_len, int) or not (20 <= max_len <= 500):
                    errors.append(f"memory_write_rules.max_len {max_len} must be an integer between 20 and 500")

            note_format = mem_rules.get("note_format")
            if note_format is not None and note_format != "fact_only":
                errors.append(f"memory_write_rules.note_format '{note_format}' must be 'fact_only' or absent")

            deny_patterns = mem_rules.get("deny_patterns", [])
            if not isinstance(deny_patterns, list):
                errors.append("memory_write_rules.deny_patterns must be a list of regex strings")
            else:
                for idx, pat in enumerate(deny_patterns):
                    if not isinstance(pat, str):
                        errors.append(f"deny_patterns[{idx}] must be a string")
                        continue
                    if pat.strip() in TRIVIAL_WILDCARDS:
                        errors.append(f"deny_patterns[{idx}] '{pat}' matches everything and is rejected")
                        continue
                    try:
                        re.compile(pat)
                    except re.error as e:
                        errors.append(f"deny_patterns[{idx}] failed to compile: {e}")
                        continue

                    # Check catastrophic backtracking
                    if NESTED_QUANTIFIER_REGEX.search(pat):
                        timed_out = not safe_regex_search(pat, CATASTROPHIC_TEST_STRING, timeout=0.05)
                        if timed_out:
                            errors.append(f"deny_patterns[{idx}] '{pat}' exceeded 50ms regex timeout guard (catastrophic backtracking)")

    # Tool policy checks
    tool_policy = patch.get("tool_policy")
    if tool_policy is not None:
        if not isinstance(tool_policy, dict):
            errors.append("'tool_policy' must be a dictionary")
        else:
            send_rep = tool_policy.get("send_report")
            if send_rep is not None and isinstance(send_rep, dict):
                redact_known_secrets = send_rep.get("redact_known_secrets")
                if redact_known_secrets is not None and not isinstance(redact_known_secrets, bool):
                    errors.append("tool_policy.send_report.redact_known_secrets must be a boolean")
                tolerant_format = send_rep.get("tolerant_format")
                if tolerant_format is not None:
                    if not isinstance(tolerant_format, str):
                        errors.append("tool_policy.send_report.tolerant_format must be a string")
                    elif len(tolerant_format) > 200:
                        errors.append(f"tolerant_format length {len(tolerant_format)} exceeds limit 200")
                redact_patterns = send_rep.get("redact_patterns", [])
                if not isinstance(redact_patterns, list):
                    errors.append("tool_policy.send_report.redact_patterns must be a list of strings")
                else:
                    if len(redact_patterns) > 20:
                        errors.append(f"redact_patterns length {len(redact_patterns)} exceeds maximum of 20")
                    for idx, pat in enumerate(redact_patterns):
                        if not isinstance(pat, str):
                            errors.append(f"redact_patterns[{idx}] must be a string")
                            continue
                        if len(pat) > 200:
                            errors.append(f"redact_patterns[{idx}] length {len(pat)} exceeds limit 200")
                            continue
                        if pat.strip() in TRIVIAL_WILDCARDS:
                            errors.append(f"redact_patterns[{idx}] '{pat}' matches everything and is rejected")
                            continue
                        try:
                            re.compile(pat)
                        except re.error as e:
                            errors.append(f"redact_patterns[{idx}] failed to compile: {e}")
                            continue

                        # Check catastrophic backtracking
                        if NESTED_QUANTIFIER_REGEX.search(pat):
                            timed_out = not safe_regex_search(pat, CATASTROPHIC_TEST_STRING, timeout=0.05)
                            if timed_out:
                                errors.append(f"redact_patterns[{idx}] '{pat}' exceeded 50ms regex timeout guard (catastrophic backtracking)")

    if errors:
        return False, errors, None

    try:
        normalized = Patch(**patch)
        return True, [], normalized
    except Exception as e:
        return False, [f"Pydantic validation failed: {e}"], None
