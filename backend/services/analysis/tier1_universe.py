"""
Tier 1 curated universe — Layer B Week-1 PR 2
==============================================

Per ``docs/design/valuation-architecture-simplification.md`` §2.1, Tier 1 is a
curated set of ~150 stable Indian large-caps for which the generic FCF-DCF
engine already lands within ~15% of analyst consensus. These tickers are
explicitly opted-in (curated by hand against the canary + reconciliation
table) rather than discovered by a pure rules-based filter — the rules-based
filter (``is_tier1_eligible``) exists only as a **reconciliation gate** to
flag drift from the curated set (e.g. a ticker becomes ineligible after a
bad year and should be reviewed).

This module is intentionally additive in this PR:
  * It is NOT wired into ``backend/services/analysis/service.py`` yet (the
    routing change is a separate Week-2 PR).
  * No cache invalidation. ``CACHE_VERSION`` is not bumped.

Public surface
--------------
  TIER1_TICKERS       : frozenset[str]  — the curated bare tickers
  is_tier1(ticker)    : bool            — strip suffix + membership test
  is_tier1_eligible(ticker, financials) : bool — re-check the 5 criteria
                                                 from the design doc for
                                                 the reconciliation drift
                                                 report.

Curation notes (excluded by design)
-----------------------------------
  * MANKIND, AJANTPHARM         — recent IPO / outside 3y trailing window
                                  AND the canonical Tier-2 fix case
                                  (see fmcg-dcf-fix.md §3 and the design
                                  doc §2.2 MANKIND illustration).
  * EMBASSY, MINDSPACE          — REITs, Tier 3 skip.
  * NIFTYBEES, BANKBEES         — ETFs, Tier 3 skip.
  * BAJAJHLDNG, PILANIINVS      — holdcos, Tier 3 skip.
  * HDFCLIFE, SBILIFE, LIC,
    ICICIGI, NIACL              — insurance, kept in the financial engine
                                  (Tier 3 KEEP path).
  * HAL, BEL, BDL, BEML,
    MAZDOCK, COCHINSHIP         — Defense PSU, flag path (PR #333).
  * SBIN, BANKBARODA, PNB,
    CANBK                       — PSU banks; P/B engine covers them.
  * ADANIENT, ADANIPORTS,
    ADANIGREEN, etc.            — Adani complex deliberately deferred
                                  pending case-by-case review (per task
                                  brief "ADANI-class curated review").
  * VEDL, JINDALSTEL, SAIL,
    NMDC, COALINDIA             — pure commodity / cyclical; cohort path.
  * ZOMATO, PAYTM, NYKAA,
    POLICYBZR                   — new-economy listings <3y stable FCF.
  * YESBANK, IDEA, RCOM         — distressed / restructured.
"""
from __future__ import annotations

from typing import Any, Mapping


__all__ = [
    "TIER1_TICKERS",
    "strip_suffix",
    "is_tier1",
    "is_tier1_eligible",
    "TIER1_MARKET_CAP_FLOOR_CR",
    "TIER1_REVENUE_CAGR_CEILING",
    "TIER1_MIN_ROCE",
]


# ── Eligibility thresholds (per design doc §2.1) ─────────────────
TIER1_MARKET_CAP_FLOOR_CR = 50_000.0     # ₹ Cr
TIER1_REVENUE_CAGR_CEILING = 0.30        # 30 %; null also disqualifies
TIER1_MIN_ROCE = 0.15                    # 15 % sustained


# ── Sectors that are NEVER Tier 1 (live in Tier 3 / dedicated engine) ─
_TIER1_BLOCKED_SECTORS = frozenset({
    "ETF",
    "REIT",
    "Holdco",
    "Holding Company",
    "Insurance",
    "Defense PSU",
    "Defence PSU",
    "Recent IPO",
})


# ── The curated list ─────────────────────────────────────────────
# Order within each sector grouping is alphabetic for readability; the
# overall iteration order does not matter because membership is the
# only operation.
TIER1_TICKERS: frozenset[str] = frozenset({
    # IT Services (10)
    "TCS", "INFY", "HCLTECH", "WIPRO", "TECHM",
    "MPHASIS", "LTIM", "PERSISTENT", "COFORGE", "BIRLASOFT",

    # Private Banks (7)
    "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK",
    "INDUSINDBK", "IDFCFIRSTB", "FEDERALBNK",

    # NBFCs (6)
    "BAJFINANCE", "BAJAJFINSV", "CHOLAFIN",
    "MUTHOOTFIN", "MANAPPURAM", "SHRIRAMFIN",

    # FMCG (12)
    "HINDUNILVR", "ITC", "NESTLEIND", "BRITANNIA",
    "DABUR", "MARICO", "GODREJCP", "COLPAL",
    "PIDILITIND", "EMAMILTD", "JYOTHYLAB", "TATACONSUM",

    # Auto OEMs (7)
    "MARUTI", "M&M", "TATAMOTORS", "BAJAJ-AUTO",
    "EICHERMOT", "HEROMOTOCO", "TVSMOTOR",

    # Paints & Specialty Chem (4)
    "ASIANPAINT", "BERGEPAINT", "KANSAINER", "AKZOINDIA",

    # Pharma — stable large-cap (8)
    "SUNPHARMA", "CIPLA", "DIVISLAB",
    "TORNTPHARM", "ALKEM", "AUROPHARMA",
    "DRREDDY", "LUPIN",

    # Cement — post-clean + the design-doc §2.1 examples (7)
    "SHREECEM", "JKCEMENT", "DALBHARAT", "RAMCOCEM",
    "ULTRACEMCO", "AMBUJACEM", "ACC",

    # Power / Utilities — eligible (rate-base engine still routes them
    # first, but they pass the Tier 1 criteria as a fall-through) (2)
    "POWERGRID", "NTPC",

    # Metals — top-3 stable large-cap (cyclical caveat acknowledged
    # in design doc §2.1) (3)
    "HINDALCO", "TATASTEEL", "JSWSTEEL",

    # Oil & Gas (5)
    "RELIANCE", "ONGC", "BPCL", "IOC", "GAIL",

    # Telecom (1)
    "BHARTIARTL",

    # Diversified / Capital Goods bellwether & survivors (per
    # design doc §2.1 "rare survivors") (6)
    "LT", "CUMMINSIND", "ABB", "SIEMENS", "HAVELLS", "GRASIM",

    # Consumer Discretionary / Retail stable large-caps (6)
    "TITAN", "DMART", "TRENT", "VBL", "JUBLFOOD", "PAGEIND",

    # Auto Ancillaries — stable large-cap (5)
    "BOSCHLTD", "MOTHERSON", "BALKRISIND", "MRF", "APOLLOTYRE",

    # Misc large-cap FMCG-adjacent personal care (2)
    "PGHH", "GILLETTE",

    # Consumer durables (2)
    "VOLTAS", "BLUESTARCO",
})


# ── Helpers ──────────────────────────────────────────────────────
def strip_suffix(ticker: str) -> str:
    """Return the bare ticker with NSE/BSE suffix removed.

    ``"TCS.NS"`` → ``"TCS"``;  ``"500325.BO"`` → ``"500325"``.
    Whitespace is also stripped and the result upper-cased so the
    comparison is consistent with ``TIER1_TICKERS``.
    """
    if ticker is None:
        return ""
    t = str(ticker).strip().upper()
    for suffix in (".NS", ".BO", ".NSE", ".BSE"):
        if t.endswith(suffix):
            t = t[: -len(suffix)]
            break
    return t


def is_tier1(ticker: str) -> bool:
    """Membership test against the curated set, suffix-tolerant."""
    return strip_suffix(ticker) in TIER1_TICKERS


def _coerce_float(value: Any) -> float | None:
    """Best-effort numeric coercion. ``None`` for non-numeric / NaN."""
    if value is None:
        return None
    try:
        f = float(value)
    except (TypeError, ValueError):
        return None
    # Filter NaN (NaN != NaN)
    if f != f:
        return None
    return f


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    s = sorted(values)
    n = len(s)
    mid = n // 2
    if n % 2 == 1:
        return s[mid]
    return 0.5 * (s[mid - 1] + s[mid])


def is_tier1_eligible(ticker: str, financials: Mapping[str, Any] | None) -> bool:
    """Re-check the five Tier-1 design-doc criteria against fresh data.

    Used by the reconciliation framework to flag drift from the curated
    ``TIER1_TICKERS`` set — when a curated ticker fails this predicate
    or a non-curated ticker passes it, the reconciliation report calls
    for a manual review.

    Required keys in ``financials`` (all optional / nullable; a missing
    or non-numeric value disqualifies the ticker):

      * ``market_cap_cr``       — market cap in ₹ Crore
      * ``revenue_cagr_5y``     — 5-year revenue CAGR as a decimal (0.12 = 12%)
      * ``fcf_5y``              — list of last 5 annual FCF values
      * ``roce_5y``             — list of last 5 annual ROCE values
                                   (decimals, 0.18 = 18%)
      * ``sector``              — sector tag (see ``_TIER1_BLOCKED_SECTORS``)
      * ``listed_years``        — years since IPO (for the "recent IPO"
                                   gate; <3 disqualifies regardless of
                                   sector tag)
    """
    if not financials:
        return False

    # 5. Sector gate (cheapest, fails fastest)
    sector = financials.get("sector")
    if sector and str(sector).strip() in _TIER1_BLOCKED_SECTORS:
        return False

    listed_years = _coerce_float(financials.get("listed_years"))
    if listed_years is not None and listed_years < 3.0:
        return False

    # 1. Market cap > ₹50,000 Cr
    mcap = _coerce_float(financials.get("market_cap_cr"))
    if mcap is None or mcap <= TIER1_MARKET_CAP_FLOOR_CR:
        return False

    # 2. 5y revenue CAGR available + sensible (not null, not > 30%)
    cagr = _coerce_float(financials.get("revenue_cagr_5y"))
    if cagr is None or cagr > TIER1_REVENUE_CAGR_CEILING:
        return False

    # 3. 5y FCF positive median (no severe cycle troughs)
    fcf_series_raw = financials.get("fcf_5y") or []
    fcf_series: list[float] = []
    for v in fcf_series_raw:
        f = _coerce_float(v)
        if f is not None:
            fcf_series.append(f)
    if len(fcf_series) < 5:
        return False
    fcf_median = _median(fcf_series)
    if fcf_median is None or fcf_median <= 0:
        return False

    # 4. ROCE > 15% sustained (median of 5y series ≥ 15 %)
    roce_series_raw = financials.get("roce_5y") or []
    roce_series: list[float] = []
    for v in roce_series_raw:
        f = _coerce_float(v)
        if f is not None:
            roce_series.append(f)
    if len(roce_series) < 5:
        return False
    roce_median = _median(roce_series)
    if roce_median is None or roce_median < TIER1_MIN_ROCE:
        return False

    return True
