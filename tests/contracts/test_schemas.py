"""
Tests that validate mock data files against Pydantic models and exported JSON Schemas.
"""
import json
from pathlib import Path
import pytest
import jsonschema

from contracts.models import Attack, Event, Patch, Results

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MOCK_DIR = REPO_ROOT / "data" / "mock"
SCHEMAS_DIR = REPO_ROOT / "contracts" / "schemas"
ATTACKS_DIR = REPO_ROOT / "attacks"


def load_json(path: Path):
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def test_results_mock_validation():
    results_path = MOCK_DIR / "results.json"
    assert results_path.exists(), "results.json missing"
    data = load_json(results_path)

    # 1. Pydantic validation
    model = Results.model_validate(data)
    assert model.sample is True
    assert len(model.rounds) == 3
    assert model.rounds[0].asr == 0.8
    assert model.rounds[1].asr == 0.5
    assert model.rounds[2].asr == 0.15

    # 2. JSON Schema validation
    schema = load_json(SCHEMAS_DIR / "results.schema.json")
    jsonschema.validate(instance=data, schema=schema)


@pytest.mark.parametrize("round_id", ["R0", "R1", "R2"])
def test_events_mock_validation(round_id):
    events_path = MOCK_DIR / f"events-{round_id}.json"
    assert events_path.exists(), f"events-{round_id}.json missing"
    events_list = load_json(events_path)
    assert len(events_list) >= 20, "Should have ~25 events"

    schema = load_json(SCHEMAS_DIR / "event.schema.json")

    # Validate every single event
    for raw_event in events_list:
        Event.model_validate(raw_event)
        jsonschema.validate(instance=raw_event, schema=schema)


def test_attacks_library_validation():
    library_path = ATTACKS_DIR / "library.json"
    assert library_path.exists(), "library.json missing"
    attacks_list = load_json(library_path)
    assert len(attacks_list) >= 6, "Expected at least 6 attacks"

    schema = load_json(SCHEMAS_DIR / "attack.schema.json")
    for raw_attack in attacks_list:
        attack = Attack.model_validate(raw_attack)
        assert len(attack.text) <= 500
        jsonschema.validate(instance=raw_attack, schema=schema)


def test_patches_in_results_validation():
    results_path = MOCK_DIR / "results.json"
    data = load_json(results_path)
    schema = load_json(SCHEMAS_DIR / "patch.schema.json")

    for p in data.get("patches", []):
        if p.get("patch"):
            Patch.model_validate(p["patch"])
            jsonschema.validate(instance=p["patch"], schema=schema)
