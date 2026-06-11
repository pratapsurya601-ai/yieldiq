# backend/services/dividend_discount_model_service.py
"""
Dividend Discount Model (DDM) — standalone valuation service.

T2.1 Phase A of the engine refinement roadmap. Adds a 4th independent
valuation estimator alongside DCF (engine), Multiples (multiples_fv),
and Wall-Street consensus. DDM is appropriate for high-payout-ratio
mature businesses where dividends are the dominant component of
shareholder returns: utilities, FMCG staples, mature IT services with
high payouts, and certain banks.

NOTE — distinction from dividend_service.py:
    dividend_service.DividendService is a CLASSIFIER (sustainability
    label + coverage ratio + streak). It does NOT compute a fair
    value. This module computes a *fair value per share* by
    discounting future dividends at the cost of equity.

Three model variants:

    1. Gordon Growth (single-stage)
           P = D_1 / (k - g)
       where D_1 = next year's expected dividend, k = cost of equity,
       g = perpetual growth rate. Requires g < k strictly.

    2. Two-stage DDM
       Stage 1: explicit dividend forecast for years 1..N at g_h.
       Stage 2: terminal value = D_{N+1} / (k - g_t) discounted back.

    3. H-model (smooth taper)
           P = D_0 * [(1 + g_t) + H * (g_h - g_t)] / (k - g_t)
       Linear transition from g_h to g_t over H years.

Public API:
    gordon_growth(inputs)        -> DDMResult
    two_stage_ddm(inputs)        -> DDMResult
    h_model(inputs)              -> DDMResult
    select_and_compute(...)      -> DDMResult  (auto-routes)
    is_ddm_applicable(...)       -> (bool, reason)
    to_dict(result)              -> dict

Phase A scope: this module + tests + a no-op manifest entry. Wiring
into composite_iv_service and AnalysisResponse is Phase B (separate
PR).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional

log = logging.getLogger("yieldiq.ddm")


# ─────────────────────────────────────────────────────────────────
# Data classes
# ─────────────────────────────────────────────────────────────────

@dataclass
class DDMInputs:
    """Inputs for any DDM variant.

    Attributes:
        current_dividend: Most recent annual dividend per share (D_0).
            Currency-agnostic; output FV uses the same unit.
        cost_of_equity: k, in decimal form (e.g. 0.115 for 11.5%).
        stable_growth: g (Gordon) or g_t (terminal stage for two-stage /
            H-model), in decimal form (e.g. 0.05 for 5%).
        high_growth: g_h for H-model or two-stage. Optional; Gordon
            ignores it. If None for two-stage or H-model, callers
            should fall back to stable_growth (callers responsibility).
        high_growth_years: N (two-stage) or H (H-model). Default 5y.
        expected_payout_ratio: Optional; used only by sanity warnings,
            not by the math. If supplied with ROE upstream, can flag
            cases where g exceeds the sustainable growth ceiling
            (ROE * retention).
    """
    current_dividend: float
    cost_of_equity: float
    stable_growth: float
    high_growth: Optional[float] = None
    high_growth_years: int = 5
    expected_payout_ratio: Optional[float] = None


@dataclass
class DDMResult:
    """Output of any DDM computation.

    Attributes:
        fair_value: Computed fair value per share. None when the
            model is mathematically inapplicable (e.g. g >= k) or
            when inputs are degenerate (e.g. dividend <= 0).
        method: Which variant produced this result. "unavailable" if
            no variant was attempted (e.g. is_ddm_applicable returned
            False upstream and the caller still asked for a result).
        inputs: Echo of the DDMInputs used. Aids transparency and
            downstream debug.
        sanity_warnings: Human-readable warnings collected during
            computation (e.g. "g_t > k", "payout > 100%",
            "dividend = 0"). Empty list when nothing notable.
    """
    fair_value: Optional[float]
    method: str
    inputs: DDMInputs
    sanity_warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Internal helpers
# ─────────────────────────────────────────────────────────────────

#: Minimum spread between k and g for the Gordon-style terminal
#: formula to be numerically well-behaved. Anything tighter than
#: 50bps produces silly large fair values that are an artefact of the
#: model, not a real signal.
_MIN_KG_SPREAD = 0.005

#: Cap on H-model / two-stage high-growth horizon. Beyond ~20y the
#: assumption that g_h holds becomes implausible. Caller-supplied
#: longer horizons are clamped with a warning.
_MAX_HIGH_GROWTH_YEARS = 20


def _validate_common(inputs: DDMInputs) -> list[str]:
    """Run input sanity checks shared by every variant.

    Returns a list of warnings. An empty list means inputs are clean
    enough for the model to attempt a computation; non-empty warnings
    do NOT necessarily mean the model is unusable (e.g. payout > 100%
    is informational), but a few specific conditions (dividend <= 0)
    are caught here and reported.
    """
    warnings: list[str] = []
    if inputs.current_dividend is None or inputs.current_dividend <= 0:
        warnings.append("dividend = 0")
    if inputs.cost_of_equity is None or inputs.cost_of_equity <= 0:
        warnings.append("cost_of_equity <= 0")
    if (
        inputs.expected_payout_ratio is not None
        and inputs.expected_payout_ratio > 1.0
    ):
        warnings.append("payout > 100%")
    return warnings


def _is_finite_positive(x: Optional[float]) -> bool:
    """True if x is a finite, positive, non-NaN float."""
    if x is None:
        return False
    try:
        f = float(x)
    except (TypeError, ValueError):
        return False
    if f != f:  # NaN check
        return False
    if f == float("inf") or f == float("-inf"):
        return False
    return f > 0


# ─────────────────────────────────────────────────────────────────
# Gordon Growth Model
# ─────────────────────────────────────────────────────────────────

def gordon_growth(inputs: DDMInputs) -> DDMResult:
    """Single-stage Gordon Growth DDM.

    P = D_1 / (k - g)
    where D_1 = D_0 * (1 + g).

    Returns DDMResult with fair_value=None when:
        - dividend <= 0
        - cost_of_equity <= 0
        - g >= k (perpetuity diverges)
        - k - g < _MIN_KG_SPREAD (numerically unstable)
    """
    warnings = _validate_common(inputs)

    if "dividend = 0" in warnings or "cost_of_equity <= 0" in warnings:
        return DDMResult(
            fair_value=None,
            method="gordon",
            inputs=inputs,
            sanity_warnings=warnings,
        )

    try:
        d0 = float(inputs.current_dividend)
        k = float(inputs.cost_of_equity)
        g = float(inputs.stable_growth)
    except (TypeError, ValueError):
        warnings.append("non-numeric inputs")
        return DDMResult(
            fair_value=None,
            method="gordon",
            inputs=inputs,
            sanity_warnings=warnings,
        )

    if g >= k:
        warnings.append("g >= k")
        return DDMResult(
            fair_value=None,
            method="gordon",
            inputs=inputs,
            sanity_warnings=warnings,
        )
    if (k - g) < _MIN_KG_SPREAD:
        warnings.append("k - g < 50bps (numerically unstable)")
        return DDMResult(
            fair_value=None,
            method="gordon",
            inputs=inputs,
            sanity_warnings=warnings,
        )

    try:
        d1 = d0 * (1.0 + g)
        fv = d1 / (k - g)
    except (ZeroDivisionError, OverflowError):
        return DDMResult(
            fair_value=None,
            method="gordon",
            inputs=inputs,
            sanity_warnings=warnings + ["arithmetic error"],
        )

    if not _is_finite_positive(fv):
        return DDMResult(
            fair_value=None,
            method="gordon",
            inputs=inputs,
            sanity_warnings=warnings + ["non-finite fair value"],
        )

    return DDMResult(
        fair_value=round(fv, 2),
        method="gordon",
        inputs=inputs,
        sanity_warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────
# Two-Stage DDM
# ─────────────────────────────────────────────────────────────────

def two_stage_ddm(inputs: DDMInputs) -> DDMResult:
    """Two-stage DDM: explicit high-growth phase, then perpetual stable.

    Stage 1 (years 1..N): explicit dividend forecast at g_h.
        D_t = D_0 * (1 + g_h)^t
        PV_stage1 = sum_{t=1..N} D_t / (1 + k)^t

    Stage 2 (year N+1 onwards): terminal Gordon-style perpetuity.
        D_{N+1} = D_N * (1 + g_t)
        TV_at_N = D_{N+1} / (k - g_t)
        PV_TV   = TV_at_N / (1 + k)^N

    P = PV_stage1 + PV_TV

    Returns DDMResult with fair_value=None when:
        - dividend <= 0
        - cost_of_equity <= 0
        - g_t >= k (terminal perpetuity diverges)
        - k - g_t < _MIN_KG_SPREAD
        - high_growth not supplied (caller error)
    """
    warnings = _validate_common(inputs)

    if "dividend = 0" in warnings or "cost_of_equity <= 0" in warnings:
        return DDMResult(
            fair_value=None,
            method="two_stage",
            inputs=inputs,
            sanity_warnings=warnings,
        )

    if inputs.high_growth is None:
        warnings.append("two_stage requires high_growth")
        return DDMResult(
            fair_value=None,
            method="two_stage",
            inputs=inputs,
            sanity_warnings=warnings,
        )

    try:
        d0 = float(inputs.current_dividend)
        k = float(inputs.cost_of_equity)
        g_h = float(inputs.high_growth)
        g_t = float(inputs.stable_growth)
        n = int(inputs.high_growth_years)
    except (TypeError, ValueError):
        warnings.append("non-numeric inputs")
        return DDMResult(
            fair_value=None,
            method="two_stage",
            inputs=inputs,
            sanity_warnings=warnings,
        )

    if n <= 0:
        warnings.append("high_growth_years <= 0")
        return DDMResult(
            fair_value=None,
            method="two_stage",
            inputs=inputs,
            sanity_warnings=warnings,
        )
    if n > _MAX_HIGH_GROWTH_YEARS:
        warnings.append(
            f"high_growth_years clamped to {_MAX_HIGH_GROWTH_YEARS}"
        )
        n = _MAX_HIGH_GROWTH_YEARS

    if g_t >= k:
        warnings.append("g_t >= k")
        return DDMResult(
            fair_value=None,
            method="two_stage",
            inputs=inputs,
            sanity_warnings=warnings,
        )
    if (k - g_t) < _MIN_KG_SPREAD:
        warnings.append("k - g_t < 50bps (numerically unstable)")
        return DDMResult(
            fair_value=None,
            method="two_stage",
            inputs=inputs,
            sanity_warnings=warnings,
        )

    if g_h >= k:
        # Informational; the math still works (no divergence — the
        # high-growth stage is a finite sum, not a perpetuity), but
        # warn the caller because a high-growth rate above cost of
        # equity is a strong assumption.
        warnings.append("g_h >= k (high-growth above cost of equity)")

    try:
        pv_stage1 = 0.0
        d_t = d0
        for t in range(1, n + 1):
            d_t = d_t * (1.0 + g_h)
            pv_stage1 += d_t / ((1.0 + k) ** t)

        # d_t is now D_N. Terminal-stage dividend is D_{N+1}.
        d_n_plus_1 = d_t * (1.0 + g_t)
        tv_at_n = d_n_plus_1 / (k - g_t)
        pv_tv = tv_at_n / ((1.0 + k) ** n)

        fv = pv_stage1 + pv_tv
    except (ZeroDivisionError, OverflowError):
        return DDMResult(
            fair_value=None,
            method="two_stage",
            inputs=inputs,
            sanity_warnings=warnings + ["arithmetic error"],
        )

    if not _is_finite_positive(fv):
        return DDMResult(
            fair_value=None,
            method="two_stage",
            inputs=inputs,
            sanity_warnings=warnings + ["non-finite fair value"],
        )

    return DDMResult(
        fair_value=round(fv, 2),
        method="two_stage",
        inputs=inputs,
        sanity_warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────
# H-Model
# ─────────────────────────────────────────────────────────────────

def h_model(inputs: DDMInputs) -> DDMResult:
    """H-model DDM: smooth linear taper from g_h down to g_t over H years.

    P = D_0 * [(1 + g_t) + H * (g_h - g_t)] / (k - g_t)

    The half-life H captures the intuition that the firm gradually
    transitions from a high growth rate g_h to a sustainable g_t,
    with the average extra growth in the transition equal to
    H * (g_h - g_t) / 2 — which simplifies to the formula above when
    written per the standard derivation.

    Returns DDMResult with fair_value=None when:
        - dividend <= 0
        - cost_of_equity <= 0
        - g_t >= k
        - k - g_t < _MIN_KG_SPREAD
        - high_growth not supplied
        - high_growth_years <= 0
    """
    warnings = _validate_common(inputs)

    if "dividend = 0" in warnings or "cost_of_equity <= 0" in warnings:
        return DDMResult(
            fair_value=None,
            method="h_model",
            inputs=inputs,
            sanity_warnings=warnings,
        )

    if inputs.high_growth is None:
        warnings.append("h_model requires high_growth")
        return DDMResult(
            fair_value=None,
            method="h_model",
            inputs=inputs,
            sanity_warnings=warnings,
        )

    try:
        d0 = float(inputs.current_dividend)
        k = float(inputs.cost_of_equity)
        g_h = float(inputs.high_growth)
        g_t = float(inputs.stable_growth)
        h_years = int(inputs.high_growth_years)
    except (TypeError, ValueError):
        warnings.append("non-numeric inputs")
        return DDMResult(
            fair_value=None,
            method="h_model",
            inputs=inputs,
            sanity_warnings=warnings,
        )

    if h_years <= 0:
        warnings.append("high_growth_years <= 0")
        return DDMResult(
            fair_value=None,
            method="h_model",
            inputs=inputs,
            sanity_warnings=warnings,
        )
    if h_years > _MAX_HIGH_GROWTH_YEARS:
        warnings.append(
            f"high_growth_years clamped to {_MAX_HIGH_GROWTH_YEARS}"
        )
        h_years = _MAX_HIGH_GROWTH_YEARS

    if g_t >= k:
        warnings.append("g_t >= k")
        return DDMResult(
            fair_value=None,
            method="h_model",
            inputs=inputs,
            sanity_warnings=warnings,
        )
    if (k - g_t) < _MIN_KG_SPREAD:
        warnings.append("k - g_t < 50bps (numerically unstable)")
        return DDMResult(
            fair_value=None,
            method="h_model",
            inputs=inputs,
            sanity_warnings=warnings,
        )

    if g_h < g_t:
        # H-model assumes g_h >= g_t (taper DOWN). Inverted inputs
        # still produce a number but with the opposite intent — warn
        # but proceed so the caller sees the math.
        warnings.append("g_h < g_t (H-model assumes taper down)")

    try:
        numerator = (1.0 + g_t) + h_years * (g_h - g_t)
        fv = d0 * numerator / (k - g_t)
    except (ZeroDivisionError, OverflowError):
        return DDMResult(
            fair_value=None,
            method="h_model",
            inputs=inputs,
            sanity_warnings=warnings + ["arithmetic error"],
        )

    if not _is_finite_positive(fv):
        return DDMResult(
            fair_value=None,
            method="h_model",
            inputs=inputs,
            sanity_warnings=warnings + ["non-finite fair value"],
        )

    return DDMResult(
        fair_value=round(fv, 2),
        method="h_model",
        inputs=inputs,
        sanity_warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────
# Routing + applicability
# ─────────────────────────────────────────────────────────────────

#: Sectors where DDM produces misleading results regardless of payout.
#: - "recent ipo": insufficient dividend history; growth assumption pure speculation
#: - "biotech":   binary-outcome firms, dividends are not the value driver
#: - "deep cyclical": dividends collapse to zero in down-cycles, breaking g
#: - "holdco":    fair value is sum-of-parts on underlyings, NOT dividends
_DDM_EXCLUDED_SECTOR_KEYWORDS: tuple[str, ...] = (
    "recent ipo",
    "biotech",
    "deep cyclical",
    "holdco",
    "holding company",
)

#: Sectors that route to single-stage Gordon by default. These are
#: high-payout mature businesses where the perpetual constant-growth
#: assumption is reasonable.
_GORDON_PREFERRED_SECTOR_KEYWORDS: tuple[str, ...] = (
    "fmcg",
    "consumer staples",
    "utility",
    "utilities",
    "power generation",
    "transmission",
    "it services",
    "information technology",
    "bank",
    "banking",
)


def is_ddm_applicable(
    ticker: str,
    sector: Optional[str],
    payout_ratio: Optional[float],
    dividend_streak_years: Optional[int],
) -> tuple[bool, str]:
    """Return (applicable, reason).

    DDM is applicable when ALL of these hold:
        - payout_ratio >= 0.30  (DDM massively understates FV at low
          payouts — most of shareholder return comes from retained
          earnings, not dividends)
        - dividend_streak_years >= 5  (otherwise the growth assumption
          is speculative; a 5-year track record at least demonstrates
          the firm treats dividend as a commitment)
        - sector is NOT in the excluded set (recent-IPO, biotech, deep
          cyclical, holdco)

    Defensive on None inputs: missing payout or streak returns False
    with a reason naming the missing input.
    """
    if not ticker:
        return (False, "ticker required")

    # Sector exclusions first — applies regardless of payout / streak.
    if sector:
        sector_lower = sector.lower()
        for kw in _DDM_EXCLUDED_SECTOR_KEYWORDS:
            if kw in sector_lower:
                return (
                    False,
                    f"sector '{sector}' excluded from DDM ({kw})",
                )

    # Reason strings below are USER-FACING — the router inject writes
    # them verbatim to `ddm_reason`, which the composite-composition
    # panel renders. Keep them descriptive sentences without raw field
    # names (v_composite_warm_path_estimator_fix_2026_06_11; the old
    # "payout_ratio 26% < 30% (...)" form leaked an internal field
    # name to the analysis page).
    if payout_ratio is None:
        return (False, "Dividend payout data is unavailable for this company")
    try:
        po = float(payout_ratio)
    except (TypeError, ValueError):
        return (False, "Dividend payout data could not be read for this company")
    if po < 0.30:
        return (
            False,
            (
                f"Dividend payout of {po:.0%} sits below the 30% level "
                "where a dividend-discount model becomes informative"
            ),
        )

    if dividend_streak_years is None:
        return (False, "Dividend payout history length is unavailable")
    try:
        streak = int(dividend_streak_years)
    except (TypeError, ValueError):
        return (False, "Dividend payout history length could not be read")
    if streak < 5:
        return (
            False,
            (
                f"Dividend track record of {streak} years sits below the "
                "5-year streak a dividend-growth assumption is anchored to"
            ),
        )

    return (True, "applicable")


def select_and_compute(
    ticker: str,
    sector: Optional[str],
    inputs: DDMInputs,
) -> DDMResult:
    """Auto-select the right DDM variant based on sector + inputs.

    Routing heuristic:
        - sector is FMCG / utility / bank / mature IT (high-payout
          mature): Gordon single-stage.
        - sector is anything else AND high_growth is supplied:
          H-model (smooth transition is more honest than two-stage
          when there's no explicit forecast).
        - high_growth is None: Gordon (the only variant that works
          without a second growth rate).

    Two-stage is exposed publicly via two_stage_ddm() but is NOT
    routed to here. Two-stage is appropriate when there IS an
    explicit analyst forecast for years 1..N — that input is not
    available at this layer, so the auto-router never picks it.
    Callers with explicit forecasts should call two_stage_ddm()
    directly.

    Returns DDMResult with method="unavailable" only when inputs are
    too degenerate to attempt any variant.
    """
    if inputs is None:
        return DDMResult(
            fair_value=None,
            method="unavailable",
            inputs=DDMInputs(
                current_dividend=0.0,
                cost_of_equity=0.0,
                stable_growth=0.0,
            ),
            sanity_warnings=["inputs is None"],
        )

    # Defensive: if dividend or cost of equity are missing, no variant
    # will produce a number. Return early with a clear method tag.
    if (
        inputs.current_dividend is None
        or inputs.current_dividend <= 0
        or inputs.cost_of_equity is None
        or inputs.cost_of_equity <= 0
    ):
        return DDMResult(
            fair_value=None,
            method="unavailable",
            inputs=inputs,
            sanity_warnings=["dividend or cost_of_equity missing/zero"],
        )

    # Route by sector keyword.
    sector_lower = (sector or "").lower()
    is_gordon_preferred = any(
        kw in sector_lower for kw in _GORDON_PREFERRED_SECTOR_KEYWORDS
    )

    if is_gordon_preferred or inputs.high_growth is None:
        return gordon_growth(inputs)

    return h_model(inputs)


# ─────────────────────────────────────────────────────────────────
# Serialization
# ─────────────────────────────────────────────────────────────────

def to_dict(result: DDMResult) -> dict:
    """JSON-safe serialization of a DDMResult.

    Returns a flat dict suitable for embedding in an API response or
    a cache row. Inputs are nested under "inputs" to keep the FV +
    method at the top level for ergonomic consumer code.
    """
    if result is None:
        return {
            "fair_value": None,
            "method": "unavailable",
            "inputs": None,
            "sanity_warnings": ["result is None"],
        }
    inputs = result.inputs
    return {
        "fair_value": result.fair_value,
        "method": result.method,
        "inputs": {
            "current_dividend": inputs.current_dividend,
            "cost_of_equity": inputs.cost_of_equity,
            "stable_growth": inputs.stable_growth,
            "high_growth": inputs.high_growth,
            "high_growth_years": inputs.high_growth_years,
            "expected_payout_ratio": inputs.expected_payout_ratio,
        },
        "sanity_warnings": list(result.sanity_warnings),
    }
