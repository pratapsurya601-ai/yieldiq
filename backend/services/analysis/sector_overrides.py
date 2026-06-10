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
# CAPM systematically over-charges them. Floor aligned with Damodaran's
# India staples cost-of-capital reference, originally 8.5%.
#
# This constant gates WACC via cap semantics, NOT floor semantics.
# The call site at service.py:1517-1520 does: if wacc > target: wacc = target
# i.e., it CAPS WACC from above. Raising this value would loosen the cap
# (allow higher WACC inputs, but clamp them lower). The original PR #672
# intent (raise WACC to lower FMCG FVs) requires either renaming this to
# FMCG_WACC_CAP or inverting the operator. Reverted to 0.085 pending
# semantic fix in a separate PR.
FMCG_WACC_FLOOR: Final[float] = 0.085

# Moat pillar floor for top-4 franchise leaders. Above the existing
# ALLOWLIST_MOAT_FLOOR_SCORE (70 / "Wide") because their moats are
# durably stronger than the broader allowlist set.
FMCG_TOP_MOAT_FLOOR: Final[int] = 75

# Scenario weights — modest bullish tilt for top-4 franchise leaders.
# Default elsewhere is 30/50/20. Top-4 use 35/45/20, re-centred toward
# the base case (task #229: 40/40/20 skewed the blended FV too high
# relative to the Damodaran-anchored WACC floor above).
FMCG_TOP_SCENARIO_WEIGHTS: Final[tuple[float, float, float]] = (0.35, 0.45, 0.20)


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


# ─────────────────────────────────────────────────────────────────
# Day-111b (2026-05-23) — pure-bank detector for D/E numerator
# ─────────────────────────────────────────────────────────────────
# The Day-109a banking cohort is scoped to PB-anchoring eligibility
# (Tier-1 private / PSU / Tier-2). For the Day-111b D/E fix we need a
# broader "is this a commercial bank?" predicate that also captures
# the rest of the top-100 PSU bank universe (PNB, BANKBARODA, etc.)
# whose D/E was being computed as ~0.95 because deposits weren't in
# the numerator. We deliberately do NOT include NBFCs / insurers /
# AMCs here — their leverage profile is different and they already
# carry meaningful `total_debt`. Pure commercial banks only.
_PURE_BANK_TICKERS_FOR_DE: Final[frozenset[str]] = frozenset({
    # Tier-1 private (Day-109a)
    "HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK",
    # Tier-2 / regional / mid-cap private (Day-109a)
    "FEDERALBNK", "IDFCFIRSTB", "AUBANK", "BANDHANBNK", "RBLBANK",
    # PSU banks (SBIN from Day-109a + the broader top-100 PSU set)
    "SBIN", "PNB", "BANKBARODA", "CANBK", "BANKINDIA", "IOB",
    "UCOBANK", "CENTRALBK", "INDIANB", "MAHABANK", "IDBI", "UNIONBANK",
    # Older private + small-finance banks
    "YESBANK", "KARURVYSYA", "CUB", "DCBBANK", "SOUTHBANK", "TMB",
    "CAPITALSFB", "ESAFSFB", "EQUITASBNK", "UJJIVANSFB", "SURYODAY",
    "FINOPB", "JANASURF", "UTKARSHBNK", "FINCABK", "SFBAJM",
})


def is_pure_bank_for_de(ticker: str | None) -> bool:
    """True if the ticker is a commercial bank for D/E-numerator purposes.

    Broader than ``is_banking_cohort_ticker`` (which is PB-anchoring
    scoped). Used by Day-111b to route banks to the
    "(total_liabilities - equity) / equity" D/E formula instead of
    the generic "total_debt / equity" — which gives nonsensical ~0.95
    for banks because deposits live in total_liabilities, not
    total_debt. Excludes NBFCs / insurers / AMCs by design.
    """
    return _bare(ticker) in _PURE_BANK_TICKERS_FOR_DE


# Re-export for tests
PURE_BANK_TICKERS_FOR_DE = _PURE_BANK_TICKERS_FOR_DE


# ═══════════════════════════════════════════════════════════════════
# Day-110c (2026-05-23) — REIT / InvIT sector cohort overrides
# ═══════════════════════════════════════════════════════════════════
# Indian REITs (Real Estate Investment Trusts) and InvITs
# (Infrastructure Investment Trusts) are SEBI-regulated pass-through
# trusts that distribute >=90% of NDCF as DPU/distribution. Standard
# DCF mis-prices them by ~50% because:
#
#   1. Mandatory >=90% payout → retained earnings are structurally
#      near-zero → no organic compounding.
#   2. Forward growth = AUM expansion (new asset acquisitions), not
#      organic earnings growth → DCF terminal value is mispriced.
#   3. WACC under CAPM is artificially low (high leverage allowed
#      under SEBI rules), so the discount factor is wrong.
#
# The existing PR #333 / REIT short-circuit routes the 4 curated REITs
# (EMBASSY/MINDSPACE/BROOKFIELD/NEXUS) to a ``data_limited`` verdict
# with ``valuation_model="reit_nav_dpu_required"`` and IV=0. This
# cohort module is ADDITIVE — it computes a distribution-yield-based
# implied fair price and surfaces it in ``_meta`` for downstream
# callers (verdict gate, panel rendering, canary diff). It does NOT
# replace the short-circuit; the short-circuit's "DCF doesn't fit"
# message remains the user-facing engine model name.
#
# Sub-segments + fair distribution yield (vs 10y G-sec ~7.0%):
#
#   Office REIT (EMBASSY/MINDSPACE/BIRET):
#       fair yield band 6.5-7.5%, anchor 7.0%
#       (premium ~0-50bps over G-sec; rated commercial real estate)
#   Retail REIT (NEXUSSELECT):
#       fair yield band 7.0-8.0%, anchor 7.5%
#       (mall + consumption-cycle risk premium)
#   Roads InvIT (IRBINVIT):
#       fair yield band 10-12%, anchor 11.0%
#       (single-asset concentration, traffic-cycle risk)
#   Transmission InvIT (POWERGRIDIT/INDIGRID):
#       fair yield band 8-10%, anchor 9.0%
#       (regulated returns, transmission availability-linked)
#   Other InvIT (VIRTUS):
#       fair yield band 9-11%, anchor 10.0%
#
# Implied fair price = trailing_annual_distribution / fair_yield_anchor.
# Distribution-growth boost: trailing 3y distribution CAGR > 8% adds
# +10% to the implied fair price; CAGR < 3% cuts it by 10%.
#
# NOTE on the NEXUS / NEXUSSELECT split: the existing PR #335 curated
# REIT_TICKERS set in constants.py contains "NEXUS" (the legacy bare
# ticker used in earlier PRs). The actual NSE listing trades as
# "NEXUSSELECT". We accept BOTH in the Day-110c cohort to avoid
# breaking the existing classifier contract; the sub-segment helper
# maps both to "retail_reit".
#
# Data-availability discipline: if a per-unit annual distribution is
# not available in the parquet ratio store, callers should fall back
# to ``dividend_yield * current_price`` as a proxy. If even that's
# missing, SKIP (don't fabricate) and document in _meta as Phase 2.
# ═══════════════════════════════════════════════════════════════════

# ── Office REITs (commercial real estate) ───────────────────────
_REIT_OFFICE: Final[frozenset[str]] = frozenset({
    "EMBASSY",
    "MINDSPACE",
    "BIRET",           # Brookfield India Real Estate Trust
    "BROOKFIELD",      # legacy alias used in REIT_TICKERS (PR #335)
})

# ── Retail REITs (malls / consumption) ──────────────────────────
_REIT_RETAIL: Final[frozenset[str]] = frozenset({
    "NEXUSSELECT",
    "NEXUS",           # legacy alias used in REIT_TICKERS (PR #335)
})

# ── Roads InvITs (highway / toll concessions) ───────────────────
_INVIT_ROADS: Final[frozenset[str]] = frozenset({
    "IRBINVIT",
})

# ── Transmission InvITs (regulated power transmission) ──────────
_INVIT_TRANSMISSION: Final[frozenset[str]] = frozenset({
    "POWERGRIDIT",     # PowerGrid Infrastructure Investment Trust
    "INDIGRID",        # IndiGrid Trust
})

# ── Other / catch-all InvITs ────────────────────────────────────
_INVIT_OTHER: Final[frozenset[str]] = frozenset({
    "VIRTUS",          # Virtus Infra Trust
})

# ── Union (all REIT/InvIT cohort members) ───────────────────────
_REIT_INVIT_COHORT_TICKERS_INLINE: Final[frozenset[str]] = (
    _REIT_OFFICE
    | _REIT_RETAIL
    | _INVIT_ROADS
    | _INVIT_TRANSMISSION
    | _INVIT_OTHER
)

# Union of just-the-InvITs (used by the constants.is_invit
# classifier — separate from REITs because the existing PR #333
# REIT short-circuit branch logic also catches InvITs via this
# cohort helper).
_INVIT_TICKERS_INLINE: Final[frozenset[str]] = (
    _INVIT_ROADS | _INVIT_TRANSMISSION | _INVIT_OTHER
)

# ── Sub-segment fair distribution yield (anchor + band) ─────────
# Anchor is the single-number "fair yield" used to derive implied
# fair price (= trailing_distribution / anchor). Band is the
# undervalued/overvalued gate (yield ABOVE band-high → undervalued,
# BELOW band-low → overvalued; remember yield and price are
# inverse).
REIT_INVIT_YIELD_BAND_OFFICE: Final[tuple[float, float]] = (0.065, 0.075)
REIT_INVIT_YIELD_ANCHOR_OFFICE: Final[float] = 0.070

REIT_INVIT_YIELD_BAND_RETAIL: Final[tuple[float, float]] = (0.070, 0.080)
REIT_INVIT_YIELD_ANCHOR_RETAIL: Final[float] = 0.075

REIT_INVIT_YIELD_BAND_ROADS: Final[tuple[float, float]] = (0.100, 0.120)
REIT_INVIT_YIELD_ANCHOR_ROADS: Final[float] = 0.110

REIT_INVIT_YIELD_BAND_TRANSMISSION: Final[tuple[float, float]] = (0.080, 0.100)
REIT_INVIT_YIELD_ANCHOR_TRANSMISSION: Final[float] = 0.090

REIT_INVIT_YIELD_BAND_OTHER_INVIT: Final[tuple[float, float]] = (0.090, 0.110)
REIT_INVIT_YIELD_ANCHOR_OTHER_INVIT: Final[float] = 0.100

# Distribution-growth boost thresholds + multipliers
REIT_INVIT_DIST_GROWTH_HIGH_THRESHOLD: Final[float] = 0.08   # CAGR > 8%
REIT_INVIT_DIST_GROWTH_HIGH_MULT: Final[float] = 1.10        # +10% lift
REIT_INVIT_DIST_GROWTH_LOW_THRESHOLD: Final[float] = 0.03    # CAGR < 3%
REIT_INVIT_DIST_GROWTH_LOW_MULT: Final[float] = 0.90         # -10% cut


def is_reit_invit_cohort_ticker(ticker: str | None) -> bool:
    """True if the ticker is in the Day-110c REIT/InvIT cohort
    (any sub-segment). Used by service.py to surface sub-segment
    metadata + implied fair value in _meta alongside the existing
    PR #333 REIT short-circuit."""
    return _bare(ticker) in _REIT_INVIT_COHORT_TICKERS_INLINE


def is_invit_cohort_ticker(ticker: str | None) -> bool:
    """True if the ticker is an InvIT (Infrastructure Investment
    Trust) — roads / transmission / other. Separate from is_reit()
    because the existing PR #335 REIT classifier deliberately
    excludes InvITs (they are a separate SEBI category)."""
    return _bare(ticker) in _INVIT_TICKERS_INLINE


def reit_invit_subsegment(ticker: str | None) -> str | None:
    """Return the sub-segment key for a Day-110c cohort member, or
    ``None`` if the ticker is not in the cohort.

    Sub-segment keys (stable, surfaced in _meta):
      ``office_reit`` | ``retail_reit`` | ``roads_invit`` |
      ``transmission_invit`` | ``other_invit``
    """
    bare = _bare(ticker)
    if bare in _REIT_OFFICE:
        return "office_reit"
    if bare in _REIT_RETAIL:
        return "retail_reit"
    if bare in _INVIT_ROADS:
        return "roads_invit"
    if bare in _INVIT_TRANSMISSION:
        return "transmission_invit"
    if bare in _INVIT_OTHER:
        return "other_invit"
    return None


def reit_invit_fair_yield(
    ticker: str | None,
) -> tuple[float, tuple[float, float]] | None:
    """Return ``(anchor, (band_low, band_high))`` fair-distribution
    yield for the sub-segment, or ``None`` if the ticker is not in
    the cohort.

    Yields are expressed as decimals (0.07 == 7%). The anchor is the
    single-number "fair yield" used to derive implied fair price
    (= trailing annual distribution per unit / anchor).
    """
    seg = reit_invit_subsegment(ticker)
    if seg == "office_reit":
        return REIT_INVIT_YIELD_ANCHOR_OFFICE, REIT_INVIT_YIELD_BAND_OFFICE
    if seg == "retail_reit":
        return REIT_INVIT_YIELD_ANCHOR_RETAIL, REIT_INVIT_YIELD_BAND_RETAIL
    if seg == "roads_invit":
        return REIT_INVIT_YIELD_ANCHOR_ROADS, REIT_INVIT_YIELD_BAND_ROADS
    if seg == "transmission_invit":
        return (
            REIT_INVIT_YIELD_ANCHOR_TRANSMISSION,
            REIT_INVIT_YIELD_BAND_TRANSMISSION,
        )
    if seg == "other_invit":
        return (
            REIT_INVIT_YIELD_ANCHOR_OTHER_INVIT,
            REIT_INVIT_YIELD_BAND_OTHER_INVIT,
        )
    return None


def reit_invit_distribution_growth_boost(
    ticker: str | None,
    distribution_cagr_3y: float | None,
) -> float:
    """Return the multiplicative boost to apply to the implied fair
    price based on trailing 3y distribution CAGR.

    - CAGR > 8% → 1.10 (high-growth REIT/InvIT lift)
    - CAGR < 3% → 0.90 (stalled-distribution de-rating)
    - otherwise (or None / NaN / non-cohort) → 1.0 (no change)
    """
    if not is_reit_invit_cohort_ticker(ticker):
        return 1.0
    if distribution_cagr_3y is None:
        return 1.0
    try:
        c = float(distribution_cagr_3y)
    except (TypeError, ValueError):
        return 1.0
    if c != c:   # NaN guard
        return 1.0
    if c > REIT_INVIT_DIST_GROWTH_HIGH_THRESHOLD:
        return REIT_INVIT_DIST_GROWTH_HIGH_MULT
    if c < REIT_INVIT_DIST_GROWTH_LOW_THRESHOLD:
        return REIT_INVIT_DIST_GROWTH_LOW_MULT
    return 1.0


def compute_distribution_yield_fair_value(
    ticker: str | None,
    annual_distribution_per_unit: float | None,
    distribution_cagr_3y: float | None = None,
) -> dict | None:
    """Compute the distribution-yield-anchored implied fair price for
    a Day-110c REIT/InvIT cohort member.

    Args:
        ticker: bare or suffixed ticker (e.g. "EMBASSY", "EMBASSY.NS")
        annual_distribution_per_unit: trailing 12m distribution / DPU
            per unit, in INR. If None / non-positive, returns None
            (degrades gracefully — Phase 2 ingestion).
        distribution_cagr_3y: optional 3y trailing CAGR (decimal,
            e.g. 0.09 for 9%). If supplied, triggers the +/-10%
            boost gate. If None, the boost factor is 1.0.

    Returns:
        ``None`` if the ticker is not in the cohort or the
        distribution input is missing. Otherwise a dict with keys:

          ``subsegment`` (str): sub-segment key
          ``fair_yield_anchor`` (float): anchor yield (decimal)
          ``fair_yield_band`` (tuple[float, float]): low, high band
          ``annual_distribution_per_unit`` (float): echoed input
          ``implied_fair_price`` (float): distribution / anchor
              (in INR; pre-boost)
          ``distribution_growth_boost`` (float): 1.0 / 1.10 / 0.90
          ``implied_fair_price_boosted`` (float): post-boost fair
              price
          ``distribution_cagr_3y`` (float | None): echoed input

    Math:
        implied_fair_price = annual_distribution_per_unit / anchor
        boosted = implied_fair_price * boost
    """
    seg = reit_invit_subsegment(ticker)
    if seg is None:
        return None
    yield_pair = reit_invit_fair_yield(ticker)
    if yield_pair is None:
        return None
    if annual_distribution_per_unit is None:
        return None
    try:
        dist = float(annual_distribution_per_unit)
    except (TypeError, ValueError):
        return None
    if dist != dist:   # NaN guard
        return None
    if dist <= 0:
        return None

    anchor, band = yield_pair
    implied_fair = dist / anchor
    boost = reit_invit_distribution_growth_boost(
        ticker, distribution_cagr_3y,
    )
    boosted = implied_fair * boost
    return {
        "subsegment": seg,
        "fair_yield_anchor": float(anchor),
        "fair_yield_band": (float(band[0]), float(band[1])),
        "annual_distribution_per_unit": float(dist),
        "implied_fair_price": float(round(implied_fair, 4)),
        "distribution_growth_boost": float(boost),
        "implied_fair_price_boosted": float(round(boosted, 4)),
        "distribution_cagr_3y": (
            float(distribution_cagr_3y)
            if distribution_cagr_3y is not None
            else None
        ),
    }


# ═══════════════════════════════════════════════════════════════════
# Day-110b (2026-05-23) — Insurance sector cohort overrides
# ═══════════════════════════════════════════════════════════════════
# Companion to Day-109a (banking) and Day-109b (NBFC). Insurance is
# fundamentally different math: Indian life insurers are anchored on
# Price-to-Embedded-Value (P/EV), not P/B and never DCF. General
# insurers are P/B with a combined-ratio (CR) overlay.
#
# Existing infra context:
#   - ``backend/services/insurance_appraisal_service.py`` already ships
#     a full Appraisal-Value engine (EV + N×VNB) gated on operator-
#     loaded ``insurance_appraisal_inputs`` rows. When that table is
#     empty (every environment that hasn't had operator data entered)
#     the code falls through to the P/BV peer-median path. That fall-
#     through path is what Day-110b nuances.
#   - The peer groups ``life_insurance`` / ``psu_gi`` / ``private_gi``
#     / ``health_insurance`` already exist in financial_valuation_
#     service.py with per-bucket P/B fallbacks. Those buckets stay; we
#     LAYER tier-aware anchors + bands per sub-segment.
#   - Day-109b's ``is_nbfc_insurance_excluded`` continues to return
#     True for life insurers — this cohort is dual-handled (insurance
#     has its own router; the NBFC exclusion just keeps insurers out of
#     the NBFC P/B math). Documented in tests.
#
# Override knobs (P/EV ≈ P/B × 4-5 ratio for life; P/B + CR for GI):
#
#   Life insurance Tier-1 private (HDFCLIFE / SBILIFE / ICICIPRULI /
#       MAXFIN): anchor 2.5× EV, band [2.0, 3.5]. When EV is not
#       loaded, fall back to P/B ~4.5× book (rough EV ≈ 2× book × P/EV
#       2.5 = 5× book; use 4.5× to be slightly conservative).
#   Life insurance PSU (LICI): anchor 1.0× EV, band [0.8, 1.5]. P/B
#       fallback 1.5×. PSU governance + slower VNB growth discount.
#   General insurance Tier-1 private (ICICIGI): anchor 6.5× book when
#       combined_ratio < 100% (underwriting profit), 6.0× when CR ≥
#       100% or unknown. Band [4.5, 7.5]. Calibrated against the real
#       2026-05 private_gi peer-median 5.9× (ICICIGI 5.68 / GODIGIT
#       6.13) so the cohort layer is consistent with consensus-pinned
#       ICICIGI FV ~₹2,020. Note: GODIGIT stays in the private_gi
#       peer bucket and is NOT in this cohort to avoid double-counting.
#   General insurance PSU (NIACL): anchor 1.05× book regardless of CR
#       (matches psu_gi peer-median; PSU discount on GI underwriting
#       franchises). Band [0.8, 1.5].
#
# Data gaps (2026-05-23 — Phase 2 follow-ups):
#   - embedded_value is NOT in yfinance / ratio_history parquet; only
#     in annual EV reports (the existing insurance_appraisal_inputs
#     admin form is the canonical ingestion path).
#   - combined_ratio is NOT consistently present in ratio_history.
#   - Both gaps surface via insurance_data_gaps() so the caller can
#     stamp ``data_limited`` and add an audit note. The cohort still
#     ships a static anchor (P/B-based) so the FV is more accurate
#     than the unsegmented peer-median fallback.
#
# Wiring:
#   - Layered into ``_compute_pbv_path`` in financial_valuation_
#     service.py AFTER the NBFC anchor block and BEFORE the
#     ``TOP_PRIVATE_BANK_PB_BUMP``. Insurance is in a separate peer
#     group from banks, so the top-private-bank bump never fires on
#     it; layering order is for code locality, not interaction.
# ═══════════════════════════════════════════════════════════════════

# ── Life insurance — Tier-1 private ──────────────────────────────
# Top private life insurers with strong VNB growth + retail+banca
# distribution moats. Anchor 2.5× EV / 4.5× P/B fallback.
# MAXFIN included per Day-110b scope; treated as Tier-1 private for
# anchor purposes although smaller scale than HDFCLIFE/SBILIFE.
_INSURANCE_LIFE_TIER1_PRIVATE: Final[frozenset[str]] = frozenset({
    "HDFCLIFE",
    "SBILIFE",
    "ICICIPRULI",
    "MAXFIN",
})

# ── Life insurance — PSU ─────────────────────────────────────────
# LICI: state-owned, ~60% market share, lower VNB margin (~16% vs
# ~26% for private peers), governance + slower-product-mix discount.
_INSURANCE_LIFE_PSU: Final[frozenset[str]] = frozenset({
    "LICI",
})

# ── General insurance — Tier-1 private ───────────────────────────
# ICICIGI is the clear Tier-1 private GI listing. GODIGIT is
# deliberately NOT included — its digital-GI multiple sits in the
# existing private_gi peer-bucket (5.5x fallback) which is already
# anchored correctly; double-applying Day-110b would over-anchor.
_INSURANCE_GI_TIER1_PRIVATE: Final[frozenset[str]] = frozenset({
    "ICICIGI",
})

# ── General insurance — PSU ──────────────────────────────────────
# NIACL: New India Assurance, PSU general insurer. Governance + GI-
# cycle drag → 1.5× book regardless of combined ratio.
_INSURANCE_GI_PSU: Final[frozenset[str]] = frozenset({
    "NIACL",
})

# ── Union (all insurance cohort members) ─────────────────────────
_INSURANCE_COHORT_TICKERS_INLINE: Final[frozenset[str]] = (
    _INSURANCE_LIFE_TIER1_PRIVATE
    | _INSURANCE_LIFE_PSU
    | _INSURANCE_GI_TIER1_PRIVATE
    | _INSURANCE_GI_PSU
)

# ── Public override constants ────────────────────────────────────
# Life insurance — P/EV anchors (used when embedded_value column is
# available — currently Phase 2 since EV is not in yfinance).
INSURANCE_LIFE_TIER1_PEV_ANCHOR: Final[float] = 2.5
INSURANCE_LIFE_TIER1_PEV_BAND: Final[tuple[float, float]] = (2.0, 3.5)
INSURANCE_LIFE_PSU_PEV_ANCHOR: Final[float] = 1.0
INSURANCE_LIFE_PSU_PEV_BAND: Final[tuple[float, float]] = (0.8, 1.5)

# Life insurance — P/B fallback anchors (used in current path, since
# EV ingestion has not landed). Calibrated so that
#   fair_pb_fallback ≈ pev_anchor × (book / EV ratio)
# where book/EV ≈ 1.8 for Tier-1 private (HDFCLIFE 2.5 × 1.8 = 4.5)
# and ~1.5 for LICI (1.0 × 1.5 = 1.5).
INSURANCE_LIFE_TIER1_PB_FALLBACK_ANCHOR: Final[float] = 4.5
INSURANCE_LIFE_TIER1_PB_FALLBACK_BAND: Final[tuple[float, float]] = (3.0, 6.0)
INSURANCE_LIFE_PSU_PB_FALLBACK_ANCHOR: Final[float] = 1.5
INSURANCE_LIFE_PSU_PB_FALLBACK_BAND: Final[tuple[float, float]] = (1.0, 2.5)

# General insurance — P/B with combined-ratio overlay.
# Calibrated against real market multiples (ICICIGI 5.68×, NIACL 0.94×
# as of 2026-05-17 market_metrics) and the consensus-pinned tests in
# test_financial_valuation.py (ICICIGI FV ~₹2,020, NIACL FV ~₹170).
# Tier-1 private anchors land near the existing private_gi peer-median
# (5.9×) so the cohort layer is consistent with the bucket median; the
# CR overlay nudges +/- around it. PSU anchor (1.05×) matches the
# psu_gi peer-median (1.05×); the cohort gives an explicit named
# constant for that anchor and a tight band to surface in _meta.
INSURANCE_GI_TIER1_PB_ANCHOR_UW_PROFIT: Final[float] = 6.5   # CR < 100%
INSURANCE_GI_TIER1_PB_ANCHOR_UW_LOSS: Final[float] = 6.0     # CR ≥ 100% / unknown
INSURANCE_GI_TIER1_PB_BAND: Final[tuple[float, float]] = (4.5, 7.5)
INSURANCE_GI_PSU_PB_ANCHOR: Final[float] = 1.05
INSURANCE_GI_PSU_PB_BAND: Final[tuple[float, float]] = (0.8, 1.5)

# Combined-ratio threshold: below this is underwriting profit.
INSURANCE_GI_COMBINED_RATIO_PROFIT_THRESHOLD: Final[float] = 1.00


def is_insurance_cohort_ticker(ticker: str | None) -> bool:
    """True if the ticker is in the Day-110b insurance cohort (any
    sub-segment). HDFCLIFE / SBILIFE / ICICIPRULI / LICI / MAXFIN /
    ICICIGI / NIACL.

    Note: ``is_nbfc_insurance_excluded`` from Day-109b returns True
    for the four life insurers listed there (HDFCLIFE / SBILIFE /
    ICICIPRULI / LICI / CANHLIFE). Day-110b is the POSITIVE cohort;
    the Day-109b exclusion stays in place to keep insurers out of NBFC
    P/B math. Both helpers can return True simultaneously for the
    same ticker — that's intentional dual-handling, not a bug."""
    return _bare(ticker) in _INSURANCE_COHORT_TICKERS_INLINE


def insurance_subsegment(ticker: str | None) -> str | None:
    """Return the insurance sub-segment key, or ``None`` if not in
    cohort.

    Keys (stable, surfaced in ``_meta`` for canary diff + admin debug):
      ``life_tier1_private`` | ``life_psu`` |
      ``gi_tier1_private`` | ``gi_psu``
    """
    bare = _bare(ticker)
    if bare in _INSURANCE_LIFE_TIER1_PRIVATE:
        return "life_tier1_private"
    if bare in _INSURANCE_LIFE_PSU:
        return "life_psu"
    if bare in _INSURANCE_GI_TIER1_PRIVATE:
        return "gi_tier1_private"
    if bare in _INSURANCE_GI_PSU:
        return "gi_psu"
    return None


def insurance_anchor_multiple(
    ticker: str | None,
    embedded_value_per_share: float | None = None,
    combined_ratio: float | None = None,
) -> float | None:
    """Return the fair-multiple anchor for the cohort sub-segment.

    For LIFE insurers:
      - If ``embedded_value_per_share`` is provided (>0), the anchor
        is interpreted as a P/EV multiple (Tier-1 2.5×, PSU 1.0×).
        Caller multiplies anchor × EV-per-share for FV.
      - If EV is None (current default path — EV not in parquet),
        the anchor is a P/B fallback (Tier-1 4.5×, PSU 1.5×). Caller
        multiplies anchor × BVPS for FV.

    For GENERAL insurers:
      - Tier-1 private: 4.0× book when CR < 100% (underwriting
        profit), 2.5× when CR ≥ 100% or unknown.
      - PSU: 1.5× book regardless of CR (governance discount).

    Returns ``None`` for non-cohort tickers."""
    seg = insurance_subsegment(ticker)
    if seg is None:
        return None
    if seg == "life_tier1_private":
        if embedded_value_per_share is not None and embedded_value_per_share > 0:
            return INSURANCE_LIFE_TIER1_PEV_ANCHOR
        return INSURANCE_LIFE_TIER1_PB_FALLBACK_ANCHOR
    if seg == "life_psu":
        if embedded_value_per_share is not None and embedded_value_per_share > 0:
            return INSURANCE_LIFE_PSU_PEV_ANCHOR
        return INSURANCE_LIFE_PSU_PB_FALLBACK_ANCHOR
    if seg == "gi_tier1_private":
        if combined_ratio is not None:
            try:
                cr = float(combined_ratio)
                # Auto-detect percent vs decimal (>3 → percent).
                if cr > 3.0:
                    cr = cr / 100.0
                if cr < INSURANCE_GI_COMBINED_RATIO_PROFIT_THRESHOLD:
                    return INSURANCE_GI_TIER1_PB_ANCHOR_UW_PROFIT
            except (TypeError, ValueError):
                pass
        return INSURANCE_GI_TIER1_PB_ANCHOR_UW_LOSS
    if seg == "gi_psu":
        return INSURANCE_GI_PSU_PB_ANCHOR
    return None


def insurance_anchor_band(
    ticker: str | None,
    embedded_value_per_share: float | None = None,
) -> tuple[float, float] | None:
    """Return the (low, high) clamp band for the cohort sub-segment.
    Mirrors ``insurance_anchor_multiple``: P/EV band when EV is
    supplied for life, P/B band otherwise. Returns ``None`` for
    non-cohort tickers."""
    seg = insurance_subsegment(ticker)
    if seg is None:
        return None
    if seg == "life_tier1_private":
        if embedded_value_per_share is not None and embedded_value_per_share > 0:
            return INSURANCE_LIFE_TIER1_PEV_BAND
        return INSURANCE_LIFE_TIER1_PB_FALLBACK_BAND
    if seg == "life_psu":
        if embedded_value_per_share is not None and embedded_value_per_share > 0:
            return INSURANCE_LIFE_PSU_PEV_BAND
        return INSURANCE_LIFE_PSU_PB_FALLBACK_BAND
    if seg == "gi_tier1_private":
        return INSURANCE_GI_TIER1_PB_BAND
    if seg == "gi_psu":
        return INSURANCE_GI_PSU_PB_BAND
    return None


def insurance_data_gaps(
    ticker: str | None,
    embedded_value_per_share: float | None = None,
    combined_ratio: float | None = None,
    bvps: float | None = None,
) -> dict:
    """Return a dict describing which Day-110b inputs are missing for
    transparency / data_issues surfacing.

    Keys (all bool):
      ``ev_missing``        — life insurers need EV for the P/EV path.
                              True when seg is life-* and EV is None
                              or non-positive.
      ``combined_ratio_missing`` — GI tier-1 needs CR to pick the
                              underwriting-profit-vs-loss anchor. True
                              when seg is gi_tier1_private and CR is
                              None. (gi_psu does not need CR — always
                              1.5× book.)
      ``bvps_missing``      — every fallback path needs BVPS. True
                              when bvps is None or non-positive.
      ``data_limited``      — convenience aggregate: True when any
                              critical input is missing such that the
                              cohort can only ship a STATIC anchor (no
                              EV, no CR overlay). For life: True iff
                              ev_missing. For gi_tier1_private: True
                              iff combined_ratio_missing. For gi_psu /
                              non-cohort: always False (the static
                              anchor IS the published model).

    Non-cohort tickers return an empty dict (caller treats absence as
    "no gaps to report")."""
    seg = insurance_subsegment(ticker)
    if seg is None:
        return {}
    ev_missing = False
    cr_missing = False
    if seg in ("life_tier1_private", "life_psu"):
        ev_missing = not (
            embedded_value_per_share is not None
            and embedded_value_per_share > 0
        )
    if seg == "gi_tier1_private":
        cr_missing = combined_ratio is None
    bvps_missing = not (bvps is not None and bvps > 0)
    if seg.startswith("life_"):
        data_limited = ev_missing
    elif seg == "gi_tier1_private":
        data_limited = cr_missing
    else:  # gi_psu
        data_limited = False
    return {
        "sub_segment": seg,
        "ev_missing": ev_missing,
        "combined_ratio_missing": cr_missing,
        "bvps_missing": bvps_missing,
        "data_limited": data_limited,
    }


# Re-export inline sets for source-text tests + downstream callers.
REIT_INVIT_COHORT_TICKERS_INLINE = _REIT_INVIT_COHORT_TICKERS_INLINE
REIT_OFFICE = _REIT_OFFICE
REIT_RETAIL = _REIT_RETAIL
INVIT_ROADS = _INVIT_ROADS
INVIT_TRANSMISSION = _INVIT_TRANSMISSION
INVIT_OTHER = _INVIT_OTHER
INVIT_TICKERS_INLINE = _INVIT_TICKERS_INLINE
INSURANCE_COHORT_TICKERS_INLINE = _INSURANCE_COHORT_TICKERS_INLINE
INSURANCE_LIFE_TIER1_PRIVATE = _INSURANCE_LIFE_TIER1_PRIVATE
INSURANCE_LIFE_PSU = _INSURANCE_LIFE_PSU
INSURANCE_GI_TIER1_PRIVATE = _INSURANCE_GI_TIER1_PRIVATE
INSURANCE_GI_PSU = _INSURANCE_GI_PSU


# ═══════════════════════════════════════════════════════════════════
# T1.3 (2026-06-09) — Per-sector calibrated WACC + Terminal Growth
# ═══════════════════════════════════════════════════════════════════
# Engine refinement roadmap T1.3. Damodaran India 2026 anchored.
# Closes the audit gaps:
#
#   - Issue #229 (FMCG TG uniformity): vanilla DCF used the country
#     default ~4% for every FMCG name, regardless of whether the
#     business was a staples franchise (HUL/NESTLE; AlphaSpread 5-7%)
#     or a tobacco mono-line (ITC; AlphaSpread ~3%). The Day-107b
#     cohort already lifts the four sub-tiers (top/itc/tier2/tier3)
#     but only for the 11 cohort tickers. Names outside the cohort
#     still default. This table covers the broader sector universe.
#
#   - Issue #260 (cyclical cluster — AMBUJACEM/JSWSTEEL/IOC/BPCL/
#     CIPLA): DCF over-extrapolated trough or peak cash flows because
#     the terminal growth was set to a benign 4% even for commodity-
#     linked sectors that structurally won't grow above the 2.5-3.0%
#     band at a 10-year horizon. The table prices that in.
#
# ═══════════════════════════════════════════════════════════════════
# Scope (Phase A — tables + helpers; wiring is a follow-up)
# ═══════════════════════════════════════════════════════════════════
# This module ships the CALIBRATED VALUES as importable constants
# and a thin helper API. It deliberately does NOT modify service.py /
# models/forecaster.py / models/dcf.py read paths. Wiring is deferred
# to a follow-up PR so the engine impact can be measured against the
# canary-diff harness as a single change (and so the table values can
# be cited from documentation pages, /calibration, audit notes, and
# AI summary prompts in the interim without touching FV).
#
# Existing inline TG-lift / WACC-floor blocks in service.py and
# forecaster.py (Day-84 pharma franchise, Day-92 utility, Day-107a
# IT services, Day-107b FMCG, Day-107c auto, etc.) remain the
# authoritative production gates today; the values in those blocks
# are consistent with the table below (verified in
# test_sector_wacc_tg_calibrated.py — see
# ``test_calibrated_values_match_existing_cohort_constants``).
#
# ═══════════════════════════════════════════════════════════════════
# Source — Damodaran India dataset (2026) + AlphaSpread cross-checks
# ═══════════════════════════════════════════════════════════════════
# WACC anchors (Indian equity risk premium ~7.5%, risk-free ~7.1%,
# beta-weighted by sector):
#
#   IT Services             11.5%      Banking                 11.8%
#   NBFC                    12.5%      Insurance               11.2%
#   FMCG                    10.5%      Pharma                  12.0%
#   Auto OEMs               13.5%      Auto Components         13.0%
#   Cement                  13.5%      Metals & Mining         14.5%
#   Oil & Gas               12.5%      Power & Utilities        9.5%
#   Telecom                 11.0%      Capital Goods           13.0%
#   Real Estate / REITs      9.8%      Consumer Discretionary  12.0%
#   Hotels & Tourism        14.0%      Aviation                16.0%
#   Construction / Infra    13.0%      Media                   14.5%
#   Retail                  12.5%      Chemicals               12.5%
#   Defense PSU             10.5%
#
# Terminal-growth anchors (India long-run nominal GDP ~9-10%; mature
# sector ceilings well below):
#
#   IT Services              5.0%      Banking                  5.5%
#   NBFC                     5.5%      Insurance                6.0%
#   FMCG (staples)           5.5%      FMCG (tobacco)           3.0%
#   Pharma (chronic)         5.5%      Pharma (generic US)      4.0%
#   Auto OEMs                4.5%      Cement                   4.0%
#   Metals & Mining          3.0%      Oil & Gas                2.5%
#   Power (regulated)        4.5%      Power (renewable)        6.0%
#   Telecom                  4.0%      Capital Goods            4.5%
#   REITs                    4.5%      Hotels & Tourism         5.0%
#   Defense PSU              5.5%
#
# Sub-sector keys are the second-resolution lookup: when a sector
# alone is too coarse (FMCG → staples vs tobacco; Pharma → chronic
# vs generic US; Power → regulated vs renewable) the caller passes
# the sub_sector and the helper returns the more specific value.
#
# Sector strings match the canonical labels produced by
# ``backend/services/analysis/utils._resolve_sector`` (which maps
# raw yfinance labels through ``SECTOR_OVERRIDES`` /
# ``TICKER_SECTOR_OVERRIDES`` in constants.py).
# ═══════════════════════════════════════════════════════════════════

# ── Calibrated WACC by sector (decimal: 0.115 = 11.5%) ───────────
SECTOR_WACC_CALIBRATED: Final[dict[str, float]] = {
    "IT": 0.115,
    "Information Technology": 0.115,
    "Banking": 0.118,
    "NBFC": 0.125,
    "Insurance": 0.112,
    "FMCG": 0.105,
    "Pharma": 0.120,
    "Automobiles": 0.135,
    "Auto Components": 0.130,
    "Cement": 0.135,
    "Metals & Mining": 0.145,
    "Oil & Gas": 0.125,
    "Power & Utilities": 0.095,
    "Telecom": 0.110,
    "Capital Goods": 0.130,
    "Real Estate": 0.098,
    "Consumer Discretionary": 0.120,
    "Hotels & Tourism": 0.140,
    "Aviation": 0.160,
    "Construction": 0.130,
    "Engineering": 0.130,
    "Media": 0.145,
    "Retail": 0.125,
    "Chemicals": 0.125,
    "Defense": 0.105,
    "Financial Services": 0.118,   # fallback when bank/NBFC/insurance is unknown
}

# ── Calibrated Terminal Growth by sector (decimal: 0.050 = 5.0%) ──
SECTOR_TERMINAL_GROWTH_CALIBRATED: Final[dict[str, float]] = {
    "IT": 0.050,
    "Information Technology": 0.050,
    "Banking": 0.055,
    "NBFC": 0.055,
    "Insurance": 0.060,
    "FMCG": 0.055,           # default to staples; tobacco sub_sector overrides
    "Pharma": 0.055,         # default to chronic+branded; generic-US sub_sector overrides
    "Automobiles": 0.045,
    "Auto Components": 0.040,
    "Cement": 0.040,
    "Metals & Mining": 0.030,
    "Oil & Gas": 0.025,
    "Power & Utilities": 0.045,   # default regulated; renewable sub_sector overrides
    "Telecom": 0.040,
    "Capital Goods": 0.045,
    "Real Estate": 0.045,
    "Consumer Discretionary": 0.050,
    "Hotels & Tourism": 0.050,
    "Aviation": 0.035,
    "Construction": 0.045,
    "Engineering": 0.045,
    "Media": 0.035,
    "Retail": 0.050,
    "Chemicals": 0.045,
    "Defense": 0.055,
    "Financial Services": 0.055,
}

# ── Sub-sector overrides (key = "sector::sub_sector", lower-cased) ──
# These trump the sector-only lookup when the caller provides a
# sub_sector that maps to a structurally different long-run growth
# / risk profile (e.g. tobacco regulatory headwind, generic-US price
# erosion, renewable-power demand tailwind).
SECTOR_WACC_CALIBRATED_BY_SUB: Final[dict[str, float]] = {
    "fmcg::staples": 0.105,
    "fmcg::tobacco": 0.105,
    "pharma::chronic": 0.120,
    "pharma::branded_generics": 0.120,
    "pharma::generic_us": 0.130,   # higher beta on US-genx price-erosion exposure
    "power & utilities::regulated": 0.095,
    "power & utilities::renewable": 0.105,
    "automobiles::2w": 0.130,
    "automobiles::4w": 0.135,
    "automobiles::cv": 0.140,
}

SECTOR_TERMINAL_GROWTH_CALIBRATED_BY_SUB: Final[dict[str, float]] = {
    "fmcg::staples": 0.055,
    "fmcg::tobacco": 0.030,   # cigarette regulatory headwind
    "pharma::chronic": 0.055,
    "pharma::branded_generics": 0.055,
    "pharma::generic_us": 0.040,
    "power & utilities::regulated": 0.045,
    "power & utilities::renewable": 0.060,
    "automobiles::2w": 0.050,
    "automobiles::4w": 0.045,
    "automobiles::cv": 0.040,
}


def _canon_sector(sector: str | None) -> str:
    """Trim + treat as canonical. Returns '' for None / empty."""
    if not sector:
        return ""
    return str(sector).strip()


def _sub_key(sector: str | None, sub_sector: str | None) -> str:
    """Compose the lookup key for the sub-sector dict (lower-cased)."""
    if not sector or not sub_sector:
        return ""
    return f"{str(sector).strip().lower()}::{str(sub_sector).strip().lower()}"


def get_calibrated_wacc(
    sector: str | None,
    sub_sector: str | None = None,
) -> float | None:
    """Return the T1.3 calibrated WACC for a sector, or ``None`` if
    no calibration exists.

    Lookup order:
      1. If ``sub_sector`` is provided, try the
         ``SECTOR_WACC_CALIBRATED_BY_SUB`` map first
         (key = ``f"{sector}::{sub_sector}"``, lower-cased). This lets
         the caller distinguish FMCG-tobacco (10.5%) from FMCG-staples
         (10.5% — same WACC, different TG), or Pharma-generic-US
         (13.0% — higher beta on US price erosion) from Pharma-chronic
         (12.0%).
      2. Otherwise, ``SECTOR_WACC_CALIBRATED[sector]`` exact match
         on the canonical sector label.
      3. Otherwise, ``None`` (caller falls back to CAPM / country
         default).

    Returns a decimal (0.115 = 11.5%) ready to consume by the DCF
    engine. Caller is responsible for the ``wacc > terminal_g + 2%``
    safety guard.
    """
    if sub_sector:
        v = SECTOR_WACC_CALIBRATED_BY_SUB.get(_sub_key(sector, sub_sector))
        if v is not None:
            return float(v)
    canon = _canon_sector(sector)
    if not canon:
        return None
    v = SECTOR_WACC_CALIBRATED.get(canon)
    if v is None:
        return None
    return float(v)


def get_calibrated_terminal_growth(
    sector: str | None,
    sub_sector: str | None = None,
) -> float | None:
    """Return the T1.3 calibrated terminal growth for a sector, or
    ``None`` if no calibration exists.

    Same lookup order as ``get_calibrated_wacc``:
      1. Sub-sector key first (e.g. ``fmcg::tobacco`` → 3.0%).
      2. Sector key (e.g. ``FMCG`` → 5.5% staples default).
      3. ``None``.

    Returns a decimal (0.055 = 5.5%) ready to consume by the DCF
    engine. Caller is responsible for the ``terminal_g < wacc - 2%``
    safety guard.
    """
    if sub_sector:
        v = SECTOR_TERMINAL_GROWTH_CALIBRATED_BY_SUB.get(
            _sub_key(sector, sub_sector),
        )
        if v is not None:
            return float(v)
    canon = _canon_sector(sector)
    if not canon:
        return None
    v = SECTOR_TERMINAL_GROWTH_CALIBRATED.get(canon)
    if v is None:
        return None
    return float(v)
