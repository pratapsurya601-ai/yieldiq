# screener/dcf_engine.py
# ═══════════════════════════════════════════════════════════════
# DCF ENGINE v4 — COMPLETE EDGE CASE HANDLING
# ═══════════════════════════════════════════════════════════════
# NEW in v4:
#   ✅ Negative earnings detection (loss companies, cyclical, turnaround)
#   ✅ High volatility adjustment (beta-based WACC, confidence penalty)
#   ✅ Extreme P/E handling (negative, >1000, <5)
#   ✅ Recent IPO detection (<2 years historical data)
#   ✅ High debt screening (D/E ratio > 2.0)
#   ✅ Negative cash handling
#   ✅ Share dilution tracking
#   ✅ Reliability score (0-100)
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Optional, List, Dict, Tuple
from datetime import datetime, timedelta
from utils.logger import get_logger
from utils.config import DISCOUNT_RATE, TERMINAL_GROWTH_RATE, FORECAST_YEARS

log = get_logger(__name__)

MIN_DISCOUNT_RATE   = 0.07    
MAX_TERMINAL_GROWTH = 0.04
IV_HARD_CAP_MULT    = 5.0     
TV_WARNING_PCT      = 0.75    

# NEW: Edge case thresholds
HIGH_VOLATILITY_BETA = 1.5      # Beta > 1.5 = high volatility
EXTREME_PE_HIGH = 100           # P/E > 100 = overheated/speculative
EXTREME_PE_LOW = 5              # P/E < 5 = distressed/cyclical bottom
HIGH_DEBT_RATIO = 2.0           # Debt/Equity > 2.0 = overleveraged
MIN_OPERATING_HISTORY_YEARS = 2 # IPO < 2 years = unreliable
NEGATIVE_FCF_THRESHOLD = 0.3    # >30% of FCFs negative = troubled


class EdgeCaseFlags:
    """Tracks all edge case warnings for a DCF calculation"""
    def __init__(self):
        self.flags: List[str] = []
        self.reliability_score = 100  # Start at 100, deduct points
        
    def add_flag(self, flag: str, penalty: int = 10):
        """Add warning and reduce reliability score"""
        self.flags.append(flag)
        self.reliability_score = max(0, self.reliability_score - penalty)
        
    def is_reliable(self) -> bool:
        """DCF reliable if score >= 60"""
        return self.reliability_score >= 60
        
    def get_category(self) -> str:
        """Categorize reliability"""
        if self.reliability_score >= 80:
            return "High Confidence"
        elif self.reliability_score >= 60:
            return "Moderate Confidence"
        elif self.reliability_score >= 40:
            return "Low Confidence"
        else:
            return "Unreliable"


class DCFEngine:
    def __init__(self, discount_rate=DISCOUNT_RATE, terminal_growth=TERMINAL_GROWTH_RATE):
        self.r = max(discount_rate, MIN_DISCOUNT_RATE)
        self.g = min(terminal_growth, MAX_TERMINAL_GROWTH)
        if self.g >= self.r:
            self.g = self.r - 0.02
            
        self.edge_flags = EdgeCaseFlags()

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

    # ══════════════════════════════════════════════════════════════
    # NEW: EDGE CASE DETECTION METHODS
    # ══════════════════════════════════════════════════════════════
    
    def _check_negative_earnings(self, projected_fcfs: List[float], 
                                 historical_fcf: Optional[List[float]] = None):
        """
        Detect negative earnings patterns:
        - All negative (loss company)
        - Mostly negative (>30% of projections)
        - Cyclical (alternating pos/neg)
        - Recent turnaround (historical losses → projected gains)
        """
        if not projected_fcfs:
            self.edge_flags.add_flag("No FCF projections", penalty=50)
            return
            
        neg_count = sum(1 for fcf in projected_fcfs if fcf <= 0)
        neg_ratio = neg_count / len(projected_fcfs)
        
        # All negative = loss company
        if neg_ratio == 1.0:
            self.edge_flags.add_flag("❌ Loss Company (all FCFs negative)", penalty=40)
            log.warning("Loss company detected - DCF unreliable")
            return
            
        # Mostly negative = troubled
        if neg_ratio > NEGATIVE_FCF_THRESHOLD:
            self.edge_flags.add_flag(
                f"⚠️ Troubled Company ({neg_ratio:.0%} negative FCFs)", 
                penalty=30
            )
            
        # Check for alternating pattern (cyclical)
        if len(projected_fcfs) >= 3:
            sign_changes = sum(
                1 for i in range(len(projected_fcfs)-1) 
                if (projected_fcfs[i] > 0) != (projected_fcfs[i+1] > 0)
            )
            if sign_changes >= 2:
                self.edge_flags.add_flag("🔄 Cyclical Business (volatile FCF)", penalty=15)
                
        # Turnaround detection (historical losses → projected gains)
        if historical_fcf and len(historical_fcf) >= 2:
            hist_avg = np.mean(historical_fcf[-2:])  # Last 2 years
            proj_avg = np.mean(projected_fcfs[:2])    # First 2 projection years
            if hist_avg <= 0 and proj_avg > 0:
                self.edge_flags.add_flag("📈 Turnaround Story (verify sustainability)", penalty=20)
    
    def _check_volatility(self, beta: Optional[float], ticker: str = "?"):
        """
        Adjust WACC for high volatility stocks (beta > 1.5)
        Typical high-volatility: tech growth, biotech, crypto-related
        """
        if beta is None or beta <= 0:
            # Only warn if beta was not available at all (sector default ensures > 0)
            self.edge_flags.add_flag("⚠️ Missing Beta (using default WACC)", penalty=5)
            return
            
        if beta > HIGH_VOLATILITY_BETA:
            # Increase discount rate by volatility premium
            volatility_premium = (beta - 1.0) * 0.03  # 3% per beta point above 1.0
            old_r = self.r
            self.r = min(old_r + volatility_premium, 0.25)  # Cap at 25%
            
            self.edge_flags.add_flag(
                f"📊 High Volatility (β={beta:.2f}, WACC {old_r:.1%}→{self.r:.1%})", 
                penalty=15
            )
            log.info(f"[{ticker}] High beta {beta:.2f} - increased WACC to {self.r:.1%}")
            
        elif beta < 0.5:
            # Ultra-low beta = defensive stock (utilities, staples)
            self.edge_flags.add_flag(f"🛡️ Defensive Stock (β={beta:.2f})", penalty=0)
    
    def _check_extreme_pe(self, pe_ratio: Optional[float], ticker: str = "?"):
        """
        Flag extreme P/E ratios:
        - Negative P/E = losses (already caught above)
        - P/E > 100 = overheated/speculative  
        - P/E < 5 = distressed/deep value trap
        """
        if pe_ratio is None:
            return
            
        if pe_ratio < 0:
            self.edge_flags.add_flag("❌ Negative P/E (company losing money)", penalty=35)
            
        elif pe_ratio > EXTREME_PE_HIGH:
            self.edge_flags.add_flag(
                f"🔥 Extreme P/E ({pe_ratio:.0f}) - speculative/overheated", 
                penalty=20
            )
            log.warning(f"[{ticker}] Extreme P/E {pe_ratio:.0f} - high expectations priced in")
            
        elif 0 < pe_ratio < EXTREME_PE_LOW:
            self.edge_flags.add_flag(
                f"💎 Very Low P/E ({pe_ratio:.1f}) - verify not value trap", 
                penalty=10
            )
    
    def _check_ipo_age(self, ipo_date: Optional[str], ticker: str = "?"):
        """
        Recent IPOs (<2 years) have unreliable financials
        """
        if not ipo_date:
            # Missing IPO date is a data-completeness issue, not a business risk.
            # Skip flagging it — it was adding noise to red flags.
            return
            
        try:
            ipo_dt = pd.to_datetime(ipo_date)
            years_since_ipo = (datetime.now() - ipo_dt).days / 365.25
            
            if years_since_ipo < MIN_OPERATING_HISTORY_YEARS:
                self.edge_flags.add_flag(
                    f"🆕 Recent IPO ({years_since_ipo:.1f}y) - limited history", 
                    penalty=25
                )
                log.warning(f"[{ticker}] Recent IPO {ipo_date} - only {years_since_ipo:.1f}y history")
                
        except:
            self.edge_flags.add_flag("⚠️ Invalid IPO date", penalty=5)
    
    def _check_debt_levels(self, total_debt: float, market_cap: float, 
                          total_equity: Optional[float] = None, ticker: str = "?"):
        """
        Flag overleveraged companies (D/E > 2.0)
        """
        if total_debt <= 0:
            return
            
        if total_equity and total_equity > 0:
            de_ratio = total_debt / total_equity
            if de_ratio > HIGH_DEBT_RATIO:
                self.edge_flags.add_flag(
                    f"⚠️ High Debt (D/E={de_ratio:.1f}) - bankruptcy risk", 
                    penalty=20
                )
                log.warning(f"[{ticker}] High D/E ratio {de_ratio:.1f}")
        elif market_cap > 0:
            debt_to_mcap = total_debt / market_cap
            if debt_to_mcap > 1.5:
                self.edge_flags.add_flag(
                    f"⚠️ High Debt (Debt/MCap={debt_to_mcap:.1f})", 
                    penalty=20
                )
    
    def _check_cash_position(self, total_cash: float, ticker: str = "?"):
        """
        Negative cash can happen with restricted cash accounting
        """
        if total_cash < 0:
            self.edge_flags.add_flag(
                f"⚠️ Negative Cash (${total_cash/1e9:.1f}B) - verify accounting", 
                penalty=10
            )
            log.warning(f"[{ticker}] Negative cash position: ${total_cash/1e9:.1f}B")
    
    def _check_share_dilution(self, shares_outstanding: float, 
                             shares_outstanding_1y_ago: Optional[float] = None,
                             ticker: str = "?"):
        """
        Excessive share dilution (>10% YoY) = value destruction
        """
        if shares_outstanding_1y_ago and shares_outstanding_1y_ago > 0:
            dilution = (shares_outstanding - shares_outstanding_1y_ago) / shares_outstanding_1y_ago
            
            if dilution > 0.10:  # >10% dilution
                self.edge_flags.add_flag(
                    f"📉 Share Dilution ({dilution:.0%} YoY)", 
                    penalty=15
                )
                log.warning(f"[{ticker}] {dilution:.0%} share dilution YoY")
            elif dilution < -0.05:  # >5% buyback
                self.edge_flags.add_flag(f"📈 Share Buyback ({abs(dilution):.0%})", penalty=-5)

    # ══════════════════════════════════════════════════════════════
    # MAIN INTRINSIC VALUE CALCULATION WITH EDGE CASE CHECKS
    # ══════════════════════════════════════════════════════════════

    def intrinsic_value_per_share(
        self,
        projected_fcfs: List[float], 
        terminal_fcf_norm: float,
        total_debt: float, 
        total_cash: float, 
        shares_outstanding: float,
        current_price: float = 0.0, 
        ticker: str = "?",
        # NEW: Edge case detection parameters
        beta: Optional[float] = None,
        pe_ratio: Optional[float] = None,
        ipo_date: Optional[str] = None,
        market_cap: Optional[float] = None,
        total_equity: Optional[float] = None,
        shares_outstanding_1y_ago: Optional[float] = None,
        historical_fcf: Optional[List[float]] = None,
    ) -> dict:
        """
        Calculate intrinsic value with comprehensive edge case detection.
        
        New parameters:
        - beta: Stock beta for volatility adjustment
        - pe_ratio: P/E ratio for valuation sanity check
        - ipo_date: IPO date string (YYYY-MM-DD) to check operating history
        - market_cap: Market cap for debt ratio calculation
        - total_equity: Book equity for D/E ratio
        - shares_outstanding_1y_ago: For dilution tracking
        - historical_fcf: Historical FCF for turnaround detection
        """
        
        # Reset edge case flags
        self.edge_flags = EdgeCaseFlags()
        
        # RUN ALL EDGE CASE CHECKS
        self._check_negative_earnings(projected_fcfs, historical_fcf)
        self._check_volatility(beta, ticker)
        self._check_extreme_pe(pe_ratio, ticker)
        self._check_ipo_age(ipo_date, ticker)
        self._check_debt_levels(total_debt, market_cap or (current_price * shares_outstanding), 
                               total_equity, ticker)
        self._check_cash_position(total_cash, ticker)
        self._check_share_dilution(shares_outstanding, shares_outstanding_1y_ago, ticker)
        
        # Existing validation
        if shares_outstanding <= 0:
            self.edge_flags.add_flag("❌ No shares data", penalty=50)
            return self._build_result(0.0, ticker, suspicious=True)

        if all(v <= 0 for v in projected_fcfs):
            self.edge_flags.add_flag("❌ Zero FCF projections", penalty=50)
            return self._build_result(0.0, ticker, suspicious=True)

        # Calculate DCF
        ev_dict      = self.enterprise_value(projected_fcfs, terminal_fcf_norm)
        equity_value = ev_dict["enterprise_value"] - total_debt + total_cash

        # Terminal value sanity check
        if ev_dict["tv_pct_of_ev"] > TV_WARNING_PCT:
            self.edge_flags.add_flag(
                f"⚠️ Terminal Value = {ev_dict['tv_pct_of_ev']:.0%} of EV (highly sensitive)", 
                penalty=15
            )

        if equity_value <= 0:
            self.edge_flags.add_flag("❌ Negative equity value", penalty=40)
            return self._build_result(0.0, ticker, equity_value=equity_value,
                                     ev_dict=ev_dict, shares=shares_outstanding)

        iv_per_share_raw = equity_value / shares_outstanding
        iv_per_share = iv_per_share_raw

        # ── Structured DCF trace ──────────────────────────────────
        # Emit a single-line JSON trace on EVERY DCF so that when a
        # blow-up is later reported (HCLTECH ₹6,067 style), we can
        # grep production logs by ticker and see exactly which input
        # drove the raw IV past the 5× cap. Fields chosen so the
        # culprit (fcf_base vs growth vs TV dominance vs debt/cash
        # adjustment) is immediately visible.
        try:
            _fcf0 = float(projected_fcfs[0]) if len(projected_fcfs) else 0.0
            _fcfN = float(projected_fcfs[-1]) if len(projected_fcfs) else 0.0
            # Implied compound growth across the forecast horizon
            if _fcf0 > 0 and _fcfN > 0 and len(projected_fcfs) > 1:
                _impl_g = (_fcfN / _fcf0) ** (1.0 / (len(projected_fcfs) - 1)) - 1.0
            else:
                _impl_g = 0.0
            _ratio = (iv_per_share_raw / current_price) if current_price > 0 else 0.0
            log.info(
                "DCF_TRACE ticker=%s fcf_base=%.2f fcfN=%.2f impl_g=%.4f "
                "terminal_fcf_norm=%.2f terminal_value=%.2f pv_tv=%.2f "
                "tv_pct_ev=%.4f enterprise_value=%.2f total_debt=%.2f "
                "total_cash=%.2f equity_value=%.2f shares=%.0f "
                "raw_iv=%.4f price=%.4f iv_ratio=%.2fx wacc=%.4f g=%.4f "
                "capped=%s",
                ticker, _fcf0, _fcfN, _impl_g,
                float(terminal_fcf_norm or 0.0),
                float(ev_dict.get("terminal_value") or 0.0),
                float(ev_dict.get("pv_tv") or 0.0),
                float(ev_dict.get("tv_pct_of_ev") or 0.0),
                float(ev_dict.get("enterprise_value") or 0.0),
                float(total_debt or 0.0), float(total_cash or 0.0),
                float(equity_value or 0.0), float(shares_outstanding or 0),
                iv_per_share_raw, float(current_price or 0.0), _ratio,
                float(self.r), float(self.g),
                iv_per_share_raw > IV_HARD_CAP_MULT * current_price if current_price > 0 else False,
            )
        except Exception:
            # Never let instrumentation break the DCF
            pass

        # HARD CAP: IV cannot exceed 5× current price
        suspicious = False
        if current_price > 0 and iv_per_share_raw > IV_HARD_CAP_MULT * current_price:
            suspicious = True
            self.edge_flags.add_flag(
                f"⚠️ IV ${iv_per_share_raw:.2f} > {IV_HARD_CAP_MULT}× price ${current_price:.2f} (capped)",
                penalty=25
            )
            iv_per_share = IV_HARD_CAP_MULT * current_price

        return self._build_result(
            iv_per_share, ticker, suspicious=suspicious,
            equity_value=equity_value, ev_dict=ev_dict,
            shares=shares_outstanding, total_debt=total_debt, total_cash=total_cash
        )
    
    def _build_result(self, iv: float, ticker: str, suspicious: bool = False,
                     equity_value: float = 0.0, ev_dict: dict = None,
                     shares: float = 0.0, total_debt: float = 0.0, 
                     total_cash: float = 0.0) -> dict:
        """Helper to build standardized result dict"""
        result = {
            "intrinsic_value_per_share": max(iv, 0.0),
            "suspicious": suspicious,
            "warnings": self.edge_flags.flags,
            "reliability_score": self.edge_flags.reliability_score,
            "reliability_category": self.edge_flags.get_category(),
            "dcf_reliable": self.edge_flags.is_reliable(),
        }
        
        if ev_dict:
            result.update(ev_dict)
            result.update({
                "equity_value": equity_value,
                "shares_outstanding": shares,
                "total_debt": total_debt,
                "total_cash": total_cash,
            })
        else:
            result["tv_pct_of_ev"] = 0
            
        return result


# ══════════════════════════════════════════════════════════════
# MARGIN OF SAFETY (unchanged from v3)
# ══════════════════════════════════════════════════════════════

def margin_of_safety(intrinsic_value: float, current_price: float) -> float:
    """MoS = (IV - Price) / Price"""
    if current_price <= 0:
        return 0.0
    return (intrinsic_value - current_price) / current_price


def assign_signal(
    mos: float,
    suspicious: bool = False,
    reliable: bool = True,
    insider_adj: float = 0.0,
    reliability_score: int = 100,  # NEW parameter
) -> str:
    """
    Signal based on MoS + reliability score
    
    NEW: If reliability_score < 60, return "Low Confidence" signal
    """
    if not reliable or reliability_score < 60:
        return "⬜ Low Confidence"
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
# SENSITIVITY ANALYSIS (unchanged)
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
# MONTE CARLO (unchanged)
# ══════════════════════════════════════════════════════════════

def monte_carlo_valuation(
    enriched, forecaster, total_debt, total_cash,
    shares_outstanding, current_price, base_wacc=0.10, n_simulations=1000,
) -> dict:
    from models.forecaster import FORECAST_YEARS, _exponential_fade, _clamp

    if not enriched.get("dcf_reliable", True):
        return {"error": "Company unreliable for DCF"}

    forecast_result = forecaster.predict(enriched, years=FORECAST_YEARS)
    if not forecast_result.get("reliable", True):
        return {"error": "No valid FCF base for Monte Carlo"}

    projected    = forecast_result["projections"]
    growth_sched = forecast_result["growth_schedule"]
    base_growth  = forecast_result["base_growth"]

    if projected and growth_sched and growth_sched[0] > -1:
        fcf_base = projected[0] / (1 + growth_sched[0])
    else:
        return {"error": "No valid FCF base for Monte Carlo"}

    if fcf_base <= 0:
        return {"error": "No valid FCF base for Monte Carlo"}

    iv_values = []
    np.random.seed(42)

    for _ in range(n_simulations):
        sim_growth = _clamp(np.random.normal(base_growth, 0.02))
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
        if 0 < iv < current_price * 5:
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
