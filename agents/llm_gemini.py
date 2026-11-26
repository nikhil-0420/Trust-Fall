"""
Owner: Nikhil (Phase N1, updated C1)
Gemini LLM Adapter using google-genai SDK.
Implements the LLM protocol with exponential backoff on 429/503, on-disk caching, and budget limits.
"""
import asyncio
from datetime import datetime, timezone
import hashlib
import json
import os
import re
import time
from pathlib import Path

from google import genai
from google.genai import types

from arena.interfaces import LLM


class BudgetExceeded(Exception):
    """Raised when LLM calls exceed 80% of daily cap."""


class GeminiLLM(LLM):
    # Class-level pacing lock to prevent bursting across concurrent tasks
    _call_lock = asyncio.Lock()
    _last_call_time: float = 0.0
    _min_call_interval: float = 13.0  # 5 RPM limit -> 1 call every 12-13 seconds

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str | None = None,
        cache_dir: Path | None = None,
    ):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY")
        self.model_name = model_name or os.getenv("MODEL_NAME", "gemini-3.5-flash-lite")
        self.client = genai.Client(api_key=self.api_key) if self.api_key else None
        self.cache_dir = Path(cache_dir or "data/cache/llm")
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.call_count = 0

    def _get_cache_path(self, system: str, prompt: str, json_mode: bool, salt: str | None = None) -> Path:
        key = f"{self.model_name}::{system}::{prompt}::{json_mode}::{salt or ''}"
        digest = hashlib.sha256(key.encode("utf-8")).hexdigest()
        return self.cache_dir / f"{digest}.json"

    def _check_budget(self) -> None:
        cap_str = os.getenv("LLM_DAILY_CAP")
        if cap_str:
            try:
                cap = float(cap_str)
                if cap > 0 and self.call_count >= (cap * 0.8):
                    raise BudgetExceeded(
                        f"LLM call count {self.call_count} reached 80% of daily cap {cap}"
                    )
            except ValueError:
                pass

    def _log_call(self, purpose: str) -> None:
        try:
            now = datetime.now(timezone.utc).isoformat()
            ledger_path = Path("docs/CALL_LEDGER.md")
            if ledger_path.exists():
                with open(ledger_path, "a", encoding="utf-8") as f:
                    f.write(f"| {now} | Gemini ({self.model_name}) | {purpose} | 1 |\n")
        except Exception:
            pass

    @classmethod
    def get_min_interval(cls) -> float:
        val = os.getenv("GEMINI_MIN_INTERVAL_S")
        if val is not None:
            try:
                return float(val)
            except ValueError:
                pass
        return cls._min_call_interval

    async def _rate_limit_wait(self) -> None:
        interval = self.get_min_interval()
        if interval <= 0:
            return
        async with GeminiLLM._call_lock:
            now = time.time()
            elapsed = now - GeminiLLM._last_call_time
            if elapsed < interval:
                sleep_needed = interval - elapsed
                await asyncio.sleep(sleep_needed)
            GeminiLLM._last_call_time = time.time()

    def _extract_retry_delay(self, error_str: str, default_wait: float) -> float:
        # Check if error message provides a retry-after duration, and cap sleep at 20s
        m = re.search(r"retry[- ]after[:\s]+(\d+(?:\.\d+)?)", error_str, re.IGNORECASE)
        if m:
            try:
                val = float(m.group(1))
                return min(20.0, max(1.0, val))
            except Exception:
                pass
        return min(20.0, default_wait)

    async def switch_to_fallback_model(self, error: Exception) -> str:
        """Switch to fallback Flash model when primary exhausts limits."""
        old_model = self.model_name
        candidates = []
        try:
            models_pager = self.client.models.list()
            for m in models_pager:
                m_name = getattr(m, "name", "") or ""
                short_name = m_name.replace("models/", "")
                lower = short_name.lower()
                if "flash" in lower and not any(x in lower for x in ["pro", "image", "audio", "tts", "live", "embedding", "preview", "exp"]):
                    candidates.append(short_name)
        except Exception:
            candidates = ["gemini-3.5-flash", "gemini-2.5-flash", "gemini-1.5-flash"]

        def rank(name: str) -> int:
            if name == "gemini-3.5-flash":
                return 0
            if "2.5" in name:
                return 1
            if "1.5" in name:
                return 2
            return 3

        candidates.sort(key=rank)
        fallback = None
        for cand in candidates:
            if cand != old_model:
                try:
                    await self._rate_limit_wait()
                    await self.client.aio.models.generate_content(
                        model=cand,
                        contents="Ping",
                    )
                    fallback = cand
                    break
                except Exception:
                    continue

        if not fallback:
            fallback = "gemini-2.5-flash"

        self.model_name = fallback
        now = datetime.now(timezone.utc).isoformat()
        err_msg = str(error).replace("\n", " ")[:100]
        ledger_path = Path("docs/CALL_LEDGER.md")
        if ledger_path.exists():
            with open(ledger_path, "a", encoding="utf-8") as f:
                f.write(f"| {now} | Gemini Switch | {old_model} -> {fallback} ({err_msg}) | 1 |\n")
        return fallback

    async def complete(
        self,
        system: str,
        prompt: str,
        *,
        purpose: str,
        json_mode: bool = False,
        salt: str | None = None,
    ) -> str:
        # Check on-disk cache
        cache_file = self._get_cache_path(system, prompt, json_mode, salt)
        if cache_file.exists():
            try:
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                if "response" in data:
                    return data["response"]
            except Exception:
                pass

        # Check daily budget cap
        self._check_budget()

        if self.client is None:
            raise ValueError("GEMINI_API_KEY is not set or client could not be initialized.")

        config = types.GenerateContentConfig(
            system_instruction=system if system else None,
            response_mime_type="application/json" if json_mode else None,
        )

        waits = [5.0, 15.0, 20.0]  # Capped at 20s max
        last_error = None
        for attempt in range(3):
            try:
                await self._rate_limit_wait()
                self.call_count += 1
                resp = await asyncio.wait_for(
                    self.client.aio.models.generate_content(
                        model=self.model_name,
                        contents=prompt,
                        config=config,
                    ),
                    timeout=45.0,
                )
                self._log_call(purpose)
                text = resp.text or ""
                # Cache response
                try:
                    cache_file.write_text(
                        json.dumps({
                            "model": self.model_name,
                            "purpose": purpose,
                            "salt": salt,
                            "response": text,
                        }, indent=2),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
                return text
            except asyncio.TimeoutError as e:
                last_error = e
                self._log_call(f"gemini_timeout_45s_attempt_{attempt+1}")
                logger.warning(f"[GEMINI_TIMEOUT] Gemini call hung >45s on attempt {attempt+1}/3; abandoned.")
                sleep_time = min(20.0, waits[attempt])
                await asyncio.sleep(sleep_time)
                continue
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                if any(x in err_str for x in ["429", "503", "unavailable", "resource_exhausted", "quota"]):
                    sleep_time = min(20.0, self._extract_retry_delay(err_str, waits[attempt]))
                    self._log_call(f"429_backoff_{sleep_time:.1f}s")
                    logger.warning(
                        f"[GEMINI_RATE_LIMIT] 429/503 on attempt {attempt+1}/3: {err_str[:120]}. "
                        f"Sleeping for {sleep_time:.1f}s (capped at 20s)"
                    )
                    await asyncio.sleep(sleep_time)
                    continue
                raise e

        # If retries on primary model failed with quota/availability, switch model
        err_str = str(last_error).lower()
        if any(x in err_str for x in ["429", "503", "unavailable", "resource_exhausted", "quota"]) or isinstance(last_error, asyncio.TimeoutError):
            await self.switch_to_fallback_model(last_error)
            for fb_attempt in range(3):
                try:
                    await self._rate_limit_wait()
                    resp = await asyncio.wait_for(
                        self.client.aio.models.generate_content(
                            model=self.model_name,
                            contents=prompt,
                            config=config,
                        ),
                        timeout=45.0,
                    )
                    self._log_call(f"{purpose}_fallback")
                    text = resp.text or ""
                    try:
                        fb_cache_file = self._get_cache_path(system, prompt, json_mode, salt)
                        fb_cache_file.write_text(
                            json.dumps({
                                "model": self.model_name,
                                "purpose": purpose,
                                "salt": salt,
                                "response": text,
                            }, indent=2),
                            encoding="utf-8",
                        )
                    except Exception:
                        pass
                    return text
                except Exception as fb_e:
                    fb_err_str = str(fb_e).lower()
                    if any(x in fb_err_str for x in ["429", "503", "unavailable", "resource_exhausted", "quota"]):
                        fb_sleep = self._extract_retry_delay(fb_err_str, waits[fb_attempt])
                        await asyncio.sleep(fb_sleep)
                        continue
                    raise fb_e

        raise last_error or RuntimeError("Gemini call failed after retries")
