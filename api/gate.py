"""
api/gate.py
Lyzr Prompt Injection Detector client and Gate protocol implementation.
Owner: Nehaa (WS-D D3)
"""
import hashlib
import json
import os
from pathlib import Path
from typing import Any

import httpx

from api.budget import get_budget
from arena.interfaces import Gate, GateResult
from arena.mocks import MockGate

LYZR_DETECTOR_URL = "https://rai-prod.studio.lyzr.ai/prompt-injection-dectector/"


class LyzrGate(Gate):
    """
    Prompt injection screening gate utilizing Lyzr API with fail-closed behavior,
    SHA-256 disk caching, budget governor integration, and mock fallback.
    """

    def __init__(
        self,
        api_key: str | None = None,
        cache_dir: str = "data/cache/gate",
        timeout_s: float = 20.0,
    ):
        self.api_key = api_key or os.getenv("LYZR_API_KEY")
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.timeout_s = timeout_s
        self.mock_gate = MockGate()
        self.consecutive_real_errors = 0

    def _hash(self, text: str, impl: str = "lyzr") -> str:
        # Cache key includes implementation name (lyzr vs mock)
        return hashlib.sha256(f"{impl}:{text.strip()}".encode("utf-8")).hexdigest()

    def _read_cache(self, text_hash: str, required_impl: str | None = None) -> dict[str, Any] | None:
        cf = self.cache_dir / f"{text_hash}.json"
        if cf.exists():
            try:
                with open(cf, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if required_impl:
                        # Ignore entries not matching the required implementation (e.g. untagged or mock-tagged)
                        if data.get("impl") != required_impl:
                            return None
                    return data
            except Exception:
                return None
        return None

    def _write_cache(self, text_hash: str, data: dict[str, Any]) -> None:
        cf = self.cache_dir / f"{text_hash}.json"
        try:
            with open(cf, "w", encoding="utf-8") as f:
                json.dump(data, f)
        except Exception:
            pass

    async def screen(self, text: str, stage: str = "inbound") -> GateResult:
        """
        Screen text for prompt injection.
        - Cap at 500 characters
        - Check disk cache with implementation provenance (zero live calls on hit)
        - In mock mode (USE_MOCKS=1 or no key), use MockGate
        - On timeout (5s), error, or budget exhaustion -> FAIL CLOSED (blocked=True, decision=ERROR)
        """
        truncated_text = text[:500]
        use_mocks = os.getenv("USE_MOCKS", "1").strip().lower() in {"1", "true", "yes"}
        target_impl = "mock" if (use_mocks or not self.api_key) else "lyzr"
        text_hash = self._hash(truncated_text, impl=target_impl)

        # 1. Disk Cache check
        cached_val = self._read_cache(text_hash, required_impl=target_impl)
        if cached_val is not None:
            return GateResult(
                decision=cached_val["decision"],
                confidence=float(cached_val["confidence"]),
                cached=True,
                blocked=bool(cached_val["blocked"]),
            )

        # 2. Check mock mode
        if use_mocks or not self.api_key:
            res = await self.mock_gate.screen(truncated_text, stage)
            # Store in cache tagged with mock provenance
            self._write_cache(
                text_hash,
                {
                    "impl": "mock",
                    "decision": res.decision,
                    "confidence": res.confidence,
                    "blocked": res.blocked,
                },
            )
            return res

        # 3. Check Budget
        budget = get_budget()
        if not budget.try_spend("lyzr", 1):
            # Budget exhausted -> Fail closed
            return GateResult(
                decision="ERROR",
                confidence=1.0,
                cached=False,
                blocked=True,
            )

        # 4. Live Lyzr API call
        headers = {
            "x-api-key": self.api_key,
            "Content-Type": "application/json",
        }
        payload = {"input_text": truncated_text}

        try:
            async with httpx.AsyncClient(timeout=self.timeout_s) as client:
                response = await client.post(LYZR_DETECTOR_URL, headers=headers, json=payload)

            if response.status_code != 200:
                self.consecutive_real_errors += 1
                if self.consecutive_real_errors >= 3:
                    raise RuntimeError("INVALID-GATE: 3 consecutive REAL Lyzr calls returned ERROR")
                return GateResult(decision="ERROR", confidence=1.0, cached=False, blocked=True)

            self.consecutive_real_errors = 0
            data = response.json()
            message = str(data.get("message", "")).upper()
            details = data.get("details", {})
            is_injection = details.get("is_injection", (message == "INJECTION"))
            confidence = float(details.get("confidence", 0.96 if is_injection else 0.04))

            decision = "INJECTION" if is_injection else "SAFE"
            blocked = bool(is_injection)

            # Persist to disk cache tagged with live Lyzr provenance
            self._write_cache(
                text_hash,
                {
                    "impl": "lyzr",
                    "decision": decision,
                    "confidence": confidence,
                    "blocked": blocked,
                },
            )

            return GateResult(
                decision=decision,
                confidence=confidence,
                cached=False,
                blocked=blocked,
            )

        except (httpx.TimeoutException, httpx.RequestError, json.JSONDecodeError, Exception) as exc:
            if "INVALID-GATE" in str(exc):
                raise exc
            self.consecutive_real_errors += 1
            if self.consecutive_real_errors >= 3:
                raise RuntimeError("INVALID-GATE: 3 consecutive REAL Lyzr calls returned ERROR") from exc
            # Fail closed on any network error or timeout
            return GateResult(
                decision="ERROR",
                confidence=1.0,
                cached=False,
                blocked=True,
            )
