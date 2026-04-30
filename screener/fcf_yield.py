# screener/fcf_yield.py
# ═══════════════════════════════════════════════════════════════
# FCF YIELD vs BOND YIELD — THE EQUITY RISK PREMIUM SHORTCUT
# ═══════════════════════════════════════════════════════════════
#
# The single most important relative-value question for any stock:
#
#   "Am I getting paid enough in cash earnings to take equity risk
#    vs just buying a risk-free Treasury bond?"
#
# FCF Yield = Free Cash Flow Per Share / Current Price
#           = the cash return you earn on every dollar invested today
#
# Bond Yield = 10-Year US Treasury yield (risk-free rate)
#
# The comparison:
#   FCF Yield > Bond Yield  → Stock pays more than bonds → equity premium exists
#   FCF Yield < Bond Yield  → You'd earn more in T-Bills → equity is expensive
#   FCF Yield >> Bond Yield → Strong buy signal (wide margin of safety)
#
# Historical context (S&P 500):
#   S&P 500 average FCF yield: ~3.5-4.0%
#   Pre-2022 (ZIRP era):       ~3.5% yield, bonds 0.5% → huge equity premium
#   2024-2026:                 ~3.5% yield, bonds 4.3% → thin equity premium
#   This is why stocks felt "overvalued" in 2024 even though DCFs looked OK.
#
# Additional metrics computed:
#   • Earnings yield (E/P)         — P/E inverted, classic Graham metric
#   • Dividend yield               — income component
#   • Total shareholder yield      — FCF yield + buyback yield
#   • Equity Risk Premium (ERP)    — FCF yield minus bond yield
#   • "Years to payback"           — 1 / FCF yield (how many years to earn back price)
#
# Sources:
#   Bond yield: Yahoo Finance ^TNX (live)
#   India 10Y:  Yahoo Finance ^INBMK (live)
#   Fallbacks:  US 4.3%, India 7.2%
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
from utils.logger import get_logger

log = get_logger(__name__)

# ── BENCHMARK YIELDS ─────────────────────────────────────────
# S&P 500 historical averages (for context)
SP500_AVG_FCF_YIELD    = 0.035   # 3.5% long-run average
SP500_AVG_EPS_YIELD    = 0.050   # 5.0% long-run earnings yield (~20x PE)
NIFTY50_AVG_FCF_YIELD  = 0.040   # 4.0% Nifty 50 long-run average FCF yield
FALLBACK_US_BOND       = 0.043   # 4.3% US 10Y Treasury fallback
FALLBACK_INDIA_BOND    = 0.0675  # 6.75% India 10Y G-Sec fallback (Mar 2026)

# Thresholds for signal generation
ERP_STRONG_BUY   =  0.030   # FCF yield > bond + 3% → strong buy
ERP_BUY          =  0.010   # FCF yield > bond + 1%
ERP_FAIR         =  0.000   # FCF yield = bond → fair
ERP_EXPENSIVE    = -0.010   # FCF yield < bond - 1% → expensive
ERP_VERY_EXP     = -0.020   # FCF yield < bond - 2% → very expensive


# ── LIVE RATE FETCHING ────────────────────────────────────────
_RATE_CACHE: dict = {}

def fetch_bond_yield(is_indian: bool = False) -> tuple[float, str]:
    """
    Fetch live 10-year government bond yield.
    Returns (yield_as_decimal, source_string)
    """
    global _RATE_CACHE
    cache_key = "india" if is_indian else "us"

    # Cache for 30 minutes
    import time
    cached = _RATE_CACHE.get(cache_key)
    if cached and (time.time() - cached["ts"]) < 1800:
        return cached["rate"], cached["source"] + " (cached)"

    ticker_sym = "^INBMK" if is_indian else "^TNX"
    fallback   = FALLBACK_INDIA_BOND if is_indian else FALLBACK_US_BOND
    label      = "India 10Y G-Sec" if is_indian else "US 10Y Treasury"

    try:
        import yfinance as yf
        info  = yf.Ticker(ticker_sym).info
        price = info.get("regularMarketPrice") or info.get("previousClose")
        if price and 0.5 < price < 25:   # sanity: yield between 0.5% and 25%
            rate = float(price) / 100
            _RATE_CACHE[cache_key] = {"rate": rate, "source": f"Live {label}", "ts": time.time()}
            return rate, f"Live {label} ({price:.2f}%)"
    except Exception as e:
        log.debug(f"Bond yield fetch failed ({ticker_sym}): {e}")

    _RATE_CACHE[cache_key] = {"rate": fallback, "source": f"Fallback {label}", "ts": time.time()}
    return fallback, f"Fallback {label} ({fallback*100:.1f}%)"


# ── CORE COMPUTATION ──────────────────────────────────────────

def compute_fcf_yield_analysis(
    enriched:      dict,
    current_price: float,
    fx:            float = 1.0,
) -> dict:
    """
    Full FCF yield vs bond yield analysis.

    Returns all yield metrics plus plain-English verdict and summary.
    """
    ticker  = enriched.get("ticker", "?")
    sector  = enriched.get("sector", "general")
    shares  = enriched.get("shares", 1)
    # Prefer Yahoo TTM FCF (trailing 12 months from info dict)
    # over cf_df.iloc[-1] which can be a single quarter
    fcf_ttm = enriched.get("yahoo_fcf_ttm", 0)
    fcf     = fcf_ttm if fcf_ttm and fcf_ttm > 0 else enriched.get("latest_fcf", 0)
    revenue = enriched.get("latest_revenue", 0)
    mktcap  = enriched.get("market_cap", current_price * shares)

    # Is this an Indian stock?
    is_indian = ticker.upper().endswith(".NS") or ticker.upper().endswith(".BO")

    # ── Live bond yield ───────────────────────────────────────
    bond_yield, bond_source = fetch_bond_yield(is_indian)

    # ── FCF yield ─────────────────────────────────────────────
    # Always compute market cap from price × shares for unit consistency.
    # Do NOT use enriched["market_cap"] — for Indian stocks Yahoo returns
    # marketCap in USD while current_price (price_n) is in INR → mismatch.
    # price_n × shares is always in the same unit (native currency).
    mktcap_native = current_price * shares if shares > 0 else mktcap

    fcf_per_share = fcf / shares if shares > 0 else 0
    fcf_yield     = fcf_per_share / current_price if current_price > 0 else 0
    fcf_yield_mc  = fcf / mktcap_native if mktcap_native > 0 else 0

    # Sanity check: both methods should agree within 5%
    # If they diverge badly, FCF unit is likely wrong → use market cap method
    if fcf_yield > 0 and fcf_yield_mc > 0:
        ratio = fcf_yield / fcf_yield_mc
        if ratio < 0.8 or ratio > 1.2:
            # Significant divergence — market cap method is more reliable
            # as it avoids FCF-per-share unit ambiguity
            log.debug(f"[{ticker}] FCF yield methods diverge ({fcf_yield:.1%} vs {fcf_yield_mc:.1%}) — using mktcap method")
            fcf_yield_final = fcf_yield_mc
        else:
            fcf_yield_final = fcf_yield
    else:
        fcf_yield_final = fcf_yield if fcf_yield > 0 else fcf_yield_mc

    # ── Earnings yield (EPS-based) ────────────────────────────
    fwd_eps     = enriched.get("forward_eps", 0) or 0
    trail_eps   = enriched.get("trailing_eps", 0) or 0
    eps         = fwd_eps if fwd_eps > 0 else trail_eps
    # Convert EPS to reporting currency
    eps_yield   = eps / current_price if eps > 0 and current_price > 0 else 0

    # ── Dividend yield ────────────────────────────────────────
    div_yield   = enriched.get("dividend_yield", 0) or 0

    # ── Buyback yield ─────────────────────────────────────────
    # Approximate: (FCF - Dividends) / Market cap
    # This estimates what % of market cap is being returned via buybacks
    div_paid      = div_yield * mktcap_native if div_yield > 0 else 0
    buyback_approx = max(fcf - div_paid, 0)
    buyback_yield  = buyback_approx / mktcap_native if mktcap_native > 0 else 0

    # ── Total shareholder yield ───────────────────────────────
    # FCF yield + any residual returned to shareholders
    total_sh_yield = fcf_yield_final + div_yield

    # ── Equity Risk Premium ───────────────────────────────────
    # ERP = FCF yield - Bond yield
    # Positive → you're getting paid MORE than bonds to take equity risk
    # Negative → bonds pay more → equity is expensive on this metric
    erp = fcf_yield_final - bond_yield

    # ── EPS-based ERP (Graham's metric) ──────────────────────
    eps_erp = eps_yield - bond_yield if eps_yield > 0 else None

    # ── Years to payback ──────────────────────────────────────
    payback_years = 1 / fcf_yield_final if fcf_yield_final > 0 else None

    # ── Index comparison (S&P 500 for US, Nifty 50 for India) ──
    index_avg_fcf_yield = NIFTY50_AVG_FCF_YIELD if is_indian else SP500_AVG_FCF_YIELD
    index_label         = "Nifty 50" if is_indian else "S&P 500"
    vs_sp500 = fcf_yield_final - index_avg_fcf_yield

    # ── Verdict ───────────────────────────────────────────────
    verdict, verdict_colour, verdict_emoji = _yield_verdict(
        fcf_yield_final, bond_yield, erp, is_indian
    )

    # ── Summary ───────────────────────────────────────────────
    summary = _yield_summary(
        ticker=ticker,
        fcf_yield=fcf_yield_final,
        bond_yield=bond_yield,
        erp=erp,
        index_yield=index_avg_fcf_yield,
        index_label=index_label,
        payback=payback_years,
        verdict=verdict,
        is_indian=is_indian,
        bond_source=bond_source,
    )

    # ── Historical context ────────────────────────────────────
    context = _yield_context(fcf_yield_final, bond_yield, erp, is_indian)

    return {
        "ticker":              ticker,
        "is_indian":           is_indian,

        # Core yields
        "fcf_yield":           fcf_yield_final,
        "fcf_per_share":       fcf_per_share * fx,
        "eps_yield":           eps_yield,
        "div_yield":           div_yield,
        "buyback_yield":       buyback_yield,
        "total_sh_yield":      total_sh_yield,

        # Bond comparison
        "bond_yield":          bond_yield,
        "bond_source":         bond_source,
        "erp":                 erp,              # equity risk premium
        "eps_erp":             eps_erp,          # EPS-based ERP

        # vs benchmarks
        "sp500_avg_fcf_yield": SP500_AVG_FCF_YIELD,
        "vs_index":            vs_sp500,          # vs S&P500 (US) or Nifty50 (India)
        "index_label":         index_label,        # "S&P 500" or "Nifty 50"
        "index_avg_fcf_yield": index_avg_fcf_yield,
        "sp500_avg_fcf_yield": SP500_AVG_FCF_YIELD, # kept for backwards compat
        "payback_years":       payback_years,

        # Verdict
        "verdict":             verdict,
        "verdict_colour":      verdict_colour,
        "verdict_emoji":       verdict_emoji,
        "summary":             summary,
        "context":             context,
    }


def _yield_verdict(
    fcf_yield:  float,
    bond_yield: float,
    erp:        float,
    is_indian:  bool,
) -> tuple[str, str, str]:
    """
    Generate verdict based on ERP (FCF yield minus bond yield).
    More nuanced than a simple threshold — considers absolute yield level too.
    """
    # Edge case: negative FCF → cannot assess
    if fcf_yield <= 0:
        return "FCF negative — yield not meaningful", "#64748B", "⚪"

    if erp >= ERP_STRONG_BUY:
        return "attractive vs bonds — strong equity premium", "#059669", "🟢"
    elif erp >= ERP_BUY:
        return "modestly attractive vs bonds — positive premium", "#2563EB", "🔵"
    elif erp >= ERP_FAIR:
        return "fairly priced vs bonds — minimal premium", "#D97706", "🟡"
    elif erp >= ERP_EXPENSIVE:
        return "expensive vs bonds — below bond yield", "#EA580C", "🟠"
    else:
        return "very expensive vs bonds — bonds yield more than stock", "#DC2626", "🔴"


def _yield_summary(
    ticker:      str,
    fcf_yield:   float,
    bond_yield:  float,
    erp:         float,
    index_yield: float,
    index_label: str,
    payback:     float | None,
    verdict:     str,
    is_indian:   bool,
    bond_source: str,
) -> str:
    bond_label = "India 10Y G-Sec" if is_indian else "US 10Y Treasury"
    payback_str = f"{payback:.0f} years" if payback and payback < 100 else "100+ years"

    line1 = (
        f"{ticker} generates a {fcf_yield*100:.1f}% FCF yield at today's price — "
        f"meaning for every ₹100 you invest, the company earns ₹{fcf_yield*100:.1f} "
        f"in free cash flow annually."
    )

    if erp > 0:
        line2 = (
            f"The {bond_label} currently yields {bond_yield*100:.1f}%. "
            f"{ticker}'s FCF yield is {erp*100:.1f}% higher than bonds — "
            f"you are being compensated for taking equity risk."
        )
    elif erp > -0.01:
        line2 = (
            f"The {bond_label} currently yields {bond_yield*100:.1f}%. "
            f"{ticker}'s FCF yield is essentially the same — "
            f"bonds offer the same return with zero equity risk."
        )
    else:
        line2 = (
            f"The {bond_label} currently yields {bond_yield*100:.1f}%. "
            f"{ticker}'s FCF yield is {abs(erp)*100:.1f}% LOWER than bonds — "
            f"you earn more by simply buying Treasury bonds than owning this stock."
        )

    line3 = f"At this yield, it takes {payback_str} of current FCF to equal today's price paid."

    return f"{line1} {line2} {line3}"


def _yield_context(
    fcf_yield:  float,
    bond_yield: float,
    erp:        float,
    is_indian:  bool,
) -> list[dict]:
    """
    Return 3-4 historical context data points for the gauge chart.
    Shows where current yield sits vs historical norms.
    """
    if is_indian:
        return [
            {"label": "Nifty 50 avg FCF yield", "value": NIFTY50_AVG_FCF_YIELD, "colour": "#3B82F6"},
            {"label": "India 10Y G-Sec",         "value": bond_yield,            "colour": "#EF4444"},
            {"label": "This stock",              "value": fcf_yield,             "colour": "#059669"},
            {"label": "Pre-cut bond (2024)",     "value": 0.072,                 "colour": "#94A3B8"},
        ]
    return [
        {"label": "S&P 500 avg FCF yield",   "value": SP500_AVG_FCF_YIELD, "colour": "#3B82F6"},
        {"label": "US 10Y Treasury",          "value": bond_yield,          "colour": "#EF4444"},
        {"label": "This stock",               "value": fcf_yield,           "colour": "#059669"},
        {"label": "ZIRP-era bond (2021)",     "value": 0.015,               "colour": "#94A3B8"},
    ]
