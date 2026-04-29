# screener/piotroski.py
# ═══════════════════════════════════════════════════════════════
# PIOTROSKI F-SCORE
# ═══════════════════════════════════════════════════════════════
#
# Originally published by Professor Joseph Piotroski (Stanford GSB)
# in his 2000 paper "Value Investing: The Use of Historical Financial
# Statement Information to Separate Winners from Losers."
#
# The F-Score is 9 binary signals (0 or 1) across three categories:
#
#   PROFITABILITY (4 signals)
#   ─────────────────────────
#   F1  ROA positive             — is the company earning on assets?
#   F2  OCF positive             — is operating cash flow real?
#   F3  ROA improving            — is profitability trending up?
#   F4  Accruals ratio negative  — is FCF > net income? (earnings quality)
#
#   LEVERAGE & LIQUIDITY (3 signals)
#   ─────────────────────────────────
#   F5  Long-term debt ratio falling   — less reliance on debt?
#   F6  Current ratio improving        — short-term liquidity improving?
#   F7  No new shares issued           — not diluting shareholders?
#
#   OPERATING EFFICIENCY (2 signals)
#   ──────────────────────────────────
#   F8  Gross margin improving         — pricing power / cost control?
#   F9  Asset turnover improving       — using assets more productively?
#
# Scoring:
#   8-9  STRONG  — high quality, historically outperforms
#   6-7  GOOD    — solid fundamentals
#   4-5  AVERAGE — mixed signals
#   2-3  WEAK    — deteriorating fundamentals
#   0-1  POOR    — multiple red flags
#
# Academic validation:
#   Piotroski (2000): high F-Score stocks outperformed low by 23% annually
#   Fama & French replication (2006): confirmed across markets
#   AQR (2013): robust factor even after publication
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations
import numpy as np
from utils.logger import get_logger

log = get_logger(__name__)


# Tickers with recent (last 3 years) major M&A events. For these,
# the Piotroski f3 (ROA improving YoY) and f7 (no share dilution)
# signals fail mechanically due to merger accounting — inflated
# asset base dilutes ROA, share issuance funds the deal — but
# these don't reflect business-quality deterioration. Grant neutral
# (0.5) scores on both signals for these tickers to avoid scoring
# post-merger transition periods as permanent impairment.
#
# Review this list every 12 months. Graduate tickers out 3 years
# after their merger close date. Keys are bare tickers (no .NS).
#
# Current members (as of 2026-04-24):
RECENT_MERGER_BANKS = {
    "HDFCBANK",   # HDFC Ltd merger, closed 2023-07-01
    "AXISBANK",   # Citibank India retail merger, closed 2023-03-01
    "INDUSINDBK", # Bharat Financial Inclusion merger, closed 2024-Q1
    "IDFCFIRSTB", # IDFC Ltd reverse merger, closed 2024-Q4
}


# ── GRADE THRESHOLDS ─────────────────────────────────────────
GRADE_MAP = {
    (8, 9): ("STRONG",  "#059669", "#ECFDF5", "#A7F3D0",  "🏆"),
    (6, 7): ("GOOD",    "#2563EB", "#EFF6FF", "#BFDBFE",  "✅"),
    (4, 5): ("AVERAGE", "#D97706", "#FFFBEB", "#FDE68A",  "⚠️"),
    (2, 3): ("WEAK",    "#DC2626", "#FEF2F2", "#FECACA",  "🔴"),
    (0, 1): ("POOR",    "#7F1D1D", "#FEF2F2", "#FECACA",  "💀"),
}


def _get_grade(score: int) -> tuple[str, str, str, str, str]:
    """Returns (label, text_colour, bg_colour, border_colour, emoji)"""
    for (lo, hi), vals in GRADE_MAP.items():
        if lo <= score <= hi:
            return vals
    return ("AVERAGE", "#D97706", "#FFFBEB", "#FDE68A", "⚠️")


# ── HELPER ───────────────────────────────────────────────────
def _safe(val, default=0.0) -> float:
    try:
        v = float(val)
        return v if np.isfinite(v) else default
    except Exception:
        return default


def _series_last(df, col, n=1) -> float | None:
    """Return the last n-th value from a df column, or None."""
    try:
        if df is None or df.empty or col not in df.columns:
            return None
        vals = df[col].dropna()
        if len(vals) < n:
            return None
        return float(vals.iloc[-n])
    except Exception:
        return None


def _series_prev(df, col) -> float | None:
    """Return second-to-last value (prior year)."""
    return _series_last(df, col, 2)


# ── INDIVIDUAL SIGNAL CALCULATORS ───────────────────────────

def _f1_roa_positive(enriched: dict, income_df, cf_df) -> tuple[int, str, str]:
    """F1: ROA > 0 — is the company profitable on its assets?"""
    net_income = _safe(_series_last(income_df, "net_income"))
    total_assets = _safe(enriched.get("total_debt", 0)) + _safe(enriched.get("total_cash", 0))
    # Approximate total assets from market cap + debt - cash (simplified)
    # Better: use Yahoo's balance sheet totalAssets if available
    total_assets_yahoo = _safe(enriched.get("total_assets", 0))
    if total_assets_yahoo > 0:
        total_assets = total_assets_yahoo

    # Fallback: use net income directly (positive net income → ROA > 0)
    roa = None
    if total_assets > 0 and net_income != 0:
        roa = net_income / total_assets
    elif net_income != 0:
        # Use ROE from Yahoo as proxy if no asset data
        roa = _safe(enriched.get("roe", 0))

    if roa is None:
        net_income_raw = _safe(_series_last(income_df, "net_income"))
        score  = 1 if net_income_raw > 0 else 0
        detail = f"Net income {'positive ✓' if score else 'negative ✗'} (${net_income_raw/1e9:.2f}B)"
        # P5 FIX: roa IS None here — do NOT try to format it with :.1%
        return score, detail, "Proxy: net income sign (total_assets unavailable)"

    score = 1 if roa > 0 else 0
    return score, f"ROA = {roa:.1%} {'✓' if score else '✗'}", "Net income / Total assets"


def _f2_ocf_positive(enriched: dict, income_df, cf_df) -> tuple[int, str, str]:
    """F2: Operating cash flow > 0 — cash generation is real."""
    ocf = _safe(_series_last(cf_df, "ocf"))
    if ocf == 0:
        # Try FCF as proxy
        ocf = _safe(_series_last(cf_df, "fcf"))
    score = 1 if ocf > 0 else 0
    detail = f"Operating CF = ${ocf/1e9:.2f}B {'✓' if score else '✗'}"
    return score, detail, "Cash from operations"


def _f3_roa_improving(enriched: dict, income_df, cf_df) -> tuple[int, str, str]:
    """F3: ROA increased year-over-year — profitability trend."""
    ni_curr = _safe(_series_last(income_df, "net_income"))
    ni_prev = _safe(_series_prev(income_df, "net_income"))

    # Use operating income if net income not available
    if ni_curr == 0 and ni_prev == 0:
        ni_curr = _safe(_series_last(income_df, "operating_income"))
        ni_prev = _safe(_series_prev(income_df, "operating_income"))
        label = "Op. income"
    else:
        label = "Net income"

    if ni_prev == 0:
        score = 1 if ni_curr > 0 else 0
        return score, f"{label} trend: insufficient history", "YoY change"

    change = (ni_curr - ni_prev) / abs(ni_prev)
    score  = 1 if ni_curr > ni_prev else 0
    detail = f"{label}: {change:+.1%} YoY {'✓' if score else '✗'} (${ni_curr/1e9:.2f}B vs ${ni_prev/1e9:.2f}B)"
    return score, detail, "Year-over-year profitability trend"


def _f4_accruals(enriched: dict, income_df, cf_df) -> tuple[int, str, str]:
    """
    F4: Accruals (CFO/Assets - ROA) < 0
    Simplified: FCF > Net Income → earnings are cash-backed.
    High accruals = earnings quality concern.
    """
    fcf       = _safe(enriched.get("latest_fcf", 0))
    ni_curr   = _safe(_series_last(income_df, "net_income"))

    if fcf == 0 or ni_curr == 0:
        # Fallback: use OCF vs net income
        ocf = _safe(_series_last(cf_df, "ocf"))
        if ocf > 0 and ni_curr > 0:
            score  = 1 if ocf >= ni_curr * 0.8 else 0
            detail = f"OCF ${ocf/1e9:.2f}B vs NI ${ni_curr/1e9:.2f}B {'✓' if score else '✗ (accruals concern)'}"
            return score, detail, "Operating cash flow vs net income"
        return 0, "Insufficient data", "FCF vs net income"

    # FCF > Net Income means cash earnings exceed accrual earnings
    ratio  = fcf / ni_curr if ni_curr > 0 else 0
    score  = 1 if fcf >= ni_curr * 0.8 else 0   # FCF at least 80% of NI
    detail = (
        f"FCF/NI ratio = {ratio:.2f}× {'✓' if score else '✗'} "
        f"(FCF ${fcf/1e9:.1f}B vs NI ${ni_curr/1e9:.1f}B)"
    )
    return score, detail, "FCF vs net income — earnings quality"


def _f5_leverage_falling(enriched: dict, income_df, cf_df) -> tuple[int, str, str]:
    """
    F5: Long-term debt ratio DECLINED year-over-year.
    Piotroski (2000) definition: LT debt / avg total assets this year < prior year.
    A company reducing its reliance on debt scores 1.
    P1 FIX: Was using interest coverage (wrong metric). Now uses actual LT debt YoY.
    """
    lt_debt      = _safe(enriched.get("lt_debt",      0))
    lt_debt_prev = _safe(enriched.get("lt_debt_prev", 0))
    assets       = _safe(enriched.get("total_assets", 0))
    assets_prev  = _safe(enriched.get("total_assets_prev", 0))

    # Primary: LT debt / total assets ratio, current vs prior year
    if lt_debt > 0 and lt_debt_prev > 0 and assets > 0:
        ratio_curr = lt_debt / assets
        ratio_prev = lt_debt_prev / (assets_prev if assets_prev > 0 else assets)
        score  = 1 if ratio_curr <= ratio_prev else 0
        change = ratio_curr - ratio_prev
        detail = (
            f"LT Debt/Assets: {ratio_curr:.1%} vs {ratio_prev:.1%} prior year "
            f"({change:+.1%} {'✓ declining' if score else '✗ rising'})"
        )
        return score, detail, "Long-term debt / total assets ratio YoY"

    # Secondary: absolute LT debt declining
    if lt_debt > 0 and lt_debt_prev > 0:
        score  = 1 if lt_debt <= lt_debt_prev else 0
        change = (lt_debt - lt_debt_prev) / lt_debt_prev
        detail = f"LT Debt: ${lt_debt/1e9:.2f}B vs ${lt_debt_prev/1e9:.2f}B prior ({change:+.1%} {'✓' if score else '✗'})"
        return score, detail, "Long-term debt absolute change YoY"

    # Tertiary: use D/E ratio as a level check
    de_ratio = _safe(enriched.get("de_ratio", 0))
    if de_ratio > 0:
        score  = 1 if de_ratio < 1.0 else 0
        detail = f"D/E ratio = {de_ratio:.2f}× {'✓ <1.0x (low leverage)' if score else '✗ >1.0x (high leverage)'}"
        return score, detail, "D/E ratio (prior-year debt data unavailable)"

    # Last resort: debt/revenue level
    debt = _safe(enriched.get("total_debt", 0))
    rev  = _safe(enriched.get("latest_revenue", 1))
    dtr  = debt / rev if rev > 0 else 0
    score  = 1 if dtr < 1.0 else 0
    detail = f"Debt/Revenue = {dtr:.2f}× {'✓' if score else '✗'} (no YoY data)"
    return score, detail, "Debt-to-revenue (fallback — no YoY data available)"


def _f6_current_ratio_improving(enriched: dict, income_df, cf_df) -> tuple[int, str, str]:
    """
    F6: Current ratio IMPROVED year-over-year.
    Piotroski (2000) definition: (current assets / current liabilities) this year
    > prior year. A rising current ratio signals improving short-term liquidity.
    P2 FIX: Was checking cash/debt >= 0.3 (level check, wrong). Now uses actual
    current ratio trend from balance sheet data extracted by collector.
    """
    cr_curr = _safe(enriched.get("current_ratio",      0))
    cr_prev = _safe(enriched.get("current_ratio_prev", 0))

    # Primary: actual current ratio YoY from balance sheet
    if cr_curr > 0 and cr_prev > 0:
        score  = 1 if cr_curr > cr_prev else 0
        change = cr_curr - cr_prev
        detail = (
            f"Current ratio: {cr_curr:.2f}× vs {cr_prev:.2f}× prior year "
            f"({change:+.2f} {'✓ improving' if score else '✗ declining'})"
        )
        return score, detail, "Current assets / Current liabilities YoY"

    # Secondary: if only current ratio available (no prior year), use ≥ 1.5 as healthy proxy
    if cr_curr > 0:
        score  = 1 if cr_curr >= 1.5 else 0
        detail = f"Current ratio = {cr_curr:.2f}× {'✓ ≥1.5x' if score else '✗ <1.5x'} (prior year unavailable)"
        return score, detail, "Current ratio level (no prior year for trend)"

    # Tertiary: cash / (debt+1) as solvency proxy
    cash = _safe(enriched.get("total_cash", 0))
    debt = _safe(enriched.get("total_debt", 0))
    if debt == 0:
        return 1, "No debt — strong liquidity ✓", "Zero-debt position"
    cash_ratio = cash / debt
    score  = 1 if cash_ratio >= 0.5 else 0
    detail = f"Cash/Debt = {cash_ratio:.2f}× {'✓' if score else '✗'} (balance sheet detail unavailable)"
    return score, detail, "Cash/Debt ratio (fallback — no current ratio data)"


def _f7_no_dilution(enriched: dict, income_df, cf_df) -> tuple[int, str, str]:
    """F7: No new shares issued in the past year — no dilution."""
    # Use share count trend from income_df if available
    # Otherwise use Yahoo's sharesOutstanding vs prior
    shares_curr = _safe(enriched.get("shares", 0))
    shares_prev = _safe(enriched.get("shares_prev_year", 0))

    if shares_prev > 0 and shares_curr > 0:
        change = (shares_curr - shares_prev) / shares_prev
        score  = 1 if change <= 0.02 else 0   # allow 2% dilution (options/RSUs)
        detail = f"Share count change: {change:+.1%} {'✓' if score else '✗ (dilution)'}"
        return score, detail, "Year-over-year share count"

    # P3 FIX: FCF margin is NOT a valid proxy for dilution.
    # High FCF does not mean no share issuance (companies can do both).
    # When shares_prev_year is unavailable, default to PASS (1) with a
    # clear "data unavailable" note — it's fairer than penalising incorrectly.
    return 1, "Prior-year share count unavailable — assuming no dilution ✓", "No dilution data (defaulting to pass)"


def _f8_gross_margin_improving(enriched: dict, income_df, cf_df) -> tuple[int, str, str]:
    """
    F8: GROSS margin improved year-over-year.
    Piotroski (2000) definition: gross profit / revenue this year > prior year.
    Gross margin = (Revenue - COGS) / Revenue. Excludes SG&A unlike operating margin.
    P4 FIX: Was using operating_income/revenue (operating margin) — wrong metric.
    Now uses gross_profit column from income_df (added by collector C4 fix).
    """
    rev_curr = _safe(_series_last(income_df, "revenue"))
    rev_prev = _safe(_series_prev(income_df, "revenue"))
    gp_curr  = _safe(_series_last(income_df, "gross_profit"))
    gp_prev  = _safe(_series_prev(income_df, "gross_profit"))

    # Primary: gross profit / revenue YoY (correct Piotroski definition)
    if rev_curr > 0 and rev_prev > 0 and gp_curr != 0 and gp_prev != 0:
        gm_curr = gp_curr / rev_curr
        gm_prev = gp_prev / rev_prev
        change  = gm_curr - gm_prev
        score   = 1 if gm_curr >= gm_prev else 0
        detail  = (
            f"Gross margin: {gm_curr:.1%} vs {gm_prev:.1%} prior year "
            f"({change:+.1%} {'✓ improving' if score else '✗ declining'})"
        )
        return score, detail, "Gross profit / Revenue YoY"

    # Secondary: use enriched gross_margin (TTM, single year — level only)
    gm_ttm = _safe(enriched.get("gross_margin", 0))
    if gm_ttm > 0:
        score  = 1 if gm_ttm >= 0.30 else 0
        detail = f"Gross margin (TTM) = {gm_ttm:.1%} {'✓ ≥30%' if score else '✗ <30%'} (prior year unavailable)"
        return score, detail, "TTM gross margin level (no YoY trend available)"

    # Tertiary: operating margin as last resort (clearly labelled)
    op_curr = _safe(_series_last(income_df, "operating_income"))
    op_prev = _safe(_series_prev(income_df, "operating_income"))
    if rev_curr > 0 and rev_prev > 0 and op_curr != 0 and op_prev != 0:
        om_curr = op_curr / rev_curr
        om_prev = op_prev / rev_prev
        score   = 1 if om_curr >= om_prev else 0
        detail  = f"Op. margin: {om_curr:.1%} vs {om_prev:.1%} ({'✓' if score else '✗'}) [gross profit unavailable]"
        return score, detail, "Operating margin trend (gross profit data unavailable)"

    return 0, "Insufficient margin data", "Gross margin (no data)"


def _f9_asset_turnover_improving(enriched: dict, income_df, cf_df) -> tuple[int, str, str]:
    """
    F9: Asset turnover IMPROVED year-over-year.
    Piotroski (2000) definition: (Revenue / Total Assets) this year > prior year.
    Higher asset turnover = company is using its assets more productively.
    P6 FIX: Was using revenue growth as proxy — not the same. Revenue can grow
    while assets grow faster, meaning turnover actually fell.
    """
    rev_curr    = _safe(_series_last(income_df, "revenue"))
    rev_prev    = _safe(_series_prev(income_df, "revenue"))
    assets_curr = _safe(enriched.get("total_assets",      0))
    assets_prev = _safe(enriched.get("total_assets_prev", 0))

    # Primary: actual asset turnover ratio YoY (correct Piotroski definition)
    if rev_curr > 0 and assets_curr > 0 and rev_prev > 0 and assets_prev > 0:
        at_curr = rev_curr / assets_curr
        at_prev = rev_prev / assets_prev
        score   = 1 if at_curr > at_prev else 0
        change  = at_curr - at_prev
        detail  = (
            f"Asset turnover: {at_curr:.3f}× vs {at_prev:.3f}× prior year "
            f"({change:+.3f} {'✓ improving' if score else '✗ declining'})"
        )
        return score, detail, "Revenue / Total assets ratio YoY"

    # Secondary: if assets data partial, use revenue/assets for one year
    if rev_curr > 0 and assets_curr > 0:
        at = rev_curr / assets_curr
        score  = 1 if at >= 0.5 else 0
        detail = f"Asset turnover = {at:.3f}× {'✓ ≥0.5x' if score else '✗ <0.5x'} (prior year unavailable)"
        return score, detail, "Revenue / Total assets (no YoY trend)"

    # Tertiary: revenue growth as last-resort proxy (clearly labelled)
    if rev_curr > 0 and rev_prev > 0:
        rev_g  = (rev_curr - rev_prev) / rev_prev
        score  = 1 if rev_g > 0 else 0
        detail = f"Revenue growth: {rev_g:+.1%} {'✓' if score else '✗'} [asset data unavailable — proxy only]"
        return score, detail, "Revenue growth proxy (total assets unavailable)"

    fcf_g  = _safe(enriched.get("fcf_growth", 0))
    score  = 1 if fcf_g > 0 else 0
    detail = f"FCF growth: {fcf_g:+.1%} {'✓' if score else '✗'} (last-resort proxy)"
    return score, detail, "FCF growth (last-resort fallback)"


# ── MAIN F-SCORE FUNCTION ────────────────────────────────────

def compute_piotroski_fscore(enriched: dict) -> dict:
    """
    Compute full Piotroski F-Score (0-9) from enriched data.

    Returns:
        score       : int 0-9
        grade       : str STRONG/GOOD/AVERAGE/WEAK/POOR
        signals     : list of 9 signal dicts
        summary     : plain-English explanation
        category_scores : dict with profitability/leverage/efficiency sub-scores
    """
    ticker    = enriched.get("ticker", "?")
    income_df = enriched.get("income_df")
    cf_df     = enriched.get("cf_df")

    # ── Bank detection (BUG FIX 2026-04-24) ───────────────────
    # The classic 9-signal Piotroski was designed for industrial firms.
    # For banks, 5 of the 9 signals don't apply in any meaningful way:
    #   f4 (FCF > NI)       — banks don't report FCF in the traditional
    #                         sense; cash flow is dominated by financing
    #                         activities (deposits/lending).
    #   f5 (leverage down)  — banks are STRUCTURALLY highly-leveraged
    #                         (deposits = liabilities = 8-12x equity is
    #                         normal, not a red flag). The signal always
    #                         fails for healthy banks.
    #   f6 (current ratio)  — banks don't use current ratio; deposit
    #                         maturity structure is the real concern
    #                         and isn't captured here.
    #   f8 (gross margin)   — banks have no cost-of-goods concept; NIM
    #                         (net interest margin) is the analogue but
    #                         isn't in this signal.
    #   f9 (asset turnover) — banks' assets are loans, "turnover" is
    #                         NII / total assets which is structurally
    #                         low (~4-5%) and doesn't improve linearly.
    #
    # Result pre-fix: HDFCBANK scored 3/9 (should be 6-8). Every Indian
    # private bank got WEAK grade despite being among the strongest
    # lenders globally.
    #
    # Fix: for bank-like tickers, run only the 4 applicable signals
    # (f1, f2, f3, f7) and scale to the 0-9 range. This preserves the
    # "9-point scale" API expected by downstream consumers while
    # correctly excluding inapplicable tests.
    # BUG FIX (2026-04-25): NBFCs (BAJFINANCE, CHOLAFIN, MUTHOOTFIN etc.)
    # were falling through to classic 9-signal piotroski because their
    # sector strings are "NBFC" / "Financial Services" (varies by source)
    # and their tickers don't end with "BANK". But structurally they have
    # the same piotroski incompatibilities as banks: high leverage by
    # design, different asset-turnover math, loan-book instead of
    # inventory. They need bank-mode scoring.
    #
    # Observed pre-fix: BAJFINANCE piotroski 3/9 (WEAK) → composite 57
    # capped. Bank-mode should lift it to 7/9 → composite ~65 (PASS).
    sector_raw = enriched.get("sector") or ""
    industry_raw = enriched.get("industry") or ""
    # Unified bank classifier (2026-04-29 hotfix/bank-misclassify).
    # Delegates to backend.services.analysis.constants.is_bank_like so
    # the analysis pipeline, Prism/Hex and Piotroski all classify the
    # same tickers as bank-like. Pre-fix the local set diverged from
    # FINANCIAL_COMPANIES — CAPITALSFB and other small-finance-bank
    # peers slipped through to the 9-signal classic Piotroski.
    from backend.services.analysis.constants import is_bank_like as _is_bank_like_unified
    is_bank = bool(
        enriched.get("is_bank")
        or _is_bank_like_unified(ticker, sector_raw, industry_raw)
    )

    if is_bank:
        SIGNALS = [
            ("f1", "ROA positive",            "Profitability", _f1_roa_positive),
            ("f2", "Operating cash flow > 0", "Profitability", _f2_ocf_positive),
            ("f3", "ROA improving YoY",       "Profitability", _f3_roa_improving),
            ("f7", "No share dilution",       "Leverage",      _f7_no_dilution),
        ]
    else:
        # ── Run all 9 signals (classic Piotroski for non-banks) ───
        SIGNALS = [
            # (key, label, category, calc_fn)
            ("f1", "ROA positive",             "Profitability",  _f1_roa_positive),
            ("f2", "Operating cash flow > 0",  "Profitability",  _f2_ocf_positive),
            ("f3", "ROA improving YoY",        "Profitability",  _f3_roa_improving),
            ("f4", "FCF > Net income",         "Profitability",  _f4_accruals),
            ("f5", "Leverage declining",       "Leverage",       _f5_leverage_falling),
            ("f6", "Liquidity improving",      "Leverage",       _f6_current_ratio_improving),
            ("f7", "No share dilution",        "Leverage",       _f7_no_dilution),
            ("f8", "Gross margin improving",   "Efficiency",     _f8_gross_margin_improving),
            ("f9", "Asset turnover improving", "Efficiency",     _f9_asset_turnover_improving),
        ]

    # ── Recent-merger exception (PR #67, 2026-04-24) ──────────
    # For banks that closed major M&A in the last ~3 years, the
    # f3 (ROA improving YoY) and f7 (no share dilution) signals
    # break mechanically: the inflated post-merger asset base
    # dilutes ROA even at constant profit, and share issuance
    # funds the deal. Grant neutral (0.5) scores on those two
    # signals — see RECENT_MERGER_BANKS above for the curated
    # list and graduation policy.
    ticker_bare = (ticker or "").upper().replace(".NS", "").replace(".BO", "")
    is_recent_merger = is_bank and ticker_bare in RECENT_MERGER_BANKS

    results  = []
    total    = 0.0
    cats     = {"Profitability": 0, "Leverage": 0, "Efficiency": 0}
    cat_max  = {"Profitability": 4, "Leverage": 3, "Efficiency": 2}

    for key, label, category, fn in SIGNALS:
        try:
            score, detail, method = fn(enriched, income_df, cf_df)
            score = int(bool(score))  # ensure 0 or 1
        except Exception as e:
            score, detail, method = 0, f"Error: {e}", "N/A"
            log.debug(f"[{ticker}] F-Score {key} error: {e}")

        # Merger exception: f3 (ROA improving) and f7 (no dilution) fail
        # mechanically for 3 years post-M&A. Replace 0 with 0.5 for these
        # tickers on those two signals, so composite isn't dragged by
        # transient merger artifacts.
        if is_recent_merger and key in ("f3", "f7") and score == 0:
            score = 0.5

        total += score
        cats[category] += score
        results.append({
            "key":      key,
            "label":    label,
            "category": category,
            "score":    score,
            "detail":   detail,
            "method":   method,
            "pass":     score == 1,
        })

    # ── Bank scaling (BUG FIX 2026-04-24) ─────────────────────
    # Bank signals only run 4 of 9 (see is_bank branch above). Scale
    # the raw /4 back to the 0-9 range so downstream consumers that
    # expect a 9-point scale (grade buckets, composite scoring,
    # frontend labels) continue to work. Integer-rounded to avoid
    # fractional scores in the UI. A bank passing 4/4 gets 9; 3/4 gets 7;
    # 2/4 gets 4; 1/4 gets 2; 0/4 gets 0.
    if is_bank:
        raw_bank = total
        total = int(round(raw_bank * 9 / 4))
    else:
        total = int(round(total))

    # ── Merger-exception note (PR #67) ─────────────────────────
    if is_recent_merger:
        # Record this in the response so the frontend can surface it
        # as an analytical note (see PR #69).
        _merger_note = (
            "Post-merger transition — f3/f7 neutralised "
            "(see RECENT_MERGER_BANKS in piotroski.py)"
        )
    else:
        _merger_note = None

    # ── Grade ──────────────────────────────────────────────────
    grade, txt_c, bg_c, bd_c, emoji = _get_grade(total)

    # ── Plain-English summary ──────────────────────────────────
    summary = _build_summary(ticker, total, grade, cats, results)

    # ── Academic context ───────────────────────────────────────
    academic_note = (
        "Based on Piotroski (2000) — Stanford GSB. "
        "High F-Score (8-9) stocks historically outperformed low (0-2) by 23% annually. "
        "Validated by Fama & French (2006) and AQR (2013) across global markets."
    )

    return {
        "ticker":           ticker,
        "score":            total,
        "score_out_of":     9,
        "grade":            grade,
        "grade_colour":     txt_c,
        "grade_bg":         bg_c,
        "grade_border":     bd_c,
        "grade_emoji":      emoji,
        "signals":          results,
        "category_scores":  cats,
        "category_max":     cat_max,
        "summary":          summary,
        "academic_note":    academic_note,
        "passes":           sum(r["score"] for r in results),
        "fails":            9 - total,
        "merger_exception_applied": bool(is_recent_merger),
        "merger_note":      _merger_note,
    }


def _build_summary(
    ticker:  str,
    score:   int,
    grade:   str,
    cats:    dict,
    signals: list,
) -> str:
    prof  = cats["Profitability"]
    lev   = cats["Leverage"]
    eff   = cats["Efficiency"]

    # Opening
    if grade == "STRONG":
        opener = f"{ticker} scores {score}/9 on the Piotroski F-Score — a high-quality business firing on all cylinders."
    elif grade == "GOOD":
        opener = f"{ticker} scores {score}/9 — solid fundamentals with minor areas to watch."
    elif grade == "AVERAGE":
        opener = f"{ticker} scores {score}/9 — mixed signals. Some strengths but also some concerns."
    elif grade == "WEAK":
        opener = f"{ticker} scores {score}/9 — deteriorating fundamentals. Multiple red flags present."
    else:
        opener = f"{ticker} scores {score}/9 — very weak fundamentals. High risk of continued underperformance."

    # Category breakdown
    parts = []
    if prof >= 3:
        parts.append(f"profitability is strong ({prof}/4)")
    elif prof >= 2:
        parts.append(f"profitability is adequate ({prof}/4)")
    else:
        parts.append(f"profitability is weak ({prof}/4) — a key concern")

    if lev >= 2:
        parts.append(f"balance sheet is healthy ({lev}/3)")
    else:
        parts.append(f"leverage/liquidity needs attention ({lev}/3)")

    if eff >= 1:
        parts.append(f"operating efficiency is improving ({eff}/2)")
    else:
        parts.append(f"efficiency is declining ({eff}/2)")

    # Key red flags
    fails = [s["label"] for s in signals if not s["pass"]]
    if fails:
        flag_str = " · ".join(fails[:3])
        fail_line = f" Main concerns: {flag_str}."
    else:
        fail_line = " No major red flags detected."

    return f"{opener} Specifically, {'; '.join(parts)}.{fail_line}"
