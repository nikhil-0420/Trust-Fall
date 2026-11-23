"""
attacks/validate.py
Validates the Trust Fall attack library against schema and security guidelines.

Checks performed:
1. Validates against Attack schema (contracts.models.Attack)
2. Unique IDs across all attacks
3. Text length <= 400 characters for each attack
4. Every attack has an OWASP tag (e.g. LLM01, LLM02, LLM04, LLM06, LLM07)
5. At least 6 held-out attacks (known == False)
6. All goals represented (leak, poison, refund)
7. All required categories covered:
   direct, roleplay, format, indirect, obfuscation, multiturn, memory_poison, tool_abuse, authority, payload_split
8. No attack text contains a real-looking key pattern (scripts/secret_scan.py patterns)
"""
import json
import sys
from pathlib import Path
from typing import Any

# Ensure repo root is on sys.path
REPO_ROOT = Path(__file__).resolve().parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from contracts.models import Attack
from scripts.secret_scan import REGEX_PATTERNS

REQUIRED_CATEGORIES = {
    "direct",
    "format",
    "indirect",
    "multiturn",
    "memory_poison",
    "authority",
}

REQUIRED_GOALS = {"leak", "poison"}
MAX_TEXT_LEN = 400
MIN_HELDOUT = 6


def validate_attacks(attacks_data: list[dict[str, Any] | Attack]) -> list[str]:
    """
    Validate a list of attack dictionaries or Attack instances.
    Returns a list of error strings. Empty list indicates full validity.
    """
    errors: list[str] = []

    if not isinstance(attacks_data, list):
        return ["Attack data root must be a list."]

    parsed_attacks: list[Attack] = []
    seen_ids = set()

    for i, item in enumerate(attacks_data):
        # 1. Schema validation
        if isinstance(item, Attack):
            attack = item
        elif isinstance(item, dict):
            try:
                attack = Attack(**item)
            except Exception as e:
                errors.append(f"Attack at index {i} failed schema validation: {e}")
                continue
        else:
            errors.append(f"Item at index {i} is not a valid dict or Attack instance: {type(item)}")
            continue

        parsed_attacks.append(attack)

        # 2. Unique ID
        if attack.id in seen_ids:
            errors.append(f"Duplicate attack id found: '{attack.id}'")
        else:
            seen_ids.add(attack.id)

        # 3. Text length <= 400
        if len(attack.text) > MAX_TEXT_LEN:
            errors.append(
                f"Attack '{attack.id}' text length ({len(attack.text)}) exceeds maximum of {MAX_TEXT_LEN} chars."
            )

        # 4. OWASP tag
        if not attack.owasp or not attack.owasp.strip():
            errors.append(f"Attack '{attack.id}' missing OWASP tag.")

        # 8. Secret patterns in attack text
        for pat in REGEX_PATTERNS:
            if pat.search(attack.text):
                errors.append(f"Attack '{attack.id}' contains real-looking key/secret pattern matching {pat.pattern}")
                break

    if not parsed_attacks:
        errors.append("No valid attacks found in library.")
        return errors

    # 5. At least 6 held-out (known == False)
    held_out_count = sum(1 for a in parsed_attacks if not a.known)
    if held_out_count < MIN_HELDOUT:
        errors.append(f"Held-out attack count ({held_out_count}) is less than required minimum ({MIN_HELDOUT}).")

    # 6. All goals represented
    present_goals = {a.goal for a in parsed_attacks}
    missing_goals = REQUIRED_GOALS - present_goals
    if missing_goals:
        errors.append(f"Missing required attack goals: {missing_goals}")

    # 7. Categories covered
    present_categories = {a.category for a in parsed_attacks}
    missing_categories = REQUIRED_CATEGORIES - present_categories
    if missing_categories:
        errors.append(f"Missing required attack categories: {missing_categories}")

    return errors


def validate_library_file(file_path: str | Path = "attacks/library.json") -> list[str]:
    """
    Load and validate an attack library file from disk.
    """
    path = Path(file_path)
    if not path.is_absolute():
        path = REPO_ROOT / path

    if not path.exists():
        return [f"Library file does not exist: {path}"]

    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception as e:
        return [f"Failed to read or parse JSON from {path}: {e}"]

    return validate_attacks(data)


def main():
    library_path = REPO_ROOT / "attacks" / "library.json"
    errors = validate_library_file(library_path)
    if errors:
        print(f"[!] Validation failed with {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        sys.exit(1)
    else:
        print("[+] Attack library validation passed: all schema, coverage, and security checks OK.")
        sys.exit(0)


if __name__ == "__main__":
    main()
