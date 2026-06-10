# backend/services/apv_service.py
"""Adjusted Present Value (APV) standalone service — Stewart Myers framework.

═══════════════════════════════════════════════════════════════
What this is
═══════════════════════════════════════════════════════════════

Stewart Myers's Adjusted Present Value (1974, JFE). The textbook
alternative to WACC-based DCF for businesses whose capital structure
will change materially over the forecast horizon — LBO targets,
deleveraging stories, capital-intensive cyclicals at the inflection,
project finance vehicles, etc.

Standard DCF discounts unlevered FCF at WACC. WACC bakes in the
ASSUMPTION that the capital structure stays at a constant target
weight (D/V, E/V) forever. When the financing mix is moving —
because debt is being paid down, because a bond ladder matures into
a known schedule, because an LBO sponsor will refinance — that
single discount rate is wrong, and the resulting NPV is biased.

APV breaks the problem in three pieces and prices each on its own
discount rate, then sums:

    APV = Unlevered Value (all-equity NPV)
        + PV(Tax Shield from interest)
        - PV(Expected Distress Costs)

Where:
  * Unlevered value = NPV of free cash flow discounted at the
    UNLEVERED cost of equity (k_u = rf + asset_beta × ERP — Hamada
    unlevered, no tax-shield contamination)
  * Tax shield = (debt × interest_rate × tax_rate) per year,
    discounted at the cost of debt (because the shield is exactly
    as risky as the interest payment it depends on)
  * Distress costs = probability-weighted dead-weight cost of
    bankruptcy / restructuring; per Andrade & Kaplan (1998), the
    direct + indirect cost is ~10-30% of pre-distress firm value,
    so we expose both as caller inputs

═══════════════════════════════════════════════════════════════
Phase A scope (T2.6)
═══════════════════════════════════════════════════════════════

This module ships the standalone service only. No wiring into the
composite valuation engine, no router exposure, no UI surface.
Phase B (separate PR) wires conditional surfacing for high-D/E
names where the tax shield is a material chunk of EV and standard
WACC-DCF is materially distorted.

The caller is responsible for:
  * Building the FCF forecast (we accept either a forward forecast
    or a history that we project forward at ``fcf_growth_explicit``)
  * Building the debt schedule (year-by-year debt outstanding over
    the horizon — this is the WHOLE point of APV; if you don't have
    a schedule, you don't need APV, use WACC-DCF)
  * Unlevering equity beta to asset beta BEFORE calling (Hamada:
    β_a = β_e / (1 + (1 - t) × D/E)) — we do NOT do the unlevering
    here because the caller has the leverage context
  * Asking ``is_apv_applicable`` BEFORE calling ``compute_apv``

═══════════════════════════════════════════════════════════════
When NOT to use APV
═══════════════════════════════════════════════════════════════

APV is a niche tool. For the typical YieldIQ universe — listed
Indian large/mid-caps with stable capital structure — standard
WACC-DCF is the right primary anchor. APV adds noise without
adding signal when:

  * D/E is low and stable (most listed equities)
  * The forecast horizon doesn't span any material refinancing or
    deleveraging event
  * Tax shield is a small fraction of EV (< ~5%)
  * The business is too early-stage or volatile to forecast FCF
    out 5+ years with any honesty

APV is most informative for:
  * LBO targets (debt-to-EBITDA > 4x at entry, deleveraging fast)
  * Capital-intensive cyclicals at deleveraging inflection points
    (steel, cement, real estate after a debt-funded build cycle)
  * Project finance vehicles with known repayment schedules
  * Telecom / infrastructure post a major spectrum / capex round
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Optional

logger = logging.getLogger("yieldiq.apv")


# ═══════════════════════════════════════════════════════════════
# Tunable constants
# ═══════════════════════════════════════════════════════════════

# Forecast-horizon sanity bounds. Less than 3 years cannot meaningfully
# capture a capital-structure transition; more than 15 is fantasy.
_MIN_FORECAST_YEARS = 3
_MAX_FORECAST_YEARS = 15

# Unlevered cost of equity sanity envelope. < 4% is below risk-free
# in any sensible regime; > 30% suggests a percent-vs-decimal mix-up.
_K_U_FLOOR = 0.04
_K_U_CEILING = 0.30

# Cost of debt envelope. Below the risk-free rate is suspicious; above
# 25% suggests distress-pricing rather than a normal coupon.
_K_D_FLOOR = 0.02
_K_D_CEILING = 0.25

# Tax rate clamps — Indian effective corporate rate is ~25%; values
# above 40% are almost certainly a percent-vs-decimal mix-up.
_TAX_FLOOR = 0.0
_TAX_CEILING = 0.40

# Probability of distress: 0 disables the distress term entirely
# (yielding "apv_no_distress"). Above 50% the whole framework is
# probably the wrong tool (use a restructuring / liquidation model).
_DISTRESS_PROB_FLOOR = 0.0
_DISTRESS_PROB_CEILING = 0.50

# Cost of distress as a % of pre-distress firm value. Andrade & Kaplan
# (1998) document 10-23% direct + indirect for HLT firms; some studies
# go as high as 30%. Floor at 0 (= no distress cost), ceiling at 60%
# (catastrophic indirect-cost regime; rare).
_DISTRESS_COST_FLOOR = 0.0
_DISTRESS_COST_CEILING = 0.60

# Terminal growth clamp. Must be below the unlevered discount rate
# (no Gordon-divergence) and below long-run nominal GDP (no perpetual
# super-growth). Hard ceiling at 6% for INR rates as of 2026.
_TERMINAL_G_FLOOR = -0.02
_TERMINAL_G_CEILING = 0.06

# Sanity-warning thresholds (informational; do not fail the call).
_ASSET_BETA_HIGH_WARN = 1.5
_DISTRESS_PROB_HIGH_WARN = 0.20
_TAX_SHIELD_HEAVY_WARN = 0.30
_TERMINAL_HEAVY_WARN = 0.80


# ═══════════════════════════════════════════════════════════════
# Public dataclasses
# ═══════════════════════════════════════════════════════════════

@dataclass
class APVInputs:
    """Caller-supplied inputs for one APV computation.

    Conventions:
      * All currency figures in the SAME unit (INR crore is typical
        for YieldIQ) — we don't unit-convert.
      * ``fcf_history_or_forecast`` may be EITHER:
          - A pure forward forecast (length == forecast_years) — we
            use it verbatim; ``fcf_growth_explicit`` is ignored.
          - A history (most-recent last); we extend forward by
            applying ``fcf_growth_explicit`` year-on-year for
            ``forecast_years`` years off the last historical value.
      * ``debt_schedule_inr_cr`` must have length == forecast_years
        and represents debt OUTSTANDING at each year-end (the
        balance the interest is accruing against during that year).
    """
    # FCF projection
    fcf_history_or_forecast: list[float]
    forecast_years: int = 5
    fcf_growth_explicit: float = 0.10
    terminal_growth: float = 0.04

    # Capital structure (changing over horizon)
    debt_schedule_inr_cr: list[float] = field(default_factory=list)
    interest_rate: float = 0.08
    tax_rate: float = 0.25

    # Unlevered cost of equity (asset-beta derived)
    risk_free_rate: float = 0.071
    equity_risk_premium: float = 0.075
    asset_beta: float = 0.85

    # Distress
    probability_of_distress: float = 0.05
    distress_cost_pct_of_firm_value: float = 0.30

    # Output normalizers
    shares_outstanding: float = 0.0
    net_debt_today: float = 0.0


@dataclass
class APVResult:
    """Output of one APV computation.

    ``method``:
      * ``"apv_full"`` — standard path with all three components
        (unlevered value + tax shield − distress cost).
      * ``"apv_no_distress"`` — caller set
        ``probability_of_distress = 0`` (or the input rounded to
        zero). Distress term is exactly 0; tax shield is still
        priced. Use this for clean LBO walk-throughs where the
        sponsor's downside model lives elsewhere.
      * ``"unavailable"`` — inputs failed validation. Per-share and
        EV fields are None; ``components.reason`` carries the
        machine-readable cause.
    """
    apv_per_share: Optional[float]
    enterprise_value_apv: Optional[float]
    components: dict = field(default_factory=dict)
    method: str = "unavailable"
    sanity_warnings: list[str] = field(default_factory=list)


# ═══════════════════════════════════════════════════════════════
# Internal helpers
# ═══════════════════════════════════════════════════════════════

def _is_finite(x) -> bool:
    """True if x is a finite number (sign-agnostic)."""
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _is_finite_positive(x) -> bool:
    """True if x is a finite number > 0."""
    try:
        return math.isfinite(float(x)) and float(x) > 0.0
    except (TypeError, ValueError):
        return False


def _clamp(x: float, lo: float, hi: float, default: float) -> float:
    """Bound x to [lo, hi]; fall back to ``default`` on non-finite."""
    if not _is_finite(x):
        return default
    return max(lo, min(hi, float(x)))


def _normalize_sector(s: Optional[str]) -> str:
    return (s or "").strip().lower()


# ═══════════════════════════════════════════════════════════════
# Public API — computational primitives
# ═══════════════════════════════════════════════════════════════

def compute_unlevered_cost_of_equity(
    risk_free: float,
    erp: float,
    asset_beta: float,
) -> float:
    """k_unlevered = risk_free + asset_beta × ERP.

    This is the CAPM applied to the ASSET beta (financial leverage
    stripped out) rather than the equity beta. The whole point of
    APV is to discount unlevered FCF at this rate — the tax-shield
    benefit is priced SEPARATELY rather than baked into a WACC.

    Returns the rate as a decimal (0.115 == 11.5%). The caller is
    responsible for ensuring inputs are decimals (not percents); we
    don't second-guess units here.
    """
    rf = float(risk_free) if _is_finite(risk_free) else 0.0
    e = float(erp) if _is_finite(erp) else 0.0
    b = float(asset_beta) if _is_finite(asset_beta) else 0.0
    return rf + b * e


def compute_tax_shield_pv(
    debt_schedule: list[float],
    interest_rate: float,
    tax_rate: float,
    discount_rate: float,
) -> float:
    """PV of (debt × interest_rate × tax_rate) each year, discounted
    at the COST OF DEBT.

    Why cost of debt as the discount rate?
      The interest tax shield is exactly as risky as the interest
      payment that produces it — if the firm can pay coupon, it gets
      the shield; if it can't, neither happens. Pricing the shield
      at a rate higher than the cost of debt (e.g. WACC, or k_u)
      systematically understates its value.

    Convention:
      ``debt_schedule[i]`` is the debt outstanding during year i+1
      (i.e. the principal the interest accrues against). The shield
      generated in year i+1 is discounted by (1 + discount_rate)^(i+1).
      Year-0 (the present) is NOT included in the schedule — the
      caller picks the horizon start.

    Defensive:
      * Empty / None schedule → 0.0 (no debt, no shield).
      * Non-finite or negative debt entries → contribute 0 for that
        year (we don't credit phantom shields, and negative debt
        doesn't generate a shield either).
      * Discount rate clamped to a sane envelope; out-of-range
        inputs are treated as the floor.
    """
    if not debt_schedule:
        return 0.0
    k_d = _clamp(discount_rate, _K_D_FLOOR, _K_D_CEILING, _K_D_FLOOR)
    i = _clamp(interest_rate, _K_D_FLOOR, _K_D_CEILING, _K_D_FLOOR)
    t = _clamp(tax_rate, _TAX_FLOOR, _TAX_CEILING, 0.25)
    pv = 0.0
    for year_idx, debt in enumerate(debt_schedule, start=1):
        if not _is_finite(debt) or float(debt) <= 0.0:
            continue
        shield = float(debt) * i * t
        pv += shield / ((1.0 + k_d) ** year_idx)
    return pv


def compute_unlevered_npv(
    fcf_forecast: list[float],
    terminal_growth: float,
    discount_rate: float,
) -> float:
    """Standard NPV of FCF + Gordon perpetuity terminal value.

    Discount rate is the UNLEVERED cost of equity (k_u). Terminal
    value uses the Gordon model on the year-N+1 FCF:

        TV_N = FCF_{N+1} / (k_u - g) = FCF_N × (1+g) / (k_u - g)
        PV(TV) = TV_N / (1 + k_u)^N
        APV_explicit = sum_{t=1..N} FCF_t / (1+k_u)^t
        Unlevered NPV = APV_explicit + PV(TV)

    Defensive contract:
      * Empty forecast → 0.0.
      * Terminal growth ≥ discount rate → terminal collapses to 0
        (we refuse to divide by ≤ 0; the caller's growth assumption
        was incoherent).
      * Non-finite FCF entries treated as 0 for that year.
    """
    if not fcf_forecast:
        return 0.0
    k = _clamp(discount_rate, _K_U_FLOOR, _K_U_CEILING, _K_U_FLOOR)
    g = _clamp(terminal_growth, _TERMINAL_G_FLOOR, _TERMINAL_G_CEILING, 0.0)

    explicit_pv = 0.0
    last_finite_fcf = 0.0
    for year_idx, fcf in enumerate(fcf_forecast, start=1):
        if not _is_finite(fcf):
            continue
        cf = float(fcf)
        explicit_pv += cf / ((1.0 + k) ** year_idx)
        last_finite_fcf = cf

    n = len(fcf_forecast)
    if g >= k:
        # Incoherent — terminal would explode or invert. Drop it.
        terminal_pv = 0.0
    elif last_finite_fcf <= 0.0:
        # No positive run-rate to perpetuate.
        terminal_pv = 0.0
    else:
        tv_at_n = last_finite_fcf * (1.0 + g) / (k - g)
        terminal_pv = tv_at_n / ((1.0 + k) ** n)
    return explicit_pv + terminal_pv


# ═══════════════════════════════════════════════════════════════
# Public API — main entry point
# ═══════════════════════════════════════════════════════════════

def _build_fcf_forecast(inputs: APVInputs) -> list[float]:
    """Resolve ``fcf_history_or_forecast`` to a forward forecast.

    If the caller already supplied a forward forecast of the right
    length, use it verbatim. Otherwise extend the last historical
    FCF by ``fcf_growth_explicit`` for ``forecast_years`` years.
    """
    hist = list(inputs.fcf_history_or_forecast or [])
    n = inputs.forecast_years
    if not hist:
        return []
    if len(hist) == n:
        # Treat as a forward forecast already.
        return [float(x) if _is_finite(x) else 0.0 for x in hist]
    # Otherwise: project forward off the last historical FCF.
    last = None
    for x in reversed(hist):
        if _is_finite(x):
            last = float(x)
            break
    if last is None:
        return []
    g = float(inputs.fcf_growth_explicit) if _is_finite(inputs.fcf_growth_explicit) else 0.0
    forecast = []
    cur = last
    for _ in range(n):
        cur = cur * (1.0 + g)
        forecast.append(cur)
    return forecast


def compute_apv(inputs: APVInputs) -> APVResult:
    """Compute Adjusted Present Value for one ticker.

    Returns an ``APVResult`` with ``method = "unavailable"`` and
    None per-share / EV when inputs fail validation. The caller
    should treat a None per-share as "APV row hidden", NOT "APV = 0".

    Validation gates (all return method="unavailable"):
      * Forecast years outside [_MIN_FORECAST_YEARS, _MAX_FORECAST_YEARS]
      * Empty / unresolvable FCF input
      * Debt schedule length mismatch with forecast_years (when
        schedule is non-empty)
      * Unlevered k_u outside [_K_U_FLOOR, _K_U_CEILING] after clamp
        of the asset_beta-derived rate

    Sanity warnings (informational; do NOT fail):
      * asset_beta > 1.5 → high systematic risk
      * probability_of_distress > 0.20 → distress case may dominate
      * tax_shield_pv > 30% of EV → leverage-heavy, APV is the right
        tool here (this is a "you're using the right tool" tag, not
        a problem)
      * terminal_pv > 80% of EV → most of value is in the perpetual;
        sanity-check terminal_growth
    """
    warnings: list[str] = []

    # ── Forecast horizon gate ───────────────────────────────────
    n = int(inputs.forecast_years) if _is_finite(inputs.forecast_years) else 0
    if n < _MIN_FORECAST_YEARS or n > _MAX_FORECAST_YEARS:
        return APVResult(
            apv_per_share=None,
            enterprise_value_apv=None,
            components={
                "reason": "forecast_years_out_of_range",
                "forecast_years": n,
            },
            method="unavailable",
            sanity_warnings=[
                f"forecast_years {n} outside [{_MIN_FORECAST_YEARS}, "
                f"{_MAX_FORECAST_YEARS}]"
            ],
        )

    # ── FCF resolution gate ─────────────────────────────────────
    fcf_forecast = _build_fcf_forecast(inputs)
    if not fcf_forecast:
        return APVResult(
            apv_per_share=None,
            enterprise_value_apv=None,
            components={"reason": "fcf_forecast_unresolvable"},
            method="unavailable",
            sanity_warnings=["fcf_history_or_forecast empty or non-finite"],
        )

    # ── Debt schedule shape gate ────────────────────────────────
    debt_schedule = list(inputs.debt_schedule_inr_cr or [])
    if debt_schedule and len(debt_schedule) != n:
        return APVResult(
            apv_per_share=None,
            enterprise_value_apv=None,
            components={
                "reason": "debt_schedule_length_mismatch",
                "debt_schedule_len": len(debt_schedule),
                "forecast_years": n,
            },
            method="unavailable",
            sanity_warnings=[
                f"debt_schedule length {len(debt_schedule)} != "
                f"forecast_years {n}"
            ],
        )

    # ── Unlevered cost of equity ────────────────────────────────
    k_u = compute_unlevered_cost_of_equity(
        risk_free=inputs.risk_free_rate,
        erp=inputs.equity_risk_premium,
        asset_beta=inputs.asset_beta,
    )
    if k_u < _K_U_FLOOR or k_u > _K_U_CEILING:
        return APVResult(
            apv_per_share=None,
            enterprise_value_apv=None,
            components={
                "reason": "unlevered_cost_of_equity_out_of_range",
                "k_unlevered": k_u,
            },
            method="unavailable",
            sanity_warnings=[
                f"k_unlevered {k_u} outside [{_K_U_FLOOR}, {_K_U_CEILING}]"
            ],
        )

    # ── Unlevered NPV (all-equity DCF) ──────────────────────────
    unlevered_value = compute_unlevered_npv(
        fcf_forecast=fcf_forecast,
        terminal_growth=inputs.terminal_growth,
        discount_rate=k_u,
    )

    # Also compute the terminal-only piece for sanity warnings.
    g_clamped = _clamp(inputs.terminal_growth, _TERMINAL_G_FLOOR, _TERMINAL_G_CEILING, 0.0)
    last_fcf = fcf_forecast[-1] if fcf_forecast else 0.0
    if g_clamped >= k_u or last_fcf <= 0.0:
        terminal_pv_component = 0.0
    else:
        tv_at_n = last_fcf * (1.0 + g_clamped) / (k_u - g_clamped)
        terminal_pv_component = tv_at_n / ((1.0 + k_u) ** n)

    # ── Tax shield PV ───────────────────────────────────────────
    tax_shield_pv = compute_tax_shield_pv(
        debt_schedule=debt_schedule,
        interest_rate=inputs.interest_rate,
        tax_rate=inputs.tax_rate,
        discount_rate=inputs.interest_rate,
    )

    # ── Distress cost ───────────────────────────────────────────
    prob = _clamp(
        inputs.probability_of_distress,
        _DISTRESS_PROB_FLOOR,
        _DISTRESS_PROB_CEILING,
        0.0,
    )
    cost_pct = _clamp(
        inputs.distress_cost_pct_of_firm_value,
        _DISTRESS_COST_FLOOR,
        _DISTRESS_COST_CEILING,
        0.0,
    )
    # Distress cost is the probability-weighted dead-weight loss
    # against the levered firm value (= unlevered + tax shield, the
    # value at risk before distress is realized).
    pre_distress_value = unlevered_value + tax_shield_pv
    if prob <= 0.0 or cost_pct <= 0.0 or pre_distress_value <= 0.0:
        distress_cost_pv = 0.0
        method = "apv_no_distress"
    else:
        distress_cost_pv = prob * cost_pct * pre_distress_value
        method = "apv_full"

    # ── Enterprise value ────────────────────────────────────────
    enterprise_value = unlevered_value + tax_shield_pv - distress_cost_pv

    # ── Sanity warnings ─────────────────────────────────────────
    if _is_finite(inputs.asset_beta) and float(inputs.asset_beta) > _ASSET_BETA_HIGH_WARN:
        warnings.append(
            f"asset_beta {float(inputs.asset_beta):.2f} > "
            f"{_ASSET_BETA_HIGH_WARN}: high systematic risk"
        )
    if prob > _DISTRESS_PROB_HIGH_WARN:
        warnings.append(
            f"probability_of_distress {prob:.2f} > "
            f"{_DISTRESS_PROB_HIGH_WARN}: distress case may dominate; "
            "consider whether a restructuring model is more appropriate"
        )
    if enterprise_value > 0.0:
        shield_share = tax_shield_pv / enterprise_value if enterprise_value else 0.0
        if shield_share > _TAX_SHIELD_HEAVY_WARN:
            warnings.append(
                f"tax_shield is {shield_share * 100:.1f}% of EV "
                f"(> {int(_TAX_SHIELD_HEAVY_WARN * 100)}%): leverage-heavy "
                "name, APV is especially appropriate here"
            )
        terminal_share = terminal_pv_component / enterprise_value if enterprise_value else 0.0
        if terminal_share > _TERMINAL_HEAVY_WARN:
            warnings.append(
                f"terminal value is {terminal_share * 100:.1f}% of EV "
                f"(> {int(_TERMINAL_HEAVY_WARN * 100)}%): re-check "
                "terminal_growth assumption"
            )

    # ── Equity bridge ───────────────────────────────────────────
    shares = float(inputs.shares_outstanding) if _is_finite(inputs.shares_outstanding) else 0.0
    net_debt = float(inputs.net_debt_today) if _is_finite(inputs.net_debt_today) else 0.0
    equity_value = enterprise_value - net_debt
    apv_per_share: Optional[float]
    if shares > 0.0:
        apv_per_share = equity_value / shares
    else:
        apv_per_share = None

    components = {
        "unlevered_value": unlevered_value,
        "tax_shield_pv": tax_shield_pv,
        "distress_cost_pv": distress_cost_pv,
        "terminal_value_pv": terminal_pv_component,
        "enterprise_value": enterprise_value,
        "equity_value": equity_value,
        "k_unlevered": k_u,
        "cost_of_debt": _clamp(inputs.interest_rate, _K_D_FLOOR, _K_D_CEILING, _K_D_FLOOR),
        "tax_rate": _clamp(inputs.tax_rate, _TAX_FLOOR, _TAX_CEILING, 0.25),
        "terminal_growth": g_clamped,
        "probability_of_distress": prob,
        "distress_cost_pct": cost_pct,
        "fcf_forecast": fcf_forecast,
        "debt_schedule": debt_schedule,
        "forecast_years": n,
        "shares_outstanding": shares,
        "net_debt_today": net_debt,
    }

    return APVResult(
        apv_per_share=apv_per_share,
        enterprise_value_apv=enterprise_value,
        components=components,
        method=method,
        sanity_warnings=warnings,
    )


# ═══════════════════════════════════════════════════════════════
# Public API — applicability gate
# ═══════════════════════════════════════════════════════════════

# Sectors where leverage stories are common enough that APV often
# materially out-performs WACC-DCF. NOT an exclusion list — these
# are the sectors where the caller should bias TOWARD turning APV
# on; for everything else, WACC-DCF is the default.
_APV_FRIENDLY_SECTORS = frozenset({
    "real estate", "realty", "real_estate",
    "infrastructure", "construction",
    "power", "power generation", "power utility",
    "telecom", "telecommunications",
    "metals", "metals & mining", "steel", "cement",
    "shipping", "ports",
})


def is_apv_applicable(
    ticker: str,
    sector: Optional[str],
    debt_to_equity_changing: bool,
    is_leveraged: bool,
) -> tuple[bool, str]:
    """Gate: should APV be computed for this name?

    Returns (applicable, reason). When applicable is False the
    ``reason`` string is human-readable and intended to be surfaced
    on the analysis page ("APV not applicable: <reason>").

    APV is most informative when:
      * Capital structure changes materially over the forecast
        horizon (LBO, deleveraging, post-refinancing).
      * High leverage (D/E > 1.0).
      * Tax shield is a meaningful portion of value.

    For the typical YIQ universe (mostly listed Indian large/mid-caps
    with stable capital structure), standard WACC-DCF is fine. APV
    is a niche tool — surfaces when leverage stories are involved.

    Sectors where APV often helps: real estate (high leverage),
    infrastructure, capital-intensive cyclicals at deleveraging
    points.

    The decision rule:
      * If debt_to_equity_changing AND is_leveraged → applicable.
        (Both conditions: changing structure AND material leverage.
        Either alone is not enough — a stable highly-leveraged firm
        is fine with WACC-DCF; a low-leverage firm whose structure
        is shifting trivially won't move the valuation either way.)
      * Else if the sector is in the APV-friendly set AND
        is_leveraged → applicable. (Sector hint catches the case
        where the caller hasn't computed the "changing" flag but
        the cohort is known to be a leverage-story cohort.)
      * Else → not applicable; reason explains which gate failed.
    """
    sec = _normalize_sector(sector)

    if debt_to_equity_changing and is_leveraged:
        return True, "ok (capital structure shifting on a leveraged firm)"

    if sec in _APV_FRIENDLY_SECTORS and is_leveraged:
        return True, f"ok (leverage-story sector: {sec})"

    if not is_leveraged:
        return False, "low leverage — WACC-DCF is sufficient"
    if not debt_to_equity_changing:
        return False, (
            "capital structure stable — WACC-DCF is sufficient "
            "(APV only adds signal when D/E is shifting)"
        )
    return False, "APV not indicated for this profile"


# ═══════════════════════════════════════════════════════════════
# Serialisation
# ═══════════════════════════════════════════════════════════════

def to_dict(result: APVResult) -> dict:
    """JSON-safe projection of an APVResult.

    All numeric fields stay as Python floats / ints / None; the
    caller can let pydantic / json.dumps round-trip them.
    """
    return {
        "apv_per_share": result.apv_per_share,
        "enterprise_value_apv": result.enterprise_value_apv,
        "components": dict(result.components or {}),
        "method": result.method,
        "sanity_warnings": list(result.sanity_warnings or []),
    }
