# backend/services/sector_pages.py
# ═══════════════════════════════════════════════════════════════
# Day-108c (2026-05-23) — Sector landing page cohort registry.
#
# Purpose
# -------
# The Day-108c marketing surface (`/sector/<slug>`) needs a stable
# map: URL slug → (display name, cohort tickers, cohort notes). The
# cohort tickers must be sourced from the same definitions used by
# the analysis engines so the landing page never disagrees with the
# DCF tier assignments shown on the per-ticker pages.
#
# Tickers are deliberately stored WITHOUT the `.NS` exchange suffix
# (matching the inline cohort sets in `service.py` / `sector_overrides.py`).
# Callers building DB lookups should append `.NS` on the way out;
# `bare_tickers_with_suffix()` is provided for that purpose.
#
# Slug stability contract
# -----------------------
# These slugs are wired into the public sitemap and may be linked
# externally (newsletters, social posts). They MUST be stable. To
# rename a cohort, add an alias rather than mutating the slug.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from typing import Final


# ─────────────────────────────────────────────────────────────────
# Cohort definitions — sourced from the engine-level inline sets.
# When the engine sets change, mirror the change here in the same
# PR (covered by test_day108c_sector_pages::test_cohort_membership_
# mirrors_engine_sets).
# ─────────────────────────────────────────────────────────────────

# Day-107a IT services Tier-1 cohort (see service.py:1515).
_IT_SERVICES_TICKERS: Final[tuple[str, ...]] = (
    "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM",
)

# Day-107b FMCG cohort (see sector_overrides.py FMCG_COHORT_TICKERS_INLINE).
_FMCG_TICKERS: Final[tuple[str, ...]] = (
    "HINDUNILVR", "NESTLEIND", "BRITANNIA", "ITC",
    "DABUR", "MARICO", "COLPAL", "GODREJCP",
    "EMAMILTD", "TATACONSUM", "VBL",
)

# Day-107c Auto OEM + ancillaries cohort (see service.py:1570
# _AUTO_COHORT_ALL_INLINE).
_AUTO_TICKERS: Final[tuple[str, ...]] = (
    "MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO",
    "HEROMOTOCO", "EICHERMOT", "ASHOKLEY", "TVSMOTOR",
    "MOTHERSON", "BOSCHLTD", "MRF", "APOLLOTYRE",
)

# Capital goods (heavy engineering / infrastructure / defence).
# Sources the broader "industrials" canonical bucket from
# sector_taxonomy.py — same names the screener uses for the
# capital-goods category.
_CAPITAL_GOODS_TICKERS: Final[tuple[str, ...]] = (
    "LT", "SIEMENS", "ABB", "BHEL", "BEL", "HAL",
    "CUMMINSIND", "THERMAX", "KEC", "TIINDIA",
)

# Day-84 pharma franchise cohort (see service.py:1418
# _PHARMA_FRANCHISE_TICKERS_INLINE).
_PHARMA_TICKERS: Final[tuple[str, ...]] = (
    "MANKIND", "SUNPHARMA", "CIPLA", "TORNTPHARM", "DRREDDY",
    "DIVISLAB", "ABBOTINDIA", "GLAND", "GLAXO", "PFIZER",
    "SANOFI", "AJANTPHARM", "ERIS",
)

# Day-92 regulated utility cohort (see models/industry_wacc.py
# REGULATED_UTILITY_TICKERS).
_UTILITIES_TICKERS: Final[tuple[str, ...]] = (
    "POWERGRID", "NTPC", "NHPC", "PFC", "RECLTD",
    "GAIL", "TORNTPOWER", "ADANIENSOL", "IRFC",
    "IEX", "SJVN", "HUDCO",
)

# Banking cohort — large-cap private + PSU banks. Mirrors the
# Nifty Bank constituents covered by /nifty-bank dashboard.
_BANKING_TICKERS: Final[tuple[str, ...]] = (
    "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK",
    "INDUSINDBK", "SBIN", "BANKBARODA", "PNB",
    "CANBK", "AUBANK", "IDFCFIRSTB", "FEDERALBNK",
)

# Metals / mining cohort (steel + base metals + mining).
_METALS_TICKERS: Final[tuple[str, ...]] = (
    "TATASTEEL", "JSWSTEEL", "HINDALCO", "VEDL",
    "JINDALSTEL", "SAIL", "NMDC", "COALINDIA",
    "NATIONALUM", "HINDZINC",
)

# Cyclical "broad" bucket — cement + commodity-linked names not
# already in metals/auto. Useful for the cyclical landing page
# distinct from the per-sector slugs.
_CYCLICAL_TICKERS: Final[tuple[str, ...]] = (
    "ULTRACEMCO", "GRASIM", "ACC", "AMBUJACEM",
    "SHREECEM", "DALBHARAT", "JKCEMENT",
)


# ─────────────────────────────────────────────────────────────────
# Per-cohort notes — surfaced as the lead paragraph of the landing
# page. Describe the cohort assumptions; SEBI-safe (no buy/sell
# language). Keep under ~120 words.
# ─────────────────────────────────────────────────────────────────

_IT_SERVICES_NOTES = (
    "Tier-1 IT services (TCS, INFY, WIPRO, HCLTECH, TECHM) have terminal "
    "growth lifted to 4.5% under Day-107a to reflect multi-year deal-book "
    "visibility and deep net-cash balance sheets. The cohort's WACC is "
    "tightened toward the ~11.5% band that an analyst would use for a "
    "structurally cash-rich, low-beta franchise. Tier-2 IT names sit "
    "outside this cohort and use generic-sector defaults. See Day-107a "
    "manifest entry for the scoped invalidation."
)

_FMCG_NOTES = (
    "Day-107b assigns FMCG names to four tiers. Top-franchise leaders "
    "(HUL, NESTLE, BRITANNIA) take terminal growth 5.0% and WACC floor "
    "8.5%, reflecting 40+ year India distribution moats and net-cash "
    "books. ITC sits on a 4.5% TG with the same WACC floor (cigarette "
    "tail-risk discount). Tier-2 (DABUR, MARICO, COLPAL, GODREJCP) "
    "lifts to 4.5%; Tier-3 stays at the country default 4.0% but keeps "
    "the WACC floor. The top-4 also receive a moat-pillar floor of 75."
)

_AUTO_NOTES = (
    "Day-107c segments Indian auto OEMs by sub-sector. Two-wheelers "
    "(BAJAJ-AUTO, HEROMOTOCO, EICHERMOT, TVSMOTOR) lift terminal growth "
    "to 5.0% on under-penetration + export tailwinds. Four-wheeler "
    "passenger (MARUTI, TATAMOTORS, M&M) lifts to 4.5% on premiumization "
    "+ EV transition. Commercial vehicles (ASHOKLEY) and ancillaries / "
    "tires (MOTHERSON, BOSCHLTD, MRF, APOLLOTYRE) stay at 4.0%. The "
    "cycle-stage detector flags peak / trough margin extremes."
)

_CAPITAL_GOODS_NOTES = (
    "Capital goods names (LT, SIEMENS, ABB, BHEL, BEL, HAL, plus tier-2 "
    "engineering and rail-electrification names) inherit generic-sector "
    "defaults. Capex-cycle linked revenue is volatile, so DCF assumptions "
    "stay conservative — terminal growth is not lifted above country "
    "default. Reverse-DCF on this cohort is the more analyst-meaningful "
    "lens; see each ticker's analysis page for the implied-growth read."
)

_PHARMA_NOTES = (
    "Day-84 pharma-franchise cohort (Indian domestic-OTC + branded "
    "chronic-care MNCs). Terminal growth lifts to 5.5% to reflect India "
    "healthcare nominal-spend tailwind and pricing-power durability. "
    "CDMO names (DIVISLAB, SYNGENE) use a separate 4.5% lift under the "
    "same framework. Hospital chains are tracked under a sibling cohort "
    "(MAXHEALTH, FORTIS, APOLLOHOSP, etc.) at 5.5%."
)

_UTILITIES_NOTES = (
    "Day-92 regulated utility cohort. CERC / PNGRB tariff-driven names "
    "with bond-like cash flows route to the regulated-utility sector "
    "model (WACC ~9%) instead of the generic power / oil-gas / NBFC "
    "buckets (WACC 10.5-11%). The 15.5% regulated ROE on a regulated "
    "asset base and government-underwritten cash flows justify the "
    "tighter discount. A bear-floor protects against scenario collapse "
    "on cycle-low input years."
)

_BANKING_NOTES = (
    "Banks use a P/B + Residual Income engine instead of DCF (FCF is "
    "not meaningful for a leveraged balance-sheet business). Private "
    "banks and PSU banks share the engine but sit in separate canonical "
    "sectors with different verdict thresholds. See each bank's "
    "analysis page for the residual-income disclosure and the implied "
    "long-run ROE."
)

_METALS_NOTES = (
    "Metals and mining names are deeply cyclical. DCF inputs anchored on "
    "trailing FCF can over- or under-shoot at cycle peaks / troughs, so "
    "the cyclical-anchor block substitutes a 3-year mean annual FCF "
    "(CYCLICAL_TICKERS / CYCLICAL_SECTORS). A trough bear-floor caps "
    "downside at min(0.6 × FV, 0.4 × price). Reverse-DCF and EV/EBITDA "
    "trend the more analyst-meaningful complements."
)

_CYCLICAL_NOTES = (
    "Cement and broad-cyclical names share the cyclical-anchor framework "
    "with metals. The 3-year FCF mean substitution and the trough bear-"
    "floor are applied uniformly. The cohort is small but rate-sensitive "
    "— terminal-growth lifts are not applied because demand is "
    "fundamentally tied to housing + infra capex cycles."
)


# ─────────────────────────────────────────────────────────────────
# Public slug → cohort table.
# ─────────────────────────────────────────────────────────────────
SECTOR_PAGES: Final[dict[str, dict]] = {
    "it-services": {
        "display_name": "IT Services",
        "tickers": _IT_SERVICES_TICKERS,
        "notes": _IT_SERVICES_NOTES,
        "manifest_ref": "Day-107a",
    },
    "fmcg": {
        "display_name": "FMCG",
        "tickers": _FMCG_TICKERS,
        "notes": _FMCG_NOTES,
        "manifest_ref": "Day-107b",
    },
    "auto": {
        "display_name": "Auto",
        "tickers": _AUTO_TICKERS,
        "notes": _AUTO_NOTES,
        "manifest_ref": "Day-107c",
    },
    "capital-goods": {
        "display_name": "Capital Goods",
        "tickers": _CAPITAL_GOODS_TICKERS,
        "notes": _CAPITAL_GOODS_NOTES,
        "manifest_ref": None,
    },
    "pharma": {
        "display_name": "Pharma",
        "tickers": _PHARMA_TICKERS,
        "notes": _PHARMA_NOTES,
        "manifest_ref": "Day-84",
    },
    "utilities": {
        "display_name": "Utilities",
        "tickers": _UTILITIES_TICKERS,
        "notes": _UTILITIES_NOTES,
        "manifest_ref": "Day-92",
    },
    "banking": {
        "display_name": "Banking",
        "tickers": _BANKING_TICKERS,
        "notes": _BANKING_NOTES,
        "manifest_ref": None,
    },
    "metals": {
        "display_name": "Metals & Mining",
        "tickers": _METALS_TICKERS,
        "notes": _METALS_NOTES,
        "manifest_ref": None,
    },
    "cyclical": {
        "display_name": "Cyclical (Cement & Broad)",
        "tickers": _CYCLICAL_TICKERS,
        "notes": _CYCLICAL_NOTES,
        "manifest_ref": None,
    },
}


SECTOR_PAGE_SLUGS: Final[tuple[str, ...]] = tuple(SECTOR_PAGES.keys())


def get_cohort(slug: str) -> dict | None:
    """Return the cohort dict for a slug, or None if unknown.

    The returned dict has stable keys: ``display_name``, ``tickers``
    (tuple of bare symbols, no exchange suffix), ``notes`` (str),
    and ``manifest_ref`` (str or None).
    """
    if not slug:
        return None
    return SECTOR_PAGES.get(slug.strip().lower())


def tickers_with_suffix(slug: str, suffix: str = ".NS") -> list[str]:
    """Return cohort tickers with the given exchange suffix appended.

    Convenience for DB lookups where ``analysis_cache.ticker`` and
    similar tables key by the suffixed symbol. Unknown slug → empty
    list (callers gate on this rather than raising)."""
    cohort = get_cohort(slug)
    if not cohort:
        return []
    return [f"{t}{suffix}" for t in cohort["tickers"]]
