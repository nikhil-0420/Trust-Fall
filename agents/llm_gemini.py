"""
Owner: Nikhil (Phase N1)
Gemini LLM Adapter using google-genai SDK.
Implements the LLM protocol with exponential backoff on 429, on-disk caching, and budget limits.
"""
import asyncio
import hashlib
import json
import os
from pathlib import Path

from google import genai
from google.genai import types

from arena.interfaces import LLM


class BudgetExceeded(Exception):
    """Raised when LLM calls exceed 80% of daily cap."""


class GeminiLLM(LLM):
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

    def _get_cache_path(self, system: str, prompt: str, json_mode: bool) -> Path:
        key = f"{self.model_name}::{system}::{prompt}::{json_mode}"
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

    async def complete(
        self,
        system: str,
        prompt: str,
        *,
        purpose: str,
        json_mode: bool = False,
    ) -> str:
        # Check on-disk cache
        cache_file = self._get_cache_path(system, prompt, json_mode)
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

        # Exponential backoff for 429
        last_error = None
        for attempt in range(3):
            try:
                self.call_count += 1
                resp = await self.client.aio.models.generate_content(
                    model=self.model_name,
                    contents=prompt,
                    config=config,
                )
                text = resp.text or ""
                # Cache response
                try:
                    cache_file.write_text(
                        json.dumps({
                            "model": self.model_name,
                            "purpose": purpose,
                            "response": text,
                        }, indent=2),
                        encoding="utf-8",
                    )
                except Exception:
                    pass
                return text
            except Exception as e:
                last_error = e
                err_str = str(e).lower()
                if "429" in err_str or "503" in err_str or "unavailable" in err_str or "resource_exhausted" in err_str or "quota" in err_str:
                    await asyncio.sleep(2 ** attempt)
                    continue
                raise e

        raise last_error or RuntimeError("Gemini call failed after retries")
