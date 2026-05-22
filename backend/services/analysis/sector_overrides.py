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


# ═══════════════════════════════════════════════════════════════════
# Day-109b (2026-05-23) — NBFC (Non-Bank Finance) sector cohort
# ═══════════════════════════════════════════════════════════════════
# NBFCs already route through the P/B financial-company path
# (``is_bank_like`` returns True for them via the
# ``_NBFC_INSURANCE_BANKLIKE`` set in constants.py). What they lack
# is sub-segment-aware fair-P/B anchoring. The peer-median engine in
# financial_valuation_service splits HFCs (traditional vs premium)
# but lumps diversified-Tier-1 NBFCs (BAJFINANCE) with gold-loan
# (MUTHOOTFIN/MANAPPURAM) and vehicle-finance (CHOLAFIN/SHRIRAMFIN/
# SUNDARMFIN/MMFIN) in a single ``lending_nbfc`` bucket. That bucket
# median over-anchors gold-loan and vehicle-finance (which trade at
# ~2.0-2.5× P/BV) toward BAJFINANCE's structurally higher multiple
# (5-6× P/BV), and under-anchors BAJFINANCE itself.
#
# This module is the SSOT for NBFC sub-segment fair-P/B anchoring +
# AUM-growth boost. Wired into:
#
#   - ``backend/services/financial_valuation_service.py`` in
#     ``_compute_pbv_path`` AFTER the peer-median × ROE-adj math and
#     BEFORE the top-private-bank P/B bump, via
#     ``nbfc_pb_anchor(ticker)`` + ``nbfc_pb_band(ticker)``. The
#     anchor REPLACES ``fair_pb`` when set; the band CLAMPS it. The
#     AUM-growth boost is a multiplicative lift on the anchor.
#   - ``backend/services/cache_invalidation_manifest.py`` (scoped
#     entry, no CACHE_VERSION bump).
#
# Sub-segment medians (anchor / band):
#
#   Diversified Tier-1 (BAJFINANCE): anchor 5.0, band [4.0, 7.0].
#       Justification: 20%+ ROE, tech-led acquisition, structurally
#       higher P/BV than the broader NBFC cohort.
#   HFC pure-play (LICHSGFIN/PNBHOUSING/REPCO): anchor 1.4, band
#       [1.0, 2.0]. Justification: tight NIM (~2.5%), low credit
#       cost but low ROE (10-13%).
#   Gold loan (MUTHOOTFIN/MANAPPURAM): anchor 2.2, band [1.8, 3.0].
#       Justification: secured lending, AUM-linked, gold-price
#       cyclical.
#   MFI / Microfinance (CREDITACC): anchor 1.8, band [1.5, 2.5].
#       Stress flag at GNPA > 3% (MFI defaults concentrate fast).
#   Vehicle finance (CHOLAFIN/MMFIN/SHRIRAMFIN/SUNDARMFIN): anchor
#       2.2, band [1.8, 3.0].
#
# AUM-growth boost: TTM AUM growth > 25% → anchor × 1.15. TTM AUM
# growth < 5% → anchor × 0.90. Between → no boost.
#
# EXCLUSIONS:
#   - HDFCLIFE is INSURANCE, not lending. The classifier in
#     constants.py routes it to ``life_insurance`` (Appraisal Value
#     engine). It is NOT in any NBFC sub-segment set. See
#     follow-up: Day-XXX insurance cohort.
#   - BAJAJFINSV is a holding company (Bajaj Finserv holdco) — its
#     P/BV is dominated by sum-of-parts (BAJFINANCE stake + Bajaj
#     Allianz GI/life stakes), not by operating lending economics.
#     Flagged for skip; downstream caller (service.py) decides.
# ═══════════════════════════════════════════════════════════════════

# Diversified Tier-1 NBFCs — premium P/B band, ROE 20%+.
_NBFC_DIVERSIFIED_TIER1: Final[frozenset[str]] = frozenset({
    "BAJFINANCE",
})

# Holdcos / sum-of-parts NBFCs — flagged for skip (no operating
# anchor). BAJAJFINSV holds majority stakes in BAJFINANCE + Bajaj
# Allianz; its P/BV reflects SOTP, not lending economics.
_NBFC_HOLDCO_SKIP: Final[frozenset[str]] = frozenset({
    "BAJAJFINSV",
    "BAJAJHLDNG",
})

# HFC pure-play (housing finance) — thin NIM, low ROE.
_NBFC_HFC_PUREPLAY: Final[frozenset[str]] = frozenset({
    "LICHSGFIN",
    "PNBHOUSING",
    "REPCO",
})

# Gold-loan NBFCs — secured lending, gold-price cyclical.
_NBFC_GOLD_LOAN: Final[frozenset[str]] = frozenset({
    "MUTHOOTFIN",
    "MANAPPURAM",
})

# MFI / Microfinance — concentrated default risk.
_NBFC_MFI: Final[frozenset[str]] = frozenset({
    "CREDITACC",
})

# Vehicle-finance NBFCs.
_NBFC_VEHICLE_FINANCE: Final[frozenset[str]] = frozenset({
    "CHOLAFIN",
    "MMFIN",      # M&M Financial Services (canonical NSE: M&MFIN —
                  # but the cohort engine's _bare() upper-cases and
                  # strips suffix; downstream callers normalise '&').
    "M&MFIN",
    "SHRIRAMFIN",
    "SUNDARMFIN",
})

# Insurance — explicitly NOT in NBFC cohort. Listed here so the
# detection helper can return a sentinel and the caller can skip.
_NBFC_INSURANCE_EXCLUDE: Final[frozenset[str]] = frozenset({
    "HDFCLIFE", "SBILIFE", "ICICIPRULI", "LICI", "CANHLIFE",
})

# ── Union (all NBFC cohort members with sub-segment anchors) ──────
_NBFC_COHORT_TICKERS_INLINE: Final[frozenset[str]] = (
    _NBFC_DIVERSIFIED_TIER1
    | _NBFC_HFC_PUREPLAY
    | _NBFC_GOLD_LOAN
    | _NBFC_MFI
    | _NBFC_VEHICLE_FINANCE
)

# ── Public PB-anchor + band constants ────────────────────────────
# Diversified Tier-1 (BAJFINANCE).
NBFC_PB_ANCHOR_DIVERSIFIED_TIER1: Final[float] = 5.0
NBFC_PB_BAND_DIVERSIFIED_TIER1: Final[tuple[float, float]] = (4.0, 7.0)

# HFC pure-play.
NBFC_PB_ANCHOR_HFC: Final[float] = 1.4
NBFC_PB_BAND_HFC: Final[tuple[float, float]] = (1.0, 2.0)

# Gold loan.
NBFC_PB_ANCHOR_GOLD: Final[float] = 2.2
NBFC_PB_BAND_GOLD: Final[tuple[float, float]] = (1.8, 3.0)

# MFI / Microfinance.
NBFC_PB_ANCHOR_MFI: Final[float] = 1.8
NBFC_PB_BAND_MFI: Final[tuple[float, float]] = (1.5, 2.5)

# Vehicle finance.
NBFC_PB_ANCHOR_VEHICLE: Final[float] = 2.2
NBFC_PB_BAND_VEHICLE: Final[tuple[float, float]] = (1.8, 3.0)

# MFI stress flag — GNPA above this surfaces as data_issues item.
NBFC_MFI_GNPA_STRESS_THRESHOLD: Final[float] = 0.03

# AUM-growth boost thresholds and multipliers.
NBFC_AUM_GROWTH_HIGH_THRESHOLD: Final[float] = 0.25
NBFC_AUM_GROWTH_HIGH_MULT: Final[float] = 1.15
NBFC_AUM_GROWTH_LOW_THRESHOLD: Final[float] = 0.05
NBFC_AUM_GROWTH_LOW_MULT: Final[float] = 0.90


def is_nbfc_cohort_ticker(ticker: str | None) -> bool:
    """True if the ticker is in the Day-109b NBFC cohort (any
    sub-segment with a fair-P/B anchor). Excludes HDFCLIFE (insurance)
    and BAJAJFINSV (holdco) explicitly."""
    return _bare(ticker) in _NBFC_COHORT_TICKERS_INLINE


def is_nbfc_insurance_excluded(ticker: str | None) -> bool:
    """True if the ticker is an insurer that LOOKS NBFC-ish but is
    explicitly NOT in this cohort. The caller should route insurance
    through ``life_insurance`` / ``psu_gi`` / ``private_gi`` /
    ``health_insurance`` peer buckets instead."""
    return _bare(ticker) in _NBFC_INSURANCE_EXCLUDE


def is_nbfc_holdco_skip(ticker: str | None) -> bool:
    """True for sum-of-parts holdcos (BAJAJFINSV / BAJAJHLDNG) where
    operating-lender P/BV anchoring is structurally wrong."""
    return _bare(ticker) in _NBFC_HOLDCO_SKIP


def nbfc_sub_segment(ticker: str | None) -> str | None:
    """Return the NBFC sub-segment key for a ticker, or ``None`` if
    the ticker is not in the cohort.

    Sub-segment keys (stable, surfaced in ``_meta`` for downstream
    canary diff + admin debug):
      ``diversified_tier1`` | ``hfc_pureplay`` | ``gold_loan`` |
      ``mfi`` | ``vehicle_finance``
    """
    bare = _bare(ticker)
    if bare in _NBFC_DIVERSIFIED_TIER1:
        return "diversified_tier1"
    if bare in _NBFC_HFC_PUREPLAY:
        return "hfc_pureplay"
    if bare in _NBFC_GOLD_LOAN:
        return "gold_loan"
    if bare in _NBFC_MFI:
        return "mfi"
    if bare in _NBFC_VEHICLE_FINANCE:
        return "vehicle_finance"
    return None


def nbfc_pb_anchor(ticker: str | None) -> float | None:
    """Return the sub-segment fair-P/B anchor for a Day-109b NBFC
    cohort member, or ``None`` if not in cohort. Caller passes through
    ``nbfc_aum_growth_boost`` and ``nbfc_pb_band`` clamp before
    multiplying by BVPS."""
    seg = nbfc_sub_segment(ticker)
    if seg == "diversified_tier1":
        return NBFC_PB_ANCHOR_DIVERSIFIED_TIER1
    if seg == "hfc_pureplay":
        return NBFC_PB_ANCHOR_HFC
    if seg == "gold_loan":
        return NBFC_PB_ANCHOR_GOLD
    if seg == "mfi":
        return NBFC_PB_ANCHOR_MFI
    if seg == "vehicle_finance":
        return NBFC_PB_ANCHOR_VEHICLE
    return None


def nbfc_pb_band(ticker: str | None) -> tuple[float, float] | None:
    """Return the sub-segment fair-P/B band (low, high) for a Day-109b
    NBFC cohort member, or ``None`` if not in cohort. The caller
    clamps the AUM-growth-boosted anchor into this band BEFORE
    multiplying by BVPS — that way an extreme AUM-growth print can't
    inflate the fair multiple past the sub-segment's structural
    ceiling."""
    seg = nbfc_sub_segment(ticker)
    if seg == "diversified_tier1":
        return NBFC_PB_BAND_DIVERSIFIED_TIER1
    if seg == "hfc_pureplay":
        return NBFC_PB_BAND_HFC
    if seg == "gold_loan":
        return NBFC_PB_BAND_GOLD
    if seg == "mfi":
        return NBFC_PB_BAND_MFI
    if seg == "vehicle_finance":
        return NBFC_PB_BAND_VEHICLE
    return None


def nbfc_aum_growth_boost(
    ticker: str | None,
    aum_growth_yoy: float | None,
) -> float:
    """Return a multiplicative anchor boost factor based on TTM AUM
    growth.

    - ``aum_growth_yoy > 0.25`` → 1.15 (high-growth NBFC premium)
    - ``aum_growth_yoy < 0.05`` → 0.90 (de-rating for stalled AUM)
    - otherwise (or None / NaN / non-cohort) → 1.0 (no change)

    The caller falls back to revenue_yoy as proxy when an AUM column
    is not present in the ratio store, and documents the fallback in
    ``_meta`` for downstream auditability. Don't fabricate growth.
    """
    if not is_nbfc_cohort_ticker(ticker):
        return 1.0
    if aum_growth_yoy is None:
        return 1.0
    try:
        g = float(aum_growth_yoy)
    except (TypeError, ValueError):
        return 1.0
    # NaN guard — NaN is the only float that isn't equal to itself.
    if g != g:
        return 1.0
    if g > NBFC_AUM_GROWTH_HIGH_THRESHOLD:
        return NBFC_AUM_GROWTH_HIGH_MULT
    if g < NBFC_AUM_GROWTH_LOW_THRESHOLD:
        return NBFC_AUM_GROWTH_LOW_MULT
    return 1.0


def nbfc_mfi_stress_flag(
    ticker: str | None, gnpa: float | None,
) -> bool:
    """True if the ticker is an MFI sub-segment member AND its GNPA
    exceeds the stress threshold (3%). Caller surfaces as
    informational ``data_issues`` item — does NOT gate verdict."""
    if nbfc_sub_segment(ticker) != "mfi":
        return False
    if gnpa is None:
        return False
    try:
        g = float(gnpa)
    except (TypeError, ValueError):
        return False
    if g != g:
        return False
    return g > NBFC_MFI_GNPA_STRESS_THRESHOLD


# Re-export inline sets for source-text tests (mirrors the FMCG
# extract pattern above).
NBFC_COHORT_TICKERS_INLINE = _NBFC_COHORT_TICKERS_INLINE
NBFC_DIVERSIFIED_TIER1 = _NBFC_DIVERSIFIED_TIER1
NBFC_HFC_PUREPLAY = _NBFC_HFC_PUREPLAY
NBFC_GOLD_LOAN = _NBFC_GOLD_LOAN
NBFC_MFI = _NBFC_MFI
NBFC_VEHICLE_FINANCE = _NBFC_VEHICLE_FINANCE
NBFC_INSURANCE_EXCLUDE = _NBFC_INSURANCE_EXCLUDE
NBFC_HOLDCO_SKIP = _NBFC_HOLDCO_SKIP


# ═══════════════════════════════════════════════════════════════════
# Day-109a (2026-05-23) — Banking sector cohort overrides
# ═══════════════════════════════════════════════════════════════════
# Companion to the existing Day-76 PB-ratio skip path (banks already
# bypass generic DCF in favour of P/BV peer-median valuation via
# ``financial_valuation_service._compute_pbv_path``). The cohort here
# adds NUANCE on top of that path:
#
#   1. **Tier-specific fair P/BV bands** instead of one peer median.
#      Tier-1 private (HDFC/ICICI/KOTAK/AXIS/INDUSIND) trade at very
#      different multiples than PSU (SBIN) and Tier-2 mid-caps. The
#      Day-76 peer-median pools all "psu_banks" or "pvt_banks" but
#      the spread within each pool is wide. Anchoring to per-tier
#      medians (3.0x / 1.2x / 1.8x) reduces single-peer-blowup risk.
#
#   2. **ROE-quality boost**. Banks with TTM ROE >= 16% AND gross NPA
#      <= 2.0% are durably higher-quality (HDFCBANK shape) — anchor
#      P/BV gets a +20% lift so HDFCBANK lands near 3.6x book rather
#      than the cohort median 3.0x.
#
#   3. **Stress flag**. GNPA > 5.0% OR provision coverage < 60% sets
#      `data_limited=True` and surfaces "stressed book" in the
#      data_issues list so verdicts stay calibrated.
#
# **Critical**: banks do NOT get DCF. The cohort layers on top of the
# existing PB-ratio path. The PB band + anchor are returned for the
# caller to combine with BVPS; the engine integration in
# ``backend/services/analysis/service.py`` consults
# ``banking_pb_anchor()`` after the existing peer-median runs, so the
# Day-76 ``TOP_PRIVATE_BANK_PB_BUMP`` and tier-1 COE compression
# remain in effect — this cohort is additive nuance, not replacement.
#
# ═══════════════════════════════════════════════════════════════════
# Cohort medians (sourced from market multiples, FY24-FY26 trailing)
# ═══════════════════════════════════════════════════════════════════
# Tier-1 private (HDFCBANK 2.7x, ICICIBANK 3.3x, KOTAKBANK 3.0x,
# AXISBANK 2.4x, INDUSINDBK 2.0x): cohort median 3.0x book; fair band
# 2.5x-4.0x. ROE band 14-18%, GNPA band 1.4-2.4%.
# PSU (SBIN current 1.1-1.3x book): fair band 0.9x-1.6x, anchor 1.2x.
# Tier-2 (FEDERALBNK 1.4x, IDFCFIRSTB 1.5x, AUBANK 2.5x, BANDHANBNK
# 1.3x, RBLBANK 0.9x): cohort median 1.8x; fair band 1.2x-2.5x.
#
# Data gap (2026-05-23): GNPA + provision_coverage are not in the
# local parquet ratio_history (no `data/parquet/` exists in this
# checkout). The asset-quality knob accepts optional caller-provided
# GNPA + PCR — when both are None it degrades to "anchor only" and
# the stress flag never fires. Phase 2 will populate from
# NSE-XBRL-Sch-XVIII (Asset Classification) once extraction lands;
# see `bank_data_availability.md` for the coverage matrix.
# ═══════════════════════════════════════════════════════════════════

# ── Tier-1 private (large-cap private banks) ─────────────────────
_BANKING_TIER1_PRIVATE_TICKERS: Final[frozenset[str]] = frozenset({
    "HDFCBANK",
    "ICICIBANK",
    "KOTAKBANK",
    "AXISBANK",
    "INDUSINDBK",
})

# ── PSU (state-owned) ────────────────────────────────────────────
# SBIN is the only Tier-1 PSU in the cohort. Other PSUs (PNB,
# BANKBARODA, CANBK, ...) are deliberately out of scope here — they
# fall back to the Day-76 peer-median PB path without per-tier
# anchoring until their data quality and governance discount can be
# modelled separately.
_BANKING_PSU_TICKERS: Final[frozenset[str]] = frozenset({
    "SBIN",
})

# ── Tier-2 / regional / mid-cap private ──────────────────────────
_BANKING_TIER2_TICKERS: Final[frozenset[str]] = frozenset({
    "FEDERALBNK",
    "IDFCFIRSTB",
    "AUBANK",
    "BANDHANBNK",
    "RBLBANK",
})

# ── Union (all banking cohort members) ───────────────────────────
_BANKING_TIER1_TICKERS_INLINE: Final[frozenset[str]] = (
    _BANKING_TIER1_PRIVATE_TICKERS
    | _BANKING_PSU_TICKERS
    | _BANKING_TIER2_TICKERS
)

# ── Public override constants ────────────────────────────────────
# Tier-1 private: fair P/BV band 2.5x-4.0x, anchor 3.0x
BANKING_TIER1_PRIVATE_PB_BAND: Final[tuple[float, float]] = (2.5, 4.0)
BANKING_TIER1_PRIVATE_PB_ANCHOR: Final[float] = 3.0

# PSU: fair P/BV band 0.9x-1.6x, anchor 1.2x
BANKING_PSU_PB_BAND: Final[tuple[float, float]] = (0.9, 1.6)
BANKING_PSU_PB_ANCHOR: Final[float] = 1.2

# Tier-2 / regional: fair P/BV band 1.2x-2.5x, anchor 1.8x
BANKING_TIER2_PB_BAND: Final[tuple[float, float]] = (1.2, 2.5)
BANKING_TIER2_PB_ANCHOR: Final[float] = 1.8

# ROE-quality boost: banks with TTM ROE >= 16% AND GNPA <= 2.0%
# get a +20% lift to their fair-PB anchor. Tuned so HDFCBANK
# (ROE ~17.5%, GNPA ~1.4%) lands at 3.0 * 1.2 = 3.6x book.
BANKING_ROE_QUALITY_THRESHOLD_ROE: Final[float] = 0.16
BANKING_ROE_QUALITY_THRESHOLD_GNPA: Final[float] = 0.02
BANKING_ROE_QUALITY_BOOST: Final[float] = 1.20

# Stress flag thresholds
BANKING_STRESS_GNPA: Final[float] = 0.05   # >5% gross NPA
BANKING_STRESS_PCR: Final[float] = 0.60    # <60% provision coverage


def is_banking_cohort_ticker(ticker: str | None) -> bool:
    """True if the ticker is in the Day-109a banking cohort (any tier)."""
    return _bare(ticker) in _BANKING_TIER1_TICKERS_INLINE


def banking_tier(ticker: str | None) -> str | None:
    """Return the banking-cohort tier label or ``None`` if not in cohort.

    Tier labels: ``"tier1_private"``, ``"psu"``, ``"tier2"``. Used by
    callers to select the right PB band / anchor and to surface the
    tier in audit metadata."""
    bare = _bare(ticker)
    if bare in _BANKING_TIER1_PRIVATE_TICKERS:
        return "tier1_private"
    if bare in _BANKING_PSU_TICKERS:
        return "psu"
    if bare in _BANKING_TIER2_TICKERS:
        return "tier2"
    return None


def banking_pb_band(ticker: str | None) -> tuple[float, float] | None:
    """Return the (low, high) fair P/BV band for the cohort tier, or
    ``None`` if the ticker is not in the cohort. The caller uses this
    band as the "undervalued below low / overvalued above high" gate
    when surfacing verdicts on top of the Day-76 PB-ratio engine."""
    tier = banking_tier(ticker)
    if tier == "tier1_private":
        return BANKING_TIER1_PRIVATE_PB_BAND
    if tier == "psu":
        return BANKING_PSU_PB_BAND
    if tier == "tier2":
        return BANKING_TIER2_PB_BAND
    return None


def banking_pb_anchor(ticker: str | None) -> float | None:
    """Return the median fair P/BV anchor for the cohort tier, or
    ``None`` if the ticker is not in the cohort. The anchor is the
    single-number multiple used when no ROE-quality boost fires —
    multiply by BVPS to get the cohort-anchored fair value."""
    tier = banking_tier(ticker)
    if tier == "tier1_private":
        return BANKING_TIER1_PRIVATE_PB_ANCHOR
    if tier == "psu":
        return BANKING_PSU_PB_ANCHOR
    if tier == "tier2":
        return BANKING_TIER2_PB_ANCHOR
    return None


def banking_roe_quality_boost(
    ticker: str | None,
    roe: float | None,
    gnpa: float | None,
) -> float:
    """Return the multiplicative boost to apply to the cohort PB
    anchor for high-ROE / clean-book banks.

    Fires (returns ``BANKING_ROE_QUALITY_BOOST = 1.20``) when ALL of:
      - ticker is in the Day-109a banking cohort
      - ``roe`` is not None and >= 16% (0.16 as decimal, OR 16.0+ as
        percent — the helper auto-detects via the >1 heuristic)
      - ``gnpa`` is not None and <= 2.0% (decimal 0.02 OR percent 2.0)

    Otherwise returns 1.0 — including when either input is None
    (data gap → no boost, no penalty). Calibrated so HDFCBANK
    (ROE 17.5%, GNPA 1.4%) lands at anchor * 1.2 = 3.6x book."""
    if not is_banking_cohort_ticker(ticker):
        return 1.0
    if roe is None or gnpa is None:
        return 1.0
    # Normalise: accept either decimal (0.175) or percent (17.5).
    roe_dec = float(roe) / 100.0 if float(roe) > 1.0 else float(roe)
    gnpa_dec = float(gnpa) / 100.0 if float(gnpa) > 1.0 else float(gnpa)
    if (
        roe_dec >= BANKING_ROE_QUALITY_THRESHOLD_ROE
        and gnpa_dec <= BANKING_ROE_QUALITY_THRESHOLD_GNPA
    ):
        return BANKING_ROE_QUALITY_BOOST
    return 1.0


def banking_stress_flag(
    ticker: str | None,
    gnpa: float | None,
    provision_coverage: float | None,
) -> bool:
    """Return True when the bank is in stress per cohort thresholds:
    gross NPA > 5% OR provision coverage ratio < 60%.

    Each input may be supplied as decimal (0.05) or percent (5.0);
    the helper auto-detects via the >1 heuristic. When BOTH inputs
    are None, returns False (data gap is not stress — the caller
    handles "stress unknown" separately via ``data_limited``)."""
    if not is_banking_cohort_ticker(ticker):
        return False
    gnpa_stress = False
    pcr_stress = False
    if gnpa is not None:
        g = float(gnpa) / 100.0 if float(gnpa) > 1.0 else float(gnpa)
        gnpa_stress = g > BANKING_STRESS_GNPA
    if provision_coverage is not None:
        p = (
            float(provision_coverage) / 100.0
            if float(provision_coverage) > 1.0
            else float(provision_coverage)
        )
        pcr_stress = p < BANKING_STRESS_PCR
    return gnpa_stress or pcr_stress


# Re-export inline sets for source-text tests + downstream callers.
BANKING_TIER1_TICKERS_INLINE = _BANKING_TIER1_TICKERS_INLINE
BANKING_TIER1_PRIVATE_TICKERS = _BANKING_TIER1_PRIVATE_TICKERS
BANKING_PSU_TICKERS = _BANKING_PSU_TICKERS
BANKING_TIER2_TICKERS = _BANKING_TIER2_TICKERS
