"""
Owner: Nikhil (Phase N2)
GateClient implementing the Gate protocol.
Communicates with the internal gate screening service over HTTP.
Fails CLOSED on any error or timeout (returns ERROR and blocked=True).
"""
import os

import httpx

from arena.interfaces import Gate, GateResult
from arena.mocks import MockGate


class GateClient(Gate):
    def __init__(
        self,
        gate_url: str | None = None,
        internal_token: str | None = None,
        use_mock: bool | None = None,
    ):
        self.gate_url = gate_url or os.getenv("GATE_URL", "http://127.0.0.1:8000")
        self.internal_token = internal_token or os.getenv("INTERNAL_TOKEN", "")
        if use_mock is not None:
            self.use_mock = use_mock
        else:
            val = os.getenv("USE_MOCKS", "1").strip().lower()
            self.use_mock = val in {"1", "true", "yes"}

        self._mock_gate = MockGate()

    async def screen(self, text: str, stage: str = "pre_dispatch") -> GateResult:
        if self.use_mock:
            return await self._mock_gate.screen(text, stage=stage)

        endpoint = f"{self.gate_url.rstrip('/')}/internal/screen"
        headers = {
            "X-Internal-Token": self.internal_token,
            "Content-Type": "application/json",
        }
        payload = {"text": text, "stage": stage}

        try:
            async with httpx.AsyncClient(timeout=5.0) as client:
                resp = await client.post(endpoint, json=payload, headers=headers)
                if resp.status_code == 200:
                    data = resp.json()
                    decision = data.get("decision", "SAFE")
                    confidence = float(data.get("confidence", 0.0))
                    cached = bool(data.get("cached", False))
                    blocked = (decision == "INJECTION")
                    return GateResult(
                        decision=decision,
                        confidence=confidence,
                        cached=cached,
                        blocked=blocked,
                    )
                else:
                    # Fail closed on non-200
                    return GateResult(
                        decision="ERROR",
                        confidence=1.0,
                        cached=False,
                        blocked=True,
                    )
        except Exception:
            # Fail closed on timeout or connection error
            return GateResult(
                decision="ERROR",
                confidence=1.0,
                cached=False,
                blocked=True,
            )
