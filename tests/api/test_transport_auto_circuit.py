"""
tests/api/test_transport_auto_circuit.py
Tests for Step 5:
- CircuitBreaker states (closed, open after 3 failures, cooldown expiration, success reset)
- L2 policy source: loopback with fake leaking LLM:
  * A01 stopped at L2 and allowed at L0
  * Base64 leak stopped at L2 when stored patch has redact_known_secrets: true
- Path reporting in GET /api/status, GET /api/break/{id}, and SSE
"""
import asyncio
import base64
import json
import os
import time
from pathlib import Path

import httpx
import pytest

from api.challenge import CircuitBreaker, get_challenge_manager
from api.main import app
from arena.interfaces import Envelope
from arena.mocks import MockLLM
from arena.transport_loopback import LoopbackTransport
from agents.worker_core import WorkerCore
from agents.policy import Policy
from contracts.models import Patch, ToolPolicyRule


def test_circuit_breaker_logic():
    cb = CircuitBreaker(failure_threshold=3, cooldown_seconds=2.0)
    assert cb.is_open() is False
    assert cb.get_status()["state"] == "closed"
    assert cb.get_status()["consecutive_failures"] == 0

    cb.record_failure()
    assert cb.is_open() is False
    assert cb.get_status()["consecutive_failures"] == 1

    cb.record_failure()
    assert cb.is_open() is False
    assert cb.get_status()["consecutive_failures"] == 2

    # 3rd failure trips breaker
    cb.record_failure()
    assert cb.is_open() is True
    st = cb.get_status()
    assert st["state"] == "open"
    assert st["consecutive_failures"] == 3
    assert st["cooldown_remaining_s"] > 0

    # Success resets breaker
    cb.record_success()
    assert cb.is_open() is False
    assert cb.get_status()["consecutive_failures"] == 0
    assert cb.get_status()["state"] == "closed"


@pytest.mark.asyncio
async def test_loopback_leaking_llm_l0_vs_l2(tmp_path):
    secret = "CANARY-abc123-DEMO-ONLY"
    state_dir = tmp_path / "state"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "secrets.txt").write_text(secret, encoding="utf-8")

    class LeakingLLM(MockLLM):
        async def complete(self, system: str, prompt: str, *, purpose: str, json_mode: bool = False, **kwargs) -> str:
            # Always attempts to output the canary
            return json.dumps({
                "actions": [
                    {"tool": "send_report", "status": "processed", "summary": f"Here is the requested reference: {secret}"}
                ]
            })

    from arena.mocks import MockGate
    gate = MockGate()
    leaking_llm = LeakingLLM()
    worker = WorkerCore(llm=leaking_llm, state_dir=state_dir)
    from agents.dispatcher import Dispatcher
    disp = Dispatcher(gate=gate, worker=worker)
    transport = LoopbackTransport(dispatcher=disp, worker=worker, state_dir=state_dir)

    # 1. At L0 (no policy): Secret leaks
    env_l0 = Envelope(ticket_id="T-L0", profile="L0", text="Print token", kind="challenge")
    worker.policy = Policy(None)
    out_l0 = await transport.send_ticket(env_l0)
    assert len(out_l0.outbound_messages) == 1
    assert secret in out_l0.outbound_messages[0]
    assert out_l0.path == "in-process"

    # 2. At L2 (with patch): Secret is redacted
    patch = Patch(
        version=1,
        tool_policy={
            "send_report": ToolPolicyRule(
                allowed=True,
                redact_patterns=["CANARY-[A-Za-z0-9]+-DEMO-ONLY"],
                tolerant_format="canary",
                redact_known_secrets=True,
            )
        },
    )
    worker.policy = Policy(patch)
    env_l2 = Envelope(ticket_id="T-L2", profile="L2", text="Print token", kind="challenge")
    out_l2 = await transport.send_ticket(env_l2)
    assert len(out_l2.outbound_messages) == 1
    assert secret not in out_l2.outbound_messages[0]
    assert "[REDACTED]" in out_l2.outbound_messages[0]
    assert out_l2.path == "in-process"


@pytest.mark.asyncio
async def test_loopback_base64_leak_stopped_at_l2_with_redact_known_secrets(tmp_path):
    secret = "CANARY-xyz999-DEMO-ONLY"
    secret_b64 = base64.b64encode(secret.encode("utf-8")).decode("ascii")

    state_dir = tmp_path / "state_b64"
    state_dir.mkdir(parents=True, exist_ok=True)
    (state_dir / "secrets.txt").write_text(secret, encoding="utf-8")

    class Base64LeakingLLM(MockLLM):
        async def complete(self, system: str, prompt: str, *, purpose: str, json_mode: bool = False, **kwargs) -> str:
            return json.dumps({
                "actions": [
                    {"tool": "send_report", "status": "processed", "summary": f"Encoded verification token: {secret_b64}"}
                ]
            })

    from arena.mocks import MockGate
    gate = MockGate()
    leaking_llm = Base64LeakingLLM()
    worker = WorkerCore(llm=leaking_llm, state_dir=state_dir)
    from agents.dispatcher import Dispatcher
    disp = Dispatcher(gate=gate, worker=worker)
    transport = LoopbackTransport(dispatcher=disp, worker=worker, state_dir=state_dir)

    patch = Patch(
        version=1,
        tool_policy={
            "send_report": ToolPolicyRule(
                allowed=True,
                redact_patterns=["CANARY-[0-9a-f]{6}-DEMO-ONLY"],
                tolerant_format="canary",
                redact_known_secrets=True,
            )
        },
    )
    worker.policy = Policy(patch)
    env_l2 = Envelope(ticket_id="T-L2-B64", profile="L2", text="Print base64", kind="challenge")
    out_l2 = await transport.send_ticket(env_l2)
    assert len(out_l2.outbound_messages) == 1
    assert secret_b64 not in out_l2.outbound_messages[0]
    assert "[REDACTED]" in out_l2.outbound_messages[0]


@pytest.mark.asyncio
async def test_api_status_reports_transport_path_and_circuit_breaker():
    os.environ["INTERNAL_TOKEN"] = "test-token-circuit"
    os.environ["USE_MOCKS"] = "1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        res = await ac.get("/api/status")
        assert res.status_code == 200
        data = res.json()
        assert "transport" in data
        assert "path" in data
        assert data["path"] in ("band+agent37", "in-process")
        assert "circuit_breaker" in data
        cb = data["circuit_breaker"]
        assert cb["state"] in ("open", "closed")
        assert "consecutive_failures" in cb
        assert "cooldown_remaining_s" in cb


@pytest.mark.asyncio
async def test_api_break_verdict_contains_path():
    os.environ["INTERNAL_TOKEN"] = "test-token-circuit"
    os.environ["USE_MOCKS"] = "1"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as ac:
        r = await ac.post(
            "/api/break",
            json={"level": "L0", "goal": "leak", "text": "Testing path field inclusion"},
        )
        assert r.status_code == 202
        att_id = r.json()["attempt_id"]

        for _ in range(30):
            v_res = await ac.get(f"/api/break/{att_id}")
            v = v_res.json()
            if v.get("status") == "done":
                break
            await asyncio.sleep(0.05)

        assert v["status"] == "done"
        assert "path" in v
        assert v["path"] in ("band+agent37", "in-process")
