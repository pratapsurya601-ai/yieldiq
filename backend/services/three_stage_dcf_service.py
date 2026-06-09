# backend/services/three_stage_dcf_service.py
# ═════════════════════════════════════════════════════════════════════
# THREE-STAGE GROWTH DCF — standalone valuation service (T2.5 Phase A)
# ═════════════════════════════════════════════════════════════════════
#
# Why this exists
# ───────────────
# YieldIQ's current generic DCF is two-stage: an explicit high-growth
# horizon followed by an immediate jump to terminal growth. The cliff
# between high (e.g. 14% for HDFCBANK) and terminal (e.g. 5%) over-
# rewards the near-term horizon — every rupee in years 1..N1 is
# compounded at the high rate, and the Gordon terminal then assumes
# growth instantly halves.
#
# This systematically biases fair value high. The most-cited symptom
# in the 2026-06 cross-check vs AlphaSpread:
#
#     HDFCBANK:  YieldIQ ₹1,129  vs AlphaSpread ₹803   →  ~40% high
#
# AlphaSpread uses an explicit fade window between the two stages.
# Damodaran's three-stage framework is the same idea, formalised:
#
#     Stage 1: explicit high growth g_h for N1 years (typically 5)
#     Stage 2: LINEAR FADE from g_h down to g_t over N2 years
#              (typically 5)
#     Stage 3: terminal value via Gordon at g_t
#
# The fade window smooths the transition. In practice, intrinsic
# value lands between the two-stage (high) and a single-stage Gordon
# (low) — directionally lower than the existing two-stage, which is
# the right move for the cohort that's been printing 25–40% high vs
# AlphaSpread.
#
# What this module is and is NOT
# ──────────────────────────────
# IS:
#   - A standalone, pure-function service that returns a complete
#     ThreeStageResult given canonical inputs.
#   - Independent of the heavy analysis pipeline. No imports from
#     backend.services.analysis.*; no DB access; no caching.
#   - Symmetrical with reverse_dcf_service.py (which is also
#     standalone and pure).
#
# IS NOT (Phase A scope):
#   - NOT wired into composite_iv_service. The existing two-stage DCF
#     remains byte-identical. Phase B adds an opt-in `three_stage_fv`
#     field that composite_iv_service can weight against the existing
#     estimator (separate PR).
#   - NOT a replacement for the two-stage DCF. The discipline rule is:
#     keep both as parallel estimators, weight them in the composite,
#     and surface the divergence to the user via the calibration
#     panel.
#   - NOT a sector-specific override. Sector-tuned (g_h, g_t, fade)
#     defaults live in select_three_stage_default_horizons() but the
#     core math is sector-agnostic.
#
# Algorithm
# ─────────
# Given (FCF_0, g_h, N1, N2, g_t, r) where r is WACC:
#
#   Stage 1 (years 1..N1):
#       FCF_t = FCF_{t-1} * (1 + g_h)
#
#   Stage 2 (years N1+1..N1+N2):
#       fade_rates[i] = g_h - (g_h - g_t) * (i+1) / N2   for i=0..N2-1
#       FCF_t = FCF_{t-1} * (1 + fade_rates[t - N1 - 1])
#       (last fade year is exactly g_t)
#
#   Terminal value at end of year N1+N2:
#       TV = FCF_{N1+N2} * (1 + g_t) / (r - g_t)
#
#   Discount:
#       PV_t = FCF_t / (1 + r)^t
#       PV_TV = TV / (1 + r)^{N1+N2}
#       EV = sum(PV_t for t in 1..N1+N2) + PV_TV
#
#   Equity bridge:
#       Equity = EV - net_debt
#       FV/share = Equity / shares_outstanding
# ═════════════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Optional

log = logging.getLogger("yieldiq.three_stage_dcf_service")


# ─────────────────────────────────────────────────────────────────────
# Inputs / result dataclasses
# ─────────────────────────────────────────────────────────────────────
@dataclass
class ThreeStageInputs:
    """Canonical inputs for the three-stage DCF.

    All rates are decimals (0.15 = 15%). All cash amounts in the
    same currency unit (Crores for INR engine). The caller is
    responsible for unit consistency — this module does NOT scale
    or convert units.
    """

    base_year_fcf: float                # current FCF (year 0)
    high_growth_rate: float             # g_h, decimal (e.g. 0.15 = 15%)
    high_growth_years: int = 5          # N1
    fade_years: int = 5                 # N2
    terminal_growth: float = 0.04       # g_t
    discount_rate: float = 0.115        # WACC
    shares_outstanding: float = 0.0
    net_debt: float = 0.0               # for equity-value bridge


@dataclass
class ThreeStageYearProjection:
    """Per-year projection row. Useful for surfacing a year-by-year
    cashflow table on the analysis page (Phase B).
    """

    year: int                           # 1, 2, 3, ...
    growth_rate: float                  # rate USED for this year (interpolated in fade)
    fcf: float                          # projected FCF for this year
    discount_factor: float              # 1 / (1+r)^year
    pv: float                           # present value contribution


@dataclass
class ThreeStageResult:
    """Output of the three-stage DCF.

    method:
        - "three_stage_dcf" on success
        - "unavailable" when inputs fail validation; check
          sanity_warnings for the reason
    """

    fair_value_per_share: Optional[float]
    enterprise_value: Optional[float]
    equity_value: Optional[float]
    pv_explicit_fcf: float              # sum of stage 1 + stage 2 PVs
    pv_terminal: float                  # PV of stage 3 (terminal value)
    terminal_value: float               # nominal TV at end of N1+N2
    projections: list[ThreeStageYearProjection] = field(default_factory=list)
    method: str = "three_stage_dcf"
    sanity_warnings: list[str] = field(default_factory=list)
    # When the caller supplies the two-stage FV for comparison, we
    # surface the gap so composite_iv_service can log "three-stage is
    # N% below two-stage for this ticker".
    gap_to_two_stage_dcf: Optional[float] = None


# ─────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────
def _is_finite_number(x: Optional[float]) -> bool:
    """True iff x is a finite float (rejects None, NaN, +/-inf)."""
    if x is None:
        return False
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(xf)


def _is_finite_positive(x: Optional[float]) -> bool:
    return _is_finite_number(x) and float(x) > 0


def _unavailable_result(warnings: list[str]) -> ThreeStageResult:
    """Construct an `unavailable` result with the given warnings.
    Callers downstream key off `method == "unavailable"` rather than
    `fair_value_per_share is None` because the per-share value can
    also be None when shares_outstanding is 0 but the EV is still
    meaningful.
    """
    return ThreeStageResult(
        fair_value_per_share=None,
        enterprise_value=None,
        equity_value=None,
        pv_explicit_fcf=0.0,
        pv_terminal=0.0,
        terminal_value=0.0,
        projections=[],
        method="unavailable",
        sanity_warnings=list(warnings),
        gap_to_two_stage_dcf=None,
    )


# ─────────────────────────────────────────────────────────────────────
# Linear-fade growth rates
# ─────────────────────────────────────────────────────────────────────
def compute_fade_growth_rates(
    g_high: float,
    g_terminal: float,
    fade_years: int,
) -> list[float]:
    """Linear taper from g_high down to g_terminal over `fade_years`
    years. The taper hits g_terminal exactly on the last fade year.

    Edge cases:
        - fade_years <= 0:  return []  (no fade window)
        - fade_years == 1:  return [g_terminal]  (one-shot drop)
        - g_high == g_terminal:  every element is the common rate
                                 (no fade math, just a constant tail)

    Example:
        compute_fade_growth_rates(0.15, 0.04, 5)
            → [0.128, 0.106, 0.084, 0.062, 0.04]

    Implementation: step = (g_high - g_terminal) / fade_years; the
    i-th (0-indexed) fade year uses g_high - step * (i + 1). The
    (fade_years - 1)-th value is g_high - step * fade_years
    = g_terminal exactly (floating-point round-off aside).
    """
    if fade_years <= 0:
        return []
    if fade_years == 1:
        return [float(g_terminal)]
    step = (float(g_high) - float(g_terminal)) / float(fade_years)
    return [float(g_high) - step * (i + 1) for i in range(fade_years)]


# ─────────────────────────────────────────────────────────────────────
# Main entry
# ─────────────────────────────────────────────────────────────────────
def compute_three_stage_dcf(
    inputs: ThreeStageInputs,
    two_stage_dcf_for_comparison: Optional[float] = None,
) -> ThreeStageResult:
    """Three-stage growth DCF with linear fade.

    Validation:
        - All input values must be finite numbers.
        - base_year_fcf must be positive (the model is meaningless on
          a zero / negative baseline; sector engines handle those).
        - discount_rate must be > terminal_growth, strictly, else the
          Gordon terminal diverges. Returns unavailable.
        - high_growth_years and fade_years must each be non-negative
          and finite (but a 0-year explicit stage with a positive fade
          window is legitimate — it's a pure-fade DCF).
        - shares_outstanding may be 0; per-share FV is reported as
          None in that case but enterprise_value / equity_value
          remain meaningful.

    Soft warnings (the model still computes, but the caller should
    surface them):
        - high_growth_rate >= discount_rate (stage 1 grows faster than
          discount; possible for a few years but unusual).
        - high_growth_rate <= terminal_growth (not really a "fade";
          you'd usually just use a one-stage Gordon).

    two_stage_dcf_for_comparison: optional. When provided AND the
    result is computable, `gap_to_two_stage_dcf` is set to
    (three_stage_fv - two_stage_fv) / two_stage_fv — a signed fraction.
    Negative means three-stage is lower (the expected direction for
    the HDFCBANK-shaped over-bias case).
    """
    warnings: list[str] = []

    # ── Hard validation ──────────────────────────────────────────
    if not _is_finite_positive(inputs.base_year_fcf):
        warnings.append("base_year_fcf must be positive and finite")
        return _unavailable_result(warnings)

    if not _is_finite_number(inputs.high_growth_rate):
        warnings.append("high_growth_rate must be a finite number")
        return _unavailable_result(warnings)

    if not _is_finite_number(inputs.terminal_growth):
        warnings.append("terminal_growth must be a finite number")
        return _unavailable_result(warnings)

    if not _is_finite_positive(inputs.discount_rate):
        warnings.append("discount_rate must be positive and finite")
        return _unavailable_result(warnings)

    if not (isinstance(inputs.high_growth_years, int) and inputs.high_growth_years >= 0):
        warnings.append("high_growth_years must be a non-negative int")
        return _unavailable_result(warnings)

    if not (isinstance(inputs.fade_years, int) and inputs.fade_years >= 0):
        warnings.append("fade_years must be a non-negative int")
        return _unavailable_result(warnings)

    if inputs.high_growth_years + inputs.fade_years <= 0:
        warnings.append(
            "high_growth_years + fade_years must be > 0; no explicit horizon"
        )
        return _unavailable_result(warnings)

    if not _is_finite_number(inputs.shares_outstanding) or inputs.shares_outstanding < 0:
        warnings.append("shares_outstanding must be a non-negative finite number")
        return _unavailable_result(warnings)

    if not _is_finite_number(inputs.net_debt):
        warnings.append("net_debt must be a finite number")
        return _unavailable_result(warnings)

    # Strict r > g_t for Gordon to converge.
    if inputs.terminal_growth >= inputs.discount_rate:
        warnings.append(
            f"terminal_growth ({inputs.terminal_growth:.4f}) must be strictly "
            f"less than discount_rate ({inputs.discount_rate:.4f}) — "
            f"Gordon terminal value would diverge"
        )
        return _unavailable_result(warnings)

    # ── Soft warnings (still compute) ────────────────────────────
    if inputs.high_growth_rate >= inputs.discount_rate:
        warnings.append(
            f"high_growth_rate ({inputs.high_growth_rate:.4f}) >= "
            f"discount_rate ({inputs.discount_rate:.4f}) — stage 1 "
            f"compounds faster than discount; review inputs"
        )

    if inputs.high_growth_rate <= inputs.terminal_growth:
        warnings.append(
            f"high_growth_rate ({inputs.high_growth_rate:.4f}) <= "
            f"terminal_growth ({inputs.terminal_growth:.4f}) — not "
            f"really a fade; a single-stage Gordon would suffice"
        )

    # ── Build the fade-rate vector ───────────────────────────────
    fade_rates = compute_fade_growth_rates(
        inputs.high_growth_rate,
        inputs.terminal_growth,
        inputs.fade_years,
    )

    # ── Project FCF year-by-year + discount ──────────────────────
    projections: list[ThreeStageYearProjection] = []
    fcf_prev = float(inputs.base_year_fcf)
    pv_explicit = 0.0
    r = float(inputs.discount_rate)

    # Stage 1: years 1 .. N1 at g_h
    for t in range(1, inputs.high_growth_years + 1):
        g = float(inputs.high_growth_rate)
        fcf_t = fcf_prev * (1.0 + g)
        df_t = 1.0 / ((1.0 + r) ** t)
        pv_t = fcf_t * df_t
        projections.append(
            ThreeStageYearProjection(
                year=t,
                growth_rate=g,
                fcf=fcf_t,
                discount_factor=df_t,
                pv=pv_t,
            )
        )
        pv_explicit += pv_t
        fcf_prev = fcf_t

    # Stage 2: years N1+1 .. N1+N2 at fade_rates[i]
    for i, g_i in enumerate(fade_rates):
        t = inputs.high_growth_years + i + 1
        fcf_t = fcf_prev * (1.0 + float(g_i))
        df_t = 1.0 / ((1.0 + r) ** t)
        pv_t = fcf_t * df_t
        projections.append(
            ThreeStageYearProjection(
                year=t,
                growth_rate=float(g_i),
                fcf=fcf_t,
                discount_factor=df_t,
                pv=pv_t,
            )
        )
        pv_explicit += pv_t
        fcf_prev = fcf_t

    # ── Terminal value (Gordon on year-(N1+N2) FCF, growing at g_t) ──
    horizon = inputs.high_growth_years + inputs.fade_years
    g_t = float(inputs.terminal_growth)
    terminal_value = fcf_prev * (1.0 + g_t) / (r - g_t)
    pv_terminal = terminal_value / ((1.0 + r) ** horizon)

    # ── EV / equity / per-share ──────────────────────────────────
    enterprise_value = pv_explicit + pv_terminal
    equity_value = enterprise_value - float(inputs.net_debt)

    if inputs.shares_outstanding > 0:
        fv_per_share: Optional[float] = equity_value / float(inputs.shares_outstanding)
    else:
        fv_per_share = None

    # ── Two-stage gap (optional caller-supplied) ─────────────────
    gap: Optional[float] = None
    if (
        two_stage_dcf_for_comparison is not None
        and _is_finite_positive(two_stage_dcf_for_comparison)
        and fv_per_share is not None
        and _is_finite_number(fv_per_share)
    ):
        gap = (fv_per_share - float(two_stage_dcf_for_comparison)) / float(
            two_stage_dcf_for_comparison
        )

    return ThreeStageResult(
        fair_value_per_share=fv_per_share,
        enterprise_value=enterprise_value,
        equity_value=equity_value,
        pv_explicit_fcf=pv_explicit,
        pv_terminal=pv_terminal,
        terminal_value=terminal_value,
        projections=projections,
        method="three_stage_dcf",
        sanity_warnings=warnings,
        gap_to_two_stage_dcf=gap,
    )


# ─────────────────────────────────────────────────────────────────────
# Sector-tuned default horizons
# ─────────────────────────────────────────────────────────────────────
# Rationale per cohort:
#   - IT Services: extended high-growth window — large export franchises
#     (TCS / INFY / HCLTECH) compound at 10–14% USD revenue for longer
#     than the FMCG / Banks 5y baseline.
#   - Banks / FMCG: balanced (5, 5). Mature, slow-fading franchises.
#   - Pharma: longer fade (5, 7) — chronic franchise persistence
#     (cardiology / oncology backbones) but eventually patent / pricing
#     erode.
#   - Auto OEMs / cyclicals (metals / cement / oil): short explicit
#     stage (3y), long fade (7y) — the cycle is the dominant feature,
#     compounding a peak-cycle high-growth rate for 7 years is the
#     classic two-stage overbias the three-stage framework was built to
#     fix.
#   - Platform / recent IPO: aggressive (8, 5) — model the growth-phase
#     window explicitly.
#   - Telecom: (4, 6) — capex-heavy, ROIC fades after 4y.
#   - Power utilities (regulated): (3, 7) — RoE-capped by regulator;
#     fade quickly toward the allowed return.
# ─────────────────────────────────────────────────────────────────────
_SECTOR_KEYWORDS_HORIZONS: tuple[tuple[tuple[str, ...], tuple[int, int]], ...] = (
    # IT services & technology — extended high-growth
    (("it services", "information technology", "software", "technology services"),
     (7, 5)),
    # Pharma & healthcare — longer fade
    (("pharma", "pharmaceutical", "healthcare", "biotech", "drugs"),
     (5, 7)),
    # Telecom — short explicit, longer fade
    (("telecom", "telecommunication", "wireless"),
     (4, 6)),
    # Auto OEMs & cyclicals — short explicit, long fade
    (("auto", "automobile", "automotive", "two-wheeler", "two wheeler"),
     (3, 7)),
    (("metals", "mining", "steel", "aluminium", "aluminum", "iron ore", "copper", "zinc"),
     (3, 7)),
    (("cement",),
     (3, 7)),
    (("oil", "gas", "petroleum", "refining"),
     (3, 7)),
    # Regulated utilities — short, long fade
    (("utility", "utilities", "power generation", "power transmission", "electric"),
     (3, 7)),
    # Banks / financials — balanced
    (("bank", "banking"),
     (5, 5)),
    (("nbfc", "financial services", "finance"),
     (5, 5)),
    # FMCG — balanced
    (("fmcg", "consumer", "household", "personal care", "packaged food", "beverages"),
     (5, 5)),
)


def select_three_stage_default_horizons(
    sector: Optional[str],
    is_recent_ipo: bool = False,
) -> tuple[int, int]:
    """Return (high_growth_years, fade_years) defaults per sector.

    Recent-IPO override: when `is_recent_ipo` is True, force (8, 5)
    regardless of sector — the explicit-growth window is the dominant
    feature of an IPO valuation.

    Match is case-insensitive substring on the sector name. Unknown /
    missing sectors fall back to (5, 5).
    """
    if is_recent_ipo:
        return (8, 5)

    if not sector:
        return (5, 5)

    s = str(sector).strip().lower()
    if not s:
        return (5, 5)

    for keywords, horizons in _SECTOR_KEYWORDS_HORIZONS:
        for kw in keywords:
            if kw in s:
                return horizons

    return (5, 5)


# ─────────────────────────────────────────────────────────────────────
# Applicability gate
# ─────────────────────────────────────────────────────────────────────
# These sectors / structural types have dedicated valuation frameworks
# that the three-stage DCF would interfere with. We skip them entirely
# rather than emitting a fade-DCF the caller would have to discard.
_THREE_STAGE_SKIP_SECTOR_KEYWORDS: tuple[str, ...] = (
    "holdco",
    "holding company",
    "holding companies",
    "diversified holding",
    "reit",
    "real estate investment trust",
    "invit",
    "etf",
    "exchange traded fund",
    "exchange-traded fund",
    "mutual fund",
)


def is_three_stage_applicable(
    ticker: str,
    sector: Optional[str],
    base_year_fcf: Optional[float],
    fcf_history_years: int,
) -> tuple[bool, str]:
    """Decide whether to run the three-stage DCF for a given ticker.

    Three-stage is appropriate when:
      - base_year_fcf > 0 (a positive baseline; the model is built
        around compounding a positive FCF, not rebuilding one).
      - At least 3 years of FCF history (else the high-growth rate
        isn't anchored to anything observable).
      - The ticker is NOT a holdco / REIT / InvIT / ETF — those have
        dedicated frameworks (SOTP / NAV+DPU / NAV).

    Returns (applicable, reason). When False, `reason` is a short
    machine-readable tag the caller can log / surface.
    """
    if not _is_finite_positive(base_year_fcf):
        return (False, "base_year_fcf_non_positive")

    if not isinstance(fcf_history_years, int) or fcf_history_years < 3:
        return (False, "fcf_history_too_short")

    if sector:
        s = str(sector).strip().lower()
        for kw in _THREE_STAGE_SKIP_SECTOR_KEYWORDS:
            if kw in s:
                return (False, f"sector_uses_dedicated_framework:{kw}")

    return (True, "ok")


# ─────────────────────────────────────────────────────────────────────
# JSON serialization
# ─────────────────────────────────────────────────────────────────────
def to_dict(result: ThreeStageResult) -> dict:
    """JSON-safe dict shape. Used when the result is embedded in an
    API response payload or logged.

    Floats / ints / lists / dicts only — no dataclass instances or
    other non-JSON types.
    """
    if not isinstance(result, ThreeStageResult):
        raise TypeError(
            f"to_dict expects ThreeStageResult, got {type(result).__name__}"
        )

    return {
        "fair_value_per_share": result.fair_value_per_share,
        "enterprise_value": result.enterprise_value,
        "equity_value": result.equity_value,
        "pv_explicit_fcf": result.pv_explicit_fcf,
        "pv_terminal": result.pv_terminal,
        "terminal_value": result.terminal_value,
        "projections": [asdict(p) for p in result.projections],
        "method": result.method,
        "sanity_warnings": list(result.sanity_warnings),
        "gap_to_two_stage_dcf": result.gap_to_two_stage_dcf,
    }
