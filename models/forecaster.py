# models/forecaster.py
# ═══════════════════════════════════════════════════════════════
# AI FCF FORECASTER v4 — Fixed Growth Caps + Realistic Blending
# ═══════════════════════════════════════════════════════════════
# Root-cause fixes vs v3:
#   1. MAX_FCF_GROWTH raised 20%→35% (pharma/growth stocks need room)
#   2. Rule-based mean-reversion target raised 7%→10% (India GDP+inf)
#   3. Conservative blend weight reduced: rule 60%→40%, more weight
#      to actual historical data (lr 20%→30%, rf 20%→30%)
#   4. _rule_based_growth now uses AVERAGE not MIN of rev/fcf growth
#      — taking MIN was artificially destroying high-quality companies
#   5. FCF proxy median margin cap raised 5%→15% for asset-light cos
#   6. FADE_K reduced 0.35→0.25 so high-growth stocks don't decay too fast
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import pickle, requests
from pathlib import Path
from typing import Optional

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.preprocessing import StandardScaler

from utils.config import FORECAST_YEARS, MODEL_SAVE_PATH
from utils.logger import get_logger

log = get_logger(__name__)

# ── Growth constraints ─────────────────────────────────────────
MAX_FCF_GROWTH  =  0.35   # 35% hard cap (was 20% — too tight for pharma/IT)
MIN_FCF_GROWTH  = -0.15   # -15% floor
TERMINAL_FADE_G =  0.04   # 4% terminal growth (was 3% — India long-run ~4%)
FADE_K          =  0.25   # slower fade (was 0.35 — high-growth cos punished too early)
BLEND_WEIGHTS   = np.array([0.30, 0.30, 0.40])  # lr, rf, rule — less conservative bias


def _clamp(g: float) -> float:
    return float(np.clip(g, MIN_FCF_GROWTH, MAX_FCF_GROWTH))


def _exponential_fade(t: int, g0: float, g_terminal: float = TERMINAL_FADE_G) -> float:
    """g(t) = g_T + (g_0 - g_T) × exp(-k × t)"""
    return g_terminal + (g0 - g_terminal) * np.exp(-FADE_K * t)


def _compute_fcf_base(enriched: dict) -> tuple[float, str]:
    """
    Get the best FCF base estimate using multiple methods.

    Core principle: use the HIGHEST CREDIBLE estimate, not the median.
    For capital-cycle industries (pharma, manufacturing), one bad capex
    year drags median down. The NOPAT proxy gives the true earning power.
    """
    latest_fcf     = enriched.get("latest_fcf", 0)
    latest_revenue = enriched.get("latest_revenue", 0)
    op_margin      = enriched.get("op_margin", 0)
    cf_df          = enriched.get("cf_df", pd.DataFrame())
    income_df      = enriched.get("income_df", pd.DataFrame())
    ticker         = enriched.get("ticker", "?")
    tax_rate       = 0.25

    candidates = {}

    # ── Candidate 1: Latest FCF (strongest signal if positive) ──
    if latest_fcf > 0:
        candidates["latest_fcf"] = latest_fcf

    # ── Candidate 2: Max of last 3 positive FCF years ──────────
    # MAX not median — a company's best recent FCF year reflects
    # its true cash generation when capex is normalised
    if not cf_df.empty and "fcf" in cf_df.columns:
        pos_fcfs = cf_df["fcf"][cf_df["fcf"] > 0].tail(4)
        if len(pos_fcfs) >= 1:
            candidates["max_recent_fcf"] = float(pos_fcfs.max())
        if len(pos_fcfs) >= 2:
            candidates["median_recent_fcf"] = float(pos_fcfs.median())

    # ── Candidate 3: NOPAT proxy — THE MOST RELIABLE FOR PHARMA ─
    # NOPAT = EBIT × (1 - tax). FCF ≈ NOPAT for asset-light businesses
    # because D&A ≈ maintenance capex in steady state
    # Conversion factor: 0.85 (conservative) — pharma has low net capex
    # GUARD: Only use NOPAT proxy for companies with meaningful revenue
    # (≥ ₹100 Cr). Penny/shell stocks have tiny revenue but non-zero
    # op_margin which can produce a deceptively large NOPAT base.
    MIN_REVENUE_FOR_NOPAT = 1_000_000_000  # ₹100 Cr minimum
    if op_margin > 0 and latest_revenue >= MIN_REVENUE_FOR_NOPAT:
        nopat    = latest_revenue * op_margin * (1 - tax_rate)
        # FCF conversion: 85% for high-margin (>15%), 70% for lower margin
        fcf_conv = 0.85 if op_margin >= 0.15 else 0.70

        # Fix 1: Use normalised capex if M&A spike was detected
        norm_capex_pct = enriched.get("norm_capex_pct", None)
        if norm_capex_pct is not None:
            # Normalised FCF = NOPAT - normalised_capex + D&A
            sector = enriched.get("sector", "general")
            da_pct = 0.035  # default D&A
            try:
                from models.industry_wacc import INDUSTRY_WACC
                da_pct = INDUSTRY_WACC.get(sector, {}).get("depreciation_pct", 0.035)
            except Exception:
                pass
            norm_fcf = nopat - (latest_revenue * norm_capex_pct) + (latest_revenue * da_pct)
            if norm_fcf > 0:
                candidates["normalised_capex_fcf"] = norm_fcf
                log.info(f"[{ticker}] Using normalised capex FCF: ₹{norm_fcf/1e9:.1f}B "
                         f"(capex {norm_capex_pct:.1%} of rev)")

        candidates["nopat_proxy"] = nopat * fcf_conv

    # ── Candidate 3b: Pharma R&D-adjusted FCF ──────────────────
    # R&D is investment, not recurring opex. 60% is growth R&D (pipeline),
    # 40% is maintenance R&D. Adding back growth R&D gives economic earnings.
    # This is standard sell-side practice (EV/EBITDA ignores R&D).
    _sector = enriched.get("sector", "general")
    if _sector == "pharma" and op_margin > 0 and latest_revenue >= MIN_REVENUE_FOR_NOPAT:
        try:
            from models.industry_wacc import INDUSTRY_WACC as _IW
            _rd_pct     = _IW.get("pharma", {}).get("rd_pct_revenue", 0.08)
            _growth_rd  = latest_revenue * _rd_pct * 0.60  # 60% = growth R&D
            _econ_nopat = latest_revenue * op_margin * (1 - tax_rate) + _growth_rd * (1 - tax_rate)
            candidates["pharma_rd_adjusted"] = _econ_nopat * 0.80  # conservative 80% conversion
        except Exception:
            pass

    # ── Candidate 4: 75th percentile historical FCF margin ──────
    if not cf_df.empty and not income_df.empty:
        try:
            merged = pd.merge(
                cf_df[["year","fcf"]], income_df[["year","revenue"]],
                on="year", how="inner"
            )
            merged = merged[(merged["revenue"] > 0) & (merged["fcf"] > 0)]
            if len(merged) >= 2:
                margins    = merged["fcf"] / merged["revenue"]
                p75_margin = float(np.clip(float(np.percentile(margins, 75)), 0.03, 0.25))
                candidates["hist_p75_margin"] = latest_revenue * p75_margin
        except Exception:
            pass

    if not candidates:
        log.debug(f"[{ticker}] No valid FCF base — unreliable")
        return 0.0, "unreliable_loss_company"

    log.debug(f"[{ticker}] FCF candidates: { {k: f'₹{v/1e7:.0f}Cr' for k,v in candidates.items()} }")

    # ── Selection strategy ──────────────────────────────────────
    # Use the NOPAT proxy as the anchor (most reliable for earnings-based cos)
    # Then take the MAX of (nopat_proxy, latest_fcf, median_recent_fcf)
    # This way one bad capex year cannot collapse the valuation

    nopat_val  = candidates.get("nopat_proxy", 0)
    latest_val = candidates.get("latest_fcf", 0)
    max_val    = candidates.get("max_recent_fcf", 0)
    median_val = candidates.get("median_recent_fcf", 0)
    p75_val    = candidates.get("hist_p75_margin", 0)

    # Primary: best of latest_fcf, nopat_proxy, and max_recent_fcf
    # Including max_recent_fcf avoids trough-year bias (e.g. TSLA FY2022 negative FCF
    # drags CAGR negative even though FY2023/2024 FCF recovered to $4.4B)
    primary = max(latest_val, nopat_val, max_val)

    # Secondary check: don't let primary exceed 2× median if median exists
    # (prevents outlier high year from inflating the base)
    if median_val > 0 and primary > median_val * 2.5:
        primary = median_val * 2.0
        method  = "capped_at_2x_median"
    else:
        method = "max(latest_fcf, nopat_proxy)"

    # Final floor: never go below 60% of NOPAT (true earning power)
    nopat_floor = nopat_val * 0.60
    base = max(primary, nopat_floor)

    log.debug(f"[{ticker}] FCF base: ₹{base/1e7:.0f}Cr ({method})")
    return base, method


def _build_features(enriched: dict) -> np.ndarray:
    rev = enriched.get("latest_revenue", 1) or 1
    fcf = enriched.get("latest_fcf", 0)
    feats = np.array([
        _clamp(enriched.get("revenue_growth", 0)),
        _clamp(enriched.get("fcf_growth",     0)),
        np.clip(enriched.get("op_margin",  0), -0.5, 0.6),
        np.clip(enriched.get("fcf_margin", 0), -0.5, 0.5),
        fcf / rev if rev != 0 else 0,
        np.log1p(abs(rev)),
        np.log1p(abs(fcf)),
        1.0 if fcf >= 0 else -1.0,
    ], dtype=float)
    return np.nan_to_num(feats, nan=0.0, posinf=0.0, neginf=0.0)


def _rule_based_growth(enriched: dict) -> float:
    """
    Sector-aware mean-reverting growth estimate.
    IB fix: pharma/IT anchor 80% to revenue growth (more stable than FCF).
    FCF growth is volatile due to capex cycles and M&A — weight it less.
    """
    rev_g  = _clamp(enriched.get("revenue_growth", 0))
    fcf_g  = _clamp(enriched.get("fcf_growth",     0))
    sector = enriched.get("sector", "general")

    # Sector-specific revenue vs FCF weighting
    # Pharma/IT: FCF is lumpy (R&D, M&A) — lean heavily on revenue
    # Cyclicals (metals, oil): FCF more volatile — use revenue even more
    # FMCG: both stable — balanced blend
    REV_WEIGHT = {
        # India sectors
        "pharma":          0.80,
        "hospital":        0.80,
        "it_services":     0.75,
        "consumer_durable":0.70,
        "fmcg":            0.65,
        "chemicals":       0.70,
        "capital_goods":   0.70,
        "defence":         0.75,
        "metals":          0.80,
        "oil_gas":         0.75,
        "airlines":        0.85,
        # US sectors
        "us_mega_tech":           0.70,
        "us_semiconductors":      0.75,
        "us_it_services":         0.72,
        "us_pharma":              0.80,
        "us_healthcare_services": 0.75,
        "us_banks":               0.65,
        "us_energy":              0.80,
        "us_industrials":         0.70,
        "us_utilities":           0.65,
        "us_consumer_staples":    0.65,
        "us_consumer_disc":       0.70,
        "us_reits":               0.65,
        "us_materials":           0.80,
        "us_communication":       0.72,
        # fallback
        "general":         0.60,
    }
    rev_weight = REV_WEIGHT.get(sector, 0.60)
    fcf_weight = 1.0 - rev_weight

    blended_growth = rev_weight * rev_g + fcf_weight * fcf_g

    # ── Growth fallback chain ─────────────────────────────────
    # If both FCF and revenue growth are ~0 (data quality issue),
    # use analyst consensus or industry average as proxy
    if abs(blended_growth) < 0.005:  # effectively 0%
        # Try analyst-implied growth from forward EPS
        _fwd_eps = enriched.get("forward_eps", 0) or 0
        _trail_eps = enriched.get("trailing_eps", 0) or 0
        if _fwd_eps > 0 and _trail_eps > 0:
            _analyst_growth = (_fwd_eps / _trail_eps) - 1
            if 0 < _analyst_growth < 0.50:
                blended_growth = _analyst_growth * 0.7  # discount by 30%
                log.info(f"[{enriched.get('ticker','?')}] Growth fallback: analyst EPS growth {_analyst_growth:.1%} -> {blended_growth:.1%}")

        # Still 0? Use revenue growth alone (even if FCF is messy)
        if abs(blended_growth) < 0.005 and abs(rev_g) > 0.01:
            blended_growth = rev_g * 0.8  # use 80% of revenue growth
            log.info(f"[{enriched.get('ticker','?')}] Growth fallback: revenue growth {rev_g:.1%} -> {blended_growth:.1%}")

        # Still 0? Use industry minimum (3% for India, 2% for US)
        if abs(blended_growth) < 0.005:
            _is_us = sector.startswith("us_")
            _min_growth = 0.02 if _is_us else 0.03
            blended_growth = _min_growth
            log.info(f"[{enriched.get('ticker','?')}] Growth fallback: industry minimum {_min_growth:.1%}")

    # Mean-revert toward long-run nominal growth
    # US sectors: ~2.5% (US nominal GDP ~2.1% + small premium)
    # India sectors: ~10% (India nominal GDP ~12% minus some discount)
    US_SECTORS = {
        "us_mega_tech","us_semiconductors","us_it_services","us_pharma",
        "us_healthcare_services","us_banks","us_energy","us_industrials",
        "us_utilities","us_consumer_staples","us_consumer_disc",
        "us_reits","us_materials","us_communication","us_general",
    }
    # Sector-specific long-run nominal growth anchors (US nominal GDP ~4% = real ~2%+inflation ~2%)
    # Growth sectors (tech, semis) anchor higher; commodities/utilities anchor at GDP rate
    US_LONG_RUN = {
        "us_mega_tech":           0.055,  # secular tailwinds — AI, cloud
        "us_semiconductors":      0.055,  # AI/data-centre capex cycle
        "us_it_services":         0.045,
        "us_pharma":              0.040,
        "us_healthcare_services": 0.040,
        "us_consumer_disc":       0.050,  # includes TSLA, AMZN retail — higher growth
        "us_communication":       0.045,
        "us_financial_data":      0.045,
    }
    if sector in US_SECTORS:
        LONG_RUN_TARGET = US_LONG_RUN.get(sector, 0.035)   # default US: 3.5%
    else:
        LONG_RUN_TARGET = 0.10                               # India nominal GDP anchor
    # 60/40 blend: trust actual historical data more, mean-revert less aggressively
    mean_reverted   = 0.60 * blended_growth + 0.40 * LONG_RUN_TARGET

    # Floor: ANY company with positive FCF gets at minimum half the sector's
    # long-run growth rate. No profitable company permanently shrinks.
    latest_fcf = enriched.get("latest_fcf", 0)
    _ticker_dbg = enriched.get('ticker', '?')
    _growth_floor = LONG_RUN_TARGET * 0.5
    print(f"GROWTH_CHECK {_ticker_dbg}: blended={blended_growth:.4f} mean_rev={mean_reverted:.4f} fcf={latest_fcf} floor={_growth_floor:.4f}")
    if latest_fcf > 0 and mean_reverted < _growth_floor:
        mean_reverted = _growth_floor
        print(f"GROWTH_FLOORED {_ticker_dbg}: set to {mean_reverted:.4f}")

    return _clamp(mean_reverted)


def compute_wacc(ticker_obj, is_indian: bool = False) -> dict:
    """
    Compute CAPM-based WACC for a stock.

    Uses live 10-year government bond yields (^TNX for US, ^INBMK for India)
    fetched via utils.config.fetch_risk_free_rate() with a 6-hour module-level
    cache.  The result dict includes rf_rate_info so callers can surface the
    live rate in UI.
    """
    from utils.config import fetch_risk_free_rate as _fetch_rf

    # ── Live risk-free rate (cached 6 h) ───────────────────────
    _market    = "india" if is_indian else "us"
    _rf_info   = _fetch_rf(_market)
    live_rf    = _rf_info["rate"]

    # ── Market defaults ─────────────────────────────────────────
    DEFAULT_WACC = 0.12 if is_indian else 0.09
    DEFAULT_RF   = live_rf                         # now live instead of hardcoded
    DEFAULT_MRP  = 0.060 if is_indian else 0.050   # Damodaran 2025: India 6%, US 5%

    result = {
        "wacc": DEFAULT_WACC, "re": DEFAULT_WACC,
        "rd": 0.06 if is_indian else 0.04,
        "beta": 1.2,
        "rf": DEFAULT_RF, "market_premium": DEFAULT_MRP,
        "tax_rate": 0.25 if is_indian else 0.21,
        "e_weight": 0.8, "d_weight": 0.2,
        "auto_computed": False,
        "rf_rate_info": _rf_info,          # expose to dashboard
    }

    try:
        info = ticker_obj.info
        rf   = DEFAULT_RF
        beta = float(np.clip(info.get("beta", 1.2) or 1.2, 0.5, 3.0))
        mrp  = DEFAULT_MRP

        # Re floor: India 9% (country risk + inflation), US 6% (mature market)
        re_floor = 0.09 if is_indian else 0.06
        re_cap   = 0.25
        re = float(np.clip(rf + beta * mrp, re_floor, re_cap))

        rd = 0.06
        try:
            inc = ticker_obj.financials
            if inc is not None and not inc.empty:
                for label in ["Interest Expense", "Interest Expense Non Operating"]:
                    if label in inc.index:
                        ie   = abs(float(inc.loc[label].iloc[0] or 0))
                        debt = float(info.get("totalDebt", 0) or 0)
                        if debt > 0 and ie > 0:
                            rd = float(np.clip(ie / debt, 0.04, 0.20))
                            break
        except Exception:
            pass

        mkt_cap    = float(info.get("marketCap", 0) or 0)
        total_debt = float(info.get("totalDebt",  0) or 0)
        V   = mkt_cap + total_debt
        e_w = mkt_cap    / V if V > 0 else 0.8
        d_w = total_debt / V if V > 0 else 0.2

        tax_rate = float(np.clip(
            info.get("effectiveTaxRate", 0.25 if is_indian else 0.21)
            or (0.25 if is_indian else 0.21),
            0.10, 0.40,
        ))

        # CAPM WACC
        wacc_floor = 0.09 if is_indian else 0.06
        wacc = float(np.clip(
            e_w * re + d_w * rd * (1 - tax_rate),
            wacc_floor, 0.20,
        ))

        result.update({
            "wacc": wacc, "re": re, "rd": rd,
            "beta": beta, "rf": rf, "market_premium": mrp,
            "tax_rate": tax_rate, "e_weight": e_w, "d_weight": d_w,
            "auto_computed": True,
            "rf_rate_info": _rf_info,
        })
        log.info(
            f"WACC={wacc:.2%} Re={re:.2%} β={beta:.2f} Rd={rd:.2%} "
            f"Rf={rf:.2%} ({_rf_info['source']})"
        )
    except Exception as exc:
        log.warning(f"WACC failed: {exc}")

    return result


def compute_confidence_score(enriched: dict) -> dict:
    score   = 0
    factors = {}
    warnings = []
    income_df = enriched.get("income_df", pd.DataFrame())
    cf_df     = enriched.get("cf_df",     pd.DataFrame())

    # Note: dcf_reliable=False means DCF is not used for valuation,
    # but we still compute a confidence score for the underlying business quality.

    # ── Revenue stability (20 pts) ─────────────────────────────
    if not income_df.empty and "revenue" in income_df.columns:
        rev = income_df["revenue"].replace(0, np.nan).dropna()
        if len(rev) >= 2:
            cv = rev.std() / rev.mean() if rev.mean() != 0 else 1
            s  = max(0, 20 - int(cv * 80))
            factors["Revenue Stability"] = f"{s}/20"
            score += s

            # Detect revenue deceleration / decline
            if len(rev) >= 3:
                recent_yoy  = (rev.iloc[-1] / rev.iloc[-2]) - 1
                prev_yoy    = (rev.iloc[-2] / rev.iloc[-3]) - 1
                decel       = prev_yoy - recent_yoy
                if recent_yoy < -0.05:
                    warnings.append(f"Revenue DECLINING {recent_yoy:.1%} YoY — forward estimates likely much lower")
                    score = max(0, score - 20)   # heavy penalty
                elif recent_yoy < 0:
                    warnings.append(f"Revenue slightly negative {recent_yoy:.1%} YoY")
                elif decel > 0.10 and recent_yoy < 0.15:
                    # Only warn if deceleration brings growth below 15%
                    warnings.append(f"Revenue decelerating: {prev_yoy:.1%} → {recent_yoy:.1%} YoY")
                    score = max(0, score - 10)
    else:
        factors["Revenue Stability"] = "0/20"

    # ── FCF volatility (20 pts) ────────────────────────────────
    if not cf_df.empty and "fcf" in cf_df.columns:
        fcf = cf_df["fcf"].dropna()
        if len(fcf) >= 2 and fcf.mean() != 0:
            cv = fcf.std() / abs(fcf.mean())
            s  = max(0, 20 - int(cv * 40))
            factors["FCF Stability"] = f"{s}/20"
            score += s

            # Detect FCF spike — may be one-time (patent, asset sale)
            # But exclude genuine hypergrowth (revenue also grew similarly)
            if len(fcf) >= 3:
                recent_fcf = float(fcf.iloc[-1])
                median_fcf = float(fcf.median())
                _rev_also_spiked = False
                if not rev.empty and len(rev) >= 3:
                    _rev_ratio = float(rev.iloc[-1]) / float(rev.median()) if float(rev.median()) > 0 else 1
                    _rev_also_spiked = _rev_ratio > 2.0
                if median_fcf > 0 and recent_fcf > median_fcf * 2.5 and not _rev_also_spiked:
                    warnings.append("FCF spike detected — may be one-time (patent/asset sale). Forward FCF likely lower.")
                    score = max(0, score - 15)
                elif recent_fcf < 0:
                    warnings.append("FCF turned negative — monitor closely")
    else:
        factors["FCF Stability"] = "0/20"

    # ── Leverage (20 pts) ──────────────────────────────────────
    debt     = enriched.get("total_debt", 0)
    cash     = enriched.get("total_cash", 0)
    net_debt = debt - cash
    fcf_base = max(enriched.get("latest_fcf", 1), 1)
    lev_s    = max(0, 20 - int((net_debt / (fcf_base * 10)) * 20))
    factors["Leverage"] = f"{lev_s}/20"
    score += lev_s

    # ── FCF positivity (20 pts) ────────────────────────────────
    if not cf_df.empty and "fcf" in cf_df.columns:
        fcf_vals = cf_df["fcf"].dropna()
        pct_pos  = (fcf_vals > 0).mean() if len(fcf_vals) > 0 else 0
        pos_s    = int(pct_pos * 20)
        factors["FCF Positivity"] = f"{pos_s}/20 ({pct_pos:.0%})"
        score += pos_s
    else:
        factors["FCF Positivity"] = "0/20"

    # ── Growth quality (20 pts) ────────────────────────────────
    rev_growth = enriched.get("revenue_growth", 0)
    fcf_growth = enriched.get("fcf_growth", 0)
    op_margin  = enriched.get("op_margin", 0)

    # Check if FCF growth and revenue growth are aligned
    if rev_growth > 0.05 and fcf_growth > 0.05:
        growth_s = 20
    elif rev_growth > 0 and fcf_growth > 0:
        growth_s = 14
    elif rev_growth > 0 or fcf_growth > 0:
        growth_s = 8
    else:
        growth_s = 0
        warnings.append("Both revenue and FCF growth are negative or zero")

    # Bonus for high and stable margin
    if op_margin >= 0.20: growth_s = min(20, growth_s + 3)

    factors["Growth Quality"] = f"{growth_s}/20"
    score += growth_s

    # ── Final grade ────────────────────────────────────────────
    grade = "HIGH" if score >= 70 else "MEDIUM" if score >= 40 else "LOW"
    color = "#10b981" if grade == "HIGH" else "#f59e0b" if grade == "MEDIUM" else "#ef4444"

    return {
        "score":    score,
        "grade":    grade,
        "color":    color,
        "factors":  factors,
        "warnings": warnings,
    }


class FCFForecaster:
    def __init__(self):
        self.lr_model = Ridge(alpha=1.0)
        self.rf_model = RandomForestRegressor(n_estimators=100, max_depth=4, random_state=42, n_jobs=-1)
        self.scaler   = StandardScaler()
        self._trained = False

    def train(self, enriched_list: list[dict]) -> None:
        X, y = [], []
        for e in enriched_list:
            if not e or e.get("latest_fcf", 0) <= 0:
                continue
            if not e.get("dcf_reliable", True):
                continue
            X.append(_build_features(e))
            y.append(_clamp(e.get("fcf_growth", 0)))
        if len(X) < 5:
            log.warning("Too few samples — rule-based only.")
            return
        X_arr    = np.array(X)
        y_arr    = np.array(y)
        X_scaled = self.scaler.fit_transform(X_arr)
        self.lr_model.fit(X_scaled, y_arr)
        self.rf_model.fit(X_arr,    y_arr)
        self._trained = True
        log.info(f"Trained on {len(X)} stocks.")

    def predict_growth_rate(self, enriched: dict) -> float:
        rule_g = _rule_based_growth(enriched)
        if not self._trained:
            return rule_g
        feats  = _build_features(enriched).reshape(1, -1)
        lr_g   = _clamp(float(self.lr_model.predict(self.scaler.transform(feats))[0]))
        rf_g   = _clamp(float(self.rf_model.predict(feats)[0]))
        return _clamp(float(np.dot(BLEND_WEIGHTS, [lr_g, rf_g, rule_g])))

    def predict(self, enriched: dict, years: int = FORECAST_YEARS) -> dict:
        ticker      = enriched.get("ticker", "?")

        # CRITICAL: Skip unreliable companies
        if not enriched.get("dcf_reliable", True):
            return {
                "projections":       [0.0] * years,
                "base_growth":       0.0,
                "terminal_fcf_norm": 0.0,
                "fcf_base":          0.0,
                "fcf_base_method":   "unreliable",
                "growth_schedule":   [0.0] * years,
                "reliable":          False,
            }

        fcf_base, method = _compute_fcf_base(enriched)

        # If FCF base is 0 or negative after all checks — unreliable
        if fcf_base <= 0:
            log.warning(f"[{ticker}] FCF base = 0 after all methods — marking unreliable")
            return {
                "projections":       [0.0] * years,
                "base_growth":       0.0,
                "terminal_fcf_norm": 0.0,
                "fcf_base":          0.0,
                "fcf_base_method":   "unreliable_zero_fcf",
                "growth_schedule":   [0.0] * years,
                "reliable":          False,
            }

        base_growth     = self.predict_growth_rate(enriched)
        projections     = []
        growth_schedule = []
        fcf = fcf_base

        for yr in range(1, years + 1):
            g = _clamp(_exponential_fade(yr, base_growth))
            fcf = fcf * (1 + g)
            projections.append(fcf)
            growth_schedule.append(g)

        terminal_norm = float(np.mean(projections[-3:])) if len(projections) >= 3 else projections[-1]

        log.debug(f"[{ticker}] base={fcf_base/1e9:.2f}B ({method}) g0={base_growth:.2%} g10={growth_schedule[-1]:.2%}")

        return {
            "projections":       projections,
            "base_growth":       base_growth,
            "terminal_fcf_norm": terminal_norm,
            "fcf_base":          fcf_base,
            "fcf_base_method":   method,
            "growth_schedule":   growth_schedule,
            "reliable":          True,
        }

    def save(self, path: str = MODEL_SAVE_PATH) -> None:
        Path(path).parent.mkdir(parents=True, exist_ok=True)
        with open(path, "wb") as f:
            pickle.dump(self, f)

    @classmethod
    def load(cls, path: str = MODEL_SAVE_PATH) -> "FCFForecaster":
        with open(path, "rb") as f:
            return pickle.load(f)
