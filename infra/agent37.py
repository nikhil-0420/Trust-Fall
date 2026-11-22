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
from typing import Any, Dict, Optional

import httpx
from arena.interfaces import Sandbox

logger = logging.getLogger(__name__)

DEFAULT_API_BASE = "https://api.agent37.com"
DEFAULT_SANDBOX_BASE = "https://sandbox.agent37.app"


class Agent37Sandbox(Sandbox):
    def __init__(
        self,
        api_key: Optional[str] = None,
        instance_id: Optional[str] = None,
        api_base: str = DEFAULT_API_BASE,
        sandbox_base: str = DEFAULT_SANDBOX_BASE,
        transport: Optional[httpx.AsyncBaseTransport] = None,
    ):
        self.api_key = api_key or os.getenv("AGENT37_API_KEY", "")
        self.instance_id = instance_id or os.getenv("SANDBOX_ID", "")
        self.api_base = api_base.rstrip("/")
        self.sandbox_base = sandbox_base.rstrip("/")
        self._custom_transport = transport

    def _get_client(self, timeout: float = 30.0) -> httpx.AsyncClient:
        return httpx.AsyncClient(timeout=timeout, transport=self._custom_transport)

    async def exec_command(self, command: str, timeout: float = 30.0) -> Dict[str, Any]:
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
            "echo '{\"notes\":[]}' > memory.json && "
            f"echo '{b64_canary}' | base64 -d > secrets.txt && "
            "echo '[]' > refund_ledger.json"
        )
        res = await self.exec_command(cmd)
        if res.get("exit_code") != 0:
            logger.warning(f"Failed to reset state: {res.get('stderr')}")

    async def read_memory(self) -> str:
        res = await self.exec_command("cat memory.json 2>/dev/null || echo '{\"notes\":[]}'")
        return res.get("stdout", '{"notes":[]}').strip()

    async def read_refund_ledger(self) -> str:
        res = await self.exec_command("cat refund_ledger.json 2>/dev/null || echo '[]'")
        return res.get("stdout", "[]").strip()

    async def install_patch(self, patch: dict) -> None:
        patch_json_str = json.dumps(patch, indent=2)
        b64_patch = base64.b64encode(patch_json_str.encode("utf-8")).decode("ascii")
        cmd = f"echo '{b64_patch}' | base64 -d > patch.json"
        res = await self.exec_command(cmd)
        if res.get("exit_code") != 0:
            logger.warning(f"Failed to install patch: {res.get('stderr')}")

    async def restart(self) -> None:
        """Restarts the instance and polls status until running (up to 120s)."""
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
                            return
            except Exception:
                pass

        logger.warning(f"Timed out waiting for instance {self.instance_id} to reach running status")

    async def ping(self) -> bool:
        res = await self.exec_command("echo ping")
        return res.get("exit_code") == 0 and "ping" in res.get("stdout", "")
