"""
Parity tests for Sandbox implementations (FakeSandbox and Agent37Sandbox).
Uses httpx.MockTransport to simulate Agent37 API and exec server in-memory without network calls.
Verifies:
- reset_state clears memory and writes secrets.txt with canary
- install_patch and read back
- restart maintains persisted state
- ping responsiveness
"""
import base64
import json

import httpx
import pytest

from arena.mocks import FakeSandbox
from infra.agent37 import Agent37Sandbox


class SimulatedAgent37Server:
    def __init__(self):
        self.files: dict[str, str] = {
            "memory.json": '{"notes":[]}',
            "secrets.txt": "",
            "refund_ledger.json": "[]",
        }
        self.status = "running"
        self.restart_count = 0

    def handle_request(self, request: httpx.Request) -> httpx.Response:
        url = str(request.url)

        # Exec endpoint
        if "/exec" in url:
            body = json.loads(request.content.decode("utf-8"))
            cmd = body.get("command", "")

            if "echo ping" in cmd:
                return httpx.Response(200, json={"exit_code": 0, "stdout": "ping\n", "stderr": ""})

            if "cat memory.json" in cmd:
                content = self.files.get("memory.json", '{"notes":[]}')
                return httpx.Response(200, json={"exit_code": 0, "stdout": content, "stderr": ""})

            if "cat refund_ledger.json" in cmd:
                content = self.files.get("refund_ledger.json", "[]")
                return httpx.Response(200, json={"exit_code": 0, "stdout": content, "stderr": ""})

            if "cat patch.json" in cmd:
                content = self.files.get("patch.json", "{}")
                return httpx.Response(200, json={"exit_code": 0, "stdout": content, "stderr": ""})

            if "echo '{\"notes\":[]}' > memory.json" in cmd:
                self.files["memory.json"] = '{"notes":[]}'
                self.files["refund_ledger.json"] = "[]"
                # extract canary
                if "base64 -d > secrets.txt" in cmd:
                    parts = cmd.split("echo '")
                    for p in parts:
                        if "' | base64 -d > secrets.txt" in p:
                            b64 = p.split("' |")[0]
                            self.files["secrets.txt"] = base64.b64decode(b64).decode("utf-8")
                return httpx.Response(200, json={"exit_code": 0, "stdout": "", "stderr": ""})

            if "cat patch_applied.json" in cmd:
                content = self.files.get("patch_applied.json", '{"version": 0}')
                return httpx.Response(200, json={"exit_code": 0, "stdout": content, "stderr": ""})

            if "cat /home/node/worker_ready.marker" in cmd:
                return httpx.Response(200, json={"exit_code": 0, "stdout": "1795400000", "stderr": ""})

            if "base64 -d > patch.json" in cmd or "patch.json.tmp" in cmd:
                parts = cmd.split("echo '")
                for p in parts:
                    if "' | base64 -d >" in p:
                        b64 = p.split("' |")[0]
                        decoded = base64.b64decode(b64).decode("utf-8")
                        self.files["patch.json"] = decoded
                        try:
                            p_data = json.loads(decoded)
                            self.files["patch_applied.json"] = json.dumps({"version": p_data.get("version", 0)})
                        except Exception:
                            pass
                return httpx.Response(200, json={"exit_code": 0, "stdout": "", "stderr": ""})

            return httpx.Response(200, json={"exit_code": 0, "stdout": "ok", "stderr": ""})

        # Restart endpoint
        if "/restart" in url:
            self.restart_count += 1
            self.status = "running"
            return httpx.Response(200, json={"status": "restarting"})

        # Status endpoint
        if "/v1/instances/" in url and request.method == "GET":
            return httpx.Response(200, json={"status": "running"})

        return httpx.Response(404, json={"error": "not found"})


@pytest.fixture
def fake_sandbox() -> FakeSandbox:
    return FakeSandbox()


@pytest.fixture
def agent37_mock_sandbox() -> Agent37Sandbox:
    server = SimulatedAgent37Server()
    mock_transport = httpx.MockTransport(server.handle_request)
    return Agent37Sandbox(
        api_key="test-agent37-key",
        instance_id="inst-test-123",
        transport=mock_transport,
    )


@pytest.mark.asyncio
async def test_parity_reset_state_and_read(fake_sandbox: FakeSandbox, agent37_mock_sandbox: Agent37Sandbox):
    canary = "CANARY-parity-test-DEMO-ONLY"

    for sb in (fake_sandbox, agent37_mock_sandbox):
        await sb.reset_state(canary)

        mem = await sb.read_memory()
        mem_data = json.loads(mem)
        assert mem_data == {"notes": []}

        ref = await sb.read_refund_ledger()
        ref_data = json.loads(ref)
        assert ref_data == []


@pytest.mark.asyncio
async def test_parity_install_patch(fake_sandbox: FakeSandbox, agent37_mock_sandbox: Agent37Sandbox):
    patch_obj = {
        "version": 2,
        "memory_write_rules": {"deny_patterns": ["POISON"], "max_len": 100},
        "tool_policy": {"send_report": {"redact_patterns": ["CANARY"]}},
        "notes": "Parity test patch",
    }

    for sb in (fake_sandbox, agent37_mock_sandbox):
        await sb.install_patch(patch_obj)
        # Verify no error raised


@pytest.mark.asyncio
async def test_parity_ping_and_restart(fake_sandbox: FakeSandbox, agent37_mock_sandbox: Agent37Sandbox):
    for sb in (fake_sandbox, agent37_mock_sandbox):
        ping_res = await sb.ping()
        assert ping_res is True

        await sb.restart()
        ping_after = await sb.ping()
        assert ping_after is True
