"""
tests/arena/test_rollback.py
Unit tests for patch apply, rollback, regression verification, and incident reports.
Owner: Nehaa (WS-C C4, C5, C6)
"""
import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional
import pytest

from arena.events import EventWriter
from arena.mocks import FakeSandbox, MockGate, MockTransport, ScriptedBlue, ScriptedRed
from arena.referee import Referee
from arena.reports import generate_reports
from arena.rollback import apply_or_rollback
from contracts.models import Event, Patch, Results


@pytest.fixture
def base_referee(tmp_path):
    sandbox = FakeSandbox()
    gate = MockGate()
    transport = MockTransport(sandbox=sandbox, gate=gate)
    red = ScriptedRed()
    blue = ScriptedBlue()
    events = EventWriter(run_id="test-patch-run", base_dir=tmp_path / "runs")
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
async def test_good_patch_applied_and_recorded(base_referee):
    referee, _ = base_referee
    incident_log = [{"attack_id": "A01", "category": "direct", "goal": "leak"}]

    decision = await apply_or_rollback(
        referee=referee,
        incident_log=incident_log,
        r0_benign_rate=1.0,
        rollback_demo=False,
    )

    assert decision.accepted is True
    assert decision.active_patch is not None
    assert len(decision.history) == 1
    assert decision.history[0].status == "applied"

    # Sandbox has installed patch
    assert referee.sandbox.patch is not None
    assert referee.sandbox.patch["version"] == decision.active_version


@pytest.mark.asyncio
async def test_failing_patch_rejected_and_rolled_back(tmp_path):
    sandbox = FakeSandbox()
    gate = MockGate()

    class RejectingBlue(ScriptedBlue):
        def __init__(self):
            self.attempts = 0

        async def propose_patch(self, incident_log, previous_patch=None, rejected_reason=None):
            self.attempts += 1
            # Propose over-strict patch that redacts all output
            return {
                "version": 1,
                "memory_write_rules": {"deny_patterns": [r"(?i)[a-z0-9]"], "max_len": 20, "note_format": "fact_only"},
                "tool_policy": {"send_report": {"redact_patterns": [r"(?i)[a-z0-9]"], "allowed": True}},
                "gate": {"threshold": 0.3},
                "notes": "Failing test patch",
            }

    blue = RejectingBlue()
    transport = MockTransport(sandbox=sandbox, gate=gate)
    events = EventWriter(run_id="test-fail-patch", base_dir=tmp_path / "runs")
    referee = Referee(
        transport=transport,
        sandbox=sandbox,
        gate=gate,
        red=ScriptedRed(),
        blue=blue,
        events=events,
        benign_count=5,
    )

    initial_patch = {"version": 10, "notes": "Initial safe patch"}
    await sandbox.install_patch(initial_patch)

    decision = await apply_or_rollback(
        referee=referee,
        incident_log=[{"category": "direct", "goal": "leak"}],
        r0_benign_rate=1.0,
        rollback_demo=False,
        previous_patch=initial_patch,
    )

    # Both attempts failed
    assert decision.accepted is False
    assert len(decision.history) == 2
    assert all(h.status == "rejected" for h in decision.history)

    # FakeSandbox restored to initial_patch
    assert referee.sandbox.patch == initial_patch


@pytest.mark.asyncio
async def test_second_proposal_passes_applied(tmp_path):
    sandbox = FakeSandbox()
    gate = MockGate()

    class TwoStepBlue(ScriptedBlue):
        def __init__(self):
            self.attempt = 0

        async def propose_patch(self, incident_log, previous_patch=None, rejected_reason=None):
            self.attempt += 1
            if self.attempt == 1:
                # First attempt fails regression
                return {
                    "version": 1,
                    "memory_write_rules": {"deny_patterns": [r"(?i)[a-z0-9]"], "max_len": 20, "note_format": "fact_only"},
                    "tool_policy": {"send_report": {"redact_patterns": [r"(?i)[a-z0-9]"], "allowed": True}},
                    "gate": {"threshold": 0.3},
                    "notes": "Attempt 1 overstrict",
                }
            # Second attempt is safe
            return await super().propose_patch(incident_log, previous_patch, rejected_reason)

    blue = TwoStepBlue()
    transport = MockTransport(sandbox=sandbox, gate=gate)
    events = EventWriter(run_id="test-2step", base_dir=tmp_path / "runs")
    referee = Referee(
        transport=transport,
        sandbox=sandbox,
        gate=gate,
        red=ScriptedRed(),
        blue=blue,
        events=events,
        benign_count=5,
    )

    decision = await apply_or_rollback(
        referee=referee,
        incident_log=[{"category": "direct", "goal": "leak"}],
        r0_benign_rate=1.0,
        rollback_demo=False,
    )

    assert decision.accepted is True
    assert len(decision.history) == 2
    assert decision.history[0].status == "rejected"
    assert decision.history[1].status == "applied"


@pytest.mark.asyncio
async def test_rollback_demo_flag(base_referee):
    referee, _ = base_referee
    incident_log = [{"attack_id": "A01", "category": "direct", "goal": "leak"}]

    decision = await apply_or_rollback(
        referee=referee,
        incident_log=incident_log,
        r0_benign_rate=1.0,
        rollback_demo=True,
    )

    assert decision.accepted is True
    assert len(decision.history) == 2
    demo_entry = decision.history[0]
    assert getattr(demo_entry, "demo", False) is True
    assert demo_entry.status == "rejected"
    assert "90%" in demo_entry.reason

    applied_entry = decision.history[1]
    assert applied_entry.status == "applied"


@pytest.mark.asyncio
async def test_reports_render_cleanly(base_referee):
    referee, tmp_path = base_referee
    results = await referee.run_full(run_id="run-reports-test", rollback_demo=True)

    report_files = generate_reports(results, output_dir=tmp_path / "reports")
    assert len(report_files) == 3

    # Check for presence of all rounds and absence of secrets
    secret_pattern = re.compile(r"(AIza[0-9A-Za-z-_]{35}|lyzr-[0-9a-zA-Z]{20,}|sk-[0-9a-zA-Z]{20,})")
    for rep in report_files:
        content = rep.read_text(encoding="utf-8")
        assert len(content) > 100
        assert not secret_pattern.search(content)

    r2_content = (tmp_path / "reports" / "R2.md").read_text(encoding="utf-8")
    assert "Defender Patch Decisions & History" in r2_content
    assert "Active Patch Specification" in r2_content


@pytest.mark.asyncio
async def test_patch_events_validate_schema(base_referee):
    referee, _ = base_referee
    results = await referee.run_full(run_id="run-patch-events", rollback_demo=True)

    events_r1 = referee.events.get_events_for_round("R1")
    patch_events = [e for e in events_r1 if e.get("type") == "patch"]
    assert len(patch_events) >= 2  # proposed + rejected (demo) + proposed + applied

    for pe in patch_events:
        Event.model_validate(pe)
