# backend/services/it_services_overlay_service.py
"""
IT Services Overlay — T3.6 Phase A.

Generic DCF treats every Indian IT services company as equally robust:
TCS, INFY, WIPRO, MPHASIS, ECLERX all flow through the same WACC /
TG / scenario weight machinery (modulo the Day-107a cohort tightening,
which only adjusts WACC and TG ranges, not concentration risk).

But IT services have business-model risks generic DCF does not see:

  1. **Client concentration.** Top-5 client mix matters a lot. TCS sits
     at ~12%; INFY ~16%; the mid-tier names sit at 30-40%; ECLERX-style
     specialists run as high as 60%. The first 30% of revenue is
     "diversified"; past that, losing a single client is a material P&L
     event that no DCF growth-rate captures.

  2. **Vertical + geo concentration.** BFSI exposure is recession-
     sensitive (2008 hammered every IT services firm with high BFSI mix
     for 2-3 years). USD revenue share is high-margin but FX-exposed.
     The double-exposure (BFSI > 40% AND USD > 60%) creates a
     correlated tail risk — the kind of regional banking stress that
     hits BFSI also tends to hit USD via flight-to-safety.

  3. **SBC intensity by tier.** Tier-1 historical SBC sits ~1.5% of
     FCF; tier-2 ~3%; new-economy / digital specialists 5%+. T4.1 (PR
     #812) shipped the SBC dilution math; this overlay adds the tier-
     aware discount when SBC materially exceeds the tier norm.

  4. **Growth quality.** Revenue growth that comes purely from
     headcount growth is low-quality (linear scaling, no operating
     leverage). Revenue growth materially above headcount growth
     indicates productivity gains (automation, AI, offshore mix
     shift) — a premium-worthy quality signal. Margin compression
     reverses the signal.

The overlay returns a single multiplier applied to the base DCF FV
(``adjusted_fv = base_dcf_fv * concentration * sbc * growth_quality``),
bounded so a single overlay can never move FV more than the brief's
calibration intends (concentration ∈ [0.85, 1.05]; SBC ∈ [0.92, 1.0];
growth quality ∈ [0.95, 1.05]). Compound floor ≈ 0.74×; compound
ceiling ≈ 1.16×.

Phase A is standalone — no wiring into AnalysisResponse or the
composite engine. Phase B (separate PR) will route IT_TICKERS through
``compute_it_overlay`` and surface the multiplier alongside the base
DCF on the analysis page.

Defensive: every entry point catches bad inputs (None, NaN,
out-of-band percentages) and returns the base FV with a sanity warning
rather than raising. The function is safe to call from the engine hot
path.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger("yieldiq.it_services_overlay")

ITTier = Literal["tier_1", "tier_2", "specialist"]


# ─────────────────────────────────────────────────────────────────
# Universe — Indian IT services tickers we apply the overlay to.
#
# Tier-1: large-cap, diversified, top-5 client mix typically <20%.
# Tier-2: mid-cap, top-5 mix 20-40%, narrower vertical exposure.
# Specialist: niche / vertical-specific, top-5 can exceed 50%.
#
# Sourced from NSE IT index constituents + the spec brief. Keep in
# sync with the cache_invalidation_manifest entry's scope.tickers.
# ─────────────────────────────────────────────────────────────────
IT_TICKERS: dict[str, ITTier] = {
    "TCS": "tier_1",
    "INFY": "tier_1",
    "HCLTECH": "tier_1",
    "WIPRO": "tier_1",
    "TECHM": "tier_1",
    "LTIM": "tier_1",
    "PERSISTENT": "tier_2",
    "COFORGE": "tier_2",
    "MPHASIS": "tier_2",
    "CYIENT": "tier_2",
    "BIRLASOFT": "tier_2",
    "ECLERX": "specialist",
    "HAPPSTMNDS": "specialist",
    "AFFLE": "specialist",
    "TANLA": "specialist",
}


# ─────────────────────────────────────────────────────────────────
# Per-tier SBC norms (% of FCF). Discount fires when actual SBC
# exceeds tier-norm by more than +2pp. Calibration: tier-1 historical
# (TCS / INFY / HCLTECH 10-year median) sits at ~1.5%; tier-2
# (PERSISTENT / COFORGE) ~3%; specialist (HAPPSTMNDS / AFFLE) 5%+.
# ─────────────────────────────────────────────────────────────────
_TIER_SBC_NORM_PCT: dict[ITTier, float] = {
    "tier_1": 1.5,
    "tier_2": 3.0,
    "specialist": 5.0,
}

# Discount knobs — keep in lockstep with the docstring bounds.
_CONCENTRATION_FLOOR = 0.85
_CONCENTRATION_CEIL = 1.05
_SBC_FLOOR = 0.92
_SBC_CEIL = 1.00
_GROWTH_FLOOR = 0.95
_GROWTH_CEIL = 1.05


@dataclass
class ITServicesOverlayInputs:
    """Inputs for a single IT-overlay calculation.

    All percentages are in 0-100 (not 0-1). ``base_dcf_fv`` is the
    engine's standard DCF fair value in INR per share — this overlay
    is multiplicative, not additive, so the unit of the input flows
    through to ``adjusted_fv``.
    """
    base_dcf_fv: float
    top_5_client_concentration_pct: float
    bfsi_revenue_share_pct: float = 35.0
    usd_revenue_share_pct: float = 55.0
    europe_revenue_share_pct: float = 25.0
    sbc_pct_of_fcf: float = 2.0
    headcount_growth_pct: float = 5.0
    revenue_growth_3y_cagr_pct: float = 10.0
    operating_margin_pct: float = 22.0
    tier: ITTier = "tier_1"


@dataclass
class ITServicesOverlayResult:
    """Result of an IT-overlay calculation.

    - ``base_dcf_fv``: echoed from the input so callers don't have to
      thread the original value through.
    - ``adjusted_fv``: ``base_dcf_fv * concentration * sbc * growth``;
      ``None`` when the inputs were unrecoverably bad.
    - ``adjustments``: per-driver multipliers for transparency on the
      analysis page ("why is this overlay -7%?").
    - ``risk_summary``: coarse bucket — ``"moderate"`` when the
      compound multiplier is within ±3%, ``"elevated"`` when within
      ±10%, ``"high"`` otherwise.
    - ``sanity_warnings``: caller-facing notes about bad inputs the
      overlay had to neutralize (e.g. negative concentration %).
    """
    base_dcf_fv: float
    adjusted_fv: Optional[float]
    adjustments: dict
    risk_summary: str
    sanity_warnings: list[str] = field(default_factory=list)
    method: str = "it_services_overlay_phase_a"


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────
def _is_finite_number(x) -> bool:
    """True iff x is an int/float that's finite (not NaN, not inf)."""
    if x is None:
        return False
    if isinstance(x, bool):  # bool is subclass of int — exclude
        return False
    if not isinstance(x, (int, float)):
        return False
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


# ─────────────────────────────────────────────────────────────────
# Per-driver discount/premium calculators
# ─────────────────────────────────────────────────────────────────
def compute_concentration_discount(
    top_5_pct: float,
    bfsi_pct: float,
    usd_pct: float,
) -> float:
    """Concentration risk multiplier in [0.85, 1.05].

    Rules (additive in pp space, then clamped):
      - top_5 > 30% : -5%   (loss-of-major-client risk)
      - top_5 > 50% : -10%  (existential — replaces the -5%)
      - bfsi > 40% AND usd > 60% : -3%  (recession + FX correlation)
      - top_5 < 20% AND bfsi < 35% : +2%  (tier-1 diversified premium)

    Defensive: any non-finite input is treated as the neutral midpoint
    (top_5=25, bfsi=35, usd=55) so a single missing field never sinks
    the whole overlay.
    """
    if not _is_finite_number(top_5_pct):
        top_5_pct = 25.0
    if not _is_finite_number(bfsi_pct):
        bfsi_pct = 35.0
    if not _is_finite_number(usd_pct):
        usd_pct = 55.0

    # Clamp inputs to [0, 100] — a "120% top-5 concentration" is a
    # data error, not a real signal.
    top_5_pct = _clamp(float(top_5_pct), 0.0, 100.0)
    bfsi_pct = _clamp(float(bfsi_pct), 0.0, 100.0)
    usd_pct = _clamp(float(usd_pct), 0.0, 100.0)

    multiplier = 1.0

    # Client concentration — pick the heavier discount (50% supersedes
    # 30% — don't stack).
    if top_5_pct > 50.0:
        multiplier *= 0.90
    elif top_5_pct > 30.0:
        multiplier *= 0.95

    # BFSI + USD double-exposure — independent of the client concentration
    # adjustment, fires on the geo/vertical correlation tail.
    if bfsi_pct > 40.0 and usd_pct > 60.0:
        multiplier *= 0.97

    # Tier-1 diversified premium — only fires when concentration is
    # genuinely low on BOTH axes.
    if top_5_pct < 20.0 and bfsi_pct < 35.0:
        multiplier *= 1.02

    return _clamp(multiplier, _CONCENTRATION_FLOOR, _CONCENTRATION_CEIL)


def compute_sbc_overlay_discount(
    sbc_pct_of_fcf: float,
    tier: ITTier,
) -> float:
    """SBC overlay multiplier in [0.92, 1.0].

    Discount fires when SBC exceeds the tier norm by more than +2pp.
    Penalty: -1.5% per excess pp, capped at the floor.

    Tier-1 norm = 1.5%, tier-2 = 3.0%, specialist = 5.0%. So:
      - tier-1 with SBC=4% → excess = 0.5pp (below +2pp gate) → 1.0
      - tier-1 with SBC=6% → excess = 2.5pp (+0.5pp over gate) → -0.75%
      - tier-1 with SBC=10% → excess = 6.5pp (+4.5pp over gate) → -6.75%
      - tier-2 with SBC=10% → excess = 5pp (+3pp over gate) → -4.5%

    Defensive: non-finite SBC or unknown tier → neutral 1.0.
    """
    if not _is_finite_number(sbc_pct_of_fcf):
        return 1.0
    if tier not in _TIER_SBC_NORM_PCT:
        return 1.0

    sbc_pct = max(0.0, float(sbc_pct_of_fcf))
    norm = _TIER_SBC_NORM_PCT[tier]
    excess_pp = sbc_pct - norm - 2.0  # +2pp gate
    if excess_pp <= 0.0:
        return 1.0

    multiplier = 1.0 - 0.015 * excess_pp  # 1.5% per excess pp
    return _clamp(multiplier, _SBC_FLOOR, _SBC_CEIL)


def compute_growth_quality_premium(
    revenue_growth_pct: float,
    margin_pct: float,
    headcount_growth_pct: float,
) -> float:
    """Growth-quality multiplier in [0.95, 1.05].

    Rules:
      - rev_growth − headcount_growth >= 5pp : +3% (productivity gain)
      - rev_growth − headcount_growth >= 10pp : +5% (strong leverage)
      - margin < 18% : -3% (compression)
      - margin < 15% : -5% (severe compression)
      - rev_growth < 0 : -5% (genuine decline overrides everything else)

    Margin compression and headcount-leverage are independent signals
    and stack within the [0.95, 1.05] band.
    """
    if not _is_finite_number(revenue_growth_pct):
        revenue_growth_pct = 10.0
    if not _is_finite_number(margin_pct):
        margin_pct = 22.0
    if not _is_finite_number(headcount_growth_pct):
        headcount_growth_pct = 5.0

    rev = float(revenue_growth_pct)
    margin = float(margin_pct)
    head = float(headcount_growth_pct)

    # Revenue decline — overrides everything (no premium is appropriate
    # for a shrinking franchise even if margin held up).
    if rev < 0.0:
        return _GROWTH_FLOOR

    multiplier = 1.0

    spread = rev - head
    if spread >= 10.0:
        multiplier *= 1.05
    elif spread >= 5.0:
        multiplier *= 1.03

    if margin < 15.0:
        multiplier *= 0.95
    elif margin < 18.0:
        multiplier *= 0.97

    return _clamp(multiplier, _GROWTH_FLOOR, _GROWTH_CEIL)


# ─────────────────────────────────────────────────────────────────
# Main entry point
# ─────────────────────────────────────────────────────────────────
def compute_it_overlay(
    inputs: ITServicesOverlayInputs,
) -> ITServicesOverlayResult:
    """Compute the IT services overlay.

    Defensive — never raises. On invalid base_dcf_fv (None / NaN / <= 0)
    returns a result with ``adjusted_fv=None`` and a sanity warning,
    so callers can fall back to the base DCF without a try/except.
    """
    warnings: list[str] = []

    if not _is_finite_number(inputs.base_dcf_fv) or inputs.base_dcf_fv <= 0.0:
        warnings.append(
            "base_dcf_fv invalid (None/NaN/non-positive); overlay skipped"
        )
        return ITServicesOverlayResult(
            base_dcf_fv=float(inputs.base_dcf_fv) if _is_finite_number(inputs.base_dcf_fv) else 0.0,
            adjusted_fv=None,
            adjustments={},
            risk_summary="moderate",
            sanity_warnings=warnings,
        )

    tier = inputs.tier if inputs.tier in _TIER_SBC_NORM_PCT else "tier_1"
    if tier != inputs.tier:
        warnings.append(
            f"tier={inputs.tier!r} unknown; defaulted to tier_1"
        )

    # Sanity-flag out-of-band inputs (but proceed — the per-driver
    # functions clamp internally).
    for name, value, lo, hi in (
        ("top_5_client_concentration_pct", inputs.top_5_client_concentration_pct, 0.0, 100.0),
        ("bfsi_revenue_share_pct", inputs.bfsi_revenue_share_pct, 0.0, 100.0),
        ("usd_revenue_share_pct", inputs.usd_revenue_share_pct, 0.0, 100.0),
        ("europe_revenue_share_pct", inputs.europe_revenue_share_pct, 0.0, 100.0),
        ("sbc_pct_of_fcf", inputs.sbc_pct_of_fcf, 0.0, 100.0),
    ):
        if _is_finite_number(value) and not (lo <= float(value) <= hi):
            warnings.append(
                f"{name}={value} outside [{lo},{hi}]; clamped"
            )

    concentration = compute_concentration_discount(
        inputs.top_5_client_concentration_pct,
        inputs.bfsi_revenue_share_pct,
        inputs.usd_revenue_share_pct,
    )
    sbc = compute_sbc_overlay_discount(inputs.sbc_pct_of_fcf, tier)
    growth = compute_growth_quality_premium(
        inputs.revenue_growth_3y_cagr_pct,
        inputs.operating_margin_pct,
        inputs.headcount_growth_pct,
    )

    compound = concentration * sbc * growth
    adjusted_fv = float(inputs.base_dcf_fv) * compound

    # Risk summary buckets — symmetric ±3% / ±10% bands.
    abs_drift = abs(compound - 1.0)
    if abs_drift <= 0.03:
        risk_summary = "moderate"
    elif abs_drift <= 0.10:
        risk_summary = "elevated"
    else:
        risk_summary = "high"

    return ITServicesOverlayResult(
        base_dcf_fv=float(inputs.base_dcf_fv),
        adjusted_fv=adjusted_fv,
        adjustments={
            "concentration_multiplier": concentration,
            "sbc_multiplier": sbc,
            "growth_quality_multiplier": growth,
            "compound_multiplier": compound,
            "tier": tier,
        },
        risk_summary=risk_summary,
        sanity_warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────
# Applicability gate
# ─────────────────────────────────────────────────────────────────
def is_it_overlay_applicable(
    ticker: str,
    sector: Optional[str],
) -> tuple[bool, str]:
    """Return ``(applicable, reason)``.

    True iff the ticker is in ``IT_TICKERS`` OR the sector string
    matches the canonical "Information Technology" label (case-
    insensitive, "IT Services" / "Computers - Software" also accepted
    because the sector taxonomy is not fully normalized upstream).
    """
    if not ticker or not isinstance(ticker, str):
        return False, "ticker is empty or non-string"

    normalized = ticker.upper().replace(".NS", "").replace(".BO", "").strip()
    if normalized in IT_TICKERS:
        return True, f"{normalized} is in IT_TICKERS ({IT_TICKERS[normalized]})"

    if sector and isinstance(sector, str):
        sector_lower = sector.lower().strip()
        it_sector_keywords = (
            "information technology",
            "it services",
            "computers - software",
            "computers-software",
            "it - software",
        )
        for kw in it_sector_keywords:
            if kw in sector_lower:
                return True, f"sector matches {kw!r}"

    return False, f"ticker {normalized!r} not in IT universe; sector={sector!r}"


# ─────────────────────────────────────────────────────────────────
# JSON helper
# ─────────────────────────────────────────────────────────────────
def to_dict(result: ITServicesOverlayResult) -> dict:
    """JSON-safe projection of the result for API surfaces."""
    return {
        "base_dcf_fv": result.base_dcf_fv,
        "adjusted_fv": result.adjusted_fv,
        "adjustments": dict(result.adjustments),
        "risk_summary": result.risk_summary,
        "sanity_warnings": list(result.sanity_warnings),
        "method": result.method,
    }
