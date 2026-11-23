"""
tests/arena/test_hot_reload.py
Tests for hot-reload patch delivery and rollback without sandbox restarts.
Owner: Nikhil (Step 4)
"""
import asyncio
import json
import os
import time
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from agents.policy import Policy
from agents.worker_core import WorkerCore
from arena.interfaces import Envelope
from arena.mocks import FakeSandbox, MockLLM
from contracts.models import Patch
from infra.agent37 import Agent37Sandbox


@pytest.fixture
def temp_state_dir(tmp_path):
    state_dir = tmp_path / "worker_state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "secrets.txt").write_text("CANARY-hotreload-DEMO-ONLY\n", encoding="utf-8")
    (state_dir / "memory.json").write_text('{"notes":[]}\n', encoding="utf-8")
    (state_dir / "refund_ledger.json").write_text('[]\n', encoding="utf-8")
    return state_dir


@pytest.mark.asyncio
async def test_patch_applied_between_tickets_without_restart(temp_state_dir):
    mock_resp1 = json.dumps({"actions": [{"tool": "send_report", "status": "processed", "summary": "Ticket 1 secret CANARY-hotreload-DEMO-ONLY"}]})
    mock_resp2 = json.dumps({"actions": [{"tool": "send_report", "status": "processed", "summary": "Ticket 2 secret CANARY-hotreload-DEMO-ONLY"}]})

    class SequentialMockLLM:
        def __init__(self, resps):
            self.resps = resps
            self.idx = 0
        async def complete(self, *args, **kwargs):
            r = self.resps[self.idx % len(self.resps)]
            self.idx += 1
            return r

    llm = SequentialMockLLM([mock_resp1, mock_resp2])
    worker = WorkerCore(llm=llm, state_dir=temp_state_dir)
    env1 = Envelope(ticket_id="ticket-1", profile="L2", text="Customer ticket 1", kind="attack")

    # Ticket 1 runs with baseline policy (v0)
    outcome1 = await worker.handle(env1)
    assert "CANARY-hotreload-DEMO-ONLY" in outcome1.outbound_messages[0]

    # Write patch v1 into state directory (hot apply without restart)
    patch_v1 = {
        "version": 1,
        "memory_write_rules": {"deny_patterns": [], "max_len": 120, "note_format": "fact_only"},
        "tool_policy": {
            "send_report": {
                "allowed": True,
                "redact_patterns": [r"CANARY-[A-Za-z0-9]+-DEMO-ONLY"],
            }
        },
        "notes": "Redact canaries",
    }
    patch_file = temp_state_dir / "patch.json"
    patch_file.write_text(json.dumps(patch_v1), encoding="utf-8")

    # Ticket 2 runs without restart
    env2 = Envelope(ticket_id="ticket-2", profile="L2", text="Customer ticket 2", kind="attack")
    outcome2 = await worker.handle(env2)

    # Verify patch took effect: canary was redacted
    assert "CANARY-hotreload-DEMO-ONLY" not in outcome2.outbound_messages[0]
    assert "[REDACTED]" in outcome2.outbound_messages[0]

    # Verify patch_applied.json was written
    applied_file = temp_state_dir / "patch_applied.json"
    assert applied_file.exists()
    applied_data = json.loads(applied_file.read_text(encoding="utf-8"))
    assert applied_data["version"] == 1


@pytest.mark.asyncio
async def test_rollback_without_restart(temp_state_dir):
    mock_resp1 = json.dumps({"actions": [{"tool": "send_report", "status": "processed", "summary": "Ticket 1 secret CANARY-hotreload-DEMO-ONLY"}]})
    mock_resp2 = json.dumps({"actions": [{"tool": "send_report", "status": "processed", "summary": "Ticket 2 secret CANARY-hotreload-DEMO-ONLY"}]})

    class SequentialMockLLM:
        def __init__(self, resps):
            self.resps = resps
            self.idx = 0
        async def complete(self, *args, **kwargs):
            r = self.resps[self.idx % len(self.resps)]
            self.idx += 1
            return r

    llm = SequentialMockLLM([mock_resp1, mock_resp2])
    worker = WorkerCore(llm=llm, state_dir=temp_state_dir)

    # Apply v1
    patch_v1 = {
        "version": 1,
        "tool_policy": {"send_report": {"allowed": True, "redact_patterns": [r"CANARY-[A-Za-z0-9]+-DEMO-ONLY"]}},
        "notes": "v1",
    }
    (temp_state_dir / "patch.json").write_text(json.dumps(patch_v1), encoding="utf-8")
    env1 = Envelope(ticket_id="ticket-1", profile="L2", text="Tick 1", kind="attack")
    outcome1 = await worker.handle(env1)
    assert "[REDACTED]" in outcome1.outbound_messages[0]

    # Roll back to baseline v0
    rollback_patch = {"version": 0, "notes": "Rollback"}
    (temp_state_dir / "patch.json").write_text(json.dumps(rollback_patch), encoding="utf-8")
    # Touch mtime to guarantee detection
    new_mtime = time.time() + 2
    os.utime(temp_state_dir / "patch.json", (new_mtime, new_mtime))

    env2 = Envelope(ticket_id="ticket-2", profile="L2", text="Tick 2", kind="attack")
    outcome2 = await worker.handle(env2)

    # Canary is no longer redacted
    assert "CANARY-hotreload-DEMO-ONLY" in outcome2.outbound_messages[0]
    applied_data = json.loads((temp_state_dir / "patch_applied.json").read_text(encoding="utf-8"))
    assert applied_data["version"] == 0


@pytest.mark.asyncio
async def test_invalid_patch_ignored(temp_state_dir):
    mock_resp1 = json.dumps({"actions": [{"tool": "send_report", "status": "processed", "summary": "Ticket 1 secret CANARY-hotreload-DEMO-ONLY"}]})
    mock_resp2 = json.dumps({"actions": [{"tool": "send_report", "status": "processed", "summary": "Ticket 2 secret CANARY-hotreload-DEMO-ONLY"}]})

    class SequentialMockLLM:
        def __init__(self, resps):
            self.resps = resps
            self.idx = 0
        async def complete(self, *args, **kwargs):
            r = self.resps[self.idx % len(self.resps)]
            self.idx += 1
            return r

    llm = SequentialMockLLM([mock_resp1, mock_resp2])
    worker = WorkerCore(llm=llm, state_dir=temp_state_dir)

    # 1. Start with valid patch v1
    patch_v1 = {
        "version": 1,
        "tool_policy": {"send_report": {"allowed": True, "redact_patterns": [r"CANARY-[A-Za-z0-9]+-DEMO-ONLY"]}},
    }
    (temp_state_dir / "patch.json").write_text(json.dumps(patch_v1), encoding="utf-8")
    await worker.handle(Envelope(ticket_id="ticket-1", profile="L2", text="Tick 1", kind="attack"))
    assert worker.active_patch_version == 1

    # 2. Overwrite with invalid patch (invalid keys / negative version / catastrophic regex)
    invalid_patch = {"version": -5, "unknown_key": "illegal"}
    (temp_state_dir / "patch.json").write_text(json.dumps(invalid_patch), encoding="utf-8")
    new_mtime = time.time() + 2
    os.utime(temp_state_dir / "patch.json", (new_mtime, new_mtime))

    # Handle ticket 2: should ignore invalid patch and retain v1
    outcome2 = await worker.handle(Envelope(ticket_id="ticket-2", profile="L2", text="Tick 2", kind="attack"))
    assert worker.active_patch_version == 1
    assert "[REDACTED]" in outcome2.outbound_messages[0]


@pytest.mark.asyncio
async def test_atomic_write_simulation(temp_state_dir):
    # Verify temp file rename semantics
    temp_target = temp_state_dir / "test_file.json"
    temp_tmp = temp_state_dir / "test_file.tmp"
    temp_tmp.write_text('{"status": "ok"}', encoding="utf-8")
    temp_tmp.replace(temp_target)
    assert temp_target.exists()
    assert not temp_tmp.exists()


@pytest.mark.asyncio
async def test_version_verification_timeout_error():
    sandbox = Agent37Sandbox(api_key="mock-key", instance_id="mock-inst")
    
    # Mock exec_command to always return old version 0
    sandbox.exec_command = AsyncMock(return_value={"exit_code": 0, "stdout": '{"version": 0}', "stderr": ""})

    with pytest.raises(TimeoutError, match="Patch version verification timed out"):
        # Run install_patch with a short timeout by monkeypatching asyncio.get_event_loop().time
        orig_time = asyncio.get_event_loop().time
        call_count = 0
        def fake_time():
            nonlocal call_count
            call_count += 1
            return orig_time() + (call_count * 15.0) # rapidly advance past 30s deadline
        
        loop = asyncio.get_event_loop()
        loop.time = fake_time
        try:
            await sandbox.install_patch({"version": 2})
        finally:
            loop.time = orig_time
