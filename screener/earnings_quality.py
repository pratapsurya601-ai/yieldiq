# screener/earnings_quality.py
# ═══════════════════════════════════════════════════════════════
# EARNINGS QUALITY SCORE
# ═══════════════════════════════════════════════════════════════
#
# Earnings quality measures whether reported profits are REAL.
# Companies can report high earnings while their cash position
# deteriorates through aggressive accrual accounting.
#
# The most famous earnings quality failures:
#   Enron:    Reported $1B profit, actual FCF was negative
#   WorldCom: Capitalised operating expenses → inflated profits
#   Wirecard: Fabricated revenue, negative real FCF
#
# Our 9-factor model scores 0-100:
#
#   CASH CONVERSION (3 factors, 33.75 pts)
#   ──────────────────────────────────────
#   Q1  Accrual ratio (OCF/NI)       — are earnings cash-backed?
#   Q2  FCF/Net income ratio          — what % of profits become FCF?
#   Q3  OCF margin trend              — is cash generation stable/growing?
#
#   EARNINGS STABILITY (2 factors, 22.5 pts)
#   ──────────────────────────────────────
#   Q4  Net income margin consistency — are margins predictable?
#   Q5  Revenue-to-earnings alignment — does revenue drive earnings?
#
#   BALANCE SHEET DISCIPLINE (2 factors, 22.5 pts)
#   ─────────────────────────────────────────────
#   Q6  Capex / OCF ratio             — sustainable investment level?
#   Q7  Gross margin stability        — pricing power holding?
#
#   GROWTH QUALITY (2 factors, 21.25 pts)
#   ─────────────────────────────────────
#   Q8  Earnings growth sustainability — is growth real or cyclical?
#   Q9  Earnings beat rate             — management credibility vs estimates?
#
# Grades:
#   85-100  EXCELLENT  — institutional quality earnings
#   70-84   GOOD       — solid with minor concerns
#   50-69   MODERATE   — mixed signals, watch closely
#   30-49   WEAK       — multiple quality concerns
#   0-29    POOR       — earnings likely overstated
#
# Academic basis:
#   Sloan (1996): High accruals predict stock underperformance
#   Richardson et al. (2005): Accruals and future earnings
#   Beneish (1999): M-Score fraud detection (adapted here)
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
import pandas as pd
from utils.logger import get_logger

log = get_logger(__name__)


# ── GRADE THRESHOLDS ─────────────────────────────────────────
GRADES = [
    (85, 100, "EXCELLENT", "#059669", "#ECFDF5", "#A7F3D0", "🏆"),
    (70,  84, "GOOD",      "#2563EB", "#EFF6FF", "#BFDBFE", "✅"),
    (50,  69, "MODERATE",  "#D97706", "#FFFBEB", "#FDE68A", "⚠️"),
    (30,  49, "WEAK",      "#DC2626", "#FEF2F2", "#FECACA", "🔴"),
    ( 0,  29, "POOR",      "#7F1D1D", "#FEF2F2", "#FECACA", "💀"),
]


def _grade(score: float) -> tuple:
    for lo, hi, label, tc, bg, bd, emoji in GRADES:
        if lo <= score <= hi:
            return label, tc, bg, bd, emoji
    return "MODERATE", "#D97706", "#FFFBEB", "#FDE68A", "⚠️"


def _safe(v, default=0.0) -> float:
    try:
        f = float(v)
        return f if np.isfinite(f) else default
    except Exception:
        return default


def _series(df, col) -> list:
    """Extract a clean series from a dataframe column."""
    if df is None or df.empty or col not in df.columns:
        return []
    return [_safe(v) for v in df[col].dropna().tolist()]


def _yoy_growth(series: list) -> list:
    """Compute year-over-year growth rates."""
    if len(series) < 2:
        return []
    rates = []
    for i in range(1, len(series)):
        prev = series[i-1]
        curr = series[i]
        if prev != 0:
            rates.append((curr - prev) / abs(prev))
    return rates


# ── FACTOR CALCULATORS ────────────────────────────────────────

def _q1_accrual_ratio(income_df, cf_df, enriched) -> tuple[float, str, str]:
    """
    Q1: OCF / Net Income ratio (accrual quality)
    > 1.2  = Excellent (cash exceeds reported earnings)
    0.8-1.2 = Good
    0.5-0.8 = Moderate concern
    < 0.5  = Red flag (accruals inflating earnings)

    Max score: 37.5 (shared with Q2, Q3 — each worth 12.5)
    Returns score 0-100 for this factor.
    """
    ocf_series = _series(cf_df, "ocf")
    ni_series  = _series(income_df, "net_income")

    if not ocf_series or not ni_series:
        # Fallback: use scalar values
        ocf = _safe(enriched.get("yahoo_fcf_ttm", 0)) or _safe(enriched.get("latest_fcf", 0))
        ni  = _safe(enriched.get("latest_revenue", 0)) * _safe(enriched.get("op_margin", 0)) * 0.75
        if ocf <= 0 or ni <= 0:
            return 50.0, "Insufficient data — neutral score", "OCF/NI ratio"
        ratio = ocf / ni
    else:
        # Use multi-year average for robustness
        n = min(len(ocf_series), len(ni_series))
        ratios = []
        for i in range(n):
            ni_v = ni_series[-(n-i)]
            oc_v = ocf_series[-(n-i)]
            if ni_v > 0 and oc_v != 0:
                ratios.append(oc_v / ni_v)
        ratio = float(np.median(ratios)) if ratios else 1.0

    # Score mapping
    if ratio >= 1.3:
        score = 100
        quality = "excellent"
    elif ratio >= 1.0:
        score = 80
        quality = "good"
    elif ratio >= 0.8:
        score = 60
        quality = "moderate"
    elif ratio >= 0.5:
        score = 35
        quality = "weak"
    else:
        score = 10
        quality = "poor"

    detail = f"OCF/NI = {ratio:.2f}× ({quality}) — {'cash earnings exceed' if ratio >= 1 else 'cash earnings BELOW'} reported profits"
    return score, detail, "Operating cash flow ÷ Net income (multi-year median)"


def _q2_fcf_conversion(income_df, cf_df, enriched) -> tuple[float, str, str]:
    """
    Q2: FCF / Net Income — free cash flow conversion ratio
    High ratio means company doesn't need to reinvest all profits.
    """
    fcf_series = _series(cf_df, "fcf")
    ni_series  = _series(income_df, "net_income")

    if not fcf_series or not ni_series:
        fcf = _safe(enriched.get("yahoo_fcf_ttm", 0)) or _safe(enriched.get("latest_fcf", 0))
        rev = _safe(enriched.get("latest_revenue", 0))
        op  = _safe(enriched.get("op_margin", 0))
        ni  = rev * op * 0.75
        if ni <= 0:
            return 50.0, "Insufficient data", "FCF/NI ratio"
        ratio = fcf / ni if fcf > 0 else 0
    else:
        n = min(len(fcf_series), len(ni_series))
        ratios = []
        for i in range(n):
            ni_v  = ni_series[-(n-i)]
            fcf_v = fcf_series[-(n-i)]
            if ni_v > 0 and fcf_v > 0:
                ratios.append(fcf_v / ni_v)
        ratio = float(np.median(ratios)) if ratios else 0.5

    if ratio >= 1.0:
        score, quality = 100, "excellent — FCF exceeds net income"
    elif ratio >= 0.8:
        score, quality = 80, "good — most earnings become FCF"
    elif ratio >= 0.6:
        score, quality = 60, "moderate — significant cash leakage"
    elif ratio >= 0.3:
        score, quality = 35, "weak — large gap between profits and cash"
    else:
        score, quality = 10, "poor — earnings mostly non-cash"

    detail = f"FCF/NI = {ratio:.2f}× ({quality})"
    return score, detail, "Free cash flow ÷ Net income (multi-year median)"


def _q3_ocf_margin_trend(income_df, cf_df, enriched) -> tuple[float, str, str]:
    """
    Q3: OCF margin trend — is operating cash generation stable/improving?
    """
    ocf_series = _series(cf_df, "ocf")
    rev_series = _series(income_df, "revenue")

    if len(ocf_series) < 2 or len(rev_series) < 2:
        margin = _safe(enriched.get("fcf_margin", 0))
        if margin > 0.20:
            return 80, f"OCF margin ~{margin:.1%} (single period)", "FCF margin proxy"
        elif margin > 0.10:
            return 60, f"OCF margin ~{margin:.1%}", "FCF margin proxy"
        else:
            return 40, f"OCF margin ~{margin:.1%}", "FCF margin proxy"

    n = min(len(ocf_series), len(rev_series))
    margins = []
    for i in range(n):
        rev = rev_series[-(n-i)]
        ocf = ocf_series[-(n-i)]
        if rev > 0:
            margins.append(ocf / rev)

    if not margins:
        return 50, "Insufficient data", "OCF margin trend"

    avg_margin  = float(np.mean(margins))
    trend       = margins[-1] - margins[0] if len(margins) > 1 else 0
    consistency = float(np.std(margins)) if len(margins) > 1 else 0

    # Score: high margin + improving + consistent = best
    if avg_margin >= 0.20 and trend >= 0:
        score, detail_txt = 90, f"avg {avg_margin:.1%}, improving"
    elif avg_margin >= 0.15 and trend >= -0.02:
        score, detail_txt = 75, f"avg {avg_margin:.1%}, stable"
    elif avg_margin >= 0.10:
        score, detail_txt = 55, f"avg {avg_margin:.1%}, moderate"
    elif avg_margin >= 0.05:
        score, detail_txt = 35, f"avg {avg_margin:.1%}, low"
    else:
        score, detail_txt = 15, f"avg {avg_margin:.1%}, very low"

    if trend < -0.05:
        score = max(score - 20, 5)
        detail_txt += f" ⚠️ declining {trend*100:.1f}pp"

    detail = f"OCF margin: {detail_txt} (consistency: {consistency*100:.1f}pp std dev)"
    return float(score), detail, "OCF ÷ Revenue over time"


def _q4_margin_consistency(income_df, cf_df, enriched) -> tuple[float, str, str]:
    """
    Q4: Net income margin consistency — predictable earnings = quality earnings
    Companies that manipulate earnings show erratic margins.
    """
    ni_series  = _series(income_df, "net_income")
    rev_series = _series(income_df, "revenue")

    if len(ni_series) < 2 or len(rev_series) < 2:
        return 50, "Insufficient history", "NI margin consistency"

    n = min(len(ni_series), len(rev_series))
    margins = []
    for i in range(n):
        rev = rev_series[-(n-i)]
        ni  = ni_series[-(n-i)]
        if rev > 0:
            margins.append(ni / rev)

    if not margins:
        return 50, "Cannot compute", "NI margin consistency"

    avg_margin = float(np.mean(margins))
    std_margin = float(np.std(margins)) if len(margins) > 1 else 0
    cv         = std_margin / abs(avg_margin) if avg_margin != 0 else 999  # coeff of variation

    # Low CV = consistent margins = high quality
    if cv < 0.10:
        score, quality = 95, "very consistent"
    elif cv < 0.20:
        score, quality = 80, "consistent"
    elif cv < 0.35:
        score, quality = 60, "moderate variation"
    elif cv < 0.60:
        score, quality = 35, "volatile"
    else:
        score, quality = 15, "very volatile — earnings manipulation risk"

    # Additional check: if margins are trending strongly upward,
    # volatility may reflect expansion not manipulation → partial credit
    margins_list = margins  # already computed above
    if len(margins_list) >= 3:
        trend = margins_list[-1] - margins_list[0]
        if trend > 0.15 and cv > 0.25:
            # Improving margins with apparent volatility = growth phase, not manipulation
            score = min(score + 20, 80)
            quality += " (margin expansion phase — upward trend reduces concern)"

    detail = (
        f"NI margin avg {avg_margin:.1%}, std {std_margin*100:.1f}pp — "
        f"{quality} (CV={cv:.2f})"
    )
    return float(score), detail, "Coefficient of variation of net income margins"


def _q5_revenue_earnings_alignment(income_df, cf_df, enriched) -> tuple[float, str, str]:
    """
    Q5: Revenue growth vs Earnings growth alignment
    If earnings grow faster than revenue consistently, it's a warning sign.
    Real productivity gains are fine; accounting tricks are not.
    """
    ni_series  = _series(income_df, "net_income")
    rev_series = _series(income_df, "revenue")

    if len(ni_series) < 2 or len(rev_series) < 2:
        rev_g = _safe(enriched.get("revenue_growth", 0))
        fcf_g = _safe(enriched.get("fcf_growth", 0))
        if abs(rev_g - fcf_g) < 0.10:
            return 75, "Revenue and FCF growth roughly aligned", "Revenue vs FCF growth"
        elif fcf_g > rev_g + 0.15:
            return 85, f"FCF growing faster than revenue ({fcf_g:.1%} vs {rev_g:.1%}) — operating leverage", "FCF vs revenue growth"
        else:
            return 55, f"FCF growth ({fcf_g:.1%}) lags revenue ({rev_g:.1%})", "FCF vs revenue growth"

    ni_growth  = _yoy_growth(ni_series)
    rev_growth = _yoy_growth(rev_series)

    if not ni_growth or not rev_growth:
        return 50, "Insufficient data", "Revenue vs earnings alignment"

    n = min(len(ni_growth), len(rev_growth))
    misalignments = 0
    big_gaps_bad  = 0   # earnings >> revenue AND revenue is flat/declining
    big_gaps_good = 0   # earnings >> revenue BUT revenue is also growing (operating leverage)

    for i in range(n):
        rev_g = rev_growth[-(n-i)]
        ni_g  = ni_growth[-(n-i)]
        gap   = ni_g - rev_g
        if abs(gap) > 0.10:
            misalignments += 1
        if gap > 0.25:
            # Distinguish operating leverage from manipulation:
            # If revenue is also growing strongly (>10%), this is GOOD (operating leverage)
            # If revenue is flat/declining while earnings surge, this is BAD (manipulation)
            if rev_g < 0.10:
                big_gaps_bad += 1   # earnings surging while revenue stagnant → red flag
            else:
                big_gaps_good += 1  # operating leverage → neutral/positive

    align_rate = 1 - (misalignments / n) if n > 0 else 0.5

    if big_gaps_bad >= 2:
        score = 25
        detail = (f"Earnings grew much faster than flat/declining revenue {big_gaps_bad}× "
                  f"— potential accounting concern")
    elif big_gaps_good >= 2:
        # Operating leverage: revenue AND earnings both growing — GOOD
        score = 80
        detail = (f"Earnings grew faster than revenue {big_gaps_good}× "
                  f"— operating leverage effect (revenue also growing strongly)")
    elif align_rate >= 0.75:
        score = 85
        detail = f"Revenue and earnings well aligned ({align_rate:.0%} of years)"
    elif align_rate >= 0.50:
        score = 65
        detail = f"Moderate alignment ({align_rate:.0%} of years)"
    else:
        score = 40
        detail = f"Poor alignment ({align_rate:.0%} of years) — check for one-off items"

    return float(score), detail, "Year-over-year revenue growth vs earnings growth"


def _q6_capex_discipline(income_df, cf_df, enriched) -> tuple[float, str, str]:
    """
    Q6: Capex / OCF — sustainable investment?
    Very high capex vs OCF = company spending more than it generates
    (potential sign of distress or aggressive accounting of maintenance as investment)
    """
    ocf_series   = _series(cf_df, "ocf")
    capex_series = _series(cf_df, "capex")

    if not ocf_series or not capex_series:
        capex_int = _safe(enriched.get("capex_intensity", 0.05))
        # capex_intensity is capex as % of revenue
        # OCF margin proxy
        ocf_margin = _safe(enriched.get("fcf_margin", 0)) + capex_int
        if ocf_margin > 0:
            ratio = capex_int / ocf_margin
        else:
            ratio = 0.3
    else:
        n = min(len(ocf_series), len(capex_series))
        ratios = []
        for i in range(n):
            ocf   = ocf_series[-(n-i)]
            capex = abs(capex_series[-(n-i)])
            if ocf > 0:
                ratios.append(capex / ocf)
        ratio = float(np.median(ratios)) if ratios else 0.3

    if ratio <= 0.15:
        score, quality = 95, "very low — highly capital-light"
    elif ratio <= 0.30:
        score, quality = 85, "low — capital-efficient"
    elif ratio <= 0.50:
        score, quality = 70, "moderate — normal for industry"
    elif ratio <= 0.75:
        score, quality = 45, "high — watch maintenance vs growth capex"
    else:
        score, quality = 20, "very high — capex consuming most OCF"

    detail = f"Capex/OCF = {ratio:.2f}× ({quality})"
    return float(score), detail, "Capital expenditure as % of operating cash flow"


def _q7_gross_margin_stability(income_df, cf_df, enriched) -> tuple[float, str, str]:
    """
    Q7: Gross margin trend and stability
    Declining gross margins = pricing pressure or rising costs
    Revenue growth with declining margins = quality concern
    """
    ni_series  = _series(income_df, "net_income")
    rev_series = _series(income_df, "revenue")
    op_series  = _series(income_df, "operating_income")

    # Use operating margin as proxy for gross margin if no gross margin data
    if len(op_series) >= 2 and len(rev_series) >= 2:
        n = min(len(op_series), len(rev_series))
        margins = [op_series[-(n-i)] / rev_series[-(n-i)]
                   for i in range(n) if rev_series[-(n-i)] > 0]
        margin_label = "Operating margin"
    else:
        gm = _safe(enriched.get("gross_margin", 0))
        op = _safe(enriched.get("op_margin", 0))
        if gm > 0:
            return (85 if gm > 0.40 else 70 if gm > 0.25 else 55 if gm > 0.15 else 35,
                    f"Gross margin = {gm:.1%} (single period)",
                    "Current gross margin")
        elif op > 0:
            return (80 if op > 0.20 else 65 if op > 0.10 else 45,
                    f"Op. margin = {op:.1%} (single period)",
                    "Current operating margin")
        return 50, "Insufficient data", "Gross margin stability"

    if not margins:
        return 50, "Cannot compute margins", margin_label

    avg_m  = float(np.mean(margins))
    trend  = margins[-1] - margins[0] if len(margins) > 1 else 0
    std_m  = float(np.std(margins)) if len(margins) > 1 else 0

    # Base score on level
    if avg_m >= 0.30:
        base = 85
    elif avg_m >= 0.20:
        base = 75
    elif avg_m >= 0.12:
        base = 60
    elif avg_m >= 0.06:
        base = 40
    else:
        base = 20

    # Adjust for trend
    if trend > 0.03:
        base = min(base + 10, 100)
    elif trend < -0.05:
        base = max(base - 20, 5)
    elif trend < -0.02:
        base = max(base - 10, 5)

    direction = "improving" if trend > 0.01 else "declining" if trend < -0.01 else "stable"
    detail = (
        f"{margin_label}: avg {avg_m:.1%}, {direction} "
        f"({trend*100:+.1f}pp trend, {std_m*100:.1f}pp std dev)"
    )
    return float(base), detail, f"{margin_label} level and trend"


def _q8_growth_sustainability(income_df, cf_df, enriched) -> tuple[float, str, str]:
    """
    Q8: Growth sustainability — is earnings growth real and repeatable?
    Checks: FCF growth vs reported growth, consistency of FCF generation
    """
    fcf_series = _series(cf_df, "fcf")
    ni_series  = _series(income_df, "net_income")

    fcf_g = _safe(enriched.get("fcf_growth", 0))
    rev_g = _safe(enriched.get("revenue_growth", 0))

    if len(fcf_series) >= 2 and len(ni_series) >= 2:
        fcf_growth = _yoy_growth(fcf_series)
        ni_growth  = _yoy_growth(ni_series)

        if fcf_growth and ni_growth:
            avg_fcf_g = float(np.mean(fcf_growth[-3:]))  # last 3 years
            avg_ni_g  = float(np.mean(ni_growth[-3:]))
            # Positive FCF growth + FCF growing at least 70% as fast as NI
            gap = avg_ni_g - avg_fcf_g

            if avg_fcf_g > 0.05 and gap < 0.10:
                score = 90
                detail = f"FCF growing {avg_fcf_g:.1%}/yr, in line with earnings ({avg_ni_g:.1%}/yr)"
            elif avg_fcf_g > 0 and gap < 0.20:
                score = 70
                detail = f"FCF growing {avg_fcf_g:.1%}/yr vs earnings {avg_ni_g:.1%}/yr — moderate quality"
            elif avg_fcf_g <= 0:
                score = 25
                detail = f"FCF declining {avg_fcf_g:.1%}/yr while earnings show {avg_ni_g:.1%}/yr — red flag"
            else:
                score = 45
                detail = f"FCF ({avg_fcf_g:.1%}/yr) significantly lagging earnings ({avg_ni_g:.1%}/yr)"
            return float(score), detail, "FCF growth vs earnings growth (3-year avg)"

    # Fallback: use enriched growth rates
    if fcf_g > 0.10 and abs(fcf_g - rev_g) < 0.10:
        score = 85
        detail = f"FCF and revenue both growing ~{fcf_g:.1%}/yr — sustainable"
    elif fcf_g > 0.05:
        score = 70
        detail = f"FCF growing {fcf_g:.1%}/yr"
    elif fcf_g > 0:
        score = 55
        detail = f"FCF growing slowly at {fcf_g:.1%}/yr"
    else:
        score = 30
        detail = f"FCF growth flat/negative ({fcf_g:.1%}/yr)"

    return float(score), detail, "FCF growth sustainability"


def _q9_earnings_beat_rate(income_df, cf_df, enriched) -> tuple[float, str, str]:
    """
    Q9: Earnings surprise beat rate vs analyst estimates.

    Measures management credibility (conservative guidance) and real earnings
    power. Companies that consistently beat estimates tend to have:
      • Conservative, realistic guidance (management quality signal)
      • Genuine earnings power, not just accounting optionality
      • Positive analyst sentiment momentum

    Score mapping
    -------------
    ≥87.5% (7/8) beat rate → 95  Exceptional
    ≥75.0% (6/8)           → 82  Strong
    ≥62.5% (5/8)           → 68  Above average
    ≥50.0% (4/8)           → 55  Average
    ≥37.5% (3/8)           → 38  Below average
    < 37.5%                → 18  Poor / consistent misses

    Trend modifier  : Accelerating → +8 pts  |  Decelerating → −5 pts
    Magnitude boost : avg surprise > +5% → +3 pts
    Magnitude drag  : avg surprise < −3% → −5 pts
    """
    etr = enriched.get("earnings_track_record", {})
    if not etr or etr.get("num_quarters", 0) < 2:
        return 50.0, "Insufficient earnings surprise data (need Finnhub API key)", "EPS beat rate vs analyst estimates"

    beat_rate = float(etr.get("beat_rate", 0.5))
    avg_surp  = float(etr.get("avg_surprise_pct", 0))
    trend     = etr.get("trend", "Mixed")
    n_q       = int(etr.get("num_quarters", 0))

    if beat_rate >= 0.875:
        base, quality = 95, "exceptional — beats nearly every quarter"
    elif beat_rate >= 0.75:
        base, quality = 82, "strong — beats most quarters"
    elif beat_rate >= 0.625:
        base, quality = 68, "above average"
    elif beat_rate >= 0.50:
        base, quality = 55, "average — beats half of quarters"
    elif beat_rate >= 0.375:
        base, quality = 38, "below average"
    else:
        base, quality = 18, "poor — consistent misses"

    # Trend modifier
    if trend == "Accelerating Beats":
        base = min(base + 8, 100)
    elif trend == "Consistent Misses":
        base = max(base - 12, 5)
    elif trend == "Decelerating":
        base = max(base - 5, 5)

    # Magnitude modifiers
    if avg_surp > 5.0:
        base = min(base + 3, 100)
    elif avg_surp < -3.0:
        base = max(base - 5, 5)

    detail = (
        f"Beat rate {beat_rate:.0%} over {n_q}Q ({quality}). "
        f"Avg surprise: {avg_surp:+.1f}%. Trend: {trend}."
    )
    return float(base), detail, "EPS beat rate vs analyst estimates (Finnhub)"


# ── WEIGHTS ──────────────────────────────────────────────────
# Total = 100 pts
# Q1-Q8 each at 11.25 pts (8 × 11.25 = 90) + Q9 at 10 pts = 100
FACTORS = [
    # (key, label, category, weight, fn)
    ("q1", "Accrual ratio (OCF/NI)",       "Cash Conversion",      11.25, _q1_accrual_ratio),
    ("q2", "FCF conversion ratio",          "Cash Conversion",      11.25, _q2_fcf_conversion),
    ("q3", "OCF margin trend",              "Cash Conversion",      11.25, _q3_ocf_margin_trend),
    ("q4", "Margin consistency",            "Earnings Stability",   11.25, _q4_margin_consistency),
    ("q5", "Revenue-earnings alignment",    "Earnings Stability",   11.25, _q5_revenue_earnings_alignment),
    ("q6", "Capex discipline",              "Balance Sheet",        11.25, _q6_capex_discipline),
    ("q7", "Gross margin stability",        "Balance Sheet",        11.25, _q7_gross_margin_stability),
    ("q8", "Growth sustainability",         "Growth Quality",       11.25, _q8_growth_sustainability),
    ("q9", "Earnings beat rate",            "Growth Quality",       10.00, _q9_earnings_beat_rate),
]


# ── MAIN FUNCTION ────────────────────────────────────────────

def compute_earnings_quality(enriched: dict) -> dict:
    """
    Compute 0-100 Earnings Quality Score.

    Returns full breakdown with category scores, individual signals,
    overall grade, and plain-English summary.
    """
    ticker    = enriched.get("ticker", "?")
    income_df = enriched.get("income_df")
    cf_df     = enriched.get("cf_df")

    results    = []
    total_score = 0.0
    cat_scores  = {}
    cat_weights = {}

    for key, label, category, weight, fn in FACTORS:
        try:
            factor_score, detail, method = fn(income_df, cf_df, enriched)
            factor_score = max(0.0, min(100.0, float(factor_score)))
        except Exception as e:
            factor_score = 50.0
            detail  = f"Calculation error: {e}"
            method  = "N/A"
            log.debug(f"[{ticker}] EQ {key} error: {e}")

        weighted = factor_score * (weight / 100)
        total_score += weighted

        results.append({
            "key":      key,
            "label":    label,
            "category": category,
            "weight":   weight,
            "score":    round(factor_score, 1),
            "weighted": round(weighted, 2),
            "detail":   detail,
            "method":   method,
            "rating":   _factor_rating(factor_score),
        })

        if category not in cat_scores:
            cat_scores[category]  = 0.0
            cat_weights[category] = 0.0
        cat_scores[category]  += weighted
        cat_weights[category] += weight / 100

    # Normalise category scores to 0-100
    cat_normalized = {
        cat: round(cat_scores[cat] / cat_weights[cat], 1) if cat_weights[cat] > 0 else 50
        for cat in cat_scores
    }

    total_score = round(total_score, 1)
    grade, txt_c, bg_c, bd_c, emoji = _grade(total_score)

    # Red flags (factors scoring below 35)
    red_flags = [r["label"] for r in results if r["score"] < 35]
    green_flags = [r["label"] for r in results if r["score"] >= 85]

    summary = _build_summary(ticker, total_score, grade, cat_normalized, red_flags, green_flags)

    return {
        "ticker":           ticker,
        "score":            total_score,
        "grade":            grade,
        "grade_colour":     txt_c,
        "grade_bg":         bg_c,
        "grade_border":     bd_c,
        "grade_emoji":      emoji,
        "factors":          results,
        "category_scores":  cat_normalized,
        "red_flags":        red_flags,
        "green_flags":      green_flags,
        "summary":          summary,
        "academic_note": (
            "Based on Sloan (1996) accrual anomaly, Richardson et al. (2005), "
            "and Beneish M-Score methodology. High earnings quality stocks "
            "historically outperform low quality by 5-10% annually."
        ),
    }


def _factor_rating(score: float) -> str:
    if score >= 85: return "Excellent"
    if score >= 70: return "Good"
    if score >= 50: return "Moderate"
    if score >= 35: return "Weak"
    return "Poor"


def _build_summary(
    ticker:   str,
    score:    float,
    grade:    str,
    cats:     dict,
    red_flags:   list,
    green_flags: list,
) -> str:
    if grade == "EXCELLENT":
        opener = f"{ticker} scores {score:.0f}/100 — institutional-grade earnings quality. Reported profits are well-supported by cash generation."
    elif grade == "GOOD":
        opener = f"{ticker} scores {score:.0f}/100 — solid earnings quality with minor areas to monitor."
    elif grade == "MODERATE":
        opener = f"{ticker} scores {score:.0f}/100 — mixed earnings quality. Some signals warrant closer examination."
    elif grade == "WEAK":
        opener = f"{ticker} scores {score:.0f}/100 — earnings quality concerns. Reported profits may overstate economic reality."
    else:
        opener = f"{ticker} scores {score:.0f}/100 — significant earnings quality issues. High risk that profits are overstated."

    cat_str = ", ".join(
        f"{cat.split()[0].lower()} quality {v:.0f}/100"
        for cat, v in cats.items()
    )

    flag_str = ""
    if red_flags:
        flag_str = f" Key concerns: {' · '.join(red_flags[:2])}."
    elif green_flags:
        flag_str = f" Strengths: {' · '.join(green_flags[:2])}."

    return f"{opener} {cat_str.capitalize()}.{flag_str}"
