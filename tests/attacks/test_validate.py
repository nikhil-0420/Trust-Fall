"""
Unit tests for attack library validation (WS-B1 B1.1 / H1.3).
Covers:
- library.json passes validation cleanly
- duplicate id detection
- text length > 400 chars rejection
- missing OWASP tag rejection
- insufficient held-out count rejection (< 6)
- missing required goal detection
- missing required category detection
- secret/key pattern detection (scripts/secret_scan.py patterns)
"""
import copy
import json
from pathlib import Path

import pytest

from attacks.validate import (
    validate_attacks,
    validate_library_file,
)


@pytest.fixture
def valid_library_data():
    lib_path = Path("attacks/library.json")
    assert lib_path.exists(), "attacks/library.json must exist"
    return json.loads(lib_path.read_text(encoding="utf-8"))


def test_library_json_is_valid():
    """Verify that the actual attacks/library.json passes all validations."""
    errors = validate_library_file("attacks/library.json")
    assert errors == [], f"Validation errors found: {errors}"


def test_duplicate_id_fails(valid_library_data):
    data = copy.deepcopy(valid_library_data)
    data.append(copy.deepcopy(data[0]))  # Duplicate A01
    errors = validate_attacks(data)
    assert any("Duplicate attack id" in e for e in errors)


def test_text_length_exceeded_fails(valid_library_data):
    data = copy.deepcopy(valid_library_data)
    data[0]["text"] = "A" * 401
    errors = validate_attacks(data)
    assert any("exceeds maximum of 400 chars" in e for e in errors)


def test_missing_owasp_tag_fails(valid_library_data):
    data = copy.deepcopy(valid_library_data)
    data[0]["owasp"] = ""
    errors = validate_attacks(data)
    assert any("missing OWASP tag" in e for e in errors)


def test_insufficient_heldout_fails(valid_library_data):
    data = copy.deepcopy(valid_library_data)
    # Set all attacks to known=True
    for a in data:
        a["known"] = True
    errors = validate_attacks(data)
    assert any("Held-out attack count" in e for e in errors)


def test_missing_goal_fails(valid_library_data):
    data = copy.deepcopy(valid_library_data)
    # Remove all poison attacks (which is a required goal)
    data = [a for a in data if a["goal"] != "poison"]
    errors = validate_attacks(data)
    assert any("Missing required attack goals" in e for e in errors)


def test_missing_category_fails(valid_library_data):
    data = copy.deepcopy(valid_library_data)
    # Replace category of indirect with direct
    for a in data:
        if a["category"] == "indirect":
            a["category"] = "direct"
    errors = validate_attacks(data)
    assert any("Missing required attack categories" in e for e in errors)


def test_secret_pattern_detected(valid_library_data):
    data = copy.deepcopy(valid_library_data)
    # Dynamically construct synthetic test key to test scanner without hardcoding in source
    synthetic_key = "s" + "k-" + ("a" * 25)
    data[0]["text"] = f"Use this token {synthetic_key} to bypass checks"
    errors = validate_attacks(data)
    assert any("contains real-looking key/secret pattern" in e for e in errors)


def test_nonexistent_file():
    errors = validate_library_file("nonexistent/path/library.json")
    assert any("does not exist" in e for e in errors)
