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
CACHE_VERSION = 51  # hotfix/hex-axis-fixes (PR #58, 2026-04-24 PM): three targeted HEX scoring bugs fixed based on the Phase 2 audit (docs/audit/HEX_AXIS_SOURCE_MAP.md + SCORING_GROUND_TRUTH.md). Bug #1: D/E unit normalisation in _axis_safety — yfinance returns debtToEquity as percent (45.0 = 45%) but formula expected decimal (0.45); guard added to divide by 100 when raw value > 5. Fixes RELIANCE / ASIANPAINT / POWERGRID / NTPC / L&T Safety collapse (expected ~3/10 -> ~6/10). Bug #2: NBFC-specific Value formula in _axis_value_bank — BAJFINANCE / BAJAJFINSV / CHOLAFIN / MUTHOOTFIN were routed through bank Value (anchor P/BV 2.5x) but NBFCs structurally trade at 3-6x; new branch detects NBFC and uses anchor 3.5x with gentler slope. Expected BAJFINANCE composite 22 -> 55-65. Bug #3 Part B: bank Growth fallback in _axis_growth — when advances_yoy/deposits_yoy/pat_yoy_bank are all None (stale pre-2026-04-21 cache or missed _is_bank_like classification), fall through to general-branch revenue/EPS CAGR instead of returning neutral 5.0. Affects HDFCBANK / ICICIBANK / KOTAKBANK / SBIN / AXISBANK; expected composite 17 -> 55+ on first recompute. Bump forces every v50-cached payload to recompute. After Railway deploy, browser-verify HDFCBANK (expect 70-80), RELIANCE (expect 65-75), BAJFINANCE (expect 55-65). Separate PRs still pending: PR #57 parser fix (nse_xbrl_fundamentals.py:340) + PR #59 billing webhook (propagate tier to raw_user_meta_data + store amount_paise + normalise email case). v50=hotfix/pre-launch-cleanup (2026-04-24 PM): three additional data patches applied to Neon prod financials table before evening launch. (1) Currency mis-tag fix: 410 rows across 14 Indian IT+pharma tickers (INFY, HCLTECH, WIPRO, TECHM, MPHASIS, COFORGE, PERSISTENT, DIVISLAB, CYIENT, OFSS, LAURUSLABS, KPITTECH, TATAELXSI, MASTEK) had currency='USD' but values were already in INR Crores; FX multiplier was 83x'ing them, which silently broke the Revenue CAGR computation via _sanitize_cagr >50% clamp. Tag corrected to 'INR'. (2) INFY revenue patch: FY23/FY24/FY25 annual rows were broken by the same OneD/FourD parser bug and had no viable source in company_financials (also broken for INFY); hardcoded with published investor-relations values (153,670 FY24, 146,767 FY23, 162,990 FY25). (3) NESTLEIND fiscal-year cleanup: deleted the bogus 2024-03-31 annual NSE_XBRL row (Nestle uses Jan-Dec; the row was Q1 2024 mislabeled). Remaining Nestle annuals are legitimate Dec-end yfinance rows. This bump forces every v49-cached payload to recompute and pick up all three patches. Expected: HCLTECH score jumps 37->60-75, INFY score becomes sensible, NESTLE CAGR series becomes monotone. Permanent parser fix (nse_xbrl_fundamentals.py:340 context-name vs duration) lands later in PR #57. v49=hotfix/data-patch-onedfourd-bug (PR #56): emergency data patch applied to prod Neon financials table on 2026-04-24 to protect first paying subscriber. 2,710 revenue rows + 2,769 pat rows + 213 cfo rows copied from company_financials into financials for NSE_XBRL-tagged rows. Root cause was _detect_period_type_from_contexts() at nse_xbrl_fundamentals.py:340 looking at context DURATIONS (all 90 days for Q4 files) instead of context NAMES (FourD vs OneD), silently demoting annual to quarterly and picking OneD Q4-standalone values. Affected HCLTECH FY24 (12,077 -> 109,913), BPCL FY24 (132,087 -> 446,666), etc. Patched in prod via docs/ops/TEMP_patch_2026-04-24.md. Bump forces every v48 cached analysis_cache payload to recompute and pick up the corrected revenue/pat/cfo. Also includes Fix B: forecaster.py _compute_fcf_base gets a sector-gated 5y median cyclical override (oil_gas/metals/cement/chemicals/auto/sugar/airlines) so BPCL-style FY24-inventory-gain outliers don't propagate into terminal. BPCL MoS should drop from +131% (both bugs compounding) toward a defensible +25-45% band. Permanent parser fix lands separately in PR #57 (7-line diff in nse_xbrl_fundamentals.py). After PR #57 + re-backfill, the TEMP data patch can be removed. Prior comment: v48=feat/xbrl-cache-pipeline (PR #48) backfill complete: 3,000 NSE tickers re-parsed from local XBRL cache with the FourD (year-to-date) context picker. 56,296 quarterly rows + 11,356 annual_synth rows written to `financials`; zero parse or store errors. This replaces ~25%-of-real-FY values (caused by OneD / standalone-quarter context preference) with ~99% accurate annual figures: BPCL FY24 rev 132,087 Cr -> 506,993 Cr, RELIANCE FY24 240,715 Cr -> 914,472 Cr, INFY FY24 37,923 Cr -> 153,670 Cr exact, etc. Bump forces every v47 cached analysis to recompute and pick up the corrected financials. BPCL MoS should drop from +131% (DCF extrapolating off Q4-only FCF) to a defensible ~20-40% range once prod re-reads. Zero frontend-contract changes; new optional fields (freshness stamps, sparkline inputs) were additive in v47-era PRs so existing cached payloads simply get the fields on recompute. Prior comment: v47=hotfix/dividend-session-factory: v46 dividend DB-first cascade imported `from backend.database import SessionLocal` which doesn't exist in this codebase — import raised ImportError, caught silently, DB-first path never ran in prod. TCS.NS still rendered stale yfinance yield 2.5% instead of the correct 4.32% (4 NSE payments × Rs.109 / CMP Rs.2521.80) despite v46 deploy. Fix: use the canonical `from backend.services.analysis_service import _get_pipeline_session` factory that every other router uses (see public.py:_get_db_session). Also log at INFO not DEBUG so future silent-fallthrough bugs are visible in Railway logs. Bump forces v46 cached payloads to recompute — without it TCS etc. would keep serving the stale yfinance data from v46's failed cascade. Prior comment: v46=fix/prism-pillars-completeness (stacked on fix/dividend-db-first v45). Two surface-fix families flushed together: (1) hex_service._fetch_core_data SQL used wrong column names (op_margin/fcf/eps/interest_coverage instead of operating_margin/free_cash_flow/eps_diluted; interest_coverage not on Financials at all). Every query raised UndefinedColumn silently, out["financials"] stayed [] — starving _axis_moat of op-margin stability and _axis_growth of revenue-CAGR fallback (TCS canary 2026-04-23 showed both axes "n/a"). Fixed column names + moat_score numeric fallback in _axis_moat + ticker-form expansion in market_metrics lookups (HDFCBANK bank-branch moat scale signal). (2) v45=DividendService DB-first cascade — reads corporate_actions table before yfinance .info fallback, so TCS's 20 NSE-recorded dividend payments actually surface in InsightCards.dividend instead of the "No dividends paid" sentinel that dropped through the old info-only path (dividend_service.py:74 early-return). Zero FV drift for both families: edits touch hex/prism/InsightCards.dividend surface only; DCF/MoS/fair_value pipeline untouched. v44=NBFC WACC floor. v43=moat floor Moderate band + strengths SSOT. v42=Day-3 W6+W9 rules. v41=PR-DET-2 + PR-D2 terminal_g clamp + NBFC WACC +50bps. v40=Day-3 sanity clamps. v39=Discover TTL. v38=PR-NTPC scenario order. v37=PR-BANKSC-2. v36=PR-BANKSC. v35=FV stability. v34=MoS formula. v33=scenarios. v32=MoS SoT.


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
