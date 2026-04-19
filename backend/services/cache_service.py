# backend/services/cache_service.py
# In-memory cache with TTL. Replace with Redis later if needed.
from __future__ import annotations
import threading
import time
from typing import Any, Optional

# Bump this integer ONLY when the DCF output (fair_value / MoS / verdict /
# score) for an EXISTING ticker would change vs the prior version. That is
# the single trigger. Every other change -- observability, new endpoints,
# error sanitization, logging, metadata, frontend wiring, schema additions
# that don't touch analysis output -- must NOT bump this.
# (This edit is a no-op trigger to force a Railway redeploy that kills a
# runaway background job. Not a semantic change.)
#
# Why the discipline matters: a bump invalidates every cached analysis in
# Railway memory. Users hitting the site during that window see 10-30s
# response times (yfinance fallback on uncached tickers) instead of the
# normal ~200ms. Today we bumped this 21 times in 12 hours and caused
# real latency problems. Don't do that again.
#
# Decision checklist before bumping:
#   - Would TCS / INFY / any existing top-100 ticker's fair_value change?
#     YES  -> bump required
#     NO   -> do not bump, even if you changed analysis_service.py
CACHE_VERSION = 40  # Day-3 sanity clamps: ROCE rounds-to-0.0% → None ("—"), Revenue CAGR 3y/5y outside ±50% → None, EV/EBITDA outside (0.5, 200) → None at response layer (defense-in-depth on top of local_data_service guard). Old payloads carry "0.0%" ROCE / "-75.5%" CAGR / "1217×" EV-EBITDA that fail audit; bump invalidates so v40 fresh computes apply the new clamps. v39=Discover TTL. v38=PR-NTPC scenario order. v37=PR-BANKSC-2. v36=PR-BANKSC. v35=FV stability. v34=MoS formula. v33=scenarios. v32=MoS SoT.


class CacheService:
    """Thread-safe in-memory cache with TTL + version-based invalidation."""

    def __init__(self):
        self._store: dict[str, tuple[Any, float, int]] = {}  # key -> (value, expires_at, version)
        self._lock = threading.Lock()

    def get(self, key: str) -> Optional[Any]:
        with self._lock:
            if key in self._store:
                entry = self._store[key]
                # Legacy entries without version → invalidate
                if len(entry) != 3:
                    del self._store[key]
                    return None
                value, expires_at, version = entry
                # Version mismatch → invalidate
                if version != CACHE_VERSION:
                    del self._store[key]
                    return None
                if time.time() < expires_at:
                    return value
                del self._store[key]
        return None

    def set(self, key: str, value: Any, ttl: int = 900) -> None:
        with self._lock:
            self._store[key] = (value, time.time() + ttl, CACHE_VERSION)

    def delete(self, key: str) -> None:
        with self._lock:
            self._store.pop(key, None)

    def clear(self) -> None:
        with self._lock:
            self._store.clear()

    def clear_pattern(self, prefix: str) -> int:
        """Remove all keys starting with prefix. Returns count."""
        with self._lock:
            matching = [k for k in self._store if k.startswith(prefix)]
            for k in matching:
                del self._store[k]
            return len(matching)

    def cleanup(self) -> int:
        """Remove expired entries. Returns count removed."""
        now = time.time()
        removed = 0
        with self._lock:
            expired: list[str] = []
            for k, entry in self._store.items():
                if len(entry) != 3 or entry[1] <= now or entry[2] != CACHE_VERSION:
                    expired.append(k)
            for k in expired:
                del self._store[k]
                removed += 1
        return removed


# Singleton
cache = CacheService()
