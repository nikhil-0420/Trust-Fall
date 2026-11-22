"""
api/budget.py
Budget governor persisted in data/budget.json with IST daily resets.
Owner: Nehaa (WS-D D4)
"""
import asyncio
import json
import os
import threading
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

IST = timezone(timedelta(hours=5, minutes=30))


class BudgetExceeded(Exception):
    """Raised when daily API budget threshold (80%) is exceeded or rate limit persists."""


class Budget:
    """
    Persisted daily budget governor enforcing 80% spending threshold.
    Resets at 00:00 IST.
    """

    def __init__(
        self,
        filepath: str = "data/budget.json",
        llm_cap: int | None = None,
        lyzr_cap: int | None = None,
        threshold: float = 0.8,
    ):
        self.filepath = Path(filepath)
        self.threshold = threshold
        self.lock = threading.Lock()
        self.listeners: list[Callable[[dict[str, int]], Any]] = []

        raw_llm = os.getenv("LLM_DAILY_CAP", "").strip()
        default_llm = int(raw_llm) if raw_llm.isdigit() else 200
        self.llm_cap = llm_cap if llm_cap is not None else default_llm

        raw_lyzr = os.getenv("LYZR_DAILY_CAP", "").strip()
        default_lyzr = int(raw_lyzr) if raw_lyzr.isdigit() else 15
        self.lyzr_cap = lyzr_cap if lyzr_cap is not None else default_lyzr

        self.llm_used = 0
        self.lyzr_used = 0
        self.date_str = self._current_ist_date()

        self._load()

    def _current_ist_date(self) -> str:
        return datetime.now(IST).strftime("%Y-%m-%d")

    def _load(self) -> None:
        with self.lock:
            today = self._current_ist_date()
            if self.filepath.exists():
                try:
                    with open(self.filepath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if data.get("date") == today:
                        self.llm_used = data.get("llm_used", 0)
                        self.lyzr_used = data.get("lyzr_used", 0)
                        if "llm_cap" in data:
                            self.llm_cap = data["llm_cap"]
                        if "lyzr_cap" in data:
                            self.lyzr_cap = data["lyzr_cap"]
                        self.date_str = today
                        return
                except Exception:
                    pass

            # Reset for fresh day
            self.llm_used = 0
            self.lyzr_used = 0
            self.date_str = today
            self._save_locked()

    def _save_locked(self) -> None:
        self.filepath.parent.mkdir(parents=True, exist_ok=True)
        data = {
            "date": self.date_str,
            "llm_used": self.llm_used,
            "llm_cap": self.llm_cap,
            "lyzr_used": self.lyzr_used,
            "lyzr_cap": self.lyzr_cap,
        }
        try:
            with open(self.filepath, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
        except Exception:
            pass

    def add_listener(self, callback: Callable[[dict[str, int]], Any]) -> None:
        if callback not in self.listeners:
            self.listeners.append(callback)

    def _notify(self) -> None:
        st = self.status()
        for cb in self.listeners:
            try:
                res = cb(st)
                if asyncio.iscoroutine(res):
                    asyncio.create_task(res)
            except Exception:
                pass

    def can_spend(self, kind: str, count: int = 1) -> bool:
        """
        Check if spend would stay under 80% cap without deducting.
        """
        with self.lock:
            today = self._current_ist_date()
            if today != self.date_str:
                return True
            if kind == "llm":
                limit = int(self.llm_cap * self.threshold)
                return (self.llm_used + count) <= limit
            elif kind == "lyzr":
                limit = int(self.lyzr_cap * self.threshold)
                return (self.lyzr_used + count) <= limit
            return True

    def try_spend(self, kind: str, count: int = 1) -> bool:
        """
        Check if spend would stay under 80% cap. If so, deduct and persist immediately.
        Returns False if 80% threshold would be exceeded.
        """
        with self.lock:
            # Check for date rollover
            today = self._current_ist_date()
            if today != self.date_str:
                self.date_str = today
                self.llm_used = 0
                self.lyzr_used = 0

            if kind == "llm":
                limit = int(self.llm_cap * self.threshold)
                if (self.llm_used + count) > limit:
                    return False
                self.llm_used += count
            elif kind == "lyzr":
                limit = int(self.lyzr_cap * self.threshold)
                if (self.lyzr_used + count) > limit:
                    return False
                self.lyzr_used += count

            self._save_locked()

        self._notify()
        return True

    def spend(self, kind: str, count: int = 1) -> None:
        """Record usage regardless of threshold."""
        with self.lock:
            if kind == "llm":
                self.llm_used += count
            elif kind == "lyzr":
                self.lyzr_used += count
            self._save_locked()
        self._notify()

    def status(self) -> dict[str, int]:
        with self.lock:
            return {
                "llm_used": self.llm_used,
                "llm_cap": self.llm_cap,
                "lyzr_used": self.lyzr_used,
                "lyzr_cap": self.lyzr_cap,
            }


async def call_with_gemini_retry(
    coroutine_func: Callable[[], Any],
    max_retries: int = 3,
    initial_delay: float = 0.1,
) -> Any:
    """
    Exponential backoff helper for handling rate limits (429) from LLM APIs.
    """
    delay = initial_delay
    last_err = None
    for attempt in range(max_retries):
        try:
            return await coroutine_func()
        except Exception as e:
            last_err = e
            err_msg = str(e).lower()
            if "429" in err_msg or "quota" in err_msg or "resource_exhausted" in err_msg:
                if attempt == max_retries - 1:
                    raise BudgetExceeded(f"Gemini 429 rate limit exceeded after {max_retries} tries: {e}")
                await asyncio.sleep(delay)
                delay *= 2
            else:
                raise e
    raise BudgetExceeded(f"Call failed: {last_err}")


_budget_instance: Budget | None = None


def get_budget() -> Budget:
    global _budget_instance
    if _budget_instance is None:
        _budget_instance = Budget()
    return _budget_instance
