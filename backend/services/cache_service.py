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
CACHE_VERSION = 65  # fix/normalize-pct-bound-correction (2026-04-28): _normalize_pct heuristic window narrowed from ±5 to ±1; previously-cached ROE/ROCE/ROA values for low-margin stocks were double-multiplied (e.g. GRASIM ROE 2.35% surfaced as 235%, ROCE 3.5% as 350%) and need recomputation. yfinance returns these ratios as decimals bounded by [-1, 1], so any |v| >= 1 is already in percent form and must NOT be re-multiplied. Bump forces every v64 cached analysis payload to recompute against the corrected normalizer. Surface-only impact: ROE/ROCE/ROA chips and any composite-score axis that consumes those (Quality, Safety) recompute to true values for affected tickers; FV/DCF pipeline untouched (those use raw decimal NI/Equity, not normalized percent). v64=feat/pre-launch-batch (2026-04-25): pre-launch batch invalidation. Forces every v63 cached payload to recompute against the unified-financials path + new bound-clamp + ticker-alias gate. Wire-format-additive changes shipped in this batch: ValuationOutput.data_limited boolean (true when FV was bound-clamped from a previously-zeroed state); AnalyticalNoteOutput.kind extended with "data_quality" (caution-severity notes appended whenever the clamp fires); analytical_notes list now optional on AnalysisResponse and rendered as a card stack in the frontend. DCF-output changes: routers/analysis.py:241-325 replaces the old FV=0 blanking with a clamp at 0.1*price (low side) or 3.0*price (high side); services/analysis/db.py::_query_ttm_financials falls back to annual FCF when all 4 quarterly cfo/capex/fcf are NULL (source='ttm+annual_fcf_fallback' for audit); services/analysis/utils.py::_compute_roe_fallback now returns None (not a spurious -439% value) when equity<=0 and stashes "negative_equity" in input_quality_flags; services/ratios_service.py::compute_roce returns None when ROCE>100% with WARNING. Routing changes: corporate-action redirect gate at top of get_analysis returns result_kind="corporate_action_redirect" sibling payload for tickers in config/ticker_aliases.yaml with status in {demerged, demerged_pending, delisted}; AnalysisResponse byte-identical for active tickers. Per-ticker DCF shifts: see canary_fv_shifts.md (pre-written) and docs/rebaseline_2026-04-25.md (28-ticker bucket attribution against 5 prior commits). Sector-isolation merge gate now blocks any future PR that produces cross-sector cascades — see docs/SECTOR_ISOLATION.md. v63=hotfix/piotroski-nbfc-insurance (PR #69, 2026-04-25): NBFCs and insurers were falling through to classic 9-signal Piotroski because their sector strings don't match "bank"/"financial" reliably and their tickers don't end with BANK. BAJFINANCE v62 showed piotroski=3/9 (WEAK) despite Wide moat + 21% revenue CAGR; composite capped at 57. Added explicit _NBFC_INSURANCE_BANKLIKE ticker set (BAJFINANCE, CHOLAFIN, MUTHOOTFIN, MANAPPURAM, SHRIRAMFIN, POONAWALLA, AAVAS, HOMEFIRST, HDFCLIFE, SBILIFE, ICICIPRULI, PFC, RECLTD, IRFC, BAJAJHLDNG, etc.) that routes to bank-mode piotroski. Also widened sector match to include "nbfc" and "insurance". Expected BAJFINANCE 57->65+ (PASS band 68-76). v62=feat/analytical-notes (PR #69, 2026-04-24): analytical_notes field added to every analysis payload. Rule-based, no ticker-list maintenance. 7 rules covering premium brands, conglomerates, regulated utilities, cyclical troughs, post-merger transitions, high-P/E growth, ADRs. Bump forces v61 payloads to recompute so every cached response carries the new field (empty list when no rule fires). Purely additive — does NOT alter FV, scoring, or any axis. v61=hotfix/piotroski-merger-exception (PR #67, 2026-04-24 PM): added RECENT_MERGER_BANKS curated set in screener/piotroski.py ({HDFCBANK, AXISBANK, INDUSINDBK, IDFCFIRSTB}) that get neutral 0.5 scores on f3 (ROA improving YoY) and f7 (no share dilution) signals. Rationale: both signals break mechanically for 3 years post-M&A — inflated asset base dilutes ROA at constant profit, share issuance funds the deal — but neither reflects real business deterioration. HDFC absorbed HDFC Ltd July 2023 (ROA 1.8->1.4%, shares +35%); scoring 4/9 (WEAK) for a business that's structurally stronger post-merger is a pure data artifact. Fix: fractional scores (0.5) allowed in the signal loop for these tickers on those two signals only; final total rounded before grade lookup; response dict carries merger_exception_applied bool + merger_note string for frontend use (see PR #69). Expected composite lifts: HDFCBANK piotroski 4->7 bank-scaled, composite 60->68-72; AXISBANK similar; INDUSINDBK +5-8; IDFCFIRSTB +5-8. Review RECENT_MERGER_BANKS every 12 months; graduate entries 3 years after merger close. v60=feat/regulated-utility-wacc-tier (PR #68, 2026-04-24): regulated-utility WACC tier 9% added for POWERGRID/NTPC/PFC/RECLTD/GAIL/TORNTPOWER/ADANITRANS/NHPC. Expected composite lifts: POWERGRID 43->60, NTPC 60->68, PFC/RECLTD +8-10, GAIL +5. Reflects CERC/PNGRB regulated ROE (15.5% on regulated asset base) with bond-like cash flows — generic utility WACC 11% over-discounts them and produces DCF FV ~30% below analyst consensus. New sector routes via REGULATED_UTILITY_TICKERS in models/industry_wacc.py before generic power/oil_gas/nbfc overrides. Also adds enriched["is_regulated_utility"] tag for analytical-note consumers. Prior: v58=hotfix/wide-moat-allowlist (PR #66, 2026-04-24 PM): raised ALLOWLIST_FLOOR_LABEL in screener/moat_engine.py from "Moderate" to "Wide". 18 bellwether franchises (HDFCBANK, HUL, NESTLE, TITAN, ASIANPAINT, TCS, INFY, HCLTECH, MARUTI, RELIANCE, BAJFINANCE, BAJAJFINSV, ICICIBANK, KOTAKBANK, BRITANNIA, DABUR, PIDILITIND, COLPAL, PGHH, MARICO, GILLETTE) now floor at Wide instead of Moderate. The 5-signal moat formula was conservatively labelling these as Moderate due to transient drags (merger/capex/margin compression); their moat durability isn't in doubt. Raising the floor aligns with street consensus and lifts composite by +10 pts each (Wide=25pts vs Moderate=15pts in compute_yieldiq_score). Expected: HDFCBANK 50->60, HCLTECH 52->62, HUL 46->56, NESTLE 52->62, ASIANPAINT 35->45, TITAN 50->60, MARUTI 58->68 (AMBER->PASS), RELIANCE 45->55, TCS 64->74 (close to target 75-82). Final source-code fix of the day. v57=hotfix/bank-equity-data-source (PR #65, 2026-04-24 PM): root-cause fix for the bank-equity inflation that drove HDFCBANK score 17->50 throughout today's calibration patches. data_pipeline/sources/yfinance_supplement.py was reading "Total Equity Gross Minority Interest" from yfinance, which includes minority interest + Tier-1 perpetuals. For banks this inflated stored equity by 30-50% (HDFCBANK: 862k Cr stored vs real 570k). Downstream cascade: ROE computed as half real value (7.8% vs 11.8%), peer-relative adj clamped to floor, fair_pb crushed to 1.75x instead of peer median 2.5x, FV bearish by 30%+. Fix: switched to "Stockholders Equity" (primary) with "Common Stock Equity" fallback, keeping the old field as last-resort for non-bank tickers where minority-interest is absent. Also in this PR: direct data patch on 5 top banks (HDFCBANK/ICICIBANK/SBIN/KOTAKBANK/AXISBANK) correcting their stored equity to published annual-report values, so v57 fresh compute picks up correct ROE/FV immediately without waiting for next backfill. Expected composite lifts post-v57: HDFCBANK 50->60+, ICICIBANK 58->68 (PASS-adjacent), SBIN 54->62 (close to PASS), AXISBANK 50->60. v56=hotfix/cement-cyclical-cap (PR #64, 2026-04-24 PM): removed "cement" from _CYCLICAL_SECTORS in forecaster.py. The 5y-median FCF cap (originally Fix B in PR #56) was crushing SHREECEM (fv/cmp=0.226) and ULTRACEMCO (fv/cmp=0.306) during India's current infrastructure / real-estate demand cycle — cement FCFs are legitimately well above their 5-year median base because the current cycle's demand base is structurally higher. The canary merge-gate was perma-failing on SHREECEM's fv/cmp < 0.35 check, blocking every PR's canary green-light. Cement is cyclical in principle but the 5y lookback is too short for this cycle; should be 7-10y. Post-launch investigation. v55=hotfix/bank-fv-calibration-v2 (PR #63, 2026-04-24 PM): v54's floor=0.85 gave HDFCBANK only +3 composite pts (45->48) vs projected +10. Root cause: HDFCBANK total_equity in the financials table is stored as 862,289 Cr but real value is ~570,000 Cr (50% inflated — yfinance likely includes minority interest / Tier-1 perpetuals). This halves the computed ROE (67k/862k=7.8% vs real 11-12%), which the floor=0.85 couldn't compensate for. Raising floor to 0.95 effectively neutralises the ROE-adjustment when data integrity is low — max 5% penalty instead of 15%. Expected HDFCBANK composite 48->55+. Same-sector beneficiaries: ICICIBANK, AXISBANK, SBIN, HDFCLIFE, SBILIFE, ICICIGI. Real root-cause fix (correct the bank equity data source) is tomorrow's work. v54=hotfix/bank-fv-calibration (PR #62, 2026-04-24 PM): raised the ROE-adjustment floor in financial_valuation_service._compute_pb_path from 0.7 to 0.85. Bank fair_pb = median_pb * adj where adj = clamp(roe/median_roe, floor, ceiling). HDFCBANK post-merger showed roe=7.81% (a separate data-computation bug that halves the real ~15-17% ROE — tomorrow's investigation), vs peer median ~15%; adj computed to 0.53 and clamped to 0.7 (the floor), making fair_pb = 2.5*0.7 = 1.75 vs peer median 2.5. That 30% penalty on fair_value produced MoS=-30% for HDFC when analyst consensus is +15%. Raising floor to 0.85 reduces max ROE-based penalty from 30%->15%; HDFC fair_pb now 2.5*0.85 = 2.125. Expected HDFCBANK: fv~1400 (from ~1150), MoS -15% (from -30%), composite ~55-60 (from 45). Similar lifts for ICICIBANK, HDFCLIFE, AXISBANK, SBIN, BANDHANBNK. v53=hotfix/piotroski-bank-mode (PR #61, 2026-04-24 PM): Piotroski F-score for banks was running the classic 9-signal formula designed for industrial firms, causing HDFCBANK to score 3/9 (WEAK) despite being among India's strongest banks. 5 of 9 signals don't apply to banks: f4 (FCF > NI — banks lack traditional FCF), f5 (leverage down — banks structurally highly-leveraged, deposits = liabilities), f6 (current ratio — not a bank metric), f8 (gross margin — no COGS concept), f9 (asset turnover — structurally low for lenders). Fix: detect bank-like tickers (is_bank flag OR "bank"/"financial" in sector OR ticker ends with BANK.NS), run only the 4 applicable signals (f1 ROA+, f2 OCF+, f3 ROA improving, f7 no dilution), then scale /4 score back to /9 range for downstream API compatibility. Local sanity: HDFCBANK piotroski 3/9 -> 7/9 (scaled from 3/4); composite 42 -> 58. ICICIBANK same pattern: 52 -> 58. BAJFINANCE (NBFC also matches is_bank): 47 -> 66 (crosses into PASS band 68-76). Non-banks unchanged — TCS still 64 whether bank-mode ran or not. Bump forces all v52 payloads to recompute. v52=hotfix/composite-score-formula (PR #60, 2026-04-24 PM): two bugs found in dashboard/utils/scoring.py::compute_yieldiq_score after PR #59's axis fixes didn't lift blue-chip scores as expected. HDFCBANK v51 had fundamental_score=79 but yieldiq_score=17 — composite formula was the choke point. Bug X: "Moderate" moat grade was NOT in _moat_map so every Moderate-moat ticker (HDFCBANK, ICICIBANK, TCS, HCLTECH, MARUTI, HUL, NESTLE, ASIANPAINT) scored 0 pts for moat instead of ~15. Added "Moderate": 15 plus A+/B+/C+ variants and n/a normalization. Bug Y: rev_growth arrived in DECIMAL (0.15) from enriched.revenue_growth but formula was calibrated for PERCENT (15), so every growing company got grw_score=5 instead of 10-20. Added unit auto-detection (|value| < 1.5 = decimal, x100). Local sanity test on 10 tickers: HDFCBANK 17->47, BAJFINANCE 22->55, RELIANCE 25->45, TCS 44->64, HUL 34->54, MARUTI 33->55, ASIANPAINT 20->40, POWERGRID 28->43; INFY stays 73-75 (already passing). Bump forces v51 recompute. Remaining: HDFCBANK ~47 vs target 78-85 because piotroski=3 is broken for banks (separate follow-up investigation). v51=hotfix/hex-axis-fixes (PR #58, 2026-04-24 PM): three targeted HEX scoring bugs fixed based on the Phase 2 audit (docs/audit/HEX_AXIS_SOURCE_MAP.md + SCORING_GROUND_TRUTH.md). Bug #1: D/E unit normalisation in _axis_safety — yfinance returns debtToEquity as percent (45.0 = 45%) but formula expected decimal (0.45); guard added to divide by 100 when raw value > 5. Fixes RELIANCE / ASIANPAINT / POWERGRID / NTPC / L&T Safety collapse (expected ~3/10 -> ~6/10). Bug #2: NBFC-specific Value formula in _axis_value_bank — BAJFINANCE / BAJAJFINSV / CHOLAFIN / MUTHOOTFIN were routed through bank Value (anchor P/BV 2.5x) but NBFCs structurally trade at 3-6x; new branch detects NBFC and uses anchor 3.5x with gentler slope. Expected BAJFINANCE composite 22 -> 55-65. Bug #3 Part B: bank Growth fallback in _axis_growth — when advances_yoy/deposits_yoy/pat_yoy_bank are all None (stale pre-2026-04-21 cache or missed _is_bank_like classification), fall through to general-branch revenue/EPS CAGR instead of returning neutral 5.0. Affects HDFCBANK / ICICIBANK / KOTAKBANK / SBIN / AXISBANK; expected composite 17 -> 55+ on first recompute. Bump forces every v50-cached payload to recompute. After Railway deploy, browser-verify HDFCBANK (expect 70-80), RELIANCE (expect 65-75), BAJFINANCE (expect 55-65). Separate PRs still pending: PR #57 parser fix (nse_xbrl_fundamentals.py:340) + PR #59 billing webhook (propagate tier to raw_user_meta_data + store amount_paise + normalise email case). v50=hotfix/pre-launch-cleanup (2026-04-24 PM): three additional data patches applied to Neon prod financials table before evening launch. (1) Currency mis-tag fix: 410 rows across 14 Indian IT+pharma tickers (INFY, HCLTECH, WIPRO, TECHM, MPHASIS, COFORGE, PERSISTENT, DIVISLAB, CYIENT, OFSS, LAURUSLABS, KPITTECH, TATAELXSI, MASTEK) had currency='USD' but values were already in INR Crores; FX multiplier was 83x'ing them, which silently broke the Revenue CAGR computation via _sanitize_cagr >50% clamp. Tag corrected to 'INR'. (2) INFY revenue patch: FY23/FY24/FY25 annual rows were broken by the same OneD/FourD parser bug and had no viable source in company_financials (also broken for INFY); hardcoded with published investor-relations values (153,670 FY24, 146,767 FY23, 162,990 FY25). (3) NESTLEIND fiscal-year cleanup: deleted the bogus 2024-03-31 annual NSE_XBRL row (Nestle uses Jan-Dec; the row was Q1 2024 mislabeled). Remaining Nestle annuals are legitimate Dec-end yfinance rows. This bump forces every v49-cached payload to recompute and pick up all three patches. Expected: HCLTECH score jumps 37->60-75, INFY score becomes sensible, NESTLE CAGR series becomes monotone. Permanent parser fix (nse_xbrl_fundamentals.py:340 context-name vs duration) lands later in PR #57. v49=hotfix/data-patch-onedfourd-bug (PR #56): emergency data patch applied to prod Neon financials table on 2026-04-24 to protect first paying subscriber. 2,710 revenue rows + 2,769 pat rows + 213 cfo rows copied from company_financials into financials for NSE_XBRL-tagged rows. Root cause was _detect_period_type_from_contexts() at nse_xbrl_fundamentals.py:340 looking at context DURATIONS (all 90 days for Q4 files) instead of context NAMES (FourD vs OneD), silently demoting annual to quarterly and picking OneD Q4-standalone values. Affected HCLTECH FY24 (12,077 -> 109,913), BPCL FY24 (132,087 -> 446,666), etc. Patched in prod via docs/ops/TEMP_patch_2026-04-24.md. Bump forces every v48 cached analysis_cache payload to recompute and pick up the corrected revenue/pat/cfo. Also includes Fix B: forecaster.py _compute_fcf_base gets a sector-gated 5y median cyclical override (oil_gas/metals/cement/chemicals/auto/sugar/airlines) so BPCL-style FY24-inventory-gain outliers don't propagate into terminal. BPCL MoS should drop from +131% (both bugs compounding) toward a defensible +25-45% band. Permanent parser fix lands separately in PR #57 (7-line diff in nse_xbrl_fundamentals.py). After PR #57 + re-backfill, the TEMP data patch can be removed. Prior comment: v48=feat/xbrl-cache-pipeline (PR #48) backfill complete: 3,000 NSE tickers re-parsed from local XBRL cache with the FourD (year-to-date) context picker. 56,296 quarterly rows + 11,356 annual_synth rows written to `financials`; zero parse or store errors. This replaces ~25%-of-real-FY values (caused by OneD / standalone-quarter context preference) with ~99% accurate annual figures: BPCL FY24 rev 132,087 Cr -> 506,993 Cr, RELIANCE FY24 240,715 Cr -> 914,472 Cr, INFY FY24 37,923 Cr -> 153,670 Cr exact, etc. Bump forces every v47 cached analysis to recompute and pick up the corrected financials. BPCL MoS should drop from +131% (DCF extrapolating off Q4-only FCF) to a defensible ~20-40% range once prod re-reads. Zero frontend-contract changes; new optional fields (freshness stamps, sparkline inputs) were additive in v47-era PRs so existing cached payloads simply get the fields on recompute. Prior comment: v47=hotfix/dividend-session-factory: v46 dividend DB-first cascade imported `from backend.database import SessionLocal` which doesn't exist in this codebase — import raised ImportError, caught silently, DB-first path never ran in prod. TCS.NS still rendered stale yfinance yield 2.5% instead of the correct 4.32% (4 NSE payments × Rs.109 / CMP Rs.2521.80) despite v46 deploy. Fix: use the canonical `from backend.services.analysis_service import _get_pipeline_session` factory that every other router uses (see public.py:_get_db_session). Also log at INFO not DEBUG so future silent-fallthrough bugs are visible in Railway logs. Bump forces v46 cached payloads to recompute — without it TCS etc. would keep serving the stale yfinance data from v46's failed cascade. Prior comment: v46=fix/prism-pillars-completeness (stacked on fix/dividend-db-first v45). Two surface-fix families flushed together: (1) hex_service._fetch_core_data SQL used wrong column names (op_margin/fcf/eps/interest_coverage instead of operating_margin/free_cash_flow/eps_diluted; interest_coverage not on Financials at all). Every query raised UndefinedColumn silently, out["financials"] stayed [] — starving _axis_moat of op-margin stability and _axis_growth of revenue-CAGR fallback (TCS canary 2026-04-23 showed both axes "n/a"). Fixed column names + moat_score numeric fallback in _axis_moat + ticker-form expansion in market_metrics lookups (HDFCBANK bank-branch moat scale signal). (2) v45=DividendService DB-first cascade — reads corporate_actions table before yfinance .info fallback, so TCS's 20 NSE-recorded dividend payments actually surface in InsightCards.dividend instead of the "No dividends paid" sentinel that dropped through the old info-only path (dividend_service.py:74 early-return). Zero FV drift for both families: edits touch hex/prism/InsightCards.dividend surface only; DCF/MoS/fair_value pipeline untouched. v44=NBFC WACC floor. v43=moat floor Moderate band + strengths SSOT. v42=Day-3 W6+W9 rules. v41=PR-DET-2 + PR-D2 terminal_g clamp + NBFC WACC +50bps. v40=Day-3 sanity clamps. v39=Discover TTL. v38=PR-NTPC scenario order. v37=PR-BANKSC-2. v36=PR-BANKSC. v35=FV stability. v34=MoS formula. v33=scenarios. v32=MoS SoT.


# ── Version-keyed wrapper (added 2026-04-27, PR fund-f-cache-audit) ──
#
# Background. The class below already invalidates entries whose
# embedded `version` differs from `CACHE_VERSION` -- but only when
# `get()` reads them. This is a *lazy* check: stale entries linger
# until accessed, the storage key is reused across versions, and any
# *projection* cached under a different key (e.g.
# `public:stock-summary:{ticker}`) is shielded by its own TTL even
# when the underlying analysis cache invalidates correctly.
#
# That last failure mode bit PR #138 on prod: bumping CACHE_VERSION
# correctly invalidated `analysis:{ticker}` on read, but the
# rendered summary stored under `public:stock-summary:{ticker}`
# (a python `dict` projection) was held by TTL alone and the new
# `fair_value_source` field never surfaced until the per-key TTL
# elapsed.
#
# Mitigation. `get()` and `set()` now accept `version_keyed=False`.
# When `True`, the actual storage key is `f"v{CACHE_VERSION}:{key}"`
# so a CACHE_VERSION bump moves the new generation into a fresh
# key namespace -- old keys become unreachable on read and TTL-reap
# in the background.
#
# Migration policy.
#   * Caches storing derived ANALYSIS output (FV, MoS, ratios,
#     score, axes, projections, summaries) SHOULD pass
#     version_keyed=True.
#   * Caches storing TRANSIENT OPERATIONAL data (rate-limit
#     counters, idempotency, per-user 60s tier lookup) MUST stay
#     TTL-only (default).
#
# Migrated in this PR:
#   * `public:stock-summary:{ticker}` (routers/public.py)
#   * `reverse_dcf:{ticker}:{wacc}:{terminal_g}:{years}` (routers/analysis.py)
#
# See `docs/cache_layer_audit.md` for the complete site-by-site
# audit + future-migration tracker.


def _vkey(key: str, version_keyed: bool) -> str:
    return f"v{CACHE_VERSION}:{key}" if version_keyed else key


class CacheService:
    """Thread-safe in-memory cache with TTL + version-based invalidation.

    By default keys are NOT version-prefixed -- the legacy
    stored-version tuple check still lazily invalidates on read.
    Pass `version_keyed=True` to opt into hard key-namespace
    isolation per CACHE_VERSION (recommended for any cache that
    stores derived analysis output).
    """

    def __init__(self):
        self._store: dict[str, tuple[Any, float, int]] = {}  # key -> (value, expires_at, version)
        self._lock = threading.Lock()

    def get(self, key: str, version_keyed: bool = False) -> Optional[Any]:
        actual = _vkey(key, version_keyed)
        with self._lock:
            if actual in self._store:
                entry = self._store[actual]
                # Legacy entries without version → invalidate
                if len(entry) != 3:
                    del self._store[actual]
                    return None
                value, expires_at, version = entry
                # Version mismatch → invalidate (stored-version check
                # still applies for TTL-only entries; for
                # version_keyed entries the prefix already isolated
                # us, but the check is harmless and protects against
                # future direct-store mutations).
                if version != CACHE_VERSION:
                    del self._store[actual]
                    return None
                if time.time() < expires_at:
                    return value
                del self._store[actual]
        return None

    def set(self, key: str, value: Any, ttl: int = 900, version_keyed: bool = False) -> None:
        actual = _vkey(key, version_keyed)
        with self._lock:
            self._store[actual] = (value, time.time() + ttl, CACHE_VERSION)

    def delete(self, key: str, version_keyed: bool = False) -> None:
        actual = _vkey(key, version_keyed)
        with self._lock:
            self._store.pop(actual, None)

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
