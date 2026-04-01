# screener/dcf_engine.py
# ═══════════════════════════════════════════════════════════════
# DCF ENGINE v3 — Fixed MoS Formula + Strict Sanity Checks
# ═══════════════════════════════════════════════════════════════
# Critical fixes:
#   1. MoS formula: (IV - Price) / Price  (NOT / IV)
#   2. IV capped at 5× price hard limit
#   3. TV > 75% EV → flag unstable
#   4. Loss companies → signal = "DCF N/A"
#   5. Microcap filter in screener
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
import pandas as pd
from utils.logger import get_logger
from utils.config import DISCOUNT_RATE, TERMINAL_GROWTH_RATE, FORECAST_YEARS

log = get_logger(__name__)

MIN_DISCOUNT_RATE   = 0.07    # floor at 7% — allows low-beta US stocks (AAPL β≈0.8) their true CAPM WACC
MAX_TERMINAL_GROWTH = 0.04
IV_HARD_CAP_MULT    = 5.0     # never show IV > 5x price
TV_WARNING_PCT      = 0.75    # warn if TV > 75% of EV


class DCFEngine:
    def __init__(self, discount_rate=DISCOUNT_RATE, terminal_growth=TERMINAL_GROWTH_RATE):
        self.r = max(discount_rate, MIN_DISCOUNT_RATE)
        self.g = min(terminal_growth, MAX_TERMINAL_GROWTH)
        if self.g >= self.r:
            self.g = self.r - 0.02

    def _pv(self, amount, year):
        return amount / (1 + self.r) ** year

    def present_value_fcfs(self, projected_fcfs):
        return [self._pv(fcf, yr + 1) for yr, fcf in enumerate(projected_fcfs)]

    def terminal_value(self, normalized_terminal_fcf):
        spread = self.r - self.g
        if spread <= 0 or normalized_terminal_fcf <= 0:
            return 0.0
        return normalized_terminal_fcf * (1 + self.g) / spread

    def enterprise_value(self, projected_fcfs, terminal_fcf_norm):
        pv_fcfs     = self.present_value_fcfs(projected_fcfs)
        sum_pv_fcfs = sum(pv_fcfs)
        tv          = self.terminal_value(terminal_fcf_norm)
        pv_tv       = self._pv(tv, len(projected_fcfs))
        ev          = sum_pv_fcfs + pv_tv
        tv_pct      = pv_tv / ev if ev > 0 else 0
        return {
            "pv_fcfs": pv_fcfs, "sum_pv_fcfs": sum_pv_fcfs,
            "terminal_value": tv, "pv_tv": pv_tv,
            "enterprise_value": ev, "tv_pct_of_ev": tv_pct,
        }

    def intrinsic_value_per_share(
        self,
        projected_fcfs, terminal_fcf_norm,
        total_debt, total_cash, shares_outstanding,
        current_price=0.0, ticker="?",
    ) -> dict:
        if shares_outstanding <= 0:
            return {"intrinsic_value_per_share": 0.0, "suspicious": True,
                    "warnings": ["No shares data"], "tv_pct_of_ev": 0}

        # Check for zero/negative FCF projections (unreliable)
        if all(v <= 0 for v in projected_fcfs):
            return {"intrinsic_value_per_share": 0.0, "suspicious": True,
                    "warnings": ["Zero FCF projections — company unreliable for DCF"],
                    "tv_pct_of_ev": 0}

        ev_dict      = self.enterprise_value(projected_fcfs, terminal_fcf_norm)
        equity_value = ev_dict["enterprise_value"] - total_debt + total_cash
        warnings     = []

        if ev_dict["tv_pct_of_ev"] > TV_WARNING_PCT:
            msg = f"Terminal value = {ev_dict['tv_pct_of_ev']:.0%} of EV — highly sensitive to assumptions"
            warnings.append(msg)
            log.warning(f"[{ticker}] {msg}")

        if equity_value <= 0:
            return {**ev_dict, "equity_value": equity_value,
                    "intrinsic_value_per_share": 0.0, "suspicious": False,
                    "warnings": ["Negative equity value"], "shares_outstanding": shares_outstanding}

        iv_per_share = equity_value / shares_outstanding

        # HARD CAP: IV cannot exceed 5× current price
        suspicious = False
        if current_price > 0 and iv_per_share > IV_HARD_CAP_MULT * current_price:
            suspicious = True
            msg = f"IV {iv_per_share:.2f} > {IV_HARD_CAP_MULT}× price {current_price:.2f} — capped"
            warnings.append(msg)
            log.warning(f"[{ticker}] {msg}")
            iv_per_share = IV_HARD_CAP_MULT * current_price

        result = {**ev_dict}
        result.update({
            "total_debt": total_debt, "total_cash": total_cash,
            "shares_outstanding": shares_outstanding,
            "equity_value": equity_value,
            "intrinsic_value_per_share": max(iv_per_share, 0.0),
            "suspicious": suspicious,
            "warnings": warnings,
        })
        return result


# ══════════════════════════════════════════════════════════════
# FIXED MARGIN OF SAFETY FORMULA
# ══════════════════════════════════════════════════════════════

def margin_of_safety(intrinsic_value: float, current_price: float) -> float:
    """
    CORRECT formula: MoS = (IV - Price) / Price

    This gives:
    - IV = 120, Price = 100 → MoS = 20%  ✅
    - IV = 50,  Price = 100 → MoS = -50% ✅

    The old (IV - Price)/IV formula was wrong and caused
    inflated MoS numbers for high IV stocks.
    """
    if current_price <= 0:
        return 0.0
    return (intrinsic_value - current_price) / current_price


def assign_signal(
    mos: float,
    suspicious: bool = False,
    reliable: bool = True,
    insider_adj: float = 0.0,
) -> str:
    """
    Signal based on corrected MoS (relative to price).

    Thresholds adjusted for new formula:
    Undervalued        > 20%  (IV is 20%+ above price)   [formerly: Deeply Undervalued]
    Near Fair Value    > 5%   (IV is 5-20% above price)
    Fairly Valued      > -10% (slight overvalue)
    Overvalued         ≤ -10% (Significantly Overvalued)

    insider_adj : float
        Small MoS nudge (±0.02–0.04) derived from insider sentiment (10% weight).
        Positive = net insider buying, negative = net insider selling.
        Can shift borderline signals by one notch.
    """
    if not reliable:
        return "N/A ⬜"
    if suspicious:
        return "⚠️ Data Limited"
    effective_mos = mos + insider_adj
    if effective_mos >= 0.20:
        return "Undervalued 🟢"
    elif effective_mos >= 0.05:
        return "Near Fair Value 🟡"
    elif effective_mos >= -0.10:
        return "Fairly Valued 🔵"
    else:
        return "Overvalued 🔴"


# ══════════════════════════════════════════════════════════════
# SENSITIVITY ANALYSIS
# ══════════════════════════════════════════════════════════════

def sensitivity_analysis(
    projected_fcfs, terminal_fcf_norm,
    total_debt, total_cash, shares_outstanding,
    current_price=0.0,
    wacc_range=None, tg_range=None,
) -> pd.DataFrame:
    if wacc_range is None:
        wacc_range = [0.08, 0.09, 0.10, 0.11, 0.12, 0.13, 0.14]
    if tg_range is None:
        tg_range = [0.01, 0.02, 0.03, 0.04]

    matrix = {}
    for tg in tg_range:
        col = {}
        for wacc in wacc_range:
            if wacc <= tg:
                col[f"{wacc:.0%}"] = np.nan
                continue
            engine = DCFEngine(discount_rate=wacc, terminal_growth=tg)
            res    = engine.intrinsic_value_per_share(
                projected_fcfs=projected_fcfs,
                terminal_fcf_norm=terminal_fcf_norm,
                total_debt=total_debt, total_cash=total_cash,
                shares_outstanding=shares_outstanding,
                current_price=current_price,
            )
            col[f"{wacc:.0%}"] = round(res["intrinsic_value_per_share"], 2)
        matrix[f"g={tg:.0%}"] = col

    df = pd.DataFrame(matrix)
    df.index.name = "WACC"
    return df


# ══════════════════════════════════════════════════════════════
# MONTE CARLO
# ══════════════════════════════════════════════════════════════

def monte_carlo_valuation(
    enriched, forecaster, total_debt, total_cash,
    shares_outstanding, current_price, base_wacc=0.10, n_simulations=1000,
) -> dict:
    from models.forecaster import FORECAST_YEARS, _exponential_fade, _clamp, TERMINAL_FADE_G

    if not enriched.get("dcf_reliable", True):
        return {"error": "Company unreliable for DCF"}

    # Use the forecaster to get the same fcf_base the main DCF used
    forecast_result = forecaster.predict(enriched, years=FORECAST_YEARS)
    if not forecast_result.get("reliable", True):
        return {"error": "No valid FCF base for Monte Carlo"}

    projected    = forecast_result["projections"]
    growth_sched = forecast_result["growth_schedule"]
    base_growth  = forecast_result["base_growth"]

    # Reconstruct the exact fcf_base the forecaster used
    if projected and growth_sched and growth_sched[0] > -1:
        fcf_base = projected[0] / (1 + growth_sched[0])
    else:
        return {"error": "No valid FCF base for Monte Carlo"}

    if fcf_base <= 0:
        return {"error": "No valid FCF base for Monte Carlo"}

    iv_values = []
    np.random.seed(42)

    for _ in range(n_simulations):
        sim_growth = _clamp(np.random.normal(base_growth, 0.02))   # tighter std
        sim_wacc   = float(np.clip(np.random.normal(base_wacc, 0.01), 0.08, 0.20))
        sim_tg     = float(np.clip(np.random.normal(0.03, 0.005), 0.01, 0.04))
        if sim_wacc <= sim_tg:
            sim_tg = sim_wacc - 0.02

        fcf = fcf_base
        projections = []
        for yr in range(1, FORECAST_YEARS + 1):
            g = _clamp(_exponential_fade(yr, sim_growth))
            fcf = fcf * (1 + g)
            projections.append(fcf)

        terminal_norm = float(np.mean(projections[-3:]))
        engine = DCFEngine(discount_rate=sim_wacc, terminal_growth=sim_tg)
        res    = engine.intrinsic_value_per_share(
            projected_fcfs=projections, terminal_fcf_norm=terminal_norm,
            total_debt=total_debt, total_cash=total_cash,
            shares_outstanding=shares_outstanding,
            current_price=current_price,
        )
        iv = res["intrinsic_value_per_share"]
        if 0 < iv < current_price * 5:   # filter outliers at 5× (matches IV_HARD_CAP_MULT)
            iv_values.append(iv)

    if not iv_values:
        return {"error": "No valid simulations"}

    arr  = np.array(iv_values)
    prob = float((arr > current_price).mean()) if current_price > 0 else 0.5

    return {
        "iv_values":        arr,
        "mean_iv":          float(np.mean(arr)),
        "median_iv":        float(np.median(arr)),
        "std_iv":           float(np.std(arr)),
        "p10":              float(np.percentile(arr, 10)),
        "p25":              float(np.percentile(arr, 25)),
        "p75":              float(np.percentile(arr, 75)),
        "p90":              float(np.percentile(arr, 90)),
        "prob_undervalued": prob,
        "n_valid":          len(iv_values),
    }
