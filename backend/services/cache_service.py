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
#     NO   -> continue to the next question.
#   - Would red_flags_structured / strengths change for any ticker?
#     (New W-rule or I-rule added, severity threshold moved, allowlist
#     extended, etc.)
#     YES  -> bump required. Cached payloads predating the rule would
#             serve empty red_flags / strengths for affected tickers —
#             the UI then shows "Red Flags: None" and "No strengths
#             found" on stocks that should fire new rules.
#     NO   -> do not bump, even if you changed analysis_service.py
CACHE_VERSION = 48  # feat/xbrl-cache-pipeline (PR #48) backfill complete: 3,000 NSE tickers re-parsed from local XBRL cache with the FourD (year-to-date) context picker. 56,296 quarterly rows + 11,356 annual_synth rows written to `financials`; zero parse or store errors. This replaces ~25%-of-real-FY values (caused by OneD / standalone-quarter context preference) with ~99% accurate annual figures: BPCL FY24 rev 132,087 Cr -> 506,993 Cr, RELIANCE FY24 240,715 Cr -> 914,472 Cr, INFY FY24 37,923 Cr -> 153,670 Cr exact, etc. Bump forces every v47 cached analysis to recompute and pick up the corrected financials. BPCL MoS should drop from +131% (DCF extrapolating off Q4-only FCF) to a defensible ~20-40% range once prod re-reads. Zero frontend-contract changes; new optional fields (freshness stamps, sparkline inputs) were additive in v47-era PRs so existing cached payloads simply get the fields on recompute. Prior comment: v47=hotfix/dividend-session-factory: v46 dividend DB-first cascade imported `from backend.database import SessionLocal` which doesn't exist in this codebase — import raised ImportError, caught silently, DB-first path never ran in prod. TCS.NS still rendered stale yfinance yield 2.5% instead of the correct 4.32% (4 NSE payments × Rs.109 / CMP Rs.2521.80) despite v46 deploy. Fix: use the canonical `from backend.services.analysis_service import _get_pipeline_session` factory that every other router uses (see public.py:_get_db_session). Also log at INFO not DEBUG so future silent-fallthrough bugs are visible in Railway logs. Bump forces v46 cached payloads to recompute — without it TCS etc. would keep serving the stale yfinance data from v46's failed cascade. Prior comment: v46=fix/prism-pillars-completeness (stacked on fix/dividend-db-first v45). Two surface-fix families flushed together: (1) hex_service._fetch_core_data SQL used wrong column names (op_margin/fcf/eps/interest_coverage instead of operating_margin/free_cash_flow/eps_diluted; interest_coverage not on Financials at all). Every query raised UndefinedColumn silently, out["financials"] stayed [] — starving _axis_moat of op-margin stability and _axis_growth of revenue-CAGR fallback (TCS canary 2026-04-23 showed both axes "n/a"). Fixed column names + moat_score numeric fallback in _axis_moat + ticker-form expansion in market_metrics lookups (HDFCBANK bank-branch moat scale signal). (2) v45=DividendService DB-first cascade — reads corporate_actions table before yfinance .info fallback, so TCS's 20 NSE-recorded dividend payments actually surface in InsightCards.dividend instead of the "No dividends paid" sentinel that dropped through the old info-only path (dividend_service.py:74 early-return). Zero FV drift for both families: edits touch hex/prism/InsightCards.dividend surface only; DCF/MoS/fair_value pipeline untouched. v44=NBFC WACC floor. v43=moat floor Moderate band + strengths SSOT. v42=Day-3 W6+W9 rules. v41=PR-DET-2 + PR-D2 terminal_g clamp + NBFC WACC +50bps. v40=Day-3 sanity clamps. v39=Discover TTL. v38=PR-NTPC scenario order. v37=PR-BANKSC-2. v36=PR-BANKSC. v35=FV stability. v34=MoS formula. v33=scenarios. v32=MoS SoT.


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
