# backend/services/analysis/sensitivity.py
# ═══════════════════════════════════════════════════════════════
# Sensitivity tornado — perturbs each model input ±X and measures
# the resulting fair-value change. Powers the tornado chart on the
# analysis page so users see WHICH assumption matters most for THIS
# specific stock (e.g. WACC for capital-intensive utilities, terminal
# margin for SaaS, capacity utilisation for cement).
#
# Implementation strategy: re-uses recompute_dcf for the four "real"
# DCF knobs (WACC, terminal_g, growth_5y, margin). The remaining
# three inputs (capex/sales, working-capital days, tax rate) are
# approximated by scaling the FCF base directly — recompute_dcf
# isn't parameterised on those, but their first-order effect on FV
# is a proportional FCF shift, which is good enough for a sensitivity
# ranking. For financials we map cost-of-equity → WACC, ROE → margin
# proxy, and book-growth → growth_5y. Sensitivity is a teaching tool,
# not a precision instrument — the goal is "which lever moves FV the
# most", not "exact FV at every perturbation".
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from typing import Optional

from backend.services.analysis.recompute import recompute_dcf
from backend.services.analysis.utils import _canonicalize_ticker
from backend.services.analysis.constants import (
    FINANCIAL_COMPANIES,
    _NBFC_TICKERS,
    _INSURANCE_TICKERS,
)


def _is_financial(ticker: str) -> bool:
    t = ticker.upper()
    return (
        t in FINANCIAL_COMPANIES
        or t in _NBFC_TICKERS
        or t in _INSURANCE_TICKERS
    )


def _safe(v, d=0.0) -> float:
    try:
        f = float(v)
        if f != f:
            return d
        return f
    except (TypeError, ValueError):
        return d


def _run(ticker, wacc, growth, margin, term_g) -> Optional[float]:
    """One DCF re-run; returns the FV or None on failure."""
    try:
        out = recompute_dcf(
            ticker=ticker,
            wacc=wacc,
            growth_5y_pct=growth,
            margin_pct=margin,
            terminal_growth=term_g,
        )
        if out.get("error"):
            return None
        fv = _safe(out.get("fair_value"))
        return fv if fv > 0 else None
    except Exception:
        return None


def compute_sensitivity(
    ticker: str,
    base_wacc: Optional[float] = None,
    base_growth: Optional[float] = None,
    base_margin: Optional[float] = None,
    terminal_growth: float = 0.03,
) -> dict:
    """
    Compute per-input sensitivity tornado for a ticker.

    Defaults (when callers don't pass explicit base inputs):
        wacc   = 0.12
        growth = 0.08
        margin = 0.15

    Returns:
        {
          "ticker": ...,
          "base_fair_value": float,
          "is_financial": bool,
          "sensitivities": [
              {"input": str, "delta_low": float, "delta_high": float,
               "fv_low": float, "fv_high": float, "swing_pct": float,
               "unit": "bps"|"pct"},
              ...
          ]  # sorted by swing_pct DESC
        }
    """
    ticker = _canonicalize_ticker(ticker)
    is_fin = _is_financial(ticker)

    # Clamp defaults to recompute_dcf's accepted ranges so the base
    # call doesn't get rejected by the DCF engine's bounds.
    w = max(0.05, min(0.20, _safe(base_wacc, 0.12) or 0.12))
    g = max(-0.05, min(0.30, _safe(base_growth, 0.08) or 0.08))
    m = max(0.0, min(0.60, _safe(base_margin, 0.15) or 0.15))
    tg = max(0.0, min(0.05, _safe(terminal_growth, 0.03) or 0.03))

    base_fv = _run(ticker, w, g, m, tg)
    if base_fv is None or base_fv <= 0:
        return {
            "ticker": ticker,
            "base_fair_value": 0.0,
            "is_financial": is_fin,
            "sensitivities": [],
            "error": "Base DCF unavailable for sensitivity analysis",
        }

    # ── Define perturbation grid ───────────────────────────────
    # Each entry: (label, unit, delta_low, delta_high, runner)
    # `runner(delta)` returns the FV after applying `delta` to that input.
    # delta_low/high are reported in display units (bps for rates,
    # percent-of-base for relative shifts) so the frontend can label
    # "±200 bps" or "±20 %" without re-deriving units.

    def _perturb_via_dcf(ww=w, gg=g, mm=m, ttg=tg):
        return _run(ticker, ww, gg, mm, ttg)

    # FCF-base proxy: capex/sales, WC days, and tax rate aren't
    # exposed as DCF engine knobs, but their first-order FV impact is
    # a proportional FCF shift. Scale the equivalent margin to mimic.
    # +20% capex/sales ≈ -20%*capex_share of FCF ≈ ~-3-6% FCF (varies).
    # We approximate with a margin tweak of ±0.5*pct_shift*current_margin
    # which captures the "this matters less than WACC" magnitude
    # without claiming false precision.
    def _scaled_margin(rel_shift: float) -> Optional[float]:
        # rel_shift in [-0.20, +0.20] etc; positive shift = WORSE FCF
        # (more capex / longer WC days / higher tax = lower margin).
        scaled = max(0.0, min(0.60, m * (1 - rel_shift)))
        return _perturb_via_dcf(mm=scaled)

    if not is_fin:
        # ── DCF stocks ────────────────────────────────────────
        plan = [
            {
                "input": "WACC",
                "unit": "bps",
                "delta_low": -200,
                "delta_high": +200,
                # WACC down → FV up; WACC up → FV down.
                "fn_low":  lambda: _perturb_via_dcf(ww=max(0.05, w - 0.02)),
                "fn_high": lambda: _perturb_via_dcf(ww=min(0.20, w + 0.02)),
            },
            {
                "input": "Terminal growth",
                "unit": "bps",
                "delta_low": -100,
                "delta_high": +100,
                "fn_low":  lambda: _perturb_via_dcf(ttg=max(0.0, tg - 0.01)),
                "fn_high": lambda: _perturb_via_dcf(ttg=min(0.05, tg + 0.01)),
            },
            {
                "input": "5y revenue CAGR",
                "unit": "pct",
                "delta_low": -20,
                "delta_high": +20,
                "fn_low":  lambda: _perturb_via_dcf(gg=max(-0.05, g * 0.8)),
                "fn_high": lambda: _perturb_via_dcf(gg=min(0.30, g * 1.2)),
            },
            {
                "input": "EBIT margin",
                "unit": "bps",
                "delta_low": -200,
                "delta_high": +200,
                "fn_low":  lambda: _perturb_via_dcf(mm=max(0.0, m - 0.02)),
                "fn_high": lambda: _perturb_via_dcf(mm=min(0.60, m + 0.02)),
            },
            {
                "input": "Capex / sales",
                "unit": "pct",
                "delta_low": -20,
                "delta_high": +20,
                # Higher capex → lower FCF → lower FV
                "fn_low":  lambda: _scaled_margin(-0.10),  # less capex
                "fn_high": lambda: _scaled_margin(+0.10),  # more capex (FV down)
            },
            {
                "input": "Working-capital days",
                "unit": "pct",
                "delta_low": -20,
                "delta_high": +20,
                "fn_low":  lambda: _scaled_margin(-0.05),
                "fn_high": lambda: _scaled_margin(+0.05),
            },
            {
                "input": "Tax rate",
                "unit": "bps",
                "delta_low": -200,
                "delta_high": +200,
                # +200bps tax ≈ ~2-3% drag on FCF
                "fn_low":  lambda: _scaled_margin(-0.025),
                "fn_high": lambda: _scaled_margin(+0.025),
            },
        ]
    else:
        # ── Financials (banks / NBFCs / insurers) ─────────────
        # We don't have a dedicated RI engine reachable from here,
        # so we map each bank input to its DCF analogue:
        #   Cost of equity   → WACC
        #   ROE              → margin (proxy: higher ROE = more cash to owners)
        #   Terminal book g. → terminal_growth
        #   Payout ratio     → 5y growth (higher payout = lower retention = lower g)
        plan = [
            {
                "input": "Cost of equity",
                "unit": "bps",
                "delta_low": -200,
                "delta_high": +200,
                "fn_low":  lambda: _perturb_via_dcf(ww=max(0.05, w - 0.02)),
                "fn_high": lambda: _perturb_via_dcf(ww=min(0.20, w + 0.02)),
            },
            {
                "input": "ROE",
                "unit": "bps",
                "delta_low": -200,
                "delta_high": +200,
                "fn_low":  lambda: _perturb_via_dcf(mm=max(0.0, m - 0.02)),
                "fn_high": lambda: _perturb_via_dcf(mm=min(0.60, m + 0.02)),
            },
            {
                "input": "Terminal book growth",
                "unit": "bps",
                "delta_low": -100,
                "delta_high": +100,
                "fn_low":  lambda: _perturb_via_dcf(ttg=max(0.0, tg - 0.01)),
                "fn_high": lambda: _perturb_via_dcf(ttg=min(0.05, tg + 0.01)),
            },
            {
                "input": "Payout ratio",
                "unit": "pct",
                "delta_low": -20,
                "delta_high": +20,
                # Higher payout → less retained earnings → lower book growth
                "fn_low":  lambda: _perturb_via_dcf(gg=min(0.30, g * 1.2)),
                "fn_high": lambda: _perturb_via_dcf(gg=max(-0.05, g * 0.8)),
            },
        ]

    sensitivities: list[dict] = []
    for spec in plan:
        fv_low = spec["fn_low"]()
        fv_high = spec["fn_high"]()
        if fv_low is None or fv_high is None:
            # Skip inputs we couldn't price; better to omit than to lie.
            continue
        swing = abs(fv_high - fv_low)
        swing_pct = (swing / base_fv) * 100.0 if base_fv > 0 else 0.0
        sensitivities.append({
            "input": spec["input"],
            "unit": spec["unit"],
            "delta_low": spec["delta_low"],
            "delta_high": spec["delta_high"],
            "fv_low": round(fv_low, 2),
            "fv_high": round(fv_high, 2),
            "swing_pct": round(swing_pct, 2),
        })

    sensitivities.sort(key=lambda s: s["swing_pct"], reverse=True)

    return {
        "ticker": ticker,
        "base_fair_value": round(base_fv, 2),
        "is_financial": is_fin,
        "sensitivities": sensitivities,
    }
