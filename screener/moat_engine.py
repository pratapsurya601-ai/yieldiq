# screener/moat_engine.py
# ═══════════════════════════════════════════════════════════════
# ECONOMIC MOAT ENGINE
# ═══════════════════════════════════════════════════════════════
#
# Scores economic moat on 5 signals × 20 points = 100 total
#
# Signal 1: Pricing Power       — operating margin trend
# Signal 2: ROIC Quality        — ROIC vs WACC spread + consistency
# Signal 3: Revenue Stability   — low volatility + consistent growth
# Signal 4: FCF Superiority     — FCF margin vs sector median
# Signal 5: Reinvestment ROI    — revenue growth per unit of capex
#
# Grades:
#   Wide   (70-100) : +15% IV premium, WACC -0.5%, growth +1.5%
#   Narrow (40-69)  : +5%  IV premium, WACC  0%,   growth +0.5%
#   None   (0-39)   : -5%  IV discount, WACC +0.5%, growth -0.5%
#
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
import pandas as pd
from utils.logger import get_logger

log = get_logger(__name__)


# ── Sector median FCF margins (for FCF Superiority signal) ──────
SECTOR_MEDIAN_FCF_MARGIN = {
    "it_services":     0.18,
    "fmcg":            0.14,
    "pharma":          0.12,
    "consumer_durable":0.10,
    "hospital":        0.08,
    "auto_oem":        0.07,
    "auto_ancillary":  0.06,
    "capital_goods":   0.07,
    "cement":          0.08,
    "chemicals":       0.10,
    "oil_gas":         0.09,
    "metals":          0.06,
    "power":           0.12,
    "telecom":         0.10,
    "realty":          0.08,
    "airlines":        0.04,
    "logistics":       0.07,
    "defence":         0.09,
    "general":         0.08,
}


# ── Signal 1: Pricing Power ─────────────────────────────────────
def _signal_pricing_power(enriched: dict) -> tuple[int, str]:
    """
    Measures ability to sustain/expand margins over time.
    Expanding margins = pricing power = moat.
    Score 0-20.
    """
    income_df = enriched.get("income_df", pd.DataFrame())
    op_margin = enriched.get("op_margin", 0)

    if income_df is None or income_df.empty:
        if op_margin >= 0.20:
            return 12, f"High margin {op_margin:.1%} but no trend data"
        return 8, "No historical data"

    try:
        if "operating_income" in income_df.columns and "revenue" in income_df.columns:
            valid = income_df[income_df["revenue"] > 0].copy()
            valid["margin"] = valid["operating_income"] / valid["revenue"]
            margins = valid["margin"].dropna().tolist()
        elif "op_margin" in income_df.columns:
            margins = income_df["op_margin"].dropna().tolist()
        else:
            margins = []

        if len(margins) < 2:
            # Fall back to point-in-time margin
            if op_margin >= 0.25: return 16, f"Strong margin {op_margin:.1%}"
            if op_margin >= 0.15: return 12, f"Good margin {op_margin:.1%}"
            if op_margin >= 0.08: return 8,  f"Average margin {op_margin:.1%}"
            return 4, f"Weak margin {op_margin:.1%}"

        # Trend: compare first half vs second half
        mid   = len(margins) // 2
        early = np.mean(margins[:mid])
        late  = np.mean(margins[mid:])
        trend = late - early

        # Absolute level bonus
        level_score = (
            8 if op_margin >= 0.25 else
            6 if op_margin >= 0.15 else
            4 if op_margin >= 0.08 else 2
        )
        # Trend bonus
        trend_score = (
            12 if trend > 0.03 else
            10 if trend > 0.01 else
            8  if trend > -0.01 else
            5  if trend > -0.03 else 2
        )
        score  = min(level_score + trend_score, 20)
        detail = f"Margin trend: {early:.1%}→{late:.1%} ({trend:+.1%}), level={op_margin:.1%}"
        return score, detail

    except Exception as e:
        log.debug(f"Pricing power signal error: {e}")
        return 8, "Calculation error"


# ── Signal 2: ROIC Quality ──────────────────────────────────────
def _signal_roic_quality(enriched: dict, wacc: float) -> tuple[int, str]:
    """
    ROIC vs WACC spread. Consistent above-WACC ROIC = strong moat.
    Score 0-20.
    """
    op_margin  = enriched.get("op_margin",      0)
    latest_rev = enriched.get("latest_revenue", 0)
    total_debt = enriched.get("total_debt",     0)
    total_cash = enriched.get("total_cash",     0)
    tax_rate   = 0.25

    if latest_rev <= 0 or op_margin <= 0:
        return 4, "Cannot compute ROIC — no revenue/margin"

    nopat = latest_rev * op_margin * (1 - tax_rate)
    # Invested capital proxy: debt + 40% of revenue (tangible assets)
    ic    = max(total_debt + latest_rev * 0.40, latest_rev * 0.10)
    roic  = nopat / ic if ic > 0 else 0
    spread = roic - wacc

    # ROIC consistency from income history
    income_df = enriched.get("income_df", pd.DataFrame())
    consistency_bonus = 0
    if income_df is not None and not income_df.empty:
        try:
            if "operating_income" in income_df.columns and "revenue" in income_df.columns:
                valid = income_df[income_df["revenue"] > 0]
                margins = (valid["operating_income"] / valid["revenue"]).dropna().tolist()
                if len(margins) >= 3:
                    all_positive = all(m > 0 for m in margins)
                    cv = np.std(margins) / np.mean(margins) if np.mean(margins) > 0 else 1
                    if all_positive and cv < 0.15: consistency_bonus = 4
                    elif all_positive and cv < 0.30: consistency_bonus = 2
        except Exception:
            pass

    spread_score = (
        12 if spread > 0.15 else
        10 if spread > 0.08 else
        8  if spread > 0.03 else
        5  if spread > 0    else
        2  if spread > -0.05 else 0
    )
    score  = min(spread_score + consistency_bonus, 20)
    detail = f"ROIC={roic:.1%}, WACC={wacc:.1%}, Spread={spread:+.1%}"
    return score, detail


# ── Signal 3: Revenue Stability ─────────────────────────────────
def _signal_revenue_stability(enriched: dict) -> tuple[int, str]:
    """
    Low revenue volatility + consistent growth = stable business.
    Score 0-20.
    """
    income_df  = enriched.get("income_df",    pd.DataFrame())
    rev_growth = enriched.get("revenue_growth", 0)

    if income_df is None or income_df.empty:
        if rev_growth >= 0.12: return 12, f"Good growth {rev_growth:.1%}"
        if rev_growth >= 0.06: return 9,  f"Moderate growth {rev_growth:.1%}"
        return 6, f"Low growth {rev_growth:.1%}"

    try:
        if "revenue" not in income_df.columns:
            return 8, "No revenue column"

        revs = income_df["revenue"].replace(0, np.nan).dropna().tolist()
        if len(revs) < 2:
            return 8, "Insufficient data"

        # Coefficient of variation (lower = more stable)
        mean_rev = np.mean(revs)
        cv       = np.std(revs) / mean_rev if mean_rev > 0 else 1

        # Year-over-year growth consistency
        yoy = [(revs[i] - revs[i-1]) / revs[i-1] for i in range(1, len(revs))]
        pct_positive = sum(1 for g in yoy if g > 0) / len(yoy) if yoy else 0

        cv_score = (
            8 if cv < 0.10 else
            6 if cv < 0.20 else
            4 if cv < 0.35 else 2
        )
        consistency_score = (
            12 if pct_positive >= 0.90 else
            10 if pct_positive >= 0.75 else
            7  if pct_positive >= 0.60 else
            4  if pct_positive >= 0.40 else 1
        )
        score  = min(cv_score + consistency_score, 20)
        detail = f"CV={cv:.2f}, {pct_positive:.0%} years grew, CAGR={rev_growth:.1%}"
        return score, detail

    except Exception as e:
        log.debug(f"Revenue stability error: {e}")
        return 8, "Calculation error"


# ── Signal 4: FCF Superiority ───────────────────────────────────
def _signal_fcf_superiority(enriched: dict) -> tuple[int, str]:
    """
    FCF margin vs sector median. Above-median FCF = competitive advantage.
    Score 0-20.
    """
    latest_rev = enriched.get("latest_revenue", 0)
    latest_fcf = enriched.get("latest_fcf",     0)
    sector     = enriched.get("sector",          "general")
    cf_df      = enriched.get("cf_df",           pd.DataFrame())

    if latest_rev <= 0:
        return 4, "No revenue data"

    fcf_margin = latest_fcf / latest_rev if latest_rev > 0 else 0
    median_fcf = SECTOR_MEDIAN_FCF_MARGIN.get(sector, 0.08)

    # Historical FCF consistency
    fcf_consistency = 0
    if cf_df is not None and not cf_df.empty and "fcf" in cf_df.columns:
        try:
            fcf_vals = cf_df["fcf"].dropna().tolist()
            if len(fcf_vals) >= 2:
                pct_pos = sum(1 for f in fcf_vals if f > 0) / len(fcf_vals)
                if pct_pos >= 0.90: fcf_consistency = 4
                elif pct_pos >= 0.75: fcf_consistency = 2
        except Exception:
            pass

    premium = fcf_margin - median_fcf
    margin_score = (
        14 if premium > 0.08 else
        12 if premium > 0.04 else
        10 if premium > 0.01 else
        7  if premium > -0.02 else
        4  if premium > -0.05 else 1
    )
    score  = min(margin_score + fcf_consistency, 20)
    detail = f"FCF margin={fcf_margin:.1%}, sector median={median_fcf:.1%}, premium={premium:+.1%}"
    return score, detail


# ── Signal 5: Reinvestment ROI ──────────────────────────────────
def _signal_reinvestment_roi(enriched: dict) -> tuple[int, str]:
    """
    Revenue growth per unit of capex invested = reinvestment quality.
    High ROIC on incremental capex = compounding moat.
    Score 0-20.
    """
    rev_growth = enriched.get("revenue_growth", 0)
    op_margin  = enriched.get("op_margin",      0)
    latest_rev = enriched.get("latest_revenue", 0)
    cf_df      = enriched.get("cf_df",          pd.DataFrame())
    tax_rate   = 0.25

    if latest_rev <= 0 or rev_growth <= 0:
        return 6, "No growth to evaluate reinvestment quality"

    # Estimate capex intensity
    capex_intensity = 0.05  # default
    if cf_df is not None and not cf_df.empty and "capex" in cf_df.columns:
        try:
            capex_vals = cf_df["capex"].dropna()
            capex_vals = capex_vals[capex_vals != 0]
            if len(capex_vals) >= 1:
                rev_vals = None
                if "revenue" in cf_df.columns:
                    rev_vals = cf_df["revenue"].replace(0, np.nan).dropna()
                income_df = enriched.get("income_df", pd.DataFrame())
                if (rev_vals is None or len(rev_vals) == 0) and income_df is not None and not income_df.empty and "revenue" in income_df.columns:
                    rev_vals = income_df["revenue"].replace(0, np.nan).dropna()
                if rev_vals is not None and len(rev_vals) > 0:
                    avg_rev   = float(rev_vals.mean())
                    avg_capex = abs(float(capex_vals.mean()))
                    if avg_rev > 0:
                        capex_intensity = avg_capex / avg_rev
        except Exception:
            pass

    # Reinvestment ROI = revenue growth × op margin × (1-tax) / capex_intensity
    reinv_roi = (rev_growth * op_margin * (1 - tax_rate)) / capex_intensity if capex_intensity > 0 else 0

    score = (
        18 if reinv_roi > 0.15 else
        15 if reinv_roi > 0.08 else
        12 if reinv_roi > 0.04 else
        9  if reinv_roi > 0.02 else
        6  if reinv_roi > 0    else 3
    )
    detail = f"Reinv ROI={reinv_roi:.2f} (growth={rev_growth:.1%}, margin={op_margin:.1%}, capex={capex_intensity:.1%})"
    return score, detail


# ── Moat Type Detection ─────────────────────────────────────────
def _detect_moat_types(enriched: dict, score: int) -> list[str]:
    """Detect specific moat sources from sector + financials + ticker."""
    moat_types = []
    sector     = enriched.get("sector",     "general")
    ticker     = enriched.get("ticker",     "").lower().replace(".ns","").replace(".bo","")
    op_margin  = enriched.get("op_margin",  0)
    rev_growth = enriched.get("revenue_growth", 0)

    if score < 30:
        return []

    # Regulatory / licensing moat
    REGULATORY = ["ongc","bpcl","hindpetro","ioc","gail","coalindia","ntpc","powergrid",
                  "irctc","concor","hal","bel","beml","cochinship","mazagon","grse",
                  "nationalum","nmdc","moil","atgl","igl","mgl"]
    if sector in ["oil_gas","power","defence"] or any(t in ticker for t in REGULATORY):
        moat_types.append("Regulatory / licensing moat")

    # Cost efficiency moat
    if sector in ["it_services","pharma","chemicals"] and op_margin >= 0.15:
        moat_types.append("Cost efficiency moat")

    # Brand / pricing power moat
    BRAND = ["itc","hindunilvr","nestle","britannia","dabur","marico","colpal","titan",
             "asianpaint","pidilitind","bajajfinsv","hdfc","kotak","bajajcon",
             "emami","godrejcp","jyothy"]
    if sector in ["fmcg","consumer_durable"] or any(t in ticker for t in BRAND):
        moat_types.append("Brand / pricing power moat")

    # Switching cost moat
    SWITCHING = ["tcs","infy","wipro","hcltech","techm","ltim","persistent",
                 "coforge","mphasis","kpittech","tataelxsi"]
    if sector == "it_services" or any(t in ticker for t in SWITCHING):
        moat_types.append("Switching cost moat")

    # Network effect moat
    NETWORK = ["nse","bse","cdsl","nsdl","bajfinance","bajajfinsv","hdfc",
               "icicibank","kotakbank","axisbank","sbicard","muthootfin"]
    if any(t in ticker for t in NETWORK):
        moat_types.append("Network effect moat")

    # Scale / distribution moat
    SCALE = ["tcs","infy","hcltech","maruti","tatasteel","jswsteel","ultracemco",
             "ambuja","hindunilvr","britannia","reliance","ongc","coalindia",
             "ntpc","powergrid","asianpaint","pidilitind","titan","bajfinance",
             "mankind","sunpharma","drreddy","cipla"]
    if any(t in ticker for t in SCALE) and score >= 50:
        moat_types.append("Scale / distribution moat")

    # Conglomerate optionality
    CONGLOM = ["reliance","tatamotors","adanient","mahindra","bajajfinsv"]
    if any(t in ticker for t in CONGLOM):
        moat_types.append("Conglomerate optionality moat")

    return moat_types[:3]  # cap at 3 most relevant


# ── Master Function ─────────────────────────────────────────────
def compute_moat_score(enriched: dict, wacc: float) -> dict:
    """
    Compute economic moat score 0-100 and grade.
    Returns dict with score, grade, moat_types, signals, summary.
    """
    ticker = enriched.get("ticker", "?")

    # DCF unreliable companies (banks, fin services) → skip moat
    if not enriched.get("dcf_reliable", True):
        return {
            "score": 0, "grade": "None",
            "moat_types": [], "summary": "DCF unreliable — moat not assessed",
            "signals": {}, "wacc_adj": 0, "growth_adj": 0, "iv_delta_pct": 0,
        }

    # Op margin < 8% → commodity / no-moat business
    op_margin = enriched.get("op_margin", 0)
    if op_margin < 0.05:
        return {
            "score": 15, "grade": "None",
            "moat_types": [],
            "summary": f"Op margin {op_margin:.1%} too low — no moat signal",
            "signals": {}, "wacc_adj": 0, "growth_adj": 0, "iv_delta_pct": 0,
        }

    # ── Run all 5 signals ────────────────────────────────────────
    s1, d1 = _signal_pricing_power(enriched)
    s2, d2 = _signal_roic_quality(enriched, wacc)
    s3, d3 = _signal_revenue_stability(enriched)
    s4, d4 = _signal_fcf_superiority(enriched)
    s5, d5 = _signal_reinvestment_roi(enriched)

    total = s1 + s2 + s3 + s4 + s5

    signals = {
        "Pricing Power":   (s1, d1),
        "ROIC Quality":    (s2, d2),
        "Rev Stability":   (s3, d3),
        "FCF Superiority": (s4, d4),
        "Reinvestment ROI":(s5, d5),
    }

    # ── Grade ────────────────────────────────────────────────────
    if total >= 70:
        grade = "Wide"
    elif total >= 40:
        grade = "Narrow"
    else:
        grade = "None"

    # ── Large-cap floor ─────────────────────────────────────────
    # Companies with massive revenue + positive FCF can't truly be "None"
    latest_rev = enriched.get("latest_revenue", 0)
    latest_fcf = enriched.get("latest_fcf", 0)
    if grade == "None" and latest_rev > 500_000_000_000 and latest_fcf > 0:
        grade = "Narrow"
        total = max(total, 42)

    # ── Moat types ───────────────────────────────────────────────
    moat_types = _detect_moat_types(enriched, total)

    # ── Summary ──────────────────────────────────────────────────
    if grade == "None":
        summary = f"No identifiable moat. Score {total}/100."
    elif moat_types:
        summary = f"{grade} moat driven by {', '.join(moat_types[:2])}. Score {total}/100."
    else:
        summary = f"{grade} moat. Score {total}/100."

    log.info(f"[{ticker}] Moat: {grade} ({total}/100) — {', '.join(moat_types) if moat_types else summary}")

    return {
        "score":      total,
        "grade":      grade,
        "moat_types": moat_types,
        "summary":    summary,
        "signals":    signals,
    }


# ── Apply Moat Adjustments to DCF Inputs ────────────────────────
def apply_moat_adjustments(
    moat_result: dict,
    wacc:        float,
    base_growth: float,
    terminal_g:  float,
    iv:          float,
    sector:      str = "general",
) -> dict:
    """
    Translate moat grade into DCF input adjustments.
    Returns adjusted WACC, growth, terminal_g, and IV delta %.
    """
    grade = moat_result.get("grade", "None")
    score = moat_result.get("score", 0)

    if grade == "Wide":
        wacc_delta    = -0.005        # -0.5% WACC (lower risk)
        growth_delta  = +0.015        # +1.5% FCF growth
        term_g_delta  = +0.005        # +0.5% terminal growth
        iv_delta_pct  = +15.0         # +15% IV premium
    elif grade == "Narrow":
        wacc_delta    = 0.0
        growth_delta  = +0.005
        term_g_delta  = 0.0
        iv_delta_pct  = +5.0
    else:
        wacc_delta    = +0.005        # +0.5% WACC (higher risk)
        growth_delta  = -0.005
        term_g_delta  = -0.005
        iv_delta_pct  = -5.0

    return {
        "adj_wacc":      max(wacc + wacc_delta, 0.08),
        "adj_growth":    base_growth + growth_delta,
        "adj_terminal_g":max(min(terminal_g + term_g_delta, 0.045), 0.02),
        "iv_delta_pct":  iv_delta_pct,
        "wacc_delta":    wacc_delta,
        "growth_delta":  growth_delta,
        "grade":         grade,
        "score":         score,
    }
