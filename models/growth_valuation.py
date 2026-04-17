"""
Growth-stock valuation path — reverse P/S-multiple for pre-profit companies.

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

  market_cap * (1 + r)^N  =  revenue * (1 + g)^N * terminal_ps
  => g = ((market_cap * (1+r)^N) / (revenue * terminal_ps)) ^ (1/N) - 1

Then compare `implied_growth` to the company's actual trailing revenue
CAGR. If implied is <= 1.1x actual → fairly valued. If >> actual → the
market is pricing in growth the company hasn't demonstrated → overvalued.

This is a well-established technique used by growth-stock analysts
(Ron Baron, Mary Meeker, etc.). It's directionally useful even when
absolute numbers are imprecise, which is the goal here.

Not investment advice. SEBI-safe: reports 'implied vs actual' as a
descriptive model output, not a recommendation.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger("yieldiq.growth_valuation")


# ── Calibration ──────────────────────────────────────────────────
# Terminal P/S multiple by sector — what would a mature version of
# this business trade at? Calibrated against actual Indian market
# observations (Q4 2024-25).
SECTOR_TERMINAL_PS: dict[str, float] = {
    "internet":          6.0,   # Google, Meta mature P/S ~6 (US); Indian equiv discount
    "e-commerce":        3.0,   # Amazon mature at 3x
    "fintech":           4.0,   # Adyen, Stripe proxies
    "insurance_tech":    3.5,
    "foodtech":          3.0,   # Meituan, Delivery Hero mature
    "saas":              6.0,
    "media":             3.0,
    "retail":            1.5,
    "consumer":          4.0,   # Nestle, HUL etc.
    "it_services":       5.0,
    "general":           3.5,
}

# Discount rate used for the reverse solve. Higher = more conservative
# (implies market needs higher growth to justify price → verdict tilts
# more overvalued). 12% matches the Indian equity cost-of-capital baseline.
DISCOUNT_RATE = 0.12
FORECAST_YEARS = 10


def _reverse_ps_implied_growth(
    market_cap: float,
    current_revenue: float,
    terminal_ps: float,
    discount_rate: float = DISCOUNT_RATE,
    years: int = FORECAST_YEARS,
) -> float | None:
    """
    Given market cap and current revenue, what CAGR does the market
    need revenue to grow at to justify today's price (assuming the
    stock re-rates to `terminal_ps` by year `years`)?

    Returns None if inputs are invalid.
    """
    if current_revenue <= 0 or market_cap <= 0 or terminal_ps <= 0:
        return None
    # Target future market cap at exit: current market cap * (1+r)^N
    # which equals: revenue_N * terminal_ps
    # So revenue_N = market_cap * (1+r)^N / terminal_ps
    target_revenue_N = market_cap * ((1 + discount_rate) ** years) / terminal_ps
    if target_revenue_N <= current_revenue:
        # Market implies flat-to-negative growth — unusual, clamp to 0.
        return 0.0
    # Solve for CAGR: (target/current)^(1/N) - 1
    implied = (target_revenue_N / current_revenue) ** (1.0 / years) - 1.0
    return float(implied)


def _classify_valuation(implied_g: float, historical_g: float) -> tuple[str, float, str]:
    """
    Given implied vs historical growth, return (verdict, fv_multiplier,
    reasoning). `fv_multiplier` is applied to current price to produce
    the fair value — e.g. 0.7 means 'market is 30% above our estimate'.

    The multiplier curve is intentionally conservative — we don't want
    to flag healthy growth stocks as dramatically overvalued when we
    lack cash-flow visibility.
    """
    # Protect against zero or negative historical growth
    if historical_g <= 0:
        # No historical growth to anchor against; lean conservative.
        if implied_g > 0.30:  # market implies >30% CAGR with no historical track record
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
                f"Market implies {implied_g*100:.1f}% vs historical {historical_g*100:.1f}% -- growth expectations aligned")
    if ratio <= 1.8:
        return ("fairly_valued", 0.90,
                f"Market implies {implied_g*100:.1f}% vs historical {historical_g*100:.1f}% -- premium but plausible")
    if ratio <= 3.0:
        return ("overvalued", 0.70,
                f"Market implies {implied_g*100:.1f}% vs historical {historical_g*100:.1f}% -- aggressive expectations")
    # ratio > 3
    return ("overvalued", 0.50,
            f"Market implies {implied_g*100:.1f}% vs historical {historical_g*100:.1f}% -- expectations appear unrealistic")


def compute_growth_valuation(
    enriched: dict,
    market_cap: float,
    sector: str = "general",
    ticker: str = "",
) -> dict[str, Any] | None:
    """
    Compute an alternative fair value for pre-profit growth stocks.

    Uses reverse P/S multiple analysis — does not require positive FCF
    or PAT. Returns a dict with fair_value, verdict, implied_growth,
    historical_growth, and human-readable reasoning.

    Returns None if the ticker is not a valid candidate (e.g. no
    revenue, no market cap, or inputs look suspicious). Caller should
    fall back to whatever logic would have run otherwise.

    Safe: wraps all logic in try/except so a bug here can never crash
    the analysis pipeline.
    """
    try:
        revenue = float(enriched.get("latest_revenue") or 0)
        rev_growth = float(enriched.get("revenue_growth") or 0)
        price = float(enriched.get("price") or 0)
        shares = float(enriched.get("shares") or 0)

        # Eligibility: must have meaningful revenue and market cap
        if revenue <= 0 or market_cap <= 0 or price <= 0 or shares <= 0:
            return None
        # Don't apply to micro-caps — data is too noisy
        if market_cap < 1e10:  # < ₹1,000 cr
            return None
        # Don't apply to companies with tiny revenue relative to mkt cap
        # (would imply unsustainable P/S > 100 which is its own signal)
        if market_cap / revenue > 100:
            log.info("[%s] growth valuation skipped: P/S=%.0f (structural)",
                     ticker, market_cap / revenue)
            return None

        # Resolve terminal P/S for this sector
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
    Decide whether a ticker should be routed through the growth
    valuation path instead of the standard DCF.

    Criteria (all must hold):
      1. Has meaningful revenue (latest_revenue > ₹100 Cr)
      2. Has meaningful market cap (> ₹10,000 Cr)
      3. FCF is non-positive OR PAT is non-positive
         (= standard DCF will produce garbage)
      4. Has some historical revenue data to anchor judgment

    This keeps the path narrow. Every cash-generative blue chip still
    uses the standard DCF — unchanged.
    """
    try:
        revenue = float(enriched.get("latest_revenue") or 0)
        fcf = float(enriched.get("latest_fcf") or 0)
        pat = float(enriched.get("latest_pat") or 0)

        if revenue < 1e9:                 # < ₹100 Cr revenue → skip
            return False
        if market_cap < 1e10:             # < ₹1,000 Cr mkt cap → skip
            return False
        if fcf > 0 and pat > 0:           # normally profitable → use standard DCF
            return False
        return True
    except Exception:
        return False
