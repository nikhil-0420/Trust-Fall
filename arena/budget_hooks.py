"""
arena/budget_hooks.py
Budget governor integration wrapping api.budget.Budget.
Owner: Nehaa (WS-C C2, WS-D D4)
"""
from api.budget import Budget


class LocalBudget(Budget):
    """
    Subclass of api.budget.Budget providing can_spend/get_status compatibility.
    """

    def can_spend(self, kind: str, count: int = 1) -> bool:
        """Check if spending count units would stay under 80% threshold without deducting yet."""
        with self.lock:
            if kind == "llm":
                return (self.llm_used + count) <= int(self.llm_cap * self.threshold)
            elif kind == "lyzr":
                return (self.lyzr_used + count) <= int(self.lyzr_cap * self.threshold)
            return True

    def get_status(self) -> dict:
        return self.status()
