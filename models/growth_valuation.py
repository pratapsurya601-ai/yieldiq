"""
Growth-stock valuation path -- reverse P/S-multiple for pre-profit companies.

The standard DCF in dcf_engine.py produces 0 or garbage for companies
with negative FCF (ETERNAL/Zomato, PAYTM, NYKAA, POLICYBZR, JSWSTEEL in
down-cycle, etc.). The output sanity gate then masks these as
'data_limited', which is honest but unhelpful for users who still want
a directional view on a loss-making growth stock.

This module provides an alternative valuation that doesn't require
positive FCF. Core idea: REVERSE the P/S multiple.

  Given: current_revenue, market_cap, terminal_ps, discount_rate, years
  Solve: the revenue CAGR that justifies today's market cap if the
         stock re-rates to `terminal_ps` at year `years`.

Then compare implied CAGR to the company's trailing revenue CAGR. If
implied is <= 1.2x actual -> fairly valued. Way above -> overvalued.

Not investment advice. SEBI-safe: reports 'implied vs actual' as a
descriptive model output, not a recommendation.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("yieldiq.growth_valuation")


SECTOR_TERMINAL_PS: dict[str, float] = {
    "internet":          6.0,
    "e-commerce":        3.0,
    "fintech":           4.0,
    "insurance_tech":    3.5,
    "foodtech":          3.0,
    "saas":              6.0,
    "media":             3.0,
    "retail":            1.5,
    "consumer":          4.0,
    "it_services":       5.0,
    "general":           3.5,
}

DISCOUNT_RATE = 0.12
FORECAST_YEARS = 10


def _reverse_ps_implied_growth(
    market_cap: float,
    current_revenue: float,
    terminal_ps: float,
    discount_rate: float = DISCOUNT_RATE,
    years: int = FORECAST_YEARS,
) -> float | None:
    if current_revenue <= 0 or market_cap <= 0 or terminal_ps <= 0:
        return None
    target_revenue_N = market_cap * ((1 + discount_rate) ** years) / terminal_ps
    if target_revenue_N <= current_revenue:
        return 0.0
    return float((target_revenue_N / current_revenue) ** (1.0 / years) - 1.0)


def _classify_valuation(implied_g: float, historical_g: float) -> tuple[str, float, str]:
    if historical_g <= 0:
        if implied_g > 0.30:
            return ("overvalued", 0.65,
                    f"Market implies {implied_g*100:.1f}% CAGR but historical growth is non-positive")
        return ("fairly_valued", 1.0,
                f"Implied {implied_g*100:.1f}% CAGR; limited historical to validate")

    ratio = implied_g / historical_g

    if ratio <= 0.9:
        return ("undervalued", 1.15,
                f"Market implies {implied_g*100:.1f}% vs historical {historical_g*100:.1f}% -- possibly underpricing")
    if ratio <= 1.2:
        return ("fairly_valued", 1.0,
                f"Market implies {implied_g*100:.1f}% vs historical {historical_g*100:.1f}% -- aligned")
    if ratio <= 1.8:
        return ("fairly_valued", 0.90,
                f"Market implies {implied_g*100:.1f}% vs historical {historical_g*100:.1f}% -- premium but plausible")
    if ratio <= 3.0:
        return ("overvalued", 0.70,
                f"Market implies {implied_g*100:.1f}% vs historical {historical_g*100:.1f}% -- aggressive")
    return ("overvalued", 0.50,
            f"Market implies {implied_g*100:.1f}% vs historical {historical_g*100:.1f}% -- unrealistic")


def compute_growth_valuation(
    enriched: dict,
    market_cap: float,
    sector: str = "general",
    ticker: str = "",
) -> dict[str, Any] | None:
    """Reverse P/S valuation. Returns dict or None. Can never raise."""
    try:
        revenue = float(enriched.get("latest_revenue") or 0)
        rev_growth = float(enriched.get("revenue_growth") or 0)
        price = float(enriched.get("price") or 0)
        shares = float(enriched.get("shares") or 0)

        if revenue <= 0 or market_cap <= 0 or price <= 0 or shares <= 0:
            return None
        if market_cap < 1e10:
            return None
        if market_cap / revenue > 100:
            return None

        sector_key = (sector or "general").lower().replace(" ", "_").replace("&", "and")
        terminal_ps = SECTOR_TERMINAL_PS.get(sector_key, SECTOR_TERMINAL_PS["general"])

        implied_g = _reverse_ps_implied_growth(
            market_cap=market_cap,
            current_revenue=revenue,
            terminal_ps=terminal_ps,
        )
        if implied_g is None:
            return None

        verdict, fv_mult, reasoning = _classify_valuation(implied_g, rev_growth)
        fair_value = round(price * fv_mult, 2)
        mos_pct = round((fair_value - price) / price * 100, 1) if price > 0 else 0.0

        log.info(
            "[%s] growth path: implied_g=%.1f%% hist_g=%.1f%% -> FV=%.2f (%s)",
            ticker, implied_g * 100, rev_growth * 100, fair_value, verdict,
        )

        return {
            "fair_value": fair_value,
            "verdict": verdict,
            "margin_of_safety": mos_pct,
            "implied_growth_rate": round(implied_g, 4),
            "historical_growth_rate": round(rev_growth, 4),
            "terminal_ps": terminal_ps,
            "valuation_method": "reverse_ps_growth",
            "reasoning": reasoning,
            "confidence": "low" if rev_growth <= 0 else "medium",
        }
    except Exception as exc:
        log.warning("[%s] growth valuation failed: %s", ticker, exc)
        return None


def should_use_growth_path(enriched: dict, market_cap: float) -> bool:
    """
    Narrow eligibility for the reverse-P/S growth path.

    A "growth stock" for this purpose has TWO signals:
      1. Low op margin (<5%)  -- DCF produces garbage
      2. High revenue growth (>20%) -- investing for scale, not cyclical

    The second check avoids false positives on CYCLICALS that
    temporarily have low margins (oil refiners like IOC during low
    crack spreads; cement during demand lulls; SHREECEM). Those are
    mature businesses with mean-reverting margins — DCF still applies
    once margins normalize.

    Calibration (observed):
      Growth stocks:  ETERNAL (0.05% margin, 30%+ rev growth) -> eligible
      Cyclicals:      IOC (3% margin, 5% rev growth) -> skip
                      SHREECEM (4% margin, 10% rev growth) -> skip
      Blue chips:     TCS (24% margin) -> skip (first gate)

    Returns False (safe default) on any error -> standard DCF runs.
    """
    try:
        revenue = float(enriched.get("latest_revenue") or 0)
        op_margin = float(enriched.get("op_margin") or 0)
        rev_growth = float(enriched.get("revenue_growth") or 0)
        if revenue < 1e9:
            return False
        if market_cap < 1e10:
            return False
        # Gate 1: reliably profitable -> standard DCF
        if op_margin > 0.05:
            return False
        # Gate 2: low-margin cyclical -> standard DCF (wait for mean-reversion)
        # Only actually-growing companies qualify for P/S-based valuation
        if rev_growth < 0.20:
            return False
        return True
    except Exception:
        return False
