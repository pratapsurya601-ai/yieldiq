# backend/services/analysis/recompute.py
# ═══════════════════════════════════════════════════════════════
# Sensitivity recompute — runs a self-contained DCF using user-
# supplied WACC / FCF growth / operating-margin overrides on top
# of the cached enriched data for a ticker. Powers the interactive
# sliders on the analysis page; never mutates the canonical
# AnalysisResponse cache.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import sys
from pathlib import Path
from typing import Optional

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from screener.dcf_engine import DCFEngine, margin_of_safety, assign_signal
from data.processor import compute_metrics
from backend.services.analysis.utils import _canonicalize_ticker

FORECAST_YEARS = 10


def _safe_float(v, default: float = 0.0) -> float:
    try:
        f = float(v)
        if f != f:  # NaN
            return default
        return f
    except (TypeError, ValueError):
        return default


def _load_enriched(ticker: str) -> Optional[dict]:
    """Re-fetch enriched data via the local-DB fast path (~100ms),
    falling back to yfinance only if the local assembler returns None.
    Mirrors the data step in service._get_full_analysis_inner without
    re-running the full pipeline."""
    raw = None
    try:
        from backend.services.local_data_service import assemble_local
        from backend.services.analysis.db import _get_pipeline_session
        db = _get_pipeline_session()
        if db is not None:
            try:
                raw = assemble_local(ticker, db)
            finally:
                try:
                    db.close()
                except Exception:
                    pass
    except Exception:
        raw = None

    if raw is None:
        try:
            from data.collector import StockDataCollector
            raw = StockDataCollector(ticker).get_all()
        except Exception:
            return None

    if raw is None:
        return None

    try:
        return compute_metrics(raw)
    except Exception:
        return raw


def recompute_dcf(
    ticker: str,
    wacc: float,
    growth_5y_pct: float,
    margin_pct: float,
    forecast_years: int = FORECAST_YEARS,
    terminal_growth: float = 0.03,
) -> dict:
    """
    Run a single user-overridden DCF.

    Parameters (all decimals, NOT percentages):
        wacc            — discount rate, e.g. 0.12 for 12 %
        growth_5y_pct   — annual FCF growth applied for the first 5
                          years; tapers linearly to ``terminal_growth``
                          across years 6-N
        margin_pct      — target operating margin used to scale the
                          base FCF: new_fcf = revenue * (margin /
                          current_op_margin) * current_fcf_margin.
                          Falls back to scaling fcf by margin /
                          current_margin if op margin is missing.

    Returns a dict with the same shape as the keys inside
    ValuationOutput plus a ``scenario`` block (bear / base / bull
    tweaks of the same overrides).
    """
    ticker = _canonicalize_ticker(ticker)
    enriched = _load_enriched(ticker)
    if not enriched:
        return {"error": "Unable to load company data for recompute"}

    price = _safe_float(enriched.get("price"), 0.0)
    if price <= 0:
        return {"error": "Price unavailable for ticker"}

    shares = _safe_float(enriched.get("shares"), 0.0)
    if shares <= 0:
        return {"error": "Share count unavailable for ticker"}

    total_debt = _safe_float(enriched.get("total_debt"), 0.0)
    total_cash = _safe_float(enriched.get("total_cash"), 0.0)
    fcf_base_orig = _safe_float(enriched.get("latest_fcf"), 0.0)
    revenue = _safe_float(enriched.get("latest_revenue"), 0.0)

    # Margin scaling: prefer op_margin -> fcf_margin -> net_margin.
    # `margin_pct` is a decimal (0.20 = 20 %).
    current_margin = (
        _safe_float(enriched.get("op_margin"), 0.0)
        or _safe_float(enriched.get("operating_margin"), 0.0)
        or _safe_float(enriched.get("fcf_margin"), 0.0)
        or _safe_float(enriched.get("net_margin"), 0.0)
    )

    # If we have revenue and a sensible current margin, derive a new
    # FCF base by holding the FCF/op-margin ratio constant and moving
    # op-margin to the slider value. Otherwise scale FCF directly by
    # the margin ratio (degrades gracefully).
    if revenue > 0 and current_margin > 0.001:
        margin_ratio = max(0.0, margin_pct) / current_margin
        fcf_base = fcf_base_orig * margin_ratio
    elif current_margin > 0.001:
        margin_ratio = max(0.0, margin_pct) / current_margin
        fcf_base = fcf_base_orig * margin_ratio
    else:
        # No reference margin — leave FCF alone, slider becomes a no-op
        fcf_base = fcf_base_orig

    if fcf_base <= 0:
        # User cranked margin to zero or company is loss-making at the
        # base. Surface a soft response rather than 500ing.
        return {
            "ticker": ticker,
            "fair_value": 0.0,
            "current_price": price,
            "margin_of_safety": -100.0,
            "verdict": "avoid",
            "wacc": wacc,
            "fcf_growth_rate": growth_5y_pct,
            "operating_margin": margin_pct,
            "terminal_growth": terminal_growth,
            "warnings": ["FCF base non-positive at supplied margin"],
            "scenarios": {},
        }

    # Build a 10-year FCF projection: 5 years at growth_5y_pct,
    # then linear taper to terminal_growth across years 6-N.
    projections: list[float] = []
    last = fcf_base
    n = max(5, forecast_years)
    fade_years = max(1, n - 5)
    for i in range(n):
        if i < 5:
            g = growth_5y_pct
        else:
            # Linear fade from growth_5y_pct → terminal_growth
            t = (i - 4) / fade_years  # 1/fade .. 1.0
            g = growth_5y_pct + (terminal_growth - growth_5y_pct) * t
        last = last * (1 + g)
        projections.append(last)

    terminal_norm = float(sum(projections[-3:]) / 3)

    engine = DCFEngine(
        discount_rate=wacc,
        terminal_growth=terminal_growth,
        sector=enriched.get("sector"),
        sub_sector=enriched.get("sub_sector"),
        ticker=ticker,
    )
    dcf_res = engine.intrinsic_value_per_share(
        projected_fcfs=projections,
        terminal_fcf_norm=terminal_norm,
        total_debt=total_debt,
        total_cash=total_cash,
        shares_outstanding=shares,
        current_price=price,
        ticker=ticker,
    )
    iv = _safe_float(dcf_res.get("intrinsic_value_per_share"), 0.0)
    mos_pct = margin_of_safety(iv, price) * 100 if price > 0 else 0.0

    # Side scenarios so the panel can show bear/base/bull around the
    # user's overrides without a second roundtrip.
    def _case(growth_delta: float, wacc_delta: float) -> dict:
        cprojs: list[float] = []
        cl = fcf_base
        cg5 = growth_5y_pct + growth_delta
        cw = max(0.05, min(0.25, wacc + wacc_delta))
        for i in range(n):
            if i < 5:
                g = cg5
            else:
                t = (i - 4) / fade_years
                g = cg5 + (terminal_growth - cg5) * t
            cl = cl * (1 + g)
            cprojs.append(cl)
        ct = float(sum(cprojs[-3:]) / 3)
        ce = DCFEngine(
            discount_rate=cw,
            terminal_growth=terminal_growth,
            sector=enriched.get("sector"),
            sub_sector=enriched.get("sub_sector"),
            ticker=ticker,
        )
        cr = ce.intrinsic_value_per_share(
            projected_fcfs=cprojs,
            terminal_fcf_norm=ct,
            total_debt=total_debt,
            total_cash=total_cash,
            shares_outstanding=shares,
            current_price=price,
            ticker=ticker,
        )
        civ = _safe_float(cr.get("intrinsic_value_per_share"), 0.0)
        return {
            "iv": civ,
            "mos_pct": (margin_of_safety(civ, price) * 100) if price > 0 else 0.0,
            "growth": cg5,
            "wacc": cw,
            "term_g": terminal_growth,
        }

    scenarios = {
        "bear": _case(growth_delta=-0.03, wacc_delta=+0.01),
        "base": {
            "iv": iv,
            "mos_pct": mos_pct,
            "growth": growth_5y_pct,
            "wacc": wacc,
            "term_g": terminal_growth,
        },
        "bull": _case(growth_delta=+0.03, wacc_delta=-0.01),
    }

    try:
        verdict = assign_signal(mos_pct / 100)
    except Exception:
        verdict = (
            "undervalued" if mos_pct >= 20
            else "fairly_valued" if mos_pct >= -10
            else "overvalued"
        )

    return {
        "ticker": ticker,
        "fair_value": iv,
        "current_price": price,
        "margin_of_safety": mos_pct,
        "verdict": verdict,
        "wacc": wacc,
        "fcf_growth_rate": growth_5y_pct,
        "operating_margin": margin_pct,
        "terminal_growth": terminal_growth,
        "bear_case": scenarios["bear"]["iv"],
        "base_case": scenarios["base"]["iv"],
        "bull_case": scenarios["bull"]["iv"],
        "scenarios": scenarios,
        "warnings": dcf_res.get("warnings", []),
    }
