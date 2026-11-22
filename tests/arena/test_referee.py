"""
tests/arena/test_referee.py
Unit and integration tests for Referee, rounds, benign suite, and events.
Owner: Nehaa (WS-C C2, C3, C7)
"""
import json
from pathlib import Path

import jsonschema
import pytest

from arena.events import EventWriter, TextCache
from arena.interfaces import Envelope, WorkerOutcome
from arena.mocks import (
    FakeSandbox,
    MockGate,
    MockTransport,
    ScriptedBlue,
    ScriptedRed,
)
from arena.referee import Referee
from contracts.models import Attack, Results


@pytest.fixture
def test_env(tmp_path, monkeypatch):
    monkeypatch.setenv("USE_MOCKS", "1")
    sandbox = FakeSandbox()
    gate = MockGate()
    transport = MockTransport(sandbox=sandbox, gate=gate)
    red = ScriptedRed()
    blue = ScriptedBlue()
    events = EventWriter(run_id="test-run", base_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    referee = Referee(
        transport=transport,
        sandbox=sandbox,
        gate=gate,
        red=red,
        blue=blue,
        events=events,
        benign_count=5,
    )
    return referee, tmp_path


@pytest.mark.asyncio
async def test_full_mock_run_schema_validation(test_env):
    referee, _tmp_path = test_env
    results = await referee.run_full(run_id="run-test-schema", attacks_per_round=4)

    # 1. Pydantic validation
    assert isinstance(results, Results)
    assert len(results.rounds) == 3
    assert results.sample is True

    # 2. JSON Schema validation
    schemas_dir = Path("contracts/schemas")
    results_schema = json.loads((schemas_dir / "results.schema.json").read_text(encoding="utf-8"))
    jsonschema.validate(instance=results.model_dump(), schema=results_schema)


@pytest.mark.asyncio
async def test_asr_decreases_across_rounds(test_env):
    referee, _ = test_env
    results = await referee.run_full(run_id="run-test-asr", attacks_per_round=6)

    r0, r1, r2 = results.rounds[0], results.rounds[1], results.rounds[2]
    # R0 has no defenses -> high ASR
    # R1 has screening gate -> lower ASR
    # R2 has patch -> lowest ASR
    assert r0.asr >= r1.asr
    assert r1.asr >= r2.asr


@pytest.mark.asyncio
async def test_heldout_attacks_only_in_r2(test_env):
    referee, _ = test_env
    results = await referee.run_full(run_id="run-test-heldout", attacks_per_round=6)

    r0_attacks = results.rounds[0].attacks
    r1_attacks = results.rounds[1].attacks
    r2_attacks = results.rounds[2].attacks

    # In R0 and R1, all attacks must be known
    assert all(a.known for a in r0_attacks)
    assert all(a.known for a in r1_attacks)

    # In R2, there must be held-out attacks
    heldout_in_r2 = [a for a in r2_attacks if not a.known]
    assert len(heldout_in_r2) > 0


@pytest.mark.asyncio
async def test_erroring_transport_retried_and_excluded(tmp_path):
    sandbox = FakeSandbox()
    gate = MockGate()

    class ErrorTransport(MockTransport):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            self.attack_call_count = 0

        async def send_ticket(self, env: Envelope, timeout_s: float = 45.0) -> WorkerOutcome:
            if env.kind == "attack":
                self.attack_call_count += 1
                return WorkerOutcome(
                    ticket_id=env.ticket_id,
                    outbound_messages=[],
                    blocked_by_gate=False,
                    latency_ms=10,
                    llm_calls=0,
                    error="Simulated network failure",
                )
            return await super().send_ticket(env, timeout_s)

    error_transport = ErrorTransport(sandbox=sandbox, gate=gate)
    events = EventWriter(run_id="test-err", base_dir=tmp_path / "runs")
    referee = Referee(
        transport=error_transport,
        sandbox=sandbox,
        gate=gate,
        red=ScriptedRed(),
        blue=ScriptedBlue(),
        events=events,
        benign_count=2,
    )

    dummy_attack = Attack(
        id="A01",
        title="Test Attack",
        category="direct",
        owasp="LLM01",
        goal="leak",
        known=True,
        text="test attack text",
    )

    round_res = await referee.run_round("R0", "L0", [dummy_attack])

    # Attack errored twice (1 initial + 1 retry)
    assert error_transport.attack_call_count == 2
    # Persistent error should be recorded in errors and excluded from ASR denominator
    assert round_res.errors == 1
    assert round_res.asr == 0.0


@pytest.mark.asyncio
async def test_round_summary_matches_attack_list(test_env):
    referee, _ = test_env
    results = await referee.run_full(run_id="run-test-recalc", attacks_per_round=4)

    for r in results.rounds:
        valid_attacks = [a for a in r.attacks]
        succeeded = [a for a in valid_attacks if a.outcome == "succeeded"]
        expected_asr = round(len(succeeded) / len(valid_attacks), 3) if valid_attacks else 0.0
        assert r.asr == expected_asr


def test_text_cache(tmp_path):
    cache = TextCache(tmp_path / "cache")
    assert cache.get("test_purpose", "some prompt text") is None

    cache.set("test_purpose", "some prompt text", {"result": "cached_val"})
    cached = cache.get("test_purpose", "some prompt text")
    assert cached == {"result": "cached_val"}

    # Different text yields cache miss
    assert cache.get("test_purpose", "other prompt text") is None
