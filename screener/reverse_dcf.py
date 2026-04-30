# screener/reverse_dcf.py
# ═══════════════════════════════════════════════════════════════
# REVERSE DCF ENGINE
# ═══════════════════════════════════════════════════════════════
#
# Normal DCF:  Growth assumption → Fair Value
# Reverse DCF: Current Price     → Implied Growth assumption
#
# The key question it answers:
#   "What growth rate is the market pricing into this stock?"
#
# If the implied growth is wildly optimistic → stock is risky
# If the implied growth is conservative      → stock has margin of safety
#
# Methodology:
#   1. Binary search over FCF growth rate (0.1% steps, -30% to +60%)
#   2. For each growth rate, run full 10-year DCF
#   3. Find the rate where DCF IV = current market price
#   4. Compare implied growth to:
#      - Historical FCF growth (what the company actually delivered)
#      - Analyst consensus growth
#      - Long-run GDP (what is sustainable forever)
#   5. Generate a plain-English verdict
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
from utils.logger import get_logger

log = get_logger(__name__)


# ── CONSTANTS ────────────────────────────────────────────────
SEARCH_MIN_GROWTH  = -0.30   # -30% floor (distressed)
SEARCH_MAX_GROWTH  =  0.60   # +60% ceiling (hyper-growth)
SEARCH_TOLERANCE   =  0.01   # Stop when IV within 1% of price
MAX_ITERATIONS     =  80     # Max binary search iterations
US_LONG_RUN_GDP    =  0.025  # 2.5% US nominal GDP
INDIA_LONG_RUN_GDP =  0.10   # 10% India nominal GDP


# ── CORE REVERSE DCF ────────────────────────────────────────

def _dcf_iv_for_growth(
    fcf_base:       float,
    growth_rate:    float,
    wacc:           float,
    terminal_g:     float,
    years:          int,
    total_debt:     float,
    total_cash:     float,
    shares:         float,
) -> float:
    """
    Run a simple DCF for a given constant growth rate.
    Returns IV per share. Used by binary search.
    """
    if shares <= 0 or fcf_base <= 0:
        return 0.0

    # Project FCFs with constant growth
    projected = [fcf_base * (1 + growth_rate) ** (i + 1) for i in range(years)]

    # Terminal value (Gordon Growth)
    terminal_fcf = projected[-1] * (1 + growth_rate * 0.5)  # fade growth for terminal
    spread = wacc - terminal_g
    if spread <= 0:
        spread = 0.02
    tv = terminal_fcf * (1 + terminal_g) / spread

    # PV of FCFs + PV of terminal value
    pv_fcfs = sum(fcf / (1 + wacc) ** (i + 1) for i, fcf in enumerate(projected))
    pv_tv   = tv / (1 + wacc) ** years

    ev           = pv_fcfs + pv_tv
    equity_value = ev - total_debt + total_cash

    if equity_value <= 0:
        return 0.0

    return equity_value / shares


def compute_implied_growth(
    current_price:  float,
    fcf_base:       float,
    wacc:           float,
    terminal_g:     float,
    total_debt:     float,
    total_cash:     float,
    shares:         float,
    years:          int = 10,
) -> dict:
    """
    Binary search to find the FCF growth rate that makes
    DCF intrinsic value equal to the current market price.

    Returns a dict with:
        implied_growth      : float — the market-implied annual FCF growth rate
        converged           : bool  — did the search find a precise answer
        iv_at_implied       : float — IV at the implied growth rate (≈ price)
        search_iterations   : int
    """
    if current_price <= 0 or fcf_base <= 0 or shares <= 0:
        return {
            "implied_growth": None,
            "converged": False,
            "iv_at_implied": 0.0,
            "search_iterations": 0,
            "error": "Invalid inputs — price, FCF or shares is zero/negative",
        }

    lo  = SEARCH_MIN_GROWTH
    hi  = SEARCH_MAX_GROWTH
    iters = 0
    mid = 0.0

    # Check bounds first
    iv_lo = _dcf_iv_for_growth(fcf_base, lo, wacc, terminal_g, years, total_debt, total_cash, shares)
    iv_hi = _dcf_iv_for_growth(fcf_base, hi, wacc, terminal_g, years, total_debt, total_cash, shares)

    # If price is above our max-growth IV, market is pricing in unreachable growth
    if current_price > iv_hi:
        return {
            "implied_growth": hi,
            "converged": False,
            "iv_at_implied": iv_hi,
            "search_iterations": 1,
            "error": f"Price implies growth > {hi:.0%} — model ceiling hit",
            "capped": True,
        }

    # If price is below our min-growth IV, market is pricing in collapse
    if current_price < iv_lo:
        return {
            "implied_growth": lo,
            "converged": False,
            "iv_at_implied": iv_lo,
            "search_iterations": 1,
            "error": f"Price implies growth < {lo:.0%} — severe distress priced in",
            "capped": True,
        }

    # Binary search
    for iters in range(1, MAX_ITERATIONS + 1):
        mid    = (lo + hi) / 2
        iv_mid = _dcf_iv_for_growth(
            fcf_base, mid, wacc, terminal_g, years, total_debt, total_cash, shares
        )

        error_pct = abs(iv_mid - current_price) / current_price
        if error_pct < SEARCH_TOLERANCE:
            return {
                "implied_growth":    mid,
                "converged":         True,
                "iv_at_implied":     iv_mid,
                "search_iterations": iters,
            }

        if iv_mid < current_price:
            lo = mid
        else:
            hi = mid

    # Return best estimate even if not fully converged
    return {
        "implied_growth":    mid,
        "converged":         False,
        "iv_at_implied":     _dcf_iv_for_growth(
            fcf_base, mid, wacc, terminal_g, years, total_debt, total_cash, shares
        ),
        "search_iterations": iters,
    }


# ── FULL REVERSE DCF ANALYSIS ───────────────────────────────

def run_reverse_dcf(
    enriched:       dict,
    current_price:  float,
    wacc:           float,
    terminal_g:     float,
    years:          int = 10,
) -> dict:
    """
    Full reverse DCF analysis. Returns everything needed
    for display in the dashboard.

    Plain-English verdicts:
        "The market is betting on X% annual growth for 10 years.
         This company has historically grown at Y%.
         That assumption looks [realistic / aggressive / unrealistic]."
    """
    ticker    = enriched.get("ticker", "?")
    sector    = enriched.get("sector", "general")
    fcf_base  = enriched.get("latest_fcf", 0)
    debt      = enriched.get("total_debt", 0)
    cash      = enriched.get("total_cash", 0)
    shares    = enriched.get("shares", 0)
    hist_rev_g = enriched.get("revenue_growth", None)
    hist_fcf_g = enriched.get("fcf_growth", None)

    # ── Use best available historical growth ──────────────────
    # FCF can be volatile year-to-year (buybacks, capex spikes)
    # Use the higher of FCF CAGR and revenue growth as the
    # historical benchmark — revenue is more stable and better
    # represents the company's underlying growth trajectory
    if hist_fcf_g is not None and hist_rev_g is not None:
        # If FCF growth is negative but revenue is positive,
        # the company likely had a one-off capex spike — use revenue
        if hist_fcf_g < 0 and hist_rev_g > 0:
            hist_g = hist_rev_g
        else:
            # Use the more conservative (lower) of the two
            # to avoid overstating historical performance
            hist_g = min(hist_fcf_g, hist_rev_g) if hist_fcf_g > 0 else hist_rev_g
    elif hist_fcf_g is not None:
        hist_g = max(hist_fcf_g, 0.0)   # floor at 0 — negative hist not useful
    elif hist_rev_g is not None:
        hist_g = hist_rev_g
    else:
        hist_g = None

    # ── Run binary search ──────────────────────────────────
    result = compute_implied_growth(
        current_price=current_price,
        fcf_base=fcf_base,
        wacc=wacc,
        terminal_g=terminal_g,
        total_debt=debt,
        total_cash=cash,
        shares=shares,
        years=years,
    )

    if result.get("error") and not result.get("capped"):
        return {**result, "ticker": ticker, "verdict": "Unable to compute — insufficient data"}

    implied_g = result["implied_growth"]

    # ── Long-run GDP anchor ────────────────────────────────
    is_indian = ticker.upper().endswith(".NS") or ticker.upper().endswith(".BO")
    long_run  = INDIA_LONG_RUN_GDP if is_indian else US_LONG_RUN_GDP

    # ── Historical growth for comparison ──────────────────
    hist_g_display = hist_g   # keep for display

    # ── Growth scenarios ───────────────────────────────────
    # What IV looks like at different growth assumptions
    scenarios = {}
    for label, rate in [
        ("GDP rate",      long_run),
        ("Historical",    hist_g if hist_g is not None else long_run * 1.5),
        ("Implied",       implied_g),
        ("Half implied",  implied_g / 2 if implied_g else long_run),
    ]:
        iv = _dcf_iv_for_growth(fcf_base, rate, wacc, terminal_g, years, debt, cash, shares)
        mos = (iv - current_price) / current_price if current_price > 0 else 0
        scenarios[label] = {
            "growth_rate": rate,
            "implied_iv":  iv,
            "mos":         mos,
        }

    # ── Realism verdict ────────────────────────────────────
    verdict_level, verdict_text, verdict_colour = _assess_realism(
        implied_g=implied_g,
        hist_g=hist_g,
        long_run=long_run,
        ticker=ticker,
    )

    # ── Years to justify price ─────────────────────────────
    # At what year does cumulative DCF IV first exceed current price
    # given historical growth?
    years_to_justify = _years_to_justify_price(
        current_price=current_price,
        fcf_base=fcf_base,
        hist_g=hist_g if hist_g is not None else long_run,
        wacc=wacc,
        terminal_g=terminal_g,
        debt=debt,
        cash=cash,
        shares=shares,
    )

    # ── Build plain-English summary ────────────────────────
    summary = _build_summary(
        ticker=ticker,
        implied_g=implied_g,
        hist_g=hist_g,
        long_run=long_run,
        verdict_level=verdict_level,
        current_price=current_price,
        years_to_justify=years_to_justify,
    )

    # ── Extra metrics ──────────────────────────────────────
    fcf_per_share       = enriched.get("latest_fcf", 0) / shares if shares > 0 else 0
    fcf_yield           = fcf_per_share / current_price if current_price > 0 else 0
    # Payback at implied growth (optimistic scenario)
    payback_at_implied  = _years_to_justify_price(
        current_price=current_price,
        fcf_base=fcf_base,
        hist_g=implied_g,    # use implied rate, not historical
        wacc=wacc,
        terminal_g=terminal_g,
        debt=debt,
        cash=cash,
        shares=shares,
    )
    # Price/FCF multiple (intuitive: "you pay Nx today's earnings")
    price_to_fcf = current_price / fcf_per_share if fcf_per_share > 0 else None

    return {
        "ticker":              ticker,
        "current_price":       current_price,
        "implied_growth":      implied_g,
        "converged":           result.get("converged", False),
        "iv_at_implied":       result.get("iv_at_implied", current_price),
        "historical_growth":   hist_g,
        "long_run_gdp":        long_run,
        "wacc":                wacc,
        "terminal_g":          terminal_g,
        "verdict_level":       verdict_level,
        "verdict_text":        verdict_text,
        "verdict_colour":      verdict_colour,
        "summary":             summary,
        "scenarios":           scenarios,
        "years_to_justify":    years_to_justify,     # at historical growth (conservative)
        "payback_at_implied":  payback_at_implied,   # at implied growth (optimistic)
        "fcf_yield":           fcf_yield,
        "price_to_fcf":        price_to_fcf,
        "excess_growth":       implied_g - (hist_g if hist_g else long_run),
        "growth_premium":      implied_g - long_run,
    }


def _assess_realism(
    implied_g:  float,
    hist_g:     float | None,
    long_run:   float,
    ticker:     str,
) -> tuple[str, str, str]:
    """
    Returns (level, text, colour) based on how realistic
    the implied growth rate is.

    Calibrated against S&P 500 historical FCF growth distributions:
      Bottom quartile:  < 3%   (slow/declining)
      Median:           5-8%   (typical)
      Top quartile:    10-15%  (good growth company)
      Top decile:      15-25%  (exceptional)
      Rare outliers:   25-40%  (hyper-growth, NVDA/META phase)
      Near-impossible: > 40%   (almost no large-cap sustains this)

    We also check vs the company's own history as a secondary signal.
    """
    # ── Primary: absolute growth rate bands ──────────────────
    # These are calibrated to S&P 500 FCF growth distributions

    # Also consider vs historical: if implied is close to history, lean green
    hist_ratio = (implied_g / hist_g) if (hist_g and hist_g > 0.01) else None

    # CONSERVATIVE: below long-run GDP — market pricing in slow/no growth
    if implied_g <= long_run:
        return (
            "conservative",
            "The market is pricing in below-GDP growth — very conservative assumption. "
            "If the company delivers anywhere near its historical rate, there is significant upside.",
            "green",
        )

    # REASONABLE: within 1.2× of own history, OR implied ≤ 12% with hist support
    # Key: if market is pricing below what the company has historically delivered → reasonable
    if hist_ratio is not None and hist_ratio <= 1.2:
        return (
            "reasonable",
            "The market's growth assumption looks achievable — it is in line with "
            "or below what this company has historically delivered.",
            "green",
        )
    hist_ok = (hist_ratio is None) or (hist_ratio <= 1.5)
    if implied_g <= 0.12 and hist_ok:
        return (
            "reasonable",
            "The market's growth assumption looks achievable for a quality business. "
            "This is within normal range — the stock is not pricing in heroic execution.",
            "green",
        )

    # AGGRESSIVE: covers two cases —
    #   a) 12-20% implied regardless of history (above-average but achievable)
    #   b) implied is up to 3× historical BUT absolute rate is still modest (<10%)
    #      e.g. T at 6% implied vs 2% history — aggressive but not alarming
    modest_absolute = implied_g <= 0.10
    if implied_g <= 0.20 or (hist_ratio and hist_ratio <= 3.0 and modest_absolute):
        return (
            "aggressive",
            "The market is pricing in above-average growth. Achievable for a high-quality "
            "business but leaves limited margin for error — any slowdown could hurt the price.",
            "amber",
        )

    # VERY AGGRESSIVE: 20-35% — exceptional growth, rare to sustain
    # Acceptable for NVDA/META class companies in a growth phase
    if implied_g <= 0.35:
        hist_context = (
            f" For context, this company has historically grown at {hist_g*100:.1f}%."
            if hist_g else ""
        )
        return (
            "very aggressive",
            f"The market is pricing in exceptional growth that only a handful of companies "
            f"sustain for a decade.{hist_context} High execution risk.",
            "red",
        )

    # UNREALISTIC: > 35% — almost no large-cap company sustains this
    return (
        "unrealistic",
        "The market is pricing in hyper-growth that virtually no established company "
        "has sustained for 10 years. This implies either a structural disruption scenario "
        "or significant overvaluation.",
        "red",
    )


def _years_to_justify_price(
    current_price: float,
    fcf_base:      float,
    hist_g:        float,
    wacc:          float,
    terminal_g:    float,
    debt:          float,
    cash:          float,
    shares:        float,
    max_years:     int = 20,
) -> int | None:
    """
    At historical growth rate, how many years until DCF IV ≥ current price?
    Returns None if never justified within max_years.
    """
    for y in range(3, max_years + 1):
        iv = _dcf_iv_for_growth(fcf_base, hist_g, wacc, terminal_g, y, debt, cash, shares)
        if iv >= current_price:
            return y
    return None


def _build_summary(
    ticker:           str,
    implied_g:        float,
    hist_g:           float | None,
    long_run:         float,
    verdict_level:    str,
    current_price:    float,
    years_to_justify: int | None,
) -> str:
    """Generate the plain-English 2-3 sentence summary shown to users."""

    implied_pct = f"{implied_g * 100:.1f}%"
    hist_pct    = f"{hist_g * 100:.1f}%" if hist_g is not None else "unknown"
    gdp_pct     = f"{long_run * 100:.1f}%"

    line1 = (
        f"To justify today's price of ₹{current_price:.2f}, "
        f"{ticker} needs to grow its free cash flow at "
        f"{implied_pct} per year for the next 10 years."
    )

    if hist_g is not None:
        diff   = implied_g - hist_g
        dir_   = "faster than" if diff > 0 else "slower than"
        line2  = (
            f"That is {abs(diff)*100:.1f}% {dir_} its historical growth rate of {hist_pct}. "
        )
    else:
        line2 = f"For context, long-run US GDP growth is {gdp_pct}. "

    if verdict_level in ("conservative", "reasonable"):
        line3 = (
            f"This looks achievable — the market is not pricing in heroic assumptions. "
            f"There may be genuine upside if the company executes."
        )
    elif verdict_level == "aggressive":
        line3 = (
            f"This is optimistic but not impossible for a high-quality business. "
            f"The stock leaves little room for error — any slowdown could hurt the price."
        )
    else:
        if years_to_justify:
            line3 = (
                f"At its historical growth rate, the stock would take "
                f"{years_to_justify} years to justify today's price. "
                f"The market is effectively paying for a perfect future."
            )
        else:
            line3 = (
                f"At its historical growth rate, the stock cannot justify its current price "
                f"within a 20-year horizon. The market is pricing in a step-change in performance."
            )

    return f"{line1} {line2}{line3}"
