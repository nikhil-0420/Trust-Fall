"""
tests/arena/test_red.py
Unit tests for AdaptiveRed adversary attack selection and mutation logic.
Owner: Nehaa (WS-B1 B1.2)
"""
import copy
import json
from pathlib import Path
import pytest

from agents.red import AdaptiveRed
from arena.budget_hooks import LocalBudget
from arena.interfaces import LLM
from contracts.models import Attack


@pytest.fixture
def library():
    lib_path = Path("attacks/library.json")
    with open(lib_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [Attack.model_validate(item) for item in data]


@pytest.mark.asyncio
async def test_reproducible_output(library):
    red = AdaptiveRed(attacks_per_round=6)
    history = []

    res1 = await red.next_attacks("R0", library, history)
    res2 = await red.next_attacks("R0", library, history)

    assert [a.id for a in res1] == [a.id for a in res2]


@pytest.mark.asyncio
async def test_r1_prefers_non_blocked_categories(library):
    red = AdaptiveRed(attacks_per_round=6)

    # Simulate R0 where blunt categories (direct, roleplay, authority) were blocked
    history_r0 = [
        {"id": "A01", "category": "direct", "outcome": "blocked_by_gate"},
        {"id": "A02", "category": "roleplay", "outcome": "blocked_by_gate"},
        {"id": "A03", "category": "authority", "outcome": "blocked_by_gate"},
    ]

    r1_attacks = await red.next_attacks("R1", library, history_r0)
    r1_categories = [a.category for a in r1_attacks]

    # Non-blocked categories should appear first
    assert r1_categories[0] not in ("direct", "roleplay", "authority")


@pytest.mark.asyncio
async def test_r2_includes_earlier_successes_and_heldout_only(library):
    red = AdaptiveRed(attacks_per_round=6)

    history = [
        {"id": "A04", "category": "memory_poison", "outcome": "succeeded", "known": True},
        {"id": "A05", "category": "obfuscation", "outcome": "succeeded", "known": True},
        {"id": "A01", "category": "direct", "outcome": "blocked_by_gate", "known": True},
    ]

    r2_attacks = await red.next_attacks("R2", library, history)

    known_in_r2 = [a for a in r2_attacks if a.known]
    heldout_in_r2 = [a for a in r2_attacks if not a.known]

    # Successful known attacks must be present
    known_ids = {a.id for a in known_in_r2}
    assert "A04" in known_ids
    assert "A05" in known_ids
    assert "A01" not in known_ids  # Failed attack excluded

    # ALL held-out attacks must be present in R2
    total_heldout_in_lib = len([a for a in library if not a.known])
    assert len(heldout_in_r2) == total_heldout_in_lib


@pytest.mark.asyncio
async def test_heldout_texts_never_appear_in_r0_or_r1(library):
    red = AdaptiveRed(attacks_per_round=8)
    heldout_ids = {a.id for a in library if not a.known}

    r0_attacks = await red.next_attacks("R0", library, [])
    r1_attacks = await red.next_attacks("R1", library, [])

    assert not any(a.id in heldout_ids for a in r0_attacks)
    assert not any(a.id in heldout_ids for a in r1_attacks)


@pytest.mark.asyncio
async def test_mutation_calls_capped_and_safety_filtered(library):
    class MockMutateLLM(LLM):
        def __init__(self, output: str):
            self.output = output
            self.call_count = 0

        async def complete(self, system: str, prompt: str, *, purpose: str, json_mode: bool = False) -> str:
            self.call_count += 1
            return self.output

    # Safe mutation test
    safe_llm = MockMutateLLM("Subtle indirect injection requesting canary code")
    red_safe = AdaptiveRed(llm=safe_llm, enable_mutation=True, attacks_per_round=4)
    history = [{"id": "A01", "category": "direct", "outcome": "blocked_by_gate", "text": "Canary override"}]

    r1_attacks = await red_safe.next_attacks("R1", library, history)
    assert safe_llm.call_count == 1
    mutated = next((a for a in r1_attacks if a.id.startswith("M-")), None)
    assert mutated is not None
    assert mutated.known is True

    # Mutated call is capped at 1
    await red_safe.next_attacks("R1", library, history)
    assert safe_llm.call_count == 1  # Still 1

    # Unsafe mutation containing API key pattern or URL is discarded
    unsafe_key = "AI" + "za" + "SyD_fakeKey1234567890123456789012345"
    unsafe_llm = MockMutateLLM(unsafe_key)
    red_unsafe = AdaptiveRed(llm=unsafe_llm, enable_mutation=True, attacks_per_round=4)
    r1_unsafe = await red_unsafe.next_attacks("R1", library, history)
    assert not any(a.id.startswith("M-") for a in r1_unsafe)


@pytest.mark.asyncio
async def test_library_not_mutated_in_place(library):
    library_snapshot = copy.deepcopy(library)
    red = AdaptiveRed(attacks_per_round=6)

    await red.next_attacks("R0", library, [])
    await red.next_attacks("R1", library, [{"id": "A01", "outcome": "blocked_by_gate"}])
    await red.next_attacks("R2", library, [{"id": "A04", "outcome": "succeeded"}])

    assert [a.model_dump() for a in library] == [a.model_dump() for a in library_snapshot]
