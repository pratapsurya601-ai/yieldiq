# backend/middleware/rate_limit.py
# In-memory rate limiter keyed by user_id + date. Thread-safe.
from __future__ import annotations
from collections import defaultdict
from datetime import date
import threading


class RateLimiter:
    """Daily rate limiter per user. Resets at midnight UTC."""

    TIER_LIMITS = {
        "free": 3,
        "starter": 25,
        "pro": 999999,
    }

    def __init__(self):
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()

    def check_and_increment(self, user_id: str, tier: str) -> tuple[bool, int, int]:
        """
        Returns: (allowed, used_today, limit)
        """
        limit = self.TIER_LIMITS.get(tier, 5)
        key = f"{user_id}:{date.today().isoformat()}"
        with self._lock:
            current = self._counts[key]
            if current >= limit:
                return False, current, limit
            self._counts[key] += 1
            return True, current + 1, limit

    def get_usage(self, user_id: str, tier: str) -> tuple[int, int]:
        """Get current usage without incrementing."""
        limit = self.TIER_LIMITS.get(tier, 5)
        key = f"{user_id}:{date.today().isoformat()}"
        with self._lock:
            return self._counts.get(key, 0), limit

    def cleanup_old(self) -> int:
        """Remove entries from previous days."""
        today = date.today().isoformat()
        removed = 0
        with self._lock:
            old_keys = [k for k in self._counts if not k.endswith(today)]
            for k in old_keys:
                del self._counts[k]
                removed += 1
        return removed


rate_limiter = RateLimiter()
