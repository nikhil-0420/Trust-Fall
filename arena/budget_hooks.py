"""
arena/budget_hooks.py
Minimal local budget governor reading LLM_DAILY_CAP and LYZR_DAILY_CAP.
Stops at 80% threshold to prevent unexpected billing.
Owner: Nehaa (WS-C C2, WS-D D4)
"""
import os
from typing import Optional


class LocalBudget:
    """
    Local budget governor checking against daily caps at 80% threshold.
    """

    def __init__(
        self,
        llm_cap: Optional[int] = None,
        lyzr_cap: Optional[int] = None,
        threshold: float = 0.8,
    ):
        if llm_cap is None:
            raw_llm = os.getenv("LLM_DAILY_CAP", "").strip()
            self.llm_cap = int(raw_llm) if raw_llm.isdigit() else 200
        else:
            self.llm_cap = llm_cap

        if lyzr_cap is None:
            raw_lyzr = os.getenv("LYZR_DAILY_CAP", "").strip()
            self.lyzr_cap = int(raw_lyzr) if raw_lyzr.isdigit() else 15
        else:
            self.lyzr_cap = lyzr_cap

        self.threshold = threshold
        self.llm_used = 0
        self.lyzr_used = 0

    def can_spend(self, kind: str, count: int = 1) -> bool:
        """Return True if spending count units would stay under 80% of cap."""
        if kind == "llm":
            return (self.llm_used + count) <= int(self.llm_cap * self.threshold)
        elif kind == "lyzr":
            return (self.lyzr_used + count) <= int(self.lyzr_cap * self.threshold)
        return True

    def spend(self, kind: str, count: int = 1) -> None:
        if kind == "llm":
            self.llm_used += count
        elif kind == "lyzr":
            self.lyzr_used += count

    def get_status(self) -> dict:
        return {
            "llm_used": self.llm_used,
            "llm_cap": self.llm_cap,
            "lyzr_used": self.lyzr_used,
            "lyzr_cap": self.lyzr_cap,
        }
