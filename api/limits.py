"""
api/limits.py
In-memory thread-safe rate limiter and input guard for challenge mode.
Owner: Nehaa (WS-D D7)
"""
import threading
from datetime import datetime, timedelta, timezone

from api.budget import get_budget

IST = timezone(timedelta(hours=5, minutes=30))


class RateLimiter:
    """
    In-memory rate limiter enforcing:
    - 5 attempts per session ID per day
    - 15 attempts per IP address per day
    - Daily rollover at 00:00 IST
    - Thread-safe storage
    """

    def __init__(
        self,
        session_limit: int = 5,
        ip_limit: int = 15,
    ):
        self.session_limit = session_limit
        self.ip_limit = ip_limit
        self.lock = threading.Lock()
        self.date_str = self._current_ist_date()
        self.session_counts: dict[str, int] = {}
        self.ip_counts: dict[str, int] = {}

    def _current_ist_date(self) -> str:
        return datetime.now(IST).strftime("%Y-%m-%d")

    def _check_rollover(self) -> None:
        today = self._current_ist_date()
        if today != self.date_str:
            self.date_str = today
            self.session_counts.clear()
            self.ip_counts.clear()

    def check_limits(
        self,
        session_id: str | None,
        client_ip: str | None,
    ) -> tuple[bool, str | None, int]:
        """
        Check rate limits. Returns (allowed: bool, reason: Optional[str], retry_after: int).
        """
        with self.lock:
            self._check_rollover()

            # 1. Check IP limit
            if client_ip:
                ip_count = self.ip_counts.get(client_ip, 0)
                if ip_count >= self.ip_limit:
                    return False, "rate", 3600

            # 2. Check Session limit
            if session_id:
                sess_count = self.session_counts.get(session_id, 0)
                if sess_count >= self.session_limit:
                    return False, "rate", 3600

            # 3. Check Global Budget
            budget = get_budget()
            # If both LLM and Lyzr budget are over 80%
            b_status = budget.status()
            llm_cap = b_status["llm_cap"]
            llm_used = b_status["llm_used"]
            if llm_used >= int(llm_cap * 0.8):
                return False, "budget", 3600

            # Record attempt
            if client_ip:
                self.ip_counts[client_ip] = self.ip_counts.get(client_ip, 0) + 1
            if session_id:
                self.session_counts[session_id] = self.session_counts.get(session_id, 0) + 1

            return True, None, 0


_limiter_instance: RateLimiter | None = None


def get_rate_limiter() -> RateLimiter:
    global _limiter_instance
    if _limiter_instance is None:
        _limiter_instance = RateLimiter()
    return _limiter_instance
