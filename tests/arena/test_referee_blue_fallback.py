"""
tests/arena/test_referee_blue_fallback.py
Unit tests verifying Blue input fallback in arena/referee.py (Phase C9).
"""
import json
from pathlib import Path
import pytest

from arena.events import EventWriter
from arena.interfaces import Envelope, WorkerOutcome
from arena.mocks import FakeSandbox, MockGate, MockLLM, MockTransport, ScriptedBlue, ScriptedRed
from arena.referee import Referee
from contracts.models import Attack, Results, RoundAttackResult, RoundResult, BenignSummary


class RecordingBlue(ScriptedBlue):
    def __init__(self):
        super().__init__()
        self.received_logs = []

    async def propose_patch(self, incident_log, previous_patch=None, rejected_reason=None):
        self.received_logs.append(list(incident_log))
        return await super().propose_patch(incident_log, previous_patch, rejected_reason)


@pytest.mark.asyncio
async def test_blue_fallback_when_r1_has_fewer_than_two_successes(tmp_path: Path):
    sandbox = FakeSandbox()
    gate = MockGate()
    transport = MockTransport(sandbox=sandbox, gate=gate)
    events = EventWriter(run_id="test-blue-fallback", base_dir=tmp_path / "runs", cache_dir=tmp_path / "cache")
    blue = RecordingBlue()
    red = ScriptedRed()

    referee = Referee(
        transport=transport,
        sandbox=sandbox,
        gate=gate,
        red=red,
        blue=blue,
        events=events,
        benign_count=2,
    )

    # Mock library: 4 known attacks, 1 heldout attack
    library = [
        Attack(id="A01", title="A1", category="direct", owasp="LLM01", goal="leak", known=True, text="t1"),
        Attack(id="A02", title="A2", category="direct", owasp="LLM01", goal="poison", known=True, text="t2 POISON-MARK"),
        Attack(id="A03", title="A3", category="roleplay", owasp="LLM01", goal="leak", known=True, text="t3"),
        Attack(id="A04", title="A4", category="obfuscation", owasp="LLM01", goal="poison", known=True, text="t4 POISON-MARK"),
        Attack(id="H01", title="H1", category="direct", owasp="LLM01", goal="leak", known=False, text="heldout"),
    ]

    # In MockTransport:
    # In R0 (L0): all attacks succeed
    # In R1 (L1): direct & roleplay attacks are blocked by MockGate!
    # A01 (direct, blocked), A02 (direct, blocked), A03 (roleplay, blocked), A04 (obfuscation, succeeds!)
    # Thus in R1, only A04 succeeds (count = 1 < 2).
    # Blue input fallback should trigger, augmenting incident log with R0 successes, setting blue_input="R0+R1".
    lib_path = tmp_path / "test_library.json"
    lib_path.write_text(json.dumps([a.model_dump() for a in library]), encoding="utf-8")

    results = await referee.run_full(
        run_id="run-blue-fb-test",
        library_path=lib_path,
        attacks_per_round=4,
    )

    assert results.blue_input == "R0+R1"
    assert len(blue.received_logs) >= 1
    incident_log = blue.received_logs[0]
    # Verify incident log has more than 1 attack thanks to R0 fallback
    assert len(incident_log) >= 2
    # Verify no held-out attack is present
    for item in incident_log:
        assert item["attack_id"] != "H01"
