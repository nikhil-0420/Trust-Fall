"""
tests/test_preflight.py
Unit tests for preflight verification checks.
"""
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from scripts.preflight import (
    check_or_start_tunnel,
    check_room_participants,
    check_sandbox_gate_reachability,
    check_system_prompt_hash,
    check_worker_process_and_env,
    clear_lingering_patch,
    reset_memory_and_canary,
    update_local_env_gate_url,
)


def test_update_local_env_gate_url(tmp_path: Path):
    env_file = tmp_path / ".env"
    env_file.write_text("FOO=bar\nGATE_URL=http://old.example.com\nBAZ=1\n", encoding="utf-8")

    update_local_env_gate_url("https://new.trycloudflare.com", env_file)

    content = env_file.read_text(encoding="utf-8")
    assert "GATE_URL=https://new.trycloudflare.com" in content
    assert "http://old.example.com" not in content
    assert "FOO=bar" in content
    assert "BAZ=1" in content


@pytest.mark.asyncio
async def test_check_or_start_tunnel_already_healthy(monkeypatch):
    monkeypatch.setenv("GATE_URL", "https://existing.trycloudflare.com")

    mock_resp = MagicMock()
    mock_resp.status_code = 200

    with patch("httpx.Client.get", return_value=mock_resp):
        ok, msg, url = await check_or_start_tunnel()
        assert ok is True
        assert "existing.trycloudflare.com" in url


@pytest.mark.asyncio
async def test_check_sandbox_gate_reachability():
    sb = MagicMock()
    # Success case
    sb.exec_command = AsyncMock(return_value={"exit_code": 0, "stdout": '{"status":"ok"}'})
    ok, msg = await check_sandbox_gate_reachability(sb, "http://gate:8000")
    assert ok is True
    assert "HTTP 200" in msg

    # Failure case
    sb.exec_command = AsyncMock(return_value={"exit_code": 7, "stderr": "Failed to connect"})
    ok, msg = await check_sandbox_gate_reachability(sb, "http://gate:8000")
    assert ok is False


@pytest.mark.asyncio
async def test_check_worker_process_and_env():
    sb = MagicMock()

    # Case 1: Healthy single process, recent marker, interval 0
    async def mock_exec_healthy(cmd: str):
        if "ps aux" in cmd:
            return {"exit_code": 0, "stdout": "node 1488 0.0 python3 -u worker_band.py\n"}
        elif "MTIME=" in cmd:
            return {"exit_code": 0, "stdout": "12\n"}
        elif "GEMINI_MIN_INTERVAL_S" in cmd:
            return {"exit_code": 0, "stdout": 'export GEMINI_MIN_INTERVAL_S="0"\n'}
        return {"exit_code": 0, "stdout": ""}

    sb.exec_command = AsyncMock(side_effect=mock_exec_healthy)
    ok, msg = await check_worker_process_and_env(sb)
    assert ok is True

    # Case 2: Process count != 1
    async def mock_exec_multi(cmd: str):
        if "ps aux" in cmd:
            return {"exit_code": 0, "stdout": "node 100 python3 -u worker_band.py\nnode 101 python3 -u worker_band.py\n"}
        return {"exit_code": 0, "stdout": ""}

    sb.exec_command = AsyncMock(side_effect=mock_exec_multi)
    ok, msg = await check_worker_process_and_env(sb)
    assert ok is False
    assert "Expected exactly 1" in msg

    # Case 3: Stale marker
    async def mock_exec_stale(cmd: str):
        if "ps aux" in cmd:
            return {"exit_code": 0, "stdout": "node 100 python3 -u worker_band.py\n"}
        elif "MTIME=" in cmd:
            return {"exit_code": 0, "stdout": "120\n"}
        elif "GEMINI_MIN_INTERVAL_S" in cmd:
            return {"exit_code": 0, "stdout": 'export GEMINI_MIN_INTERVAL_S="0"\n'}
        return {"exit_code": 0, "stdout": ""}

    sb.exec_command = AsyncMock(side_effect=mock_exec_stale)
    ok, msg = await check_worker_process_and_env(sb)
    assert ok is False
    assert "stale" in msg


@pytest.mark.asyncio
async def test_check_system_prompt_hash():
    sb = MagicMock()
    target_hash = "abcdef1234567890abcdef1234567890abcdef1234567890abcdef1234567890"

    # Match
    sb.exec_command = AsyncMock(return_value={"exit_code": 0, "stdout": f"{target_hash}  /home/node/agents/prompts/worker_system_victim.md"})
    ok, msg = await check_system_prompt_hash(sb, expected_hash=target_hash)
    assert ok is True

    # Mismatch
    sb.exec_command = AsyncMock(return_value={"exit_code": 0, "stdout": "differenthash1234  /home/node/agents/prompts/worker_system_victim.md"})
    ok, msg = await check_system_prompt_hash(sb, expected_hash=target_hash)
    assert ok is False
    assert "mismatch" in msg.lower()


@pytest.mark.asyncio
async def test_clear_lingering_patch():
    sb = MagicMock()
    sb.exec_command = AsyncMock(return_value={
        "exit_code": 0,
        "stdout": "[HOT_RELOAD] Patch reloaded: cleared policy, version=0\n",
    })

    ok, msg = await clear_lingering_patch(sb)
    assert ok is True
    assert "Lingering patch cleared" in msg


@pytest.mark.asyncio
async def test_reset_memory_and_canary():
    sb = MagicMock()
    sb.reset_state = AsyncMock()
    sb.read_memory = AsyncMock(return_value='{"notes":[]}')

    ok, msg = await reset_memory_and_canary(sb, canary="CANARY-test-demo")
    assert ok is True
    sb.reset_state.assert_called_once_with(canary="CANARY-test-demo")


def test_check_room_participants(monkeypatch):
    monkeypatch.setenv("BAND_AGENT_A_KEY", "mock_key")

    mock_client = MagicMock()
    mock_resp = MagicMock()

    # Success: All 4 agents present
    p1 = MagicMock(name="Agent A", role="owner")
    p1.name = "Agent A"
    p2 = MagicMock(name="Agent B", role="member")
    p2.name = "Agent B"
    p3 = MagicMock(name="Red Agent", role="member")
    p3.name = "Red Agent"
    p4 = MagicMock(name="Blue Agent", role="member")
    p4.name = "Blue Agent"

    mock_resp.data = [p1, p2, p3, p4]
    mock_client.agent_api_participants.list_agent_chat_participants.return_value = mock_resp

    with patch("band_rest.RestClient", return_value=mock_client):
        ok, msg = check_room_participants("mock-room-123")
        assert ok is True

    # Failure: Missing Blue Agent
    mock_resp.data = [p1, p2, p3]
    with patch("band_rest.RestClient", return_value=mock_client):
        ok, msg = check_room_participants("mock-room-123")
        assert ok is False
        assert "Missing" in msg
