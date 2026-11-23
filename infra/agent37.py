"""
Owner: Nikhil (Phase N4)
Agent37 Sandbox integration layer.
Implements the Sandbox protocol using the Agent37 management and exec APIs.
Uses retries with backoff, strict timeouts, and never logs API keys.
"""
import asyncio
import base64
import json
import logging
import os
from typing import Any

import httpx

from arena.interfaces import Sandbox

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.agent37.com"
DEFAULT_SANDBOX_BASE = "https://sandbox.agent37.app"


class Agent37Sandbox(Sandbox):
    def __init__(
        self,
        api_key: str | None = None,
        instance_id: str | None = None,
        api_base: str = DEFAULT_API_BASE,
        sandbox_base: str = DEFAULT_SANDBOX_BASE,
        transport: httpx.AsyncBaseTransport | None = None,
    ):
        self.api_key = api_key or os.getenv("AGENT37_API_KEY", "")
        self.instance_id = instance_id or os.getenv("SANDBOX_ID", "")
        self.api_base = api_base.rstrip("/")
        self.sandbox_base = sandbox_base.rstrip("/")
        self._custom_transport = transport

    def _get_client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._custom_transport)

    async def exec_command(self, command: str, timeout: float = 30.0) -> dict[str, Any]:
        """Executes a command inside the instance via the sandbox exec API."""
        if not self.instance_id:
            raise ValueError("SANDBOX_ID / instance_id is required to exec commands")

        url = f"{self.sandbox_base}/v1/instances/{self.instance_id}/exec"
        headers = {
            "X-Agent37-Key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {"command": command}

        for attempt in range(3):
            try:
                async with self._get_client(timeout=timeout) as client:
                    resp = await client.post(url, headers=headers, json=payload)
                    if resp.status_code == 200:
                        return resp.json()
                    elif resp.status_code >= 500:
                        await asyncio.sleep(2**attempt)
                        continue
                    else:
                        return {"exit_code": resp.status_code, "stdout": "", "stderr": resp.text}
            except Exception as e:
                if attempt == 2:
                    return {"exit_code": -1, "stdout": "", "stderr": str(e)}
                await asyncio.sleep(2**attempt)

        return {"exit_code": -1, "stdout": "", "stderr": "Execution timed out after retries"}

    async def reset_state(self, canary: str) -> None:
        """
        Clears memory.json to {"notes":[]}, writes secrets.txt with canary,
        and clears refund_ledger.json.
        """
        b64_canary = base64.b64encode(canary.encode("utf-8")).decode("ascii")
        cmd = (
            "mkdir -p data/worker_state && "
            "echo '{\"notes\":[]}' > memory.json && "
            "cp memory.json data/worker_state/memory.json && "
            f"echo '{b64_canary}' | base64 -d > secrets.txt && "
            "cp secrets.txt data/worker_state/secrets.txt && "
            "echo '[]' > refund_ledger.json && "
            "cp refund_ledger.json data/worker_state/refund_ledger.json"
        )
        res = await self.exec_command(cmd)
        if res.get("exit_code") != 0:
            logger.warning(f"Failed to reset state: {res.get('stderr')}")

    async def read_memory(self) -> str:
        res = await self.exec_command("cat data/worker_state/memory.json 2>/dev/null || cat memory.json 2>/dev/null || echo '{\"notes\":[]}'")
        return res.get("stdout", '{"notes":[]}').strip()

    async def read_refund_ledger(self) -> str:
        res = await self.exec_command("cat data/worker_state/refund_ledger.json 2>/dev/null || cat refund_ledger.json 2>/dev/null || echo '[]'")
        return res.get("stdout", "[]").strip()

    async def install_patch(self, patch: dict) -> None:
        """
        Hot-installs patch.json atomically without restarting the sandbox.
        Verifies active patch version via patch_applied.json (polling up to 30s).
        """
        target_version = patch.get("version", 0) if patch else 0
        patch_json_str = json.dumps(patch or {}, indent=2)
        b64_patch = base64.b64encode(patch_json_str.encode("utf-8")).decode("ascii")
        # Atomic write: write to temp file then rename
        cmd = f"echo '{b64_patch}' | base64 -d > patch.json.tmp && mv patch.json.tmp patch.json"
        res = await self.exec_command(cmd)
        if res.get("exit_code") != 0:
            raise RuntimeError(f"Failed to install patch: {res.get('stderr')}")

        # Poll patch_applied.json up to 30s
        deadline = asyncio.get_event_loop().time() + 30.0
        while asyncio.get_event_loop().time() < deadline:
            res_applied = await self.exec_command("cat patch_applied.json 2>/dev/null")
            stdout = res_applied.get("stdout", "").strip()
            if stdout:
                try:
                    data = json.loads(stdout)
                    if data.get("version") == target_version:
                        return
                except Exception:
                    pass
            await asyncio.sleep(1.0)

        raise TimeoutError(f"Patch version verification timed out for version {target_version}")

    async def restart(self) -> None:
        """Restarts the instance and polls status until running and worker is ready (up to 120s)."""
        if not self.instance_id:
            raise ValueError("SANDBOX_ID / instance_id is required to restart")

        url = f"{self.api_base}/v1/instances/{self.instance_id}/restart"
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        async with self._get_client(timeout=15.0) as client:
            resp = await client.post(url, headers=headers)
            if resp.status_code not in (200, 202):
                logger.warning(f"Restart request failed with status {resp.status_code}: {resp.text}")

        # Poll status until 'running'
        status_url = f"{self.api_base}/v1/instances/{self.instance_id}"
        deadline = asyncio.get_event_loop().time() + 120.0

        while asyncio.get_event_loop().time() < deadline:
            await asyncio.sleep(2.0)
            try:
                async with self._get_client(timeout=10.0) as client:
                    resp = await client.get(status_url, headers=headers)
                    if resp.status_code == 200:
                        status = resp.json().get("status")
                        if status == "running":
                            # Remove stale ready marker before running launcher
                            await self.exec_command("rm -f /home/node/worker_ready.marker")

                            # Execute unified launcher
                            launch_cmd = (
                                "if [ -f /home/node/run_worker.sh ]; then "
                                "    /bin/bash /home/node/run_worker.sh; "
                                "elif [ -f /home/node/.agent37/hooks/post-restart.sh ]; then "
                                "    /bin/bash /home/node/.agent37/hooks/post-restart.sh; "
                                "else "
                                "    cd /home/node && (nohup python3 -u worker_band.py >> worker.log 2>&1 & disown); "
                                "fi"
                            )
                            await self.exec_command(launch_cmd)

                            # Poll for fresh ready marker (up to 30s)
                            m_deadline = asyncio.get_event_loop().time() + 30.0
                            while asyncio.get_event_loop().time() < m_deadline:
                                res_marker = await self.exec_command("cat /home/node/worker_ready.marker 2>/dev/null")
                                marker_str = res_marker.get("stdout", "").strip()
                                if marker_str:
                                    try:
                                        ts = float(marker_str)
                                        if ts > 0:
                                            return
                                    except ValueError:
                                        return
                                await asyncio.sleep(1.0)
                            return
            except Exception:
                pass

        logger.warning(f"Timed out waiting for instance {self.instance_id} to reach running status")

    async def ping(self) -> bool:
        res = await self.exec_command("echo ping")
        return res.get("exit_code") == 0 and "ping" in res.get("stdout", "")
