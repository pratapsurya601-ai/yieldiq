# backend/services/auto_oem_cycle_service.py
# ═════════════════════════════════════════════════════════════════════
# AUTO OEM CYCLE-ADJUSTED VALUATION — standalone service (T3.7 Phase A)
# ═════════════════════════════════════════════════════════════════════
#
# Why this exists
# ───────────────
# Auto OEMs are mid-cycle businesses. Unit volumes oscillate on a
# 5–7 year demand cycle (replacement demand, BS-VI/EV transitions,
# rural monsoon, commercial freight cycles). Margins compress at
# troughs (operating leverage works in reverse) and expand at peaks.
#
# A generic two-stage DCF that anchors on TRAILING twelve-month
# volume + margin systematically:
#
#   • OVER-extrapolates from peaks — TVSMOTOR 2024 ran at ~1.05M units
#     at 12% operating margin; if today's volume × margin × multiple is
#     fed into a DCF growing at 8% terminal, the engine projects peak
#     economics forward indefinitely. Cycle reverts before terminal.
#
#   • OVER-discounts at troughs — TATAMOTORS CV 2020 ran 30% below
#     mid-cycle volume at sub-5% margin. A DCF anchored on TTM hands
#     out a "data_limited" or extremely low FV right when the cycle
#     turn is the buy signal.
#
# Standard sell-side framework (Damodaran, Morgan Stanley auto desk,
# Macquarie cyclicals):
#
#     mid_cycle_volume   = sqrt(peak_volume × trough_volume)
#     mid_cycle_revenue  = mid_cycle_volume × realization_per_unit
#     mid_cycle_EBITDA   = mid_cycle_revenue × mid_cycle_margin
#     EV                 = mid_cycle_EBITDA × segment_multiple
#     equity             = EV − net_debt
#     fair_value         = equity / shares_outstanding
#
# The geometric mean (vs arithmetic) is the convention because
# returns compound multiplicatively; sqrt(peak × trough) is also
# robust to a single outlier year on either end.
#
# Indian auto OEM universe (Phase A)
# ──────────────────────────────────
#   4W:        MARUTI, TATAMOTORS, M&M
#   2W:        BAJAJ-AUTO, HEROMOTOCO, TVSMOTOR
#   luxury 2W: EICHERMOT (Royal Enfield)
#   CV:        ASHOKLEY (M&M also has CV but is classified as pv_4w
#              primary; CV is a minority contribution).
#   specialty: MAHSCOOTER — NOT in the Phase A auto-OEM universe;
#              it is a holdco-style cash box, not a volume-cycle OEM.
#
# Segment-default EV/EBITDA multiples — anchored to FY24/25 peer
# medians of the listed Indian OEM cohort, not US/EU averages:
#
#     pv_4w     14.0x  — MARUTI dominates the segment; 11–15x band.
#     pv_2w     18.0x  — Higher capital efficiency, lower capex
#                        intensity; 15–22x band (BAJAJ-AUTO, HEROMOTOCO,
#                        TVSMOTOR).
#     luxury_2w 25.0x  — EICHERMOT / Royal Enfield commands a premium
#                        on brand + 35%+ gross margin vs 22% for mass-
#                        market 2W; 22–28x band.
#     cv        10.0x  — ASHOKLEY, deeper cyclicality, more leverage,
#                        compressed multiple; 8–12x band.
#
# Cycle position adjustment
# ─────────────────────────
# An optional ±15% taper on the mid-cycle base FV reflects where the
# user (or upstream classifier) believes the cycle currently sits.
# This is a small adjustment by design — the whole point of mid-
# cycle normalization is to ignore the current cycle position. The
# taper exists for callers who want a directional nudge:
#
#     trough            −15%  (assume mean-reversion → mid is closer)
#     early_recovery    − 7%
#     mid_cycle           0%  (default; no taper)
#     late_cycle        + 7%
#     peak              +15%
#
# Sanity warnings (NOT errors)
# ────────────────────────────
# The service does not raise on suspicious inputs — it records
# `sanity_warnings` so the caller can downgrade confidence:
#
#   • peak / trough ratio > 3 — implausibly wide cycle band; data
#     issue or merger-restated history. Mid-cycle still computed
#     but flagged.
#   • current_volume outside [trough × 0.7, peak × 1.3] — current
#     volume implies a structural break, not a cycle position.
#   • margin_current − margin_mid > 10pp — implausible margin gap;
#     either accounting noise or a structural change.
#   • multiple outside [5, 35] — out-of-bracket; caller should
#     reconsider the segment classification.
#   • shares_outstanding ≤ 0 — fair_value_per_share returned None.
#
# Scope (Phase A only)
# ────────────────────
# NOT wired into composite_iv_service. The existing two-stage DCF
# stays byte-identical. This service is a STANDALONE, pure-function
# module. Phase B (separate PR) introduces an opt-in
# auto_oem_cycle_fv field that composite_iv_service can weight
# against the existing estimator for tickers in AUTO_OEM_TICKERS.
#
# Discipline rules upheld
# ───────────────────────
#   • No imports from backend.services.analysis.*
#   • No DB access; pure-function service driven by inputs dataclass.
#   • Pydantic dataclass return shape mirrors three_stage_dcf_service
#     and bank residual-income for downstream wiring symmetry.
#   • Manifest entry scoped to the 8 auto-OEM tickers (NOT wildcard);
#     Phase A is additive only — no cached field shape changes.
# ═════════════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger("yieldiq.auto_oem_cycle")


# ── Type aliases ────────────────────────────────────────────────────
AutoSegment = Literal["pv_2w", "pv_4w", "cv", "luxury_2w"]

CyclePosition = Literal[
    "trough",
    "early_recovery",
    "mid_cycle",
    "peak",
    "late_cycle",
]


# ── Calibration tables ──────────────────────────────────────────────
#
# Ticker → segment classification. Used by is_auto_oem_applicable()
# to route a ticker to its segment-specific multiple. M&M is
# classified pv_4w because PV is its primary contribution; the CV
# arm is a secondary line. ASHOKLEY is the pure-CV reference.
#
# MAHSCOOTER intentionally NOT included: it is a holdco-style cash
# box with no manufacturing volume cycle, classified separately in
# the holdco taxonomy.
AUTO_OEM_TICKERS: dict[str, AutoSegment] = {
    # 4W passenger
    "MARUTI":      "pv_4w",
    "TATAMOTORS":  "pv_4w",
    "M&M":         "pv_4w",
    # 2W mass-market
    "BAJAJ-AUTO":  "pv_2w",
    "HEROMOTOCO":  "pv_2w",
    "TVSMOTOR":    "pv_2w",
    # 2W luxury / premium
    "EICHERMOT":   "luxury_2w",
    # Commercial vehicles
    "ASHOKLEY":    "cv",
}

# Segment-default EV/EBITDA multiples (mid-cycle, FY24/25 peer median).
# See header block for sourcing notes.
SEGMENT_MULTIPLES: dict[AutoSegment, float] = {
    "pv_4w":     14.0,
    "pv_2w":     18.0,
    "luxury_2w": 25.0,
    "cv":        10.0,
}

# Cycle position taper. Small ±15% nudge applied AFTER the mid-cycle
# valuation; the bulk of the de-cyclicalization work has already been
# done by the geometric-mean volume.
_CYCLE_POSITION_TAPER: dict[CyclePosition, float] = {
    "trough":         -0.15,
    "early_recovery": -0.07,
    "mid_cycle":       0.00,
    "late_cycle":      0.07,
    "peak":            0.15,
}

# Sanity-warning thresholds. Kept here as module constants so tests
# can pin behavior without monkeypatching internal magic numbers.
_PEAK_TROUGH_MAX_RATIO       = 3.0     # peak / trough > 3 is implausible
_CURRENT_VOL_LOWER_VS_TROUGH = 0.7     # current < trough × 0.7 → break
_CURRENT_VOL_UPPER_VS_PEAK   = 1.3     # current > peak  × 1.3 → break
_MAX_MARGIN_GAP_PP           = 10.0    # |current − mid| > 10pp → flag
_MIN_DEFENSIBLE_MULTIPLE     = 5.0
_MAX_DEFENSIBLE_MULTIPLE     = 35.0


# ── Input / output dataclasses ──────────────────────────────────────
@dataclass
class AutoOEMInputs:
    """Caller-supplied inputs for the auto-OEM cycle valuation.

    Volume units are annual unit sales (cars / 2W / trucks). Realization
    is the average INR per unit (net of dealer margin, GST). Margins
    are operating margin in percent (e.g. 11.0 for 11%). EV/EBITDA
    multiple is unitless. Net debt is INR crore (positive = debt;
    negative = net cash). Shares outstanding is the absolute count
    (NOT crores) — fair_value_per_share is INR/share.
    """

    current_year_volume_units:        float
    peak_year_volume_units:           float
    trough_year_volume_units:         float
    realization_per_unit_inr:         float
    operating_margin_current_pct:     float
    operating_margin_mid_cycle_pct:   float
    ev_ebitda_multiple_mid_cycle:     float = 12.0
    net_debt_inr_cr:                  float = 0.0
    shares_outstanding:               float = 0.0
    segment:                          AutoSegment = "pv_4w"
    cycle_position:                   CyclePosition = "mid_cycle"


@dataclass
class AutoOEMResult:
    """Result of compute_auto_oem_fv().

    fair_value_per_share is None when the equity bridge cannot be
    completed (missing shares_outstanding or negative equity after
    net-debt subtraction). All intermediate normalisations are
    populated regardless so callers can surface diagnostics.
    """

    fair_value_per_share:       Optional[float]
    mid_cycle_volume:           float
    mid_cycle_revenue_inr_cr:   float
    mid_cycle_ebitda_inr_cr:    float
    cycle_adjustment_label:     str      # trough_discount | peak_premium | mid_neutral
    components:                 dict     # full computation breakdown
    method:                     str      # always "auto_oem_mid_cycle_normalization"
    sanity_warnings:            list[str] = field(default_factory=list)


# ── Public API ──────────────────────────────────────────────────────
def is_auto_oem_applicable(
    ticker: Optional[str],
    sector: Optional[str] = None,
) -> tuple[bool, str]:
    """Structural gate.

    Returns (True, segment_label) when the ticker is a known auto
    OEM cycle candidate; (False, reason) otherwise. The `sector`
    argument is accepted but advisory only — Phase A routes purely
    by the AUTO_OEM_TICKERS membership test so the gate is
    deterministic and doesn't depend on sector-classifier drift.
    """
    if not ticker:
        return False, "missing_ticker"
    cleaned = _clean_ticker(ticker)
    if cleaned in AUTO_OEM_TICKERS:
        return True, AUTO_OEM_TICKERS[cleaned]
    return False, "ticker_not_in_auto_oem_universe"


def compute_mid_cycle_normalization(inputs: AutoOEMInputs) -> dict:
    """Return the mid-cycle normalisation components as a dict.

    Volume normalised as geometric mean of peak × trough — robust to
    a single outlier year and consistent with multiplicative-growth
    conventions in the cyclicals literature.

    Returns:
        {
            "mid_cycle_volume":         <units>,
            "mid_cycle_revenue_inr_cr": <INR cr>,
            "mid_cycle_ebitda_inr_cr":  <INR cr>,
        }

    Does NOT raise on bad inputs — returns zeros and lets the caller
    (compute_auto_oem_fv) decide how to surface the failure via
    sanity_warnings.
    """
    peak = max(0.0, float(inputs.peak_year_volume_units))
    trough = max(0.0, float(inputs.trough_year_volume_units))

    if peak <= 0 or trough <= 0:
        return {
            "mid_cycle_volume": 0.0,
            "mid_cycle_revenue_inr_cr": 0.0,
            "mid_cycle_ebitda_inr_cr": 0.0,
        }

    mid_volume = math.sqrt(peak * trough)

    # Revenue: volume × realization → INR; convert to INR cr (× 1e-7).
    realization = max(0.0, float(inputs.realization_per_unit_inr))
    mid_revenue_inr = mid_volume * realization
    mid_revenue_inr_cr = mid_revenue_inr / 1.0e7

    # EBITDA: revenue × margin / 100.
    mid_margin_pct = float(inputs.operating_margin_mid_cycle_pct)
    mid_ebitda_inr_cr = mid_revenue_inr_cr * (mid_margin_pct / 100.0)

    return {
        "mid_cycle_volume":         round(mid_volume, 2),
        "mid_cycle_revenue_inr_cr": round(mid_revenue_inr_cr, 2),
        "mid_cycle_ebitda_inr_cr":  round(mid_ebitda_inr_cr, 2),
    }


def compute_auto_oem_fv(inputs: AutoOEMInputs) -> AutoOEMResult:
    """Full mid-cycle EV/EBITDA equity bridge → per-share fair value.

    Steps:
        1. Mid-cycle volume = sqrt(peak × trough)
        2. Mid-cycle revenue = volume × realization
        3. Mid-cycle EBITDA  = revenue × mid_margin
        4. Enterprise value  = EBITDA × multiple
        5. Equity            = EV − net_debt
        6. Per share         = equity / shares_outstanding
        7. Cycle taper       = base × (1 + taper[cycle_position])

    Returns an AutoOEMResult. Per-share value is None when shares
    are missing/zero or equity is non-positive after debt subtraction
    (sanity_warnings explains which).
    """
    warnings: list[str] = []

    # ── Input sanity ────────────────────────────────────────────────
    peak    = float(inputs.peak_year_volume_units)
    trough  = float(inputs.trough_year_volume_units)
    current = float(inputs.current_year_volume_units)

    if peak <= 0 or trough <= 0:
        warnings.append("non_positive_peak_or_trough_volume")
    if peak > 0 and trough > 0 and (peak / trough) > _PEAK_TROUGH_MAX_RATIO:
        warnings.append("peak_trough_ratio_above_threshold")
    if peak > 0 and current > peak * _CURRENT_VOL_UPPER_VS_PEAK:
        warnings.append("current_volume_above_peak_band")
    if trough > 0 and current > 0 and current < trough * _CURRENT_VOL_LOWER_VS_TROUGH:
        warnings.append("current_volume_below_trough_band")
    if inputs.realization_per_unit_inr <= 0:
        warnings.append("non_positive_realization_per_unit")

    margin_gap = abs(
        float(inputs.operating_margin_current_pct)
        - float(inputs.operating_margin_mid_cycle_pct)
    )
    if margin_gap > _MAX_MARGIN_GAP_PP:
        warnings.append("current_vs_mid_margin_gap_above_threshold")

    multiple = float(inputs.ev_ebitda_multiple_mid_cycle)
    if multiple < _MIN_DEFENSIBLE_MULTIPLE or multiple > _MAX_DEFENSIBLE_MULTIPLE:
        warnings.append("ev_ebitda_multiple_out_of_defensible_band")

    # ── Mid-cycle math ──────────────────────────────────────────────
    mc = compute_mid_cycle_normalization(inputs)
    mid_volume         = mc["mid_cycle_volume"]
    mid_revenue_inr_cr = mc["mid_cycle_revenue_inr_cr"]
    mid_ebitda_inr_cr  = mc["mid_cycle_ebitda_inr_cr"]

    enterprise_value_inr_cr = round(mid_ebitda_inr_cr * multiple, 2)
    equity_value_inr_cr     = round(
        enterprise_value_inr_cr - float(inputs.net_debt_inr_cr), 2
    )

    # ── Cycle taper label ──────────────────────────────────────────
    taper = _CYCLE_POSITION_TAPER.get(inputs.cycle_position, 0.0)
    if taper < 0:
        cycle_label = "trough_discount"
    elif taper > 0:
        cycle_label = "peak_premium"
    else:
        cycle_label = "mid_neutral"

    equity_value_after_taper_inr_cr = round(
        equity_value_inr_cr * (1.0 + taper), 2
    )

    # ── Per-share bridge ───────────────────────────────────────────
    shares = float(inputs.shares_outstanding)
    fv_per_share: Optional[float]

    if shares <= 0:
        warnings.append("non_positive_shares_outstanding")
        fv_per_share = None
    elif equity_value_after_taper_inr_cr <= 0:
        warnings.append("non_positive_equity_after_net_debt")
        fv_per_share = None
    else:
        # equity_value is in INR crore; convert to INR (× 1e7) and
        # divide by share count.
        fv_per_share = round(
            equity_value_after_taper_inr_cr * 1.0e7 / shares, 2
        )

    components = {
        "current_volume":             current,
        "peak_volume":                peak,
        "trough_volume":              trough,
        "mid_cycle_volume":           mid_volume,
        "realization_per_unit_inr":   float(inputs.realization_per_unit_inr),
        "operating_margin_current_pct":   float(inputs.operating_margin_current_pct),
        "operating_margin_mid_cycle_pct": float(inputs.operating_margin_mid_cycle_pct),
        "mid_cycle_revenue_inr_cr":   mid_revenue_inr_cr,
        "mid_cycle_ebitda_inr_cr":    mid_ebitda_inr_cr,
        "ev_ebitda_multiple":         multiple,
        "enterprise_value_inr_cr":    enterprise_value_inr_cr,
        "net_debt_inr_cr":            float(inputs.net_debt_inr_cr),
        "equity_value_inr_cr":        equity_value_inr_cr,
        "cycle_position":             inputs.cycle_position,
        "cycle_taper":                taper,
        "equity_value_after_taper_inr_cr": equity_value_after_taper_inr_cr,
        "shares_outstanding":         shares,
        "segment":                    inputs.segment,
    }

    return AutoOEMResult(
        fair_value_per_share=fv_per_share,
        mid_cycle_volume=mid_volume,
        mid_cycle_revenue_inr_cr=mid_revenue_inr_cr,
        mid_cycle_ebitda_inr_cr=mid_ebitda_inr_cr,
        cycle_adjustment_label=cycle_label,
        components=components,
        method="auto_oem_mid_cycle_normalization",
        sanity_warnings=warnings,
    )


def to_dict(result: AutoOEMResult) -> dict:
    """JSON-safe projection of an AutoOEMResult for the API layer.

    Mirrors the shape of three_stage_dcf_service.to_dict so callers
    can compose results from multiple standalone estimators with
    the same field-access convention.
    """
    if result is None:
        return {
            "available": False,
            "method":    "auto_oem_mid_cycle_normalization",
            "reason":    "no_result",
        }

    return {
        "available":                  result.fair_value_per_share is not None,
        "method":                     result.method,
        "fair_value_per_share":       result.fair_value_per_share,
        "mid_cycle_volume":           result.mid_cycle_volume,
        "mid_cycle_revenue_inr_cr":   result.mid_cycle_revenue_inr_cr,
        "mid_cycle_ebitda_inr_cr":    result.mid_cycle_ebitda_inr_cr,
        "cycle_adjustment_label":     result.cycle_adjustment_label,
        "components":                 dict(result.components),
        "sanity_warnings":            list(result.sanity_warnings),
    }


# ── Internal helpers ────────────────────────────────────────────────
def _clean_ticker(ticker: str) -> str:
    """Strip exchange suffix and uppercase. Mirrors the convention used
    in regulated_utility_valuation_service._clean.
    """
    return (ticker or "").replace(".NS", "").replace(".BO", "").upper().strip()
