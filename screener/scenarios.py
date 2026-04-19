# ═══════════════════════════════════════════════════════════════
# THREE SCENARIO DCF — Bear / Base / Bull Case
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
import pandas as pd
from screener.dcf_engine import DCFEngine, margin_of_safety
from models.forecaster import _exponential_fade, _clamp, TERMINAL_FADE_G
from utils.config import FORECAST_YEARS
from utils.logger import get_logger

log = get_logger(__name__)

SCENARIOS = {
    "Bear 🐻": {
        "growth_adj":    -0.06,
        "wacc_adj":      +0.015,
        "terminal_adj":  -0.010,
        "pe_scenario":   "bear",
        "color":         "#ef4444",
        "desc":          "Pessimistic: lower growth, higher discount rate, lower terminal",
    },
    "Base 📊": {
        "growth_adj":     0.00,
        "wacc_adj":       0.00,
        "terminal_adj":   0.00,
        "pe_scenario":    "base",
        "color":          "#3b82f6",
        "desc":           "Base case: model's central estimate",
    },
    "Bull 🐂": {
        # FIX3: bumped from (+0.04 / -0.01 / +0.005) to (+0.06 / -0.015 / +0.010).
        # Old values produced Bull within ~1% of Base because (a) +4pp growth
        # fades quickly toward 4% terminal under _exponential_fade, (b) -100bps
        # WACC and +50bps terminal moved the dominant terminal-value bucket
        # only ~5%. With WACC and terminal-g being the heaviest levers in a
        # 10y DCF, widening those produces a sensible 20-40% Bull-vs-Base
        # spread on representative IT large-caps (TCS/INFY/HCLTECH).
        "growth_adj":    +0.06,
        "wacc_adj":      -0.015,
        "terminal_adj":  +0.010,
        "pe_scenario":   "bull",
        "color":         "#10b981",
        "desc":          "Optimistic: higher growth, lower discount rate, higher terminal",
    },
}


def run_scenarios(
    enriched:        dict,
    fcf_base:        float,
    base_growth:     float,
    base_wacc:       float,
    base_terminal_g: float,
    total_debt:      float,
    total_cash:      float,
    shares:          float,
    current_price:   float,
    years:           int = FORECAST_YEARS,
) -> dict:
    results = {}

    # Pre-compute PE blend inputs once — same for all scenarios
    pe_iv_base = pe_iv_bear = pe_iv_bull = 0.0
    pe_weight  = 0.0
    try:
        from screener.valuation_crosscheck import (
            compute_pe_based_iv, blend_dcf_pe, get_eps, SECTOR_PE_WEIGHT
        )
        sector    = enriched.get("sector", "general")
        eps       = get_eps(enriched)
        rev_growth = enriched.get("revenue_growth", None)
        reliable  = enriched.get("dcf_reliable", True)
        pe_weight = SECTOR_PE_WEIGHT.get(sector, 0.35)

        if eps > 0 and reliable:
            pe_iv_base = compute_pe_based_iv(eps, sector, "base",  rev_growth)
            pe_iv_bear = compute_pe_based_iv(eps, sector, "bear",  rev_growth)
            pe_iv_bull = compute_pe_based_iv(eps, sector, "bull",  rev_growth)
    except Exception as _e:
        log.debug(f"PE blend unavailable in scenarios: {_e}")

    for name, params in SCENARIOS.items():
        growth  = _clamp(base_growth     + params["growth_adj"])
        wacc    = float(np.clip(base_wacc     + params["wacc_adj"],     0.07, 0.22))
        term_g  = float(np.clip(base_terminal_g + params["terminal_adj"], 0.01, 0.05))
        if wacc <= term_g:
            term_g = wacc - 0.02

        projections = []
        fcf = fcf_base
        for yr in range(1, years + 1):
            g = _clamp(_exponential_fade(yr, growth, TERMINAL_FADE_G))
            fcf = fcf * (1 + g)
            projections.append(fcf)

        terminal_norm = float(np.mean(projections[-3:]))

        engine  = DCFEngine(discount_rate=wacc, terminal_growth=term_g)
        dcf_res = engine.intrinsic_value_per_share(
            projected_fcfs=projections,
            terminal_fcf_norm=terminal_norm,
            total_debt=total_debt,
            total_cash=total_cash,
            shares_outstanding=shares,
            current_price=current_price * 10,
        )

        dcf_iv = dcf_res.get("intrinsic_value_per_share", 0)

        # Apply PE blend
        pe_scenario = params["pe_scenario"]
        pe_iv = {"base": pe_iv_base, "bear": pe_iv_bear, "bull": pe_iv_bull}.get(pe_scenario, 0.0)

        if pe_iv > 0 and dcf_iv > 0 and pe_weight > 0:
            iv = pe_weight * pe_iv + (1 - pe_weight) * dcf_iv
        elif pe_iv > 0 and dcf_iv <= 0:
            iv = pe_iv
        else:
            iv = dcf_iv

        iv  = max(iv, 0.0)   # floor at 0 — never show negative IV
        mos = margin_of_safety(iv, current_price)

        results[name] = {
            "iv":          iv,
            "mos":         mos,
            "mos_pct":     mos * 100,
            "growth":      growth,
            "wacc":        wacc,
            "term_g":      term_g,
            "projections": projections,
            "color":       params["color"],
            "desc":        params["desc"],
        }

    # Enforce ordering: Bull >= Base >= Bear
    _keys = list(results.keys())
    _bear_key = [k for k in _keys if "Bear" in k or "bear" in k]
    _base_key = [k for k in _keys if "Base" in k or "base" in k]
    _bull_key = [k for k in _keys if "Bull" in k or "bull" in k]
    if _bear_key and _base_key and _bull_key:
        _bk, _mk, _uk = _bear_key[0], _base_key[0], _bull_key[0]
        ivs = sorted([results[_bk]["iv"], results[_mk]["iv"], results[_uk]["iv"]])
        results[_bk]["iv"] = ivs[0]
        results[_bk]["mos_pct"] = margin_of_safety(ivs[0], current_price) * 100
        results[_mk]["iv"] = ivs[1]
        results[_mk]["mos_pct"] = margin_of_safety(ivs[1], current_price) * 100
        results[_uk]["iv"] = ivs[2]
        results[_uk]["mos_pct"] = margin_of_safety(ivs[2], current_price) * 100

    return results
