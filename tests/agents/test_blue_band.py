"""
tests/agents/test_blue_band.py
Unit tests for BAND-native Blue defender client and background agent.
Verifies payload truncation <= 3KB, request-ID matching, proposal parsing,
timeout fallback to ScriptedBlue, and factory integration.
"""
import asyncio
import json
import pytest
from unittest.mock import MagicMock, AsyncMock

from agents.blue_band import (
    BandBlueAgent,
    BandBlueClient,
    summarize_incident_log_for_band,
)
from arena.factory import get_blue


def test_summarize_incident_log_size_and_secrets():
    """Verify incident log summary stays under 3KB and hides held-out attacks."""
    incidents = [
        {
            "id": f"A{i:02d}",
            "attack_id": f"A{i:02d}",
            "category": "prompt_injection",
            "goal": "exfiltrate canary secret key",
            "layer": "L0",
            "outcome": "succeeded",
            "heldout": (i % 2 == 0),
            "raw_secret": "CANARY-abc123-DEMO-ONLY",
        }
        for i in range(50)
    ]

    summary_str = summarize_incident_log_for_band(incidents, max_bytes=2800)
    data = json.loads(summary_str)

    assert len(summary_str.encode("utf-8")) <= 2800
    assert data["secret_format"] == "CANARY-[0-9a-f]{6}-DEMO-ONLY"
    assert "CANARY-abc123-DEMO-ONLY" not in summary_str
    # Heldout attacks filtered out
    for inc in data["incidents"]:
        assert inc["id"] not in [f"A{i:02d}" for i in range(50) if i % 2 == 0]


class FakeMessage:
    def __init__(self, msg_id: str, content: str):
        self.id = msg_id
        self.content = content


class FakeAgentMessagesAPI:
    def __init__(self):
        self.sent_messages = []
        self.messages = []

    def create_agent_chat_message(self, room_id, message):
        self.sent_messages.append(message)
        # Also simulate echo/presence in room
        self.messages.append(FakeMessage(f"msg-{len(self.messages)+1}", message.content))

    def list_agent_messages(self, room_id, limit=50, sort_order="desc"):
        mock_resp = MagicMock()
        mock_resp.data = list(self.messages)
        return mock_resp


class FakeRestClient:
    def __init__(self):
        self.agent_api_messages = FakeAgentMessagesAPI()


@pytest.mark.asyncio
async def test_band_blue_client_success():
    """Verify BandBlueClient posts request and parses valid patch proposal."""
    fake_client = FakeRestClient()
    client = BandBlueClient(
        room_id="test-room",
        blue_handle="agent-blue",
        rest_client=fake_client,
        timeout_s=5.0,
    )

    valid_patch = {
        "version": 1,
        "tool_policy": {
            "send_report": {
                "redact_known_secrets": True,
                "redact_patterns": [r"(?i)CANARY-[0-9a-f]{6}-DEMO-ONLY"],
            }
        },
    }

    async def simulate_defender_response():
        await asyncio.sleep(0.1)
        # Look for the request id in sent messages
        req_id = None
        for msg in fake_client.agent_api_messages.sent_messages:
            if "[DEFENSE_REQUEST:" in msg.content:
                req_id = msg.content.split("[DEFENSE_REQUEST:")[1].split("]")[0]
                break
        assert req_id is not None
        response_content = f"@{client.blue_handle} [PATCH_PROPOSAL:{req_id}] PATCH_JSON: {json.dumps(valid_patch)}"
        fake_client.agent_api_messages.messages.append(FakeMessage("resp-1", response_content))

    asyncio.create_task(simulate_defender_response())

    patch = await client.propose_patch(
        incident_log=[{"id": "A01", "goal": "leak canary", "outcome": "succeeded"}]
    )

    assert patch["version"] == 1
    assert patch["tool_policy"]["send_report"]["redact_known_secrets"] is True


@pytest.mark.asyncio
async def test_band_blue_client_timeout_fallback():
    """Verify BandBlueClient falls back to ScriptedBlue on timeout."""
    fake_client = FakeRestClient()
    client = BandBlueClient(
        room_id="test-room",
        blue_handle="agent-blue",
        rest_client=fake_client,
        timeout_s=0.2,  # very short timeout
    )

    # Defender does NOT respond
    patch = await client.propose_patch(
        incident_log=[{"id": "A01", "goal": "leak canary", "outcome": "succeeded"}]
    )

    assert patch is not None
    assert "tool_policy" in patch
    assert patch["version"] >= 1


@pytest.mark.asyncio
async def test_band_blue_client_malformed_json_fallback():
    """Verify BandBlueClient falls back to ScriptedBlue on malformed proposal JSON."""
    fake_client = FakeRestClient()
    client = BandBlueClient(
        room_id="test-room",
        blue_handle="agent-blue",
        rest_client=fake_client,
        timeout_s=2.0,
    )

    async def simulate_bad_response():
        await asyncio.sleep(0.1)
        req_id = None
        for msg in fake_client.agent_api_messages.sent_messages:
            if "[DEFENSE_REQUEST:" in msg.content:
                req_id = msg.content.split("[DEFENSE_REQUEST:")[1].split("]")[0]
                break
        assert req_id is not None
        response_content = f"@{client.blue_handle} [PATCH_PROPOSAL:{req_id}] PATCH_JSON: {{\"not_a_valid_patch\": 123}}"
        fake_client.agent_api_messages.messages.append(FakeMessage("resp-bad", response_content))

    asyncio.create_task(simulate_bad_response())

    patch = await client.propose_patch(
        incident_log=[{"id": "A01", "goal": "leak canary", "outcome": "succeeded"}]
    )

    # Should fall back to ScriptedBlue patch
    assert patch is not None
    assert "tool_policy" in patch


@pytest.mark.asyncio
async def test_band_blue_agent_handler():
    """Verify BandBlueAgent receives request, queries blue_agent, and posts proposal."""
    fake_client = FakeRestClient()
    mock_inner_blue = MagicMock()
    mock_inner_blue.propose_patch = AsyncMock(
        return_value={
            "version": 2,
            "tool_policy": {"send_report": {"allowed": True, "redact_known_secrets": True}},
        }
    )

    agent = BandBlueAgent(
        room_id="test-room",
        blue_agent=mock_inner_blue,
        rest_client=fake_client,
    )

    # Post an incoming request
    req_content = "@nikhil.guddanti/agent-blue [DEFENSE_REQUEST:req-9999] {\"secret_format\": \"CANARY-[0-9a-f]{6}-DEMO-ONLY\", \"incidents\": []}"
    handled = await agent.handle_message(FakeMessage("msg-req", req_content))
    assert handled is True

    # Check that a response message was posted with the request id and valid json
    posted = [m for m in fake_client.agent_api_messages.sent_messages if "[PATCH_PROPOSAL:req-9999]" in m.content]
    assert len(posted) == 1
    assert "PATCH_JSON:" in posted[0].content
    assert '"version": 2' in posted[0].content


def test_factory_blue_transport_env(monkeypatch):
    """Verify get_blue() selects BandBlueClient when BLUE_TRANSPORT=band."""
    monkeypatch.setenv("USE_MOCKS", "0")
    monkeypatch.setenv("BLUE_TRANSPORT", "band")
    blue = get_blue()
    assert isinstance(blue, BandBlueClient)
