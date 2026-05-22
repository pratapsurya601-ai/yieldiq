# backend/services/analysis/sector_overrides.py
"""Day-107b (2026-05-23) — FMCG sector cohort overrides.

Companion to the Day-84 pharma franchise cohort and Day-92 utility
bear-floor patterns: when an Indian FMCG large-cap franchise (HUL,
NESTLE, ITC, BRITANNIA, ...) is being valued, the generic DCF gives
up too much terminal-value because:

  1. ``terminal_growth`` defaults to 4.0% — that's below India's
     nominal household-consumption CAGR (8-10% nominal, 4-5% real,
     ~5% blended for a ~40y horizon).
  2. ``WACC`` from CAPM lands at 11-13% for these names even though
     their beta is 0.5-0.7 and balance sheets are net-cash.
  3. Pure financial-ratio moat scoring undervalues the 40+ year
     distribution moat that HUL / NESTLE / BRITANNIA enjoy.
  4. Scenario weights default to 30/50/20 (bull/base/bear) which
     is symmetric for cyclicals but too bearish for the very small
     set of franchise leaders that compound through downturns.

This module is the single source of truth for which Indian FMCG
tickers receive which overrides and at what magnitude. Wired into:

  - ``backend/services/analysis/service.py`` for the TG lift +
    WACC tighten (mirrors the Day-84 pharma-franchise inline block).
  - ``screener/moat_engine.py`` for the moat-pillar floor (top-4
    franchise leaders get a floor of 75 on the moat score — above
    the existing ALLOWLIST_MOAT_FLOOR_SCORE of 70 — because their
    moats are structurally stronger than the broader allowlist).
  - ``backend/services/cache_invalidation_manifest.py`` so the
    scoped invalidation entry (no CACHE_VERSION bump) is wired.

═══════════════════════════════════════════════════════════════════
Cohort medians (annual, multi-year)
═══════════════════════════════════════════════════════════════════
EBIT margin band: 18-25% across the cohort (top tier 20-25%, tier-2
14-20%). De ratio: <0.3 for most (net-cash businesses). ROCE: HUL
~95%, NESTLE ~80%, ITC ~32%, BRITANNIA ~58%, DABUR ~22%, MARICO
~38%, COLPAL ~85%, GODREJCP ~20%, EMAMI ~32%, TATACONSUM ~12%,
VBL ~28%. ROA: 15-25% top tier, 8-15% tier-2. These ranges drive
the tier assignment below.
═══════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

from typing import Final


# ── Top-4 franchise leaders ──────────────────────────────────────
# 40+ year India distribution moats, 20%+ category share, ROCE
# 50-100%. These deserve the strongest TG lift (5.0%) and the
# tightest WACC floor (8.5%) — except ITC which has a long cigarette
# tail risk that justifies a slightly lower TG.
_FMCG_TOP_FRANCHISE_TICKERS: Final[frozenset[str]] = frozenset({
    "HINDUNILVR",   # HUL — Lever India, 40+ yr distribution moat
    "NESTLEIND",    # Nestle India — Maggi / Nescafe / KitKat franchise
    "BRITANNIA",    # Britannia — biscuit category leader
    # ITC handled separately (see _FMCG_ITC_SPECIAL below) because
    # cigarette tail risk warrants TG 4.5% not 5.0%.
})

# ITC sits in the top-4 franchise leaders by category share but the
# cigarette business carries demographic / regulatory tail risk that
# the other three names don't. Modelled at TG 4.5% (between the
# top-tier 5.0% and the tier-2 4.5%) and the same 8.5% WACC floor.
_FMCG_ITC_SPECIAL: Final[frozenset[str]] = frozenset({"ITC"})

# ── Tier-2 franchises ────────────────────────────────────────────
# Established categories, 15-20% share, ROCE 20-40%. TG 4.5%.
_FMCG_TIER2_FRANCHISE_TICKERS: Final[frozenset[str]] = frozenset({
    "DABUR",        # Dabur — Ayurveda / oral care
    "MARICO",       # Marico — Parachute / Saffola
    "COLPAL",       # Colgate-Palmolive India — oral care
    "GODREJCP",     # Godrej Consumer Products
})

# ── Tier-3 / wider band ──────────────────────────────────────────
# Smaller share, more sub-category exposure. Default TG 4.0% but
# WACC tighten still applies (net-cash, low-beta).
_FMCG_TIER3_FRANCHISE_TICKERS: Final[frozenset[str]] = frozenset({
    "EMAMILTD",     # Emami — personal care
    "TATACONSUM",   # Tata Consumer Products — Tata Tea, Sampann
    "VBL",          # Varun Beverages — Pepsi franchise bottler
})

# ── Union (all FMCG cohort members) ──────────────────────────────
_FMCG_COHORT_TICKERS_INLINE: Final[frozenset[str]] = (
    _FMCG_TOP_FRANCHISE_TICKERS
    | _FMCG_ITC_SPECIAL
    | _FMCG_TIER2_FRANCHISE_TICKERS
    | _FMCG_TIER3_FRANCHISE_TICKERS
)

# ── Public override constants ────────────────────────────────────
# Top-tier TG lift (HUL / NESTLEIND / BRITANNIA only).
FMCG_TG_TOP: Final[float] = 0.050
# ITC TG lift (cigarette tail risk discount vs the other top-4).
FMCG_TG_ITC: Final[float] = 0.045
# Tier-2 TG lift.
FMCG_TG_TIER2: Final[float] = 0.045
# Tier-3 TG lift (default — no lift relative to country default).
FMCG_TG_TIER3: Final[float] = 0.040

# WACC floor — FMCG balance sheets are net-cash with beta 0.5-0.7.
# CAPM systematically over-charges them. Floor at 8.5%.
FMCG_WACC_FLOOR: Final[float] = 0.085

# Moat pillar floor for top-4 franchise leaders. Above the existing
# ALLOWLIST_MOAT_FLOOR_SCORE (70 / "Wide") because their moats are
# durably stronger than the broader allowlist set.
FMCG_TOP_MOAT_FLOOR: Final[int] = 75

# Scenario weights — slightly bullish skew for top-4 franchise
# leaders. Default elsewhere is 30/50/20. Top-4 get 40/40/20.
FMCG_TOP_SCENARIO_WEIGHTS: Final[tuple[float, float, float]] = (0.40, 0.40, 0.20)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _bare(ticker: str | None) -> str:
    """Strip exchange suffix; upper-case. Mirrors the Day-84 helper."""
    if not ticker:
        return ""
    bare = str(ticker).strip().upper()
    for suffix in (".NS", ".BO", ".BSE", ".NSE"):
        if bare.endswith(suffix):
            bare = bare[: -len(suffix)]
            break
    return bare


def is_fmcg_cohort_ticker(ticker: str | None) -> bool:
    """True if the ticker is in the Day-107b FMCG cohort (any tier)."""
    return _bare(ticker) in _FMCG_COHORT_TICKERS_INLINE


def is_fmcg_top_franchise(ticker: str | None) -> bool:
    """True for the top-4 franchise leaders (HUL, NESTLE, ITC,
    BRITANNIA). These receive the strongest moat-floor lift and the
    bullish scenario weighting."""
    bare = _bare(ticker)
    return bare in _FMCG_TOP_FRANCHISE_TICKERS or bare in _FMCG_ITC_SPECIAL


def fmcg_terminal_growth(ticker: str | None) -> float | None:
    """Return the Day-107b FMCG cohort terminal-growth target, or
    ``None`` if the ticker is not in the cohort. The caller is
    responsible for the ``terminal_g < target`` lift gate and the
    ``wacc - 0.02`` safety guard — same shape as the Day-84 block."""
    bare = _bare(ticker)
    if bare in _FMCG_TOP_FRANCHISE_TICKERS:
        return FMCG_TG_TOP
    if bare in _FMCG_ITC_SPECIAL:
        return FMCG_TG_ITC
    if bare in _FMCG_TIER2_FRANCHISE_TICKERS:
        return FMCG_TG_TIER2
    if bare in _FMCG_TIER3_FRANCHISE_TICKERS:
        return FMCG_TG_TIER3
    return None


def fmcg_wacc_floor(ticker: str | None) -> float | None:
    """Return the Day-107b FMCG WACC floor (8.5%), or ``None`` if the
    ticker is not in the cohort. The caller tightens via ``min()``
    against the CAPM-computed WACC — symmetric with the Day-84
    franchise WACC cap."""
    if is_fmcg_cohort_ticker(ticker):
        return FMCG_WACC_FLOOR
    return None


def fmcg_moat_floor(ticker: str | None) -> int | None:
    """Return the Day-107b moat-pillar floor for top-4 franchise
    leaders (75/100), or ``None`` for everything else.

    This is a STRICTLY HIGHER floor than the existing
    ``ALLOWLIST_MOAT_FLOOR_SCORE`` (70). The allowlist captures
    bellwether brands across all sectors; this floor is reserved for
    the narrow set of FMCG names with 20%+ category share AND 40+
    year distribution moats."""
    if is_fmcg_top_franchise(ticker):
        return FMCG_TOP_MOAT_FLOOR
    return None


def fmcg_scenario_weights(
    ticker: str | None,
) -> tuple[float, float, float] | None:
    """Return (bull, base, bear) probability weights for top-4
    franchise leaders, or ``None`` for everything else. Tier-2 and
    tier-3 use the default symmetric weighting from
    ``compute_for_date.py``."""
    if is_fmcg_top_franchise(ticker):
        return FMCG_TOP_SCENARIO_WEIGHTS
    return None


# Re-export the inline set for source-text tests that need to lift
# membership directly (mirrors Day-84's ``_PHARMA_FRANCHISE_TICKERS_
# INLINE`` extract pattern).
FMCG_COHORT_TICKERS_INLINE = _FMCG_COHORT_TICKERS_INLINE
FMCG_TOP_FRANCHISE_TICKERS = _FMCG_TOP_FRANCHISE_TICKERS
FMCG_ITC_SPECIAL = _FMCG_ITC_SPECIAL
FMCG_TIER2_FRANCHISE_TICKERS = _FMCG_TIER2_FRANCHISE_TICKERS
FMCG_TIER3_FRANCHISE_TICKERS = _FMCG_TIER3_FRANCHISE_TICKERS
