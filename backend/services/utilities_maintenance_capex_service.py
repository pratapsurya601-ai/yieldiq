# backend/services/utilities_maintenance_capex_service.py
# ═══════════════════════════════════════════════════════════════
# Utilities maintenance-capex intensity overlay (T3.12 Phase A).
#
# Standalone sibling to ``regulated_utility_valuation_service``.
# Phase B wires the overlay into the analysis route in a separate PR;
# this Phase A ships only the engine math, the applicability gate, and
# a JSON-safe serializer so the wiring PR can mirror the financial /
# regulated-utility / telecom plumbing without touching any caller
# today.
#
# Why this exists:
#   The Munger / Buffett "owner earnings" frame explicitly subtracts
#   maintenance capex (not D&A) from reported earnings. For most
#   capital-light businesses the gap is small. For utilities — power
#   generation, transmission, distribution, gas pipelines — the gap
#   is structural:
#
#     1. Reported FCF = CFO − total capex. That conflates the
#        maintenance leg (the real cost of keeping the existing asset
#        base earning) with growth capex (an investment that produces
#        future regulated revenue). The Munger correction is to
#        compute owner earnings = reported FCF − (maintenance_capex −
#        reported_D&A): if maintenance capex EXCEEDS D&A, owner
#        earnings sit BELOW reported FCF.
#     2. Utilities chronically run maintenance capex > D&A. Asset
#        bases are old, regulators demand reliability, technology
#        upgrades (e.g. smart-meter rollouts in distribution, FGD
#        retrofits in thermal generation) are mandated and recurring.
#        A 1.1-1.2x maintenance-capex-to-D&A ratio is "normal" for
#        an Indian transmission utility; below 0.5x signals deferred
#        maintenance and above 1.5x signals asset stress.
#
#   The existing ``regulated_utility_valuation_service`` correctly
#   refuses to use FCF-DCF for these names (BVPS × fair_pb is the
#   right primary path). This Phase A adds an INDEPENDENT overlay
#   layer that scores maintenance intensity per sub-segment so Phase B
#   can:
#     - surface a "maintenance intensity: heavy" badge on the
#       analysis page next to the rate-base FV
#     - feed an owner-earnings cross-check on top of the rate-base
#       result (does owner earnings × payout policy support the
#       declared dividend?)
#     - dial down confidence on names where intensity_label flags
#       underspending (deferred maintenance is the silent risk)
#
# Sub-segment norms (maintenance_capex / D&A, mid-cycle reads):
#   transmission           ~ 1.1x   (POWERGRID-shaped)
#   generation_thermal     ~ 0.9x   (NTPC-shaped; coal asset base
#                                    matures with high D&A vs
#                                    incremental maintenance)
#   generation_renewable   ~ 0.7x   (NHPC / SJVN — hydro and solar
#                                    have lower physical wear)
#   distribution           ~ 1.2x   (TORNTPOWER / RELINFRA —
#                                    last-mile asset density and
#                                    smart-meter rollouts)
#
# Ticker universe (T3.12 Phase A):
#   POWERGRID, NTPC, NHPC, SJVN, ADANIPOWER, TATAPOWER, TORNTPOWER,
#   JSWENERGY, RELINFRA.
#
# Caller contract (Phase B will wire these):
#   compute_maintenance_adjustment(inputs) -> UtilitiesMaintenanceResult
#   classify_maintenance_intensity(ratio, segment) -> str
#   is_utilities_maint_applicable(ticker, sector) -> tuple[bool, str]
#   to_dict(result) -> dict
#
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger("yieldiq.utilities_maintenance_capex")


# ── Type aliases ────────────────────────────────────────────────
UtilitySegment = Literal[
    "transmission",
    "generation_thermal",
    "generation_renewable",
    "distribution",
]

IntensityLabel = Literal["underspending", "normal", "heavy", "extreme"]


# ── Ticker universe + segment map ───────────────────────────────
#
# Mapped per public profile as of 2026-06. RELINFRA / TATAPOWER /
# TORNTPOWER are distribution-heavy (last-mile + retail tariff
# exposure); ADANIPOWER / JSWENERGY / NTPC are thermal generation;
# NHPC / SJVN are renewable (hydro). POWERGRID is the canonical
# transmission play.
UTILITIES_TICKERS: dict[str, UtilitySegment] = {
    "POWERGRID":  "transmission",
    "NTPC":       "generation_thermal",
    "NHPC":       "generation_renewable",
    "SJVN":       "generation_renewable",
    "ADANIPOWER": "generation_thermal",
    "TATAPOWER":  "generation_thermal",
    "TORNTPOWER": "distribution",
    "JSWENERGY":  "generation_thermal",
    "RELINFRA":   "distribution",
}


# Sub-segment norms (maint_capex / D&A). Calibrated from mid-cycle
# Indian utilities filings; transmission and distribution both run
# above 1.0x because asset replacement cycles compound with mandated
# upgrades. Renewable is the most capital-light at maintenance.
SEGMENT_MAINTENANCE_NORMS: dict[UtilitySegment, float] = {
    "transmission":         1.1,
    "generation_thermal":   0.9,
    "generation_renewable": 0.7,
    "distribution":         1.2,
}


# Default fraction of total capex that is maintenance when the
# operator hasn't supplied an explicit split. Utilities-specific:
# higher than the 0.5 default we'd use for industrials because
# growth-capex cycles for grid operators are episodic (a 5-year CERC
# tariff cycle), while maintenance is continuous.
_DEFAULT_MAINTENANCE_CAPEX_FRACTION = 0.65

# Intensity thresholds (multiplier vs segment norm):
#   underspending: ratio < 0.5 × norm  (deferred maintenance risk)
#   normal:        0.8 × norm ≤ ratio ≤ 1.2 × norm
#   heavy:         1.2 × norm < ratio ≤ 1.5 × norm
#   extreme:       ratio > 1.5 × norm
# Between 0.5 and 0.8 we land in the "low-but-not-yet-deferred" band;
# we classify that as "underspending" too because the right behavior
# from the analysis-page badge is to flag, not to silently accept.
_UNDERSPEND_RATIO = 0.5
_HEAVY_RATIO = 1.2
_EXTREME_RATIO = 1.5


# ── Data classes ────────────────────────────────────────────────
@dataclass
class UtilitiesMaintenanceInputs:
    """All cash-flow inputs in ₹Cr to match Indian utilities filings.

    ``maintenance_capex_fraction`` is the operator-supplied split of
    total capex into maintenance vs growth. Default 0.65 reflects
    utilities being maintenance-heavy. When ``growth_capex_inr_cr`` is
    supplied explicitly (some filings disclose it), the fraction is
    ignored and maintenance capex is derived as
    (total_capex − growth_capex).

    ``rab_per_unit_inr_cr`` is reserved for a future cross-check vs
    the regulated rate base (RAB) declared in CERC tariff orders —
    Phase A does not act on it; the field exists so Phase B can wire
    the cross-check without a schema migration.
    """
    reported_fcf_inr_cr: float
    da_inr_cr: float
    total_capex_inr_cr: float
    maintenance_capex_fraction: float = _DEFAULT_MAINTENANCE_CAPEX_FRACTION
    growth_capex_inr_cr: Optional[float] = None
    asset_base_age_years: Optional[float] = None
    rab_per_unit_inr_cr: float = 0.0
    sub_segment: UtilitySegment = "generation_thermal"


@dataclass
class UtilitiesMaintenanceResult:
    """Snapshot of the maintenance-capex intensity adjustment.

    ``owner_earnings_inr_cr`` follows the Munger / Buffett identity:
        owner_earnings = reported_FCF − (maintenance_capex − D&A)
    i.e. we strip out the part of reported FCF that came from
    UNDER-spending vs D&A, and credit back the part that came from
    OVER-spending vs D&A (a maintenance gap above D&A is a real cost
    that reported FCF already absorbed).

    ``maintenance_intensity_pct`` is maintenance_capex / D&A × 100,
    in pct units — easier for the analysis-page badge ("125% intensity"
    reads better than "1.25 ratio").

    ``intensity_label`` is the bucketed signal Phase B surfaces.
    """
    reported_fcf: float
    maintenance_capex_estimated: float
    owner_earnings_inr_cr: float
    maintenance_intensity_pct: float
    intensity_label: IntensityLabel
    sanity_warnings: list[str] = field(default_factory=list)
    sub_segment: UtilitySegment = "generation_thermal"
    segment_norm_ratio: float = 0.0
    ratio_vs_norm: float = 0.0


# ── Helpers ─────────────────────────────────────────────────────
def _clean_ticker(t: Optional[str]) -> str:
    # Uppercase first so suffix-strip handles ".bo" / ".ns" too.
    return (t or "").upper().replace(".NS", "").replace(".BO", "")


def _safe_float(x, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


# ── Classification ──────────────────────────────────────────────
def classify_maintenance_intensity(
    maint_to_da_ratio: float,
    segment: str,
) -> IntensityLabel:
    """Map a maintenance-capex / D&A ratio to an intensity label,
    normalized against the segment's mid-cycle norm.

    Rule:
      ratio_vs_norm = actual_ratio / segment_norm
      < 0.8 × norm  → "underspending"  (covers 0..0.5 deferred and
                                         0.5..0.8 light bands)
      0.8..1.2 × norm → "normal"
      1.2..1.5 × norm → "heavy"
      > 1.5 × norm  → "extreme"

    Defensive: unknown segment → use "generation_thermal" norm so the
    label still reads usefully rather than crashing.
    """
    norm = SEGMENT_MAINTENANCE_NORMS.get(
        segment,  # type: ignore[arg-type]
        SEGMENT_MAINTENANCE_NORMS["generation_thermal"],
    )
    if norm <= 0:
        return "normal"
    r = _safe_float(maint_to_da_ratio, 0.0)
    if r <= 0:
        # Zero or negative ratio is structural underspend (or bad
        # data); flag the same way the operator would read it.
        return "underspending"
    rel = r / norm
    if rel < _UNDERSPEND_RATIO + 0.3:   # < 0.8 of norm
        return "underspending"
    if rel <= _HEAVY_RATIO:              # 0.8..1.2 of norm
        return "normal"
    if rel <= _EXTREME_RATIO:            # 1.2..1.5 of norm
        return "heavy"
    return "extreme"


# ── Core engine ─────────────────────────────────────────────────
def compute_maintenance_adjustment(
    inputs: UtilitiesMaintenanceInputs,
) -> UtilitiesMaintenanceResult:
    """Return the owner-earnings / intensity overlay for a utility.

    Maintenance capex estimate:
      - If ``growth_capex_inr_cr`` is supplied: maint = total − growth
      - Else: maint = total × maintenance_capex_fraction

    Owner earnings (Munger / Buffett):
      owner_earnings = reported_FCF − (maintenance_capex − D&A)

    Intensity:
      ratio = maintenance_capex / D&A
      label = classify_maintenance_intensity(ratio, segment)

    Sanity warnings cover the cases Phase B needs to gate on:
      - D&A non-positive (cannot compute ratio)
      - growth capex > total capex (operator data error)
      - implied maintenance capex < 0
      - ratio vs norm in the "extreme" band (asset stress signal)
      - ratio vs norm in the "underspending" band (deferred risk)
    """
    warnings: list[str] = []

    reported_fcf = _safe_float(inputs.reported_fcf_inr_cr)
    da = _safe_float(inputs.da_inr_cr)
    total_capex = _safe_float(inputs.total_capex_inr_cr)
    fraction = _safe_float(
        inputs.maintenance_capex_fraction,
        _DEFAULT_MAINTENANCE_CAPEX_FRACTION,
    )
    growth_supplied = inputs.growth_capex_inr_cr
    segment = inputs.sub_segment

    # Clamp the fraction defensively so a corrupt upstream value
    # cannot produce a negative maintenance estimate or one larger
    # than total capex.
    if fraction < 0.0 or fraction > 1.0:
        warnings.append(
            f"maintenance_capex_fraction {fraction:.2f} out of [0,1]; "
            f"clamped"
        )
        fraction = max(0.0, min(1.0, fraction))

    # Maintenance capex split.
    if growth_supplied is not None:
        growth = _safe_float(growth_supplied)
        if growth > total_capex and total_capex > 0:
            warnings.append(
                f"growth_capex {growth:.0f} > total_capex {total_capex:.0f}; "
                f"falling back to fraction split"
            )
            maint = total_capex * fraction
        else:
            maint = total_capex - growth
    else:
        maint = total_capex * fraction

    if maint < 0:
        warnings.append(
            f"implied maintenance capex {maint:.0f} < 0; clamped to 0"
        )
        maint = 0.0

    # Owner earnings — Munger identity.
    owner_earnings = reported_fcf - (maint - da)

    # Maintenance intensity vs D&A.
    if da <= 0:
        warnings.append(
            "D&A non-positive; intensity ratio suppressed (label defaults "
            "to 'normal' as a conservative null)"
        )
        ratio = 0.0
        intensity_pct = 0.0
        label: IntensityLabel = "normal"
        norm = SEGMENT_MAINTENANCE_NORMS.get(segment, 0.9)
        rel = 0.0
    else:
        ratio = maint / da
        intensity_pct = ratio * 100.0
        label = classify_maintenance_intensity(ratio, segment)
        norm = SEGMENT_MAINTENANCE_NORMS.get(segment, 0.9)
        rel = (ratio / norm) if norm > 0 else 0.0

    # Surface the bands the analysis page needs to badge / gate.
    if label == "extreme":
        warnings.append(
            f"maintenance intensity {intensity_pct:.0f}% (ratio {rel:.2f}x "
            f"vs segment norm) — extreme; asset stress signal"
        )
    elif label == "heavy":
        warnings.append(
            f"maintenance intensity {intensity_pct:.0f}% (ratio {rel:.2f}x "
            f"vs segment norm) — heavy"
        )
    elif label == "underspending" and da > 0:
        warnings.append(
            f"maintenance intensity {intensity_pct:.0f}% (ratio {rel:.2f}x "
            f"vs segment norm) — underspending; deferred maintenance risk"
        )

    # Asset-base age signal (optional). A very old asset base
    # combined with underspending is a meaningfully worse signal
    # than either alone; Phase B can read both fields.
    age = inputs.asset_base_age_years
    if age is not None and _safe_float(age) >= 25 and label == "underspending":
        warnings.append(
            f"asset_base_age {age:.0f}y combined with underspending — "
            f"compounding deferred-maintenance risk"
        )

    return UtilitiesMaintenanceResult(
        reported_fcf=round(reported_fcf, 2),
        maintenance_capex_estimated=round(maint, 2),
        owner_earnings_inr_cr=round(owner_earnings, 2),
        maintenance_intensity_pct=round(intensity_pct, 2),
        intensity_label=label,
        sanity_warnings=warnings,
        sub_segment=segment,
        segment_norm_ratio=round(norm, 3),
        ratio_vs_norm=round(rel, 3),
    )


# ── Applicability gate ──────────────────────────────────────────
def is_utilities_maint_applicable(
    ticker: str,
    sector: Optional[str],
) -> tuple[bool, str]:
    """Return ``(applicable, reason)`` for the maintenance overlay.

    Applicable iff the ticker is in UTILITIES_TICKERS. Sector-tagged
    "Utilities" / "Power" names not in the explicit list return False
    with a soft signal so the caller can choose to fire defensively
    in a future Phase.
    """
    clean = _clean_ticker(ticker)
    if not clean:
        return False, "empty ticker"
    if clean in UTILITIES_TICKERS:
        seg = UTILITIES_TICKERS[clean]
        return True, f"{clean} in UTILITIES_TICKERS (segment={seg})"
    sec = (sector or "").strip().lower()
    if "utilities" in sec or "power" in sec:
        return False, (
            f"sector tagged utilities/power but {clean} not in "
            f"UTILITIES_TICKERS"
        )
    return False, f"{clean} not a utilities ticker"


# ── JSON-safe serializer ────────────────────────────────────────
def to_dict(result: UtilitiesMaintenanceResult) -> dict:
    """Project a UtilitiesMaintenanceResult into a plain dict for
    JSON responses or DB persistence. No Decimal / datetime types.
    """
    return {
        "reported_fcf_inr_cr": result.reported_fcf,
        "maintenance_capex_estimated_inr_cr": result.maintenance_capex_estimated,
        "owner_earnings_inr_cr": result.owner_earnings_inr_cr,
        "maintenance_intensity_pct": result.maintenance_intensity_pct,
        "intensity_label": result.intensity_label,
        "sub_segment": result.sub_segment,
        "segment_norm_ratio": result.segment_norm_ratio,
        "ratio_vs_norm": result.ratio_vs_norm,
        "sanity_warnings": list(result.sanity_warnings),
    }
