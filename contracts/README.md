# Contracts & Patch Validator Documentation

## Overview
This directory contains frozen contracts (`contracts/models.py`), exported JSON schemas (`contracts/schemas/`), and the patch validation engine (`contracts/patch_validate.py`).

---

## Patch Validation Rules (`contracts/patch_validate.py`)

The function `validate_patch(patch: dict) -> (ok: bool, errors: list[str], normalized: Optional[Patch])` is the formal contract used by the Referee before applying any defensive patch proposed by Blue.

### Validation Rules and Rejection Criteria:

1. **Top-Level Key Whitelist:**
   - Allowed keys: `version`, `memory_write_rules`, `tool_policy`, `gate`, `notes`.
   - **Rejection reason:** Unknown or unexpected keys are rejected to prevent configuration pollution or schema evasion.

2. **Version Increments:**
   - `version` must be an integer >= 1.
   - **Rejection reason:** Invalid, zero, or negative version numbers prevent deterministic rollback and patch lineage tracking.

3. **Memory Write Rules:**
   - `max_len`: Must be an integer between 20 and 500 characters.
     - **Rejection reason:** Below 20 prevents storing useful context; above 500 increases prompt injection exposure.
   - `note_format`: Must be `"fact_only"` or omitted.
     - **Rejection reason:** Ensures notes cannot contain imperative commands ("always", "from now on", "ignore").
   - `deny_patterns`: List of regex strings.
     - **Rejection reason:** Any non-compiling regex or trivial wildcard matching everything (e.g. `.*`, `.+`) is rejected.

4. **Regex Safety & Performance Guard:**
   - All regexes in `deny_patterns` and `redact_patterns` are pre-tested against a 2 KB adversarial string.
   - **Rejection reason:** Any pattern taking > 50 ms (catastrophic backtracking, ReDoS such as `(a+)+$`) is strictly rejected.

5. **Tool Policy (Redaction Rules):**
   - `redact_patterns`: Maximum of 20 patterns, each at most 200 characters in length.
   - **Rejection reason:** Prevents regex execution bloat and overly broad matching. Patterns matching everything (e.g. `.*`) are rejected to protect benign ticket vocabulary.

6. **Gate Thresholds:**
   - `gate.threshold`: Float between 0.05 and 0.95.
   - **Rejection reason:** Extreme values (0.0 or 1.0) either block everything or disable protection entirely.
