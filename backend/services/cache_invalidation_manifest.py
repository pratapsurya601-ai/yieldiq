# backend/services/cache_invalidation_manifest.py
"""
Granular cache invalidation manifest (Day-94, 2026-05-22).

Replaces the single global CACHE_VERSION integer as the read-path
validity gate. The integer remains as a panic-switch fallback (see
CACHE_MANIFEST_DISABLED env var) and as informational metadata on
every cached row, but the manifest is the authoritative source of
truth for "is this cached row still valid?".

═══════════════════════════════════════════════════════════════
Why this exists
═══════════════════════════════════════════════════════════════

The pre-Day-94 model:
  - CACHE_VERSION is a single integer
  - Every bump invalidates EVERY cached row across EVERY ticker
  - 2,400 tickers × 20s cold yfinance recompute = ~13 hours of
    compute per bump
  - A 4-line bear-floor fix for 6 utility tickers costs the same as
    a 400-line rewrite that affects everything

Today (2026-05-22) we hit CACHE_VERSION=136 after ~21 bumps in a
12-hour window. The Railway memory chart showed spikes lining up
with each bump, and the cache_service.py header now reads:
"Today we bumped this 21 times in 12 hours and caused real latency
problems. Don't do that again."

Day-94 replaces "don't bump" discipline with an architectural fix.

═══════════════════════════════════════════════════════════════
How it works
═══════════════════════════════════════════════════════════════

A row in analysis_cache is valid IFF:
  - It was computed AFTER the most-recent invalidation that applies
    to (ticker, fields_being_read)

Where "applies" means:
  - The manifest entry's `scope.tickers` includes this ticker
    (or is "*" for global), AND
  - The manifest entry's `scope.fields` overlaps with the fields
    the caller intends to read (or is "*" for full-payload)

The matcher is O(N × M) where N is the manifest length and M is
the field count. We expect N to grow ~5/week, capped at maybe 200
entries before we add a retention policy. Cheap.

═══════════════════════════════════════════════════════════════
How to add a new invalidation
═══════════════════════════════════════════════════════════════

When you ship an engine change, append ONE entry to MANIFEST below:

    {
        "version_id": "v137_day95_xyz",
        "applied_at": datetime(2026, 5, 23, 10, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["NTPC", "POWERGRID"],  # bare, no .NS
            "fields": ["scenarios.bear"],
        },
        "rationale": "one-line description of the fix",
    },

Field paths use dot notation matching the analysis payload shape:
  - "fair_value", "mos", "verdict", "score"
  - "scenarios.bear", "scenarios.bull", "scenarios.base"
  - "valuation.wacc", "valuation.terminal_growth"
  - "quality.moat", "quality.roe"
  - "red_flags_structured"
  - "*" for the whole payload (use sparingly — reverts to global bump)

If the fix changes the ENGINE's output for a ticker, ANY downstream
field could shift. Use ["*"] in those cases. If the fix only
changes a derived field (e.g. dividend.sustainability label which
is computed at response time, not stored), no manifest entry is
needed.
"""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable

log = logging.getLogger("yieldiq.cache_manifest")


# ─────────────────────────────────────────────────────────────────
# Panic switch
#
# Set CACHE_MANIFEST_DISABLED=1 in the environment to fall back to
# the legacy "strict cache_version equality" behavior. Use only if
# the manifest produces obviously-wrong cache hits in prod.
# ─────────────────────────────────────────────────────────────────
_DISABLED = os.environ.get("CACHE_MANIFEST_DISABLED", "").strip() in ("1", "true", "yes")


# ─────────────────────────────────────────────────────────────────
# The manifest itself
#
# Append-only. Newest entries at the bottom. Entry order doesn't
# affect correctness (the matcher iterates all entries) but
# chronological order makes the diff history readable.
# ─────────────────────────────────────────────────────────────────
MANIFEST: list[dict] = [
    {
        # The migration anchor. Every cached row predating this
        # entry's applied_at gets invalidated once — final global
        # wipe. From this point forward, all bumps are scoped.
        "version_id": "v_init_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 23, 0, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": "*"},
        "rationale": (
            "Day-94 migration anchor — invalidate everything predating "
            "the manifest deploy so the system starts from a clean state."
        ),
    },
    {
        "version_id": "v_day95_metals_sector_pins",
        "applied_at": datetime(2026, 5, 22, 4, 50, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "HINDZINC", "HINDCOPPER", "HINDALCO", "VEDL", "NATIONALUM",
                "TATASTEEL", "JSWSTEEL", "JINDALSTEL", "SAIL", "NMDC",
                "MOIL", "GMDCLTD", "COALINDIA", "WELCORP", "RATNAMANI",
                "APLAPOLLO", "JINDALSAW",
            ],
            "fields": "*",  # sector pin can shift anything downstream
        },
        "rationale": "Day-95: metals/mining sector pins (HINDZINC and 16 others). Cohort routing change.",
    },
    {
        # Day-100 / Audit #5 P0b — fair_value 0-floor leak.
        # `_extract_analysis_summary` in backend/routers/public.py used
        # to forward the engine's fair_value verbatim. When the engine
        # returned 0.0 but a real scenario midpoint (base_case) existed
        # (ULTRACEMCO.NS at 2026-05-22), the SEO fair-value page rendered
        # "₹0 fair value" on the hero pill. Fix: fall through to
        # base_case when engine fair_value is 0 and base_case > 0; emit
        # None when neither exists so the frontend hides the pill.
        "version_id": "v_audit5_p0b_fv_floor_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 12, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["ULTRACEMCO"],
            "fields": ["fair_value"],
        },
        "rationale": (
            "Audit#5 P0b: fair_value 0-floor leak — fall through to "
            "base_case in /stock-summary projection so the SEO hero "
            "pill stops rendering ₹0 when the engine collapses but "
            "scenario midpoint is meaningful."
        ),
    },
    {
        # Audit#5 P1: INDIGO asset_turnover=359808 — clearly a unit
        # mismatch. Defensive sanity gate in compute_asset_turnover
        # nulls values outside [0.001, 100] so UI shows "n/a" instead
        # of an obviously-wrong number.
        "version_id": "v_audit5_p1_asset_turnover_units_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 13, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["INDIGO"],
            "fields": ["ratios.asset_turnover"],
        },
        "rationale": (
            "Audit#5 P1: asset_turnover sanity gate — INDIGO showed "
            "359808 due to unit mismatch upstream. Scoped to INDIGO; "
            "other tickers are within plausible band."
        ),
    },
    {
        # Audit#5 P1: de_ratio=0 on all 17 audit-universe tickers.
        # Root cause: data/collector.py coerced missing yfinance
        # debtToEquity to 0 instead of None. Fix reads from
        # ratio_history (XBRL) and preserves None for genuine missing.
        "version_id": "v_audit5_p1_de_ratio_null_safety_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 13, 30, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["ratios.de_ratio"],
        },
        "rationale": (
            "Audit#5 P1: de_ratio null-safety — every audit-universe "
            "ticker was casting yfinance null to literal 0. Read from "
            "ratio_history first; reject implausible zero when debt > 0."
        ),
    },
    {
        # Task#87: asset_turnover=null for RELIANCE/TATASTEEL/
        # ULTRACEMCO/TCS/INFY. PR #498's sanity gate was correctly
        # rejecting a ~1e-7 ratio caused by a pre-existing unit
        # mismatch at the call site in analysis/service.py — revenue
        # in Crores vs total_assets in raw INR (yfinance). Fix mirrors
        # the FIX-ROCE-UNIT-MISMATCH pattern: prefer DB _ta_db (Crores)
        # so units align with revenue.
        "version_id": "v_task87_asset_turnover_unit_callsite_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 15, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["ratios.asset_turnover"],
        },
        "rationale": (
            "Task#87: asset_turnover call site mixed Crore revenue "
            "with raw-INR total_assets, producing ~1e-7 ratios that "
            "PR #498's sanity gate correctly nulled. Prefer DB total "
            "assets so units match revenue."
        ),
    },
    {
        # Audit#6: backend mirror of frontend PR #499 — asymmetric
        # bear-side bypass for the overvalued band. Layer-3 of
        # _apply_confidence_verdict_gate was capping any moderate-
        # confidence overvalued read down to fairly_valued; the
        # frontend already corrected this in the UI rendering layer,
        # so the API payload disagreed with the rendered pill on a
        # subset of bear-side tickers. Fix mirrors the frontend
        # constants (BEAR_OVERVALUED_BYPASS_MOS=-25,
        # BEAR_OVERVALUED_BYPASS_CONFIDENCE=40,
        # BEAR_NOTABLY_OVERVALUED_MOS=-40) into the gate so the
        # backend ``verdict`` field agrees with the UI label.
        "version_id": "v_audit6_backend_overvalued_mirror_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 16, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["SUNPHARMA", "MARUTI", "SBIN", "ASIANPAINT"],
            "fields": ["verdict"],
        },
        "rationale": (
            "Audit#6: backend mirror of #499 frontend overvalued gate. "
            "Re-derives verdict for the four audit-confirmed bear-side "
            "tickers so /api/v1/public/stock-summary, og-data, push and "
            "email alerts, and verdict-keyed analytics agree with the "
            "rendered pill."
        ),
    },
    {
        # Audit#7 P0 (2026-05-22): the Audit#6 bypass above returned
        # "notably_overvalued" when mos_pct <= -40. ValuationOutput.verdict
        # in backend/models/responses.py is Literal[undervalued,
        # fairly_valued, overvalued, avoid, data_limited, unavailable] and
        # does NOT include "notably_overvalued". Pydantic raised
        # ValidationError inside get_full_analysis, the public
        # stock-summary endpoint caught it in the cache-miss recompute
        # path (backend/routers/public.py:672) and started returning the
        # opaque "cache_miss_recompute_failed" placeholder for every
        # ASIANPAINT.NS request. SUNPHARMA / MARUTI / SBIN escaped the
        # bug because their MoS (-33, -31, -31) is above the -40
        # BEAR_NOTABLY_OVERVALUED_MOS boundary, so they returned plain
        # "overvalued" (a valid literal) and recomputed cleanly.
        #
        # Fix: clamp the bypass output to "overvalued" and log the
        # intensity hint in the issues array. Frontend pill rendering
        # is unaffected because it derives the label from mos_pct via
        # verdictFromMos on the client, not from this string.
        "version_id": "v_audit7_p0_asianpaint_recompute_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 16, 30, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["ASIANPAINT"],
            "fields": ["*"],
        },
        "rationale": (
            "Audit#7 P0: ASIANPAINT.NS summary recompute wedged on "
            "cache_miss_recompute_failed after Audit#6 (PR #503). The "
            "bypass returned 'notably_overvalued' which is not a valid "
            "ValuationOutput.verdict literal, pydantic raised, the "
            "recompute fell through to the under_review placeholder. "
            "Clamp to 'overvalued' so the response validates. Scoped "
            "to ASIANPAINT (the only ticker with mos_pct deep enough "
            "to cross the unmodeled branch)."
        ),
    },
    {
        # Day-103c (2026-05-22): added `compounded_growth` field to
        # /api/v1/public/stock-summary response (3y/5y/10y CAGR panel
        # for revenue/profit/ROE-avg/stock). Pure additive surface —
        # no existing field changed. Manifest entry exists so any
        # stock-summary rows cached before the deploy get refreshed
        # and start emitting the new field.
        "version_id": "v_day103c_cagr_panel_2026_05_22",
        "applied_at": datetime(2026, 5, 22, 19, 0, 0, tzinfo=timezone.utc),
        "scope": {"tickers": "*", "fields": ["compounded_growth"]},
        "rationale": "Day-103c: new compounded_growth field on stock-summary",
    },
    {
        # Day-107a (2026-05-23): IT services cohort overrides
        # (Tier-1 WACC cap 0.115, Tier-2 0.125, hard floor 0.085;
        # backwards-compat band ±20% on TCS/INFY DCF math).
        "version_id": "v_day107a_it_services_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 10, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": ["TCS", "INFY", "WIPRO", "HCLTECH", "TECHM",
                        "LTIM", "PERSISTENT", "MPHASIS", "COFORGE", "BSOFT"],
            "fields": "*",
        },
        "rationale": (
            "Day-107a: IT services cohort overrides (WACC tighten, TG "
            "lift, scenario re-weight)"
        ),
    },
    {
        # Day-107c (2026-05-23): Indian auto OEM cohort overrides.
        # Segment-differentiated TG (2W 5.0%, 4W 4.5%, CV 4.0%,
        # ancillary 4.0%), ASHOKLEY CV WACC floor 0.11, cycle-trough
        # bear-floor `min(0.6*fv, 0.4*price)` triggered when trailing
        # EBITDA margin < 50% of 5y median.
        "version_id": "v_day107c_auto_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 10, 10, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO",
                "HEROMOTOCO", "EICHERMOT", "ASHOKLEY", "TVSMOTOR",
                "MOTHERSON", "BOSCHLTD", "MRF", "APOLLOTYRE",
            ],
            "fields": "*",
        },
        "rationale": (
            "Day-107c: auto cohort overrides (5y EBIT normalization, "
            "segment TG, cycle bear-floor)"
        ),
    },
    {
        # Day-107b (2026-05-23): FMCG sector cohort overrides — TG
        # lift to 5.0%/4.5%/4.5%/4.0% by tier, WACC floor 8.5%,
        # moat-pillar floor 75 for top-4, scenario weighting 40/40/20.
        "version_id": "v_day107b_fmcg_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 10, 5, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "HUL", "NESTLEIND", "ITC", "BRITANNIA", "DABUR",
                "MARICO", "COLPAL", "GODREJCP", "EMAMI",
                "TATACONSUM", "VBL",
            ],
            "fields": "*",
        },
        "rationale": (
            "Day-107b: FMCG cohort overrides (TG lift, WACC tighten, "
            "moat premium)"
        ),
    },
    {
        # Day-107d (2026-05-23): Capital Goods / E&C cohort overrides.
        # Sub-buckets: defence+power-T&D (BEL/ABB/SIEMENS) TG 4.5%,
        # general E&C TG 4.0%, BHEL TG 3.5% + 50bps WACC penalty.
        # Order-book lift deferred to Phase 2 pending order_book col.
        "version_id": "v_day107d_capital_goods_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 10, 15, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "LT", "SIEMENS", "ABB", "CUMMINSIND", "BHEL", "BEL",
                "THERMAX", "KEC", "VOLTAS", "BLUESTARCO",
                "KIRLOSKAR", "GRINDWELL",
            ],
            "fields": "*",
        },
        "rationale": (
            "Day-107d: capital goods cohort overrides (order-book lift "
            "deferred to Phase 2, TG by sub-segment 4.5/4.0/3.5%, "
            "BHEL +50bps WACC penalty)."
        ),
    },
    {
        # Day-109b (2026-05-23): NBFC sub-segment PB anchoring.
        "version_id": "v_day109b_nbfc_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 20, 5, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "BAJFINANCE", "LICHSGFIN", "PNBHOUSING", "REPCO",
                "MUTHOOTFIN", "MANAPPURAM", "CREDITACC", "CHOLAFIN",
                "MMFIN", "SHRIRAMFIN", "SUNDARMFIN",
            ],
            "fields": "*",
        },
        "rationale": (
            "Day-109b: NBFC cohort PB anchoring by sub-segment + "
            "AUM-growth boost"
        ),
    },
    {
        # Day-110b (2026-05-23): Insurance cohort overrides (P/EV
        # anchors for life — P/B fallback today, P/EV when EV
        # ingestion lands; P/B + CR overlay for general insurance).
        "version_id": "v_day110b_insurance_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 21, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "HDFCLIFE", "SBILIFE", "ICICIPRULI", "LICI", "MAXFIN",
                "ICICIGI", "NIACL",
            ],
            "fields": "*",
        },
        "rationale": (
            "Day-110b: Insurance cohort overrides (P/EV anchors for "
            "life, P/B+CR for general)"
        ),
    },
    {
        # Day-110a (2026-05-23): observability-only manifest entry for
        # the sector landing-page read-path hotfix (aggregator now uses
        # get_cached_latest() which bypasses manifest validation).
        "version_id": "v_day110a_sector_page_read_path_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 11, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": "*",
            "fields": ["sector_page"],
        },
        "rationale": (
            "Day-110a: sector landing-page aggregator now bypasses "
            "manifest validation (read-path-only)."
        ),
    },
    {
        # Day-109a (2026-05-23): Banking sector cohort overrides.
        # Layered on Day-76 PB skip path: tier-anchored P/BV (T1 3.0x,
        # PSU 1.2x, T2 1.8x), ROE-quality boost, stress flag.
        "version_id": "v_day109a_banking_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 20, 0, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK",
                "SBIN", "INDUSINDBK", "FEDERALBNK", "IDFCFIRSTB",
                "AUBANK", "BANDHANBNK", "RBLBANK",
            ],
            "fields": "*",
        },
        "rationale": (
            "Day-109a: banking cohort PB anchoring + ROE-quality "
            "boost + stress flag"
        ),
    },
    {
        # Day-110c (2026-05-23): REIT/InvIT sector cohort overrides.
        # Distribution-yield-anchored implied fair price by
        # sub-segment (office/retail REIT, roads/transmission/other
        # InvIT). Layered on PR #333 REIT short-circuit; InvITs join
        # the same no-DCF path via the new is_invit classifier. Adds
        # ``reit_invit_cohort`` block to _computation_inputs.
        "version_id": "v_day110c_reit_invit_cohort_2026_05_23",
        "applied_at": datetime(2026, 5, 23, 21, 5, 0, tzinfo=timezone.utc),
        "scope": {
            "tickers": [
                "EMBASSY", "MINDSPACE", "BIRET", "BROOKFIELD",
                "NEXUSSELECT", "NEXUS",
                "IRBINVIT", "POWERGRIDIT", "INDIGRID", "VIRTUS",
            ],
            "fields": "*",
        },
        "rationale": (
            "Day-110c: REIT/InvIT distribution-yield anchoring by "
            "sub-segment"
        ),
    },
]


# ─────────────────────────────────────────────────────────────────
# Matcher
# ─────────────────────────────────────────────────────────────────

def _bare_ticker(ticker: str) -> str:
    """Strip exchange suffix for matching against scope.tickers."""
    if not ticker:
        return ""
    bare = ticker
    for suffix in (".NS", ".BO", ".BSE", ".NSE"):
        if bare.endswith(suffix):
            bare = bare[: -len(suffix)]
            break
    return bare.upper()


def _ticker_in_scope(ticker: str, scope_tickers) -> bool:
    """True if the ticker matches scope.tickers ('*' or list-of-bare)."""
    if scope_tickers == "*":
        return True
    if not isinstance(scope_tickers, (list, tuple, set)):
        return False
    bare = _bare_ticker(ticker)
    return bare in {_bare_ticker(t) for t in scope_tickers}


def _field_in_scope(fields_needed: Iterable[str] | None, scope_fields) -> bool:
    """True if any of fields_needed overlaps scope.fields.

    Scope semantics:
      - "*" → matches anything
      - ["a.b"] → matches only exact "a.b"
      - ["a.*"] → matches "a.b", "a.c", but NOT "x.y"

    If fields_needed is None or empty, treat as "everything" — i.e.
    err on the side of invalidation. The caller doesn't know what
    they're going to read, so we can't safely serve potentially-
    stale data.
    """
    if scope_fields == "*":
        return True
    if not isinstance(scope_fields, (list, tuple, set)):
        return False
    if not fields_needed:
        # Caller didn't declare; assume worst case (any field matters).
        return True
    for needed in fields_needed:
        for scoped in scope_fields:
            if scoped == "*" or scoped == needed:
                return True
            if scoped.endswith(".*") and needed.startswith(scoped[:-2]):
                return True
    return False


def _coerce_datetime(value) -> "datetime | None":
    """Normalise computed_at to a timezone-aware UTC datetime."""
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if isinstance(value, str):
        try:
            # ISO-8601 with optional Z suffix
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except (TypeError, ValueError):
            return None
    return None


def is_row_valid_per_manifest(
    ticker: str,
    computed_at,
    fields_needed: Iterable[str] | None = None,
    manifest: list[dict] = None,
) -> bool:
    """Return True if the cached row is still valid per the manifest.

    Used on the cache READ path to gate whether a row from
    analysis_cache should be served or treated as a miss.

    Args:
        ticker: Either bare ("NTPC") or canonical ("NTPC.NS") form.
        computed_at: When the cached row was written. Anything older
            than the most-recent applicable manifest entry → invalid.
        fields_needed: Which fields the caller intends to read. If
            None, treats as "all" (worst case → more likely to
            invalidate, which is the safe default for ignorant callers).
        manifest: Override for testing. Defaults to the module-level
            MANIFEST.

    Returns:
        True if the row should be served, False if it should be
        treated as a cache miss.

    Behavior with CACHE_MANIFEST_DISABLED=1:
        Always returns True (caller's existing cache_version equality
        check is then the only gate).
    """
    if _DISABLED:
        return True

    mfst = manifest if manifest is not None else MANIFEST
    computed_dt = _coerce_datetime(computed_at)
    if computed_dt is None:
        # Can't tell when this row was written — fail safe and
        # treat as invalid so we recompute.
        return False

    for entry in mfst:
        applied_at = _coerce_datetime(entry.get("applied_at"))
        if applied_at is None or applied_at <= computed_dt:
            # Entry predates the row; row is at least as new as the
            # fix, so the fix is already in this row.
            continue
        scope = entry.get("scope") or {}
        if not _ticker_in_scope(ticker, scope.get("tickers")):
            continue
        if not _field_in_scope(fields_needed, scope.get("fields")):
            continue
        # This entry applies AND the row is older than it.
        log.debug(
            "cache_manifest: row INVALID for %s (entry=%s, "
            "row_computed_at=%s, applied_at=%s)",
            ticker, entry.get("version_id"),
            computed_dt.isoformat(), applied_at.isoformat(),
        )
        return False

    return True


# ─────────────────────────────────────────────────────────────────
# Helpers for admin / observability
# ─────────────────────────────────────────────────────────────────

@dataclass
class ManifestSummary:
    total_entries: int
    most_recent_entry_id: str | None
    most_recent_applied_at: str | None
    global_entries_count: int   # entries with scope.tickers == "*"
    scoped_entries_count: int   # entries with a ticker list


def summarise_manifest(manifest: list[dict] = None) -> ManifestSummary:
    """Return a small structured summary for /admin/cache-manifest."""
    mfst = manifest if manifest is not None else MANIFEST
    if not mfst:
        return ManifestSummary(0, None, None, 0, 0)
    by_applied = sorted(
        mfst,
        key=lambda e: _coerce_datetime(e.get("applied_at")) or datetime.min.replace(tzinfo=timezone.utc),
        reverse=True,
    )
    newest = by_applied[0]
    newest_applied = _coerce_datetime(newest.get("applied_at"))
    global_count = sum(
        1 for e in mfst if (e.get("scope") or {}).get("tickers") == "*"
    )
    return ManifestSummary(
        total_entries=len(mfst),
        most_recent_entry_id=newest.get("version_id"),
        most_recent_applied_at=newest_applied.isoformat() if newest_applied else None,
        global_entries_count=global_count,
        scoped_entries_count=len(mfst) - global_count,
    )
