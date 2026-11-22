"""
Tests for patch validation logic in contracts/patch_validate.py.
Verifies acceptance of good patches and rejection of:
- unknown keys
- non-compiling regex
- catastrophic regex ((a+)+$)
- trivial wildcards (".*")
- threshold out of range
- max_len out of range
"""
import pytest
from contracts.patch_validate import validate_patch


@pytest.fixture
def valid_base_patch() -> dict:
    return {
        "version": 1,
        "memory_write_rules": {
            "deny_patterns": ["(?i)ignore .* instructions"],
            "max_len": 120,
            "note_format": "fact_only",
        },
        "tool_policy": {
            "send_report": {
                "redact_patterns": ["CANARY-[A-Za-z0-9]+-DEMO-ONLY"]
            },
            "write_memory": {"allowed": True},
        },
        "gate": {
            "screen_tool_outputs": True,
            "screen_memory_reads": True,
            "threshold": 0.35,
        },
        "notes": "Valid test patch",
    }


def test_validator_accepts_good_patch(valid_base_patch: dict):
    ok, errors, patch_obj = validate_patch(valid_base_patch)
    assert ok is True
    assert len(errors) == 0
    assert patch_obj is not None
    assert patch_obj.version == 1
    assert patch_obj.gate.threshold == 0.35


def test_validator_rejects_unknown_keys(valid_base_patch: dict):
    bad = dict(valid_base_patch)
    bad["unexpected_extra_key"] = "malicious_content"
    ok, errors, _ = validate_patch(bad)
    assert ok is False
    assert any("Unknown top-level keys" in e for e in errors)


def test_validator_rejects_non_compiling_regex(valid_base_patch: dict):
    bad = dict(valid_base_patch)
    bad["memory_write_rules"] = {
        "deny_patterns": ["[invalid regex (("],
        "max_len": 100,
    }
    ok, errors, _ = validate_patch(bad)
    assert ok is False
    assert any("failed to compile" in e for e in errors)


def test_validator_rejects_catastrophic_regex(valid_base_patch: dict):
    bad = dict(valid_base_patch)
    bad["memory_write_rules"] = {
        "deny_patterns": [r"(a+)+$"],
        "max_len": 100,
    }
    ok, errors, _ = validate_patch(bad)
    assert ok is False
    assert any("catastrophic backtracking" in e for e in errors)


def test_validator_rejects_trivial_wildcards(valid_base_patch: dict):
    bad = dict(valid_base_patch)
    bad["tool_policy"] = {
        "send_report": {"redact_patterns": [".*"]}
    }
    ok, errors, _ = validate_patch(bad)
    assert ok is False
    assert any("matches everything and is rejected" in e for e in errors)


def test_validator_rejects_threshold_out_of_range(valid_base_patch: dict):
    # Too high (> 0.95)
    bad_high = dict(valid_base_patch)
    bad_high["gate"] = {"threshold": 1.2}
    ok_h, errors_h, _ = validate_patch(bad_high)
    assert ok_h is False
    assert any("threshold" in e for e in errors_h)

    # Too low (< 0.05)
    bad_low = dict(valid_base_patch)
    bad_low["gate"] = {"threshold": 0.01}
    ok_l, errors_l, _ = validate_patch(bad_low)
    assert ok_l is False
    assert any("threshold" in e for e in errors_l)


def test_validator_rejects_max_len_out_of_range(valid_base_patch: dict):
    # Too small (< 20)
    bad_small = dict(valid_base_patch)
    bad_small["memory_write_rules"] = {"max_len": 5}
    ok_s, errors_s, _ = validate_patch(bad_small)
    assert ok_s is False
    assert any("max_len" in e for e in errors_s)

    # Too large (> 500)
    bad_large = dict(valid_base_patch)
    bad_large["memory_write_rules"] = {"max_len": 1000}
    ok_l, errors_l, _ = validate_patch(bad_large)
    assert ok_l is False
    assert any("max_len" in e for e in errors_l)
