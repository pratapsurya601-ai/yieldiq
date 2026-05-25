# backend/services/analysis/dcf_playground.py
# ═══════════════════════════════════════════════════════════════
# Reverse-DCF Playground — interactive 5-input DCF re-computation.
#
# The "killer interactive" surface from Design Manifesto v1
# (Week 2). A thin wrapper around `recompute_dcf` (operating
# margin + WACC + revenue/FCF growth + terminal growth) that
# adds tax-rate adjustment and produces a bear / base / bull
# fan-out for the slider UI.
#
# Why a separate module from recompute.py:
#   * The /recompute endpoint is "show me one alternative DCF"
#     (4 inputs, simpler payload). The playground is "drag five
#     sliders, see the fair value live + a bear/bull band + an
#     'adopt the market-implied assumptions' button" — different
#     UX, different response shape.
#   * Keeping the playground in its own module isolates the
#     slider feature from the existing sensitivity panel; the
#     two surfaces can evolve independently.
#   * Bisection helpers for the reverse-engineer surface live
#     here too (independently solves implied WACC / TG / CAGR).
#
# All math reuses recompute_dcf — no new DCF engine, no risk
# of drift from the cached canonical FV.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from typing import Optional

from backend.services.analysis.recompute import recompute_dcf

log = logging.getLogger("yieldiq.dcf_playground")

# ── Slider bounds (also enforced by Pydantic on the router) ────
WACC_MIN, WACC_MAX = 0.06, 0.15
TG_MIN, TG_MAX = 0.0, 0.07
REV_CAGR_MIN, REV_CAGR_MAX = -0.05, 0.30
OP_MARGIN_MIN, OP_MARGIN_MAX = 0.0, 0.50
TAX_RATE_MIN, TAX_RATE_MAX = 0.0, 0.50

# Bear/bull spread on each input (one-sigma pessimistic / optimistic).
# These are deliberately moderate — the UI also shows the user's own
# bear/bull range from the wider scenarios block. The fan-out band is
# meant to be "what if I'm one notch off on each input simultaneously".
_BEAR_DELTAS = {
    "wacc": +0.01,           # higher discount rate => lower FV
    "terminal_growth": -0.005,
    "revenue_cagr": -0.02,
    "operating_margin": -0.02,
    "tax_rate": +0.03,
}
_BULL_DELTAS = {
    "wacc": -0.01,
    "terminal_growth": +0.005,
    "revenue_cagr": +0.02,
    "operating_margin": +0.02,
    "tax_rate": -0.03,
}

# Assumed pre-tax baseline used to scale FCF for tax-rate moves. The
# underlying recompute_dcf does not know about tax — we apply the tax
# adjustment as a multiplicative FCF tweak before the slider goes in:
#   adj_margin = margin * (1 - tax_rate) / (1 - BASE_TAX)
# This keeps the math additive and reversible (tax_rate=BASE_TAX is a
# no-op).
BASE_TAX_RATE = 0.25


def _clamp(value: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, float(value)))


def _adjusted_margin(operating_margin: float, tax_rate: float) -> float:
    """Fold the tax-rate slider into the operating-margin slider.

    `recompute_dcf` scales FCF by (margin / current_margin), so to
    pass the tax move through cleanly we shift the margin we send it
    by the ratio of (1 - new_tax) / (1 - base_tax). Result: at the
    BASE_TAX_RATE default this is a no-op; lower tax => larger
    effective margin => higher FV.
    """
    tax_rate = _clamp(tax_rate, TAX_RATE_MIN, TAX_RATE_MAX)
    base_keep = max(0.05, 1.0 - BASE_TAX_RATE)
    new_keep = max(0.05, 1.0 - tax_rate)
    return float(operating_margin) * (new_keep / base_keep)


def run_playground_dcf(
    ticker: str,
    wacc: float,
    terminal_growth: float,
    revenue_cagr_yr1_5: float,
    operating_margin: float,
    tax_rate: float = BASE_TAX_RATE,
) -> dict:
    """Run a single playground DCF at the supplied 5 inputs.

    Returns the same shape `recompute_dcf` returns plus the inputs
    echo. Raises nothing — error states surface in the dict via the
    ``error`` key (same convention as recompute_dcf).
    """
    wacc = _clamp(wacc, WACC_MIN, WACC_MAX)
    terminal_growth = _clamp(terminal_growth, TG_MIN, TG_MAX)
    revenue_cagr_yr1_5 = _clamp(revenue_cagr_yr1_5, REV_CAGR_MIN, REV_CAGR_MAX)
    operating_margin = _clamp(operating_margin, OP_MARGIN_MIN, OP_MARGIN_MAX)
    tax_rate = _clamp(tax_rate, TAX_RATE_MIN, TAX_RATE_MAX)

    # Refuse the pathological wacc <= terminal_growth corner before
    # we hand it to the engine — the Gordon term blows up there. We
    # nudge terminal_growth down rather than failing because the UI
    # never lets the user reach this corner via the slider bounds
    # (max TG 7% vs min WACC 6%), but a programmatic caller could.
    if wacc - terminal_growth < 0.02:
        terminal_growth = max(0.0, wacc - 0.02)

    eff_margin = _adjusted_margin(operating_margin, tax_rate)
    return recompute_dcf(
        ticker=ticker,
        wacc=wacc,
        growth_5y_pct=revenue_cagr_yr1_5,
        margin_pct=eff_margin,
        terminal_growth=terminal_growth,
    )


def run_playground_with_band(
    ticker: str,
    wacc: float,
    terminal_growth: float,
    revenue_cagr_yr1_5: float,
    operating_margin: float,
    tax_rate: float = BASE_TAX_RATE,
) -> dict:
    """Run base + bear + bull DCFs around the user's slider position.

    The bear case applies a +1 sigma pessimistic delta to every input
    simultaneously; the bull case applies -1 sigma optimistic. The
    result is the "fan-out" band rendered next to the live FV.
    """
    base = run_playground_dcf(
        ticker=ticker,
        wacc=wacc,
        terminal_growth=terminal_growth,
        revenue_cagr_yr1_5=revenue_cagr_yr1_5,
        operating_margin=operating_margin,
        tax_rate=tax_rate,
    )
    if base.get("error"):
        return {
            "fair_value": 0.0,
            "bear_fv": 0.0,
            "bull_fv": 0.0,
            "current_price": 0.0,
            "inputs_echo": {
                "wacc": wacc,
                "terminal_growth": terminal_growth,
                "revenue_cagr_yr1_5": revenue_cagr_yr1_5,
                "operating_margin": operating_margin,
                "tax_rate": tax_rate,
            },
            "error": base["error"],
        }

    bear = run_playground_dcf(
        ticker=ticker,
        wacc=wacc + _BEAR_DELTAS["wacc"],
        terminal_growth=terminal_growth + _BEAR_DELTAS["terminal_growth"],
        revenue_cagr_yr1_5=revenue_cagr_yr1_5 + _BEAR_DELTAS["revenue_cagr"],
        operating_margin=operating_margin + _BEAR_DELTAS["operating_margin"],
        tax_rate=tax_rate + _BEAR_DELTAS["tax_rate"],
    )
    bull = run_playground_dcf(
        ticker=ticker,
        wacc=wacc + _BULL_DELTAS["wacc"],
        terminal_growth=terminal_growth + _BULL_DELTAS["terminal_growth"],
        revenue_cagr_yr1_5=revenue_cagr_yr1_5 + _BULL_DELTAS["revenue_cagr"],
        operating_margin=operating_margin + _BULL_DELTAS["operating_margin"],
        tax_rate=tax_rate + _BULL_DELTAS["tax_rate"],
    )

    return {
        "fair_value": float(base.get("fair_value") or 0.0),
        "bear_fv": float(bear.get("fair_value") or 0.0),
        "bull_fv": float(bull.get("fair_value") or 0.0),
        "current_price": float(base.get("current_price") or 0.0),
        "margin_of_safety": float(base.get("margin_of_safety") or 0.0),
        "verdict": base.get("verdict"),
        "inputs_echo": {
            "wacc": wacc,
            "terminal_growth": terminal_growth,
            "revenue_cagr_yr1_5": revenue_cagr_yr1_5,
            "operating_margin": operating_margin,
            "tax_rate": tax_rate,
        },
        "warnings": list(base.get("warnings") or []),
    }


# ── Reverse-engineer: bisect one input at a time ────────────────
_BISECT_MAX_ITERS = 50
_BISECT_TOL_PCT = 0.005   # 0.5% relative price tolerance


def _bisect_for_price(
    eval_fv: callable,
    target_price: float,
    lo: float,
    hi: float,
    max_iters: int = _BISECT_MAX_ITERS,
) -> tuple[float, bool]:
    """Bisect for the input x in [lo, hi] such that eval_fv(x) ≈ target_price.

    Returns (x, converged). Handles both monotonic directions by
    sampling the endpoints first. Capped at `max_iters` to respect
    the spec's 50-iteration ceiling.
    """
    try:
        f_lo = float(eval_fv(lo))
        f_hi = float(eval_fv(hi))
    except Exception:  # noqa: BLE001
        return (0.5 * (lo + hi), False)

    # If both endpoints land on the same side of target, the solver
    # can't bracket the answer. Return the closer endpoint with
    # converged=False so the caller can label the result as off-scale.
    if (f_lo - target_price) * (f_hi - target_price) > 0:
        nearer = lo if abs(f_lo - target_price) < abs(f_hi - target_price) else hi
        return (nearer, False)

    # Detect monotonic direction
    increasing = f_hi >= f_lo
    a, b = lo, hi
    mid = 0.5 * (a + b)
    for _ in range(max_iters):
        mid = 0.5 * (a + b)
        try:
            f_mid = float(eval_fv(mid))
        except Exception:  # noqa: BLE001
            return (mid, False)
        if target_price > 0 and abs(f_mid - target_price) / target_price < _BISECT_TOL_PCT:
            return (mid, True)
        if (f_mid < target_price) == increasing:
            a = mid
        else:
            b = mid
    return (mid, False)


def reverse_engineer_inputs(
    ticker: str,
    market_price: float,
    base_wacc: float,
    base_terminal_growth: float,
    base_revenue_cagr: float,
    base_operating_margin: float,
    base_tax_rate: float = BASE_TAX_RATE,
) -> dict:
    """For each of WACC / Terminal Growth / Revenue CAGR independently,
    bisect for the value that makes the playground DCF equal `market_price`,
    holding the other inputs at their base.

    Returns:
      {
        "market_price": float,
        "implied_wacc": float | None,
        "implied_terminal_growth": float | None,
        "implied_revenue_cagr": float | None,
        "iterations": dict,  # convergence flags per axis
      }
    """
    if not market_price or market_price <= 0:
        return {
            "error": "Invalid market price for reverse engineering",
            "market_price": market_price,
        }

    def fv_at_wacc(w: float) -> float:
        r = run_playground_dcf(
            ticker=ticker,
            wacc=w,
            terminal_growth=base_terminal_growth,
            revenue_cagr_yr1_5=base_revenue_cagr,
            operating_margin=base_operating_margin,
            tax_rate=base_tax_rate,
        )
        return float(r.get("fair_value") or 0.0)

    def fv_at_tg(g: float) -> float:
        # Keep WACC - TG >= 0.02
        if base_wacc - g < 0.02:
            g = max(0.0, base_wacc - 0.02)
        r = run_playground_dcf(
            ticker=ticker,
            wacc=base_wacc,
            terminal_growth=g,
            revenue_cagr_yr1_5=base_revenue_cagr,
            operating_margin=base_operating_margin,
            tax_rate=base_tax_rate,
        )
        return float(r.get("fair_value") or 0.0)

    def fv_at_cagr(c: float) -> float:
        r = run_playground_dcf(
            ticker=ticker,
            wacc=base_wacc,
            terminal_growth=base_terminal_growth,
            revenue_cagr_yr1_5=c,
            operating_margin=base_operating_margin,
            tax_rate=base_tax_rate,
        )
        return float(r.get("fair_value") or 0.0)

    implied_wacc, wacc_ok = _bisect_for_price(fv_at_wacc, market_price, WACC_MIN, WACC_MAX)
    implied_tg, tg_ok = _bisect_for_price(fv_at_tg, market_price, TG_MIN, TG_MAX)
    implied_cagr, cagr_ok = _bisect_for_price(fv_at_cagr, market_price, REV_CAGR_MIN, REV_CAGR_MAX)

    return {
        "market_price": float(market_price),
        "implied_wacc": float(implied_wacc) if wacc_ok else float(implied_wacc),
        "implied_terminal_growth": float(implied_tg) if tg_ok else float(implied_tg),
        "implied_revenue_cagr": float(implied_cagr) if cagr_ok else float(implied_cagr),
        "iterations": {
            "wacc_converged": bool(wacc_ok),
            "terminal_growth_converged": bool(tg_ok),
            "revenue_cagr_converged": bool(cagr_ok),
            "max_iters": _BISECT_MAX_ITERS,
        },
        "base_inputs": {
            "wacc": base_wacc,
            "terminal_growth": base_terminal_growth,
            "revenue_cagr_yr1_5": base_revenue_cagr,
            "operating_margin": base_operating_margin,
            "tax_rate": base_tax_rate,
        },
    }


__all__ = [
    "run_playground_dcf",
    "run_playground_with_band",
    "reverse_engineer_inputs",
    "WACC_MIN",
    "WACC_MAX",
    "TG_MIN",
    "TG_MAX",
    "REV_CAGR_MIN",
    "REV_CAGR_MAX",
    "OP_MARGIN_MIN",
    "OP_MARGIN_MAX",
    "TAX_RATE_MIN",
    "TAX_RATE_MAX",
    "BASE_TAX_RATE",
]
