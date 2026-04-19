# backend/services/analysis_service.py
# ═══════════════════════════════════════════════════════════════
# Wraps existing screener/, models/, data/ logic for FastAPI.
# CRITICAL: Imports from existing modules. Does NOT rewrite logic.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations
import sys
import os
from pathlib import Path
from datetime import datetime

# Ensure project root is on path so existing imports work
_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
# Dashboard also needs to be on path for some utilities
_DASHBOARD_ROOT = os.path.join(_PROJECT_ROOT, "dashboard")
if _DASHBOARD_ROOT not in sys.path:
    sys.path.insert(0, _DASHBOARD_ROOT)

from backend.models.responses import (
    AnalysisResponse, ValuationOutput, QualityOutput,
    InsightCards, BulkDealItem, CompanyInfo, ScenariosOutput, ScenarioCase,
    PriceLevels, ScreenerStock, RedFlag,
)
# CACHE_VERSION is stamped into the computation_inputs snapshot so the
# audit trail records exactly which code generation produced an FV.
from backend.services.cache_service import CACHE_VERSION

# ── Import existing engines (NO rewrites) ─────────────────────
from data.collector import StockDataCollector
from data.processor import compute_metrics
from data.validator import validate_stock_data
from models.forecaster import FCFForecaster, compute_confidence_score
from screener.dcf_engine import (
    DCFEngine, margin_of_safety, assign_signal,
)
from screener.piotroski import compute_piotroski_fscore
from screener.moat_engine import compute_moat_score, apply_moat_adjustments
from screener.earnings_quality import compute_earnings_quality
from screener.valuation_crosscheck import blend_dcf_pe, compute_pe_based_iv, get_eps
from screener.valuation_model import (
    generate_valuation_summary, score_fundamentals,
)
from screener.scenarios import run_scenarios
from screener.reverse_dcf import run_reverse_dcf
from screener.fcf_yield import compute_fcf_yield_analysis
from screener.ev_ebitda import run_ev_ebitda_analysis
from screener.momentum import calculate_momentum
from config.countries import get_active_country

# Optional imports (may need streamlit mock)
try:
    from dashboard.utils.scoring import compute_yieldiq_score
except Exception:
    def compute_yieldiq_score(mos_pct, piotroski, moat_grade, rev_growth, analyst_upside=0):
        _v = max(0, min(100, (mos_pct + 40) / 80 * 40))
        _q = max(0, min(100, (piotroski / 9) * 30))
        _g = max(0, min(100, (rev_growth * 100 + 20) / 60 * 20))
        _s = max(0, min(100, analyst_upside * 10))
        _total = int(_v + _q + _g + _s)
        return {"score": max(0, min(100, _total)), "grade": "A" if _total >= 75 else "B" if _total >= 55 else "C" if _total >= 35 else "D" if _total >= 20 else "F"}


# ── Company name overrides for cleaner display ──────────────
COMPANY_NAME_OVERRIDES = {
    "RELIANCE.NS": "Reliance Industries",
    "TCS.NS": "Tata Consultancy Services",
    "HDFCBANK.NS": "HDFC Bank",
    "BAJFINANCE.NS": "Bajaj Finance",
    "HINDUNILVR.NS": "Hindustan Unilever",
    "MARUTI.NS": "Maruti Suzuki India",
    "TITAN.NS": "Titan Company",
    "INFY.NS": "Infosys",
    "SBIN.NS": "State Bank of India",
    "ICICIBANK.NS": "ICICI Bank",
    "KOTAKBANK.NS": "Kotak Mahindra Bank",
    "AXISBANK.NS": "Axis Bank",
    "LT.NS": "Larsen & Toubro",
    "SUNPHARMA.NS": "Sun Pharmaceutical Industries",
    "NTPC.NS": "NTPC Limited",
    "ONGC.NS": "ONGC Limited",
    "WIPRO.NS": "Wipro Limited",
    "TATAMOTORS.NS": "Tata Motors",
    "ITC.NS": "ITC Limited",
}

# ── Financial company set (NBFCs, Banks, Insurance) ──────────
# These companies have negative FCF by nature (loan disbursements = operating
# outflows). FCF-based DCF does NOT apply; use P/B ratio valuation instead.
FINANCIAL_COMPANIES = {
    'HDFCBANK', 'ICICIBANK', 'SBIN', 'KOTAKBANK', 'AXISBANK',
    'BANKBARODA', 'PNB', 'CANBK', 'FEDERALBNK', 'IDFCFIRSTB',
    'INDUSINDBK', 'BANDHANBNK', 'RBLBANK', 'YESBANK',
    'BAJFINANCE', 'BAJAJFINSV', 'CHOLAFIN', 'MUTHOOTFIN',
    'MANAPPURAM', 'M&MFIN', 'SHRIRAMFIN', 'LICHOUSFIN',
    'POONAWALLA', 'AAVAS', 'HOMEFIRST',
    'HDFCLIFE', 'SBILIFE', 'ICICIGI', 'NIACL', 'STARHEALTH',
}

# P/B median multipliers by financial sub-sector
_PB_MEDIANS = {
    "Banking": 2.5,
    "NBFC": 4.0,
    "Insurance": 3.0,
}

_NBFC_TICKERS = {
    'BAJFINANCE', 'BAJAJFINSV', 'CHOLAFIN', 'MUTHOOTFIN',
    'MANAPPURAM', 'M&MFIN', 'SHRIRAMFIN', 'LICHOUSFIN',
    'POONAWALLA', 'AAVAS', 'HOMEFIRST',
}
_INSURANCE_TICKERS = {
    'HDFCLIFE', 'SBILIFE', 'ICICIGI', 'NIACL', 'STARHEALTH',
}

# Inventory-heavy retail: negative CFO from working capital, not weakness
INVENTORY_HEAVY_TICKERS = {
    'TITAN', 'TRENT', 'ABFRL', 'DMART', 'PAGEIND',
    'RAYMOND', 'VMART', 'MARUTI', 'SHOPERSTOP',
}


def _get_financial_sub_type(clean_ticker: str) -> str:
    """Return 'NBFC', 'Insurance', or 'Banking' for a financial ticker."""
    if clean_ticker in _NBFC_TICKERS:
        return "NBFC"
    if clean_ticker in _INSURANCE_TICKERS:
        return "Insurance"
    return "Banking"


def _get_adjusted_fcf(fcf, pat, is_financial):
    """Floor FCF to PAT proxy for capex-heavy companies."""
    if is_financial:
        return None  # Don't use FCF for financials
    if fcf is None:
        return pat * 0.55 if pat and pat > 0 else None
    if pat and pat > 0 and fcf < pat * 0.3:
        # FCF looks distorted by heavy capex — use PAT proxy
        return pat * 0.55
    return fcf


# ── Sector name overrides for cleaner display ─────────────────
SECTOR_OVERRIDES: dict[str, str] = {
    "Financial Services": "Financial Services",
    "Financial": "Financial Services",
    "Banks": "Banking",
    "Banks - Regional": "Banking",
    "Banks - Diversified": "Banking",
    "Insurance - Life": "Insurance",
    "Insurance - Diversified": "Insurance",
    "Insurance": "Insurance",
    "Drug Manufacturers": "Pharma",
    "Drug Manufacturers - General": "Pharma",
    "Biotechnology": "Pharma",
    "Software - Application": "IT",
    "Software - Infrastructure": "IT",
    "Information Technology Services": "IT",
    "Internet Content & Information": "IT",
    "Oil & Gas Integrated": "Oil & Gas",
    "Oil & Gas E&P": "Oil & Gas",
    "Oil & Gas Refining & Marketing": "Oil & Gas",
    "Tobacco": "FMCG",
    "Packaged Foods": "FMCG",
    "Household & Personal Products": "FMCG",
    "Beverages - Non-Alcoholic": "FMCG",
    "Auto Manufacturers": "Automobiles",
    "Auto - Manufacturers": "Automobiles",
    "Telecom Services": "Telecom",
    "Utilities - Regulated Electric": "Power & Utilities",
    "Utilities - Independent Power Producers": "Power & Utilities",
    "Building Materials": "Construction",
    "Engineering & Construction": "Engineering",
    "Specialty Chemicals": "Chemicals",
    "Metals & Mining": "Metals & Mining",
    "Steel": "Metals & Mining",
    "Real Estate - Development": "Real Estate",
    "REIT": "Real Estate",
}


# Ticker-based sector overrides — forces correct sector for known tickers
# (yfinance often returns "Financial Services" for everything)
TICKER_SECTOR_OVERRIDES: dict[str, str] = {}
for _t in _NBFC_TICKERS:
    TICKER_SECTOR_OVERRIDES[_t] = "NBFC"
for _t in _INSURANCE_TICKERS:
    TICKER_SECTOR_OVERRIDES[_t] = "Insurance"
for _t in (FINANCIAL_COMPANIES - _NBFC_TICKERS - _INSURANCE_TICKERS):
    TICKER_SECTOR_OVERRIDES[_t] = "Banking"


def _normalize_pct(val) -> float | None:
    """
    Normalize a percentage-ish value to always be in PERCENTAGE form (23.5 for 23.5%).

    Handles mixed conventions in our data pipeline:
    - yfinance returns ROE as decimal (0.235 for 23.5%)
    - Aiven XBRL sometimes stores as percentage (23.5)
    - Some computed fields use decimals

    Rule: if |val| < 5 we treat it as decimal (since real ROE/ROCE > 5%
    wouldn't be expressed as a tiny decimal), else already percentage.
    """
    if val is None:
        return None
    try:
        v = float(val)
    except (TypeError, ValueError):
        return None
    if v == 0:
        return 0.0
    # If absolute value is less than 5, assume decimal (0.23 → 23.0)
    # Real-world ROE/ROCE of < 5% are rare; treating 0.05 as 5% is safer
    # than treating 0.05 as 0.05%
    if -5.0 < v < 5.0:
        return round(v * 100, 2)
    return round(v, 2)


def _compute_roe_fallback(enriched: dict):
    """Compute ROE from net_income / total_equity when yfinance doesn't provide it."""
    try:
        net_income = enriched.get("net_income") or enriched.get("netIncome", 0)
        equity = enriched.get("total_equity") or enriched.get("totalStockholderEquity", 0)
        if net_income and equity and equity > 0:
            roe = net_income / equity
            if -2.0 <= roe <= 2.0:  # sanity: -200% to +200%
                return round(roe, 4)
    except Exception:
        pass
    return None


def _resolve_sector(raw_sector: str, clean_ticker: str = "") -> str:
    """Map raw yfinance/screener sector names to cleaner display names.

    If a ticker-based override exists it takes precedence, ensuring NBFCs,
    banks, and insurers are always labelled correctly regardless of what
    yfinance reports.
    """
    # Ticker override has highest priority
    if clean_ticker and clean_ticker in TICKER_SECTOR_OVERRIDES:
        return TICKER_SECTOR_OVERRIDES[clean_ticker]
    if not raw_sector:
        return ""
    return SECTOR_OVERRIDES.get(raw_sector, raw_sector)


# ═══════════════════════════════════════════════════════════════
# RED FLAG DEEP DIVE — structured flag generator
# ═══════════════════════════════════════════════════════════════

def _fmt_cr(val) -> str:
    """Format a Crore value for user-facing text."""
    if val is None:
        return "N/A"
    try:
        v = float(val)
    except (TypeError, ValueError):
        return "N/A"
    if abs(v) >= 100_000:
        return f"₹{v / 100_000:.1f}L Cr"
    if abs(v) >= 1_000:
        return f"₹{v:,.0f} Cr"
    return f"₹{v:.0f} Cr"


def _build_structured_flags(
    enriched: dict,
    piotroski: dict,
    moat_result: dict,
    is_financial: bool,
    existing_flags: list,
    price: float,
) -> list:
    """
    Generate structured ``RedFlag`` objects from the already-built
    enriched dict plus piotroski/moat results. Never raises —
    every individual signal is wrapped in try/except so one bad
    value cannot block the rest.

    Returns a list sorted critical → warning → info.
    """
    flags: list = []
    try:
        _add_flags(flags, enriched, piotroski, moat_result, is_financial, price)
    except Exception as exc:
        import logging
        logging.getLogger("yieldiq.red_flags").debug(
            "structured flag generator failed: %s", exc
        )
    order = {"critical": 0, "warning": 1, "info": 2}
    flags.sort(key=lambda f: order.get(f.severity, 3))
    return flags


def _add_flags(
    flags: list,
    enriched: dict,
    piotroski: dict,
    moat_result: dict,
    is_financial: bool,
    price: float,
) -> None:
    """All flag-specific logic. Appends RedFlag objects to ``flags``."""

    def add(flag, severity, title, explanation, data_point, why_it_matters):
        flags.append(RedFlag(
            flag=flag,
            severity=severity,
            title=title,
            explanation=explanation,
            data_point=data_point,
            why_it_matters=why_it_matters,
        ))

    # ── CRITICAL ───────────────────────────────────────────────

    # C1 — Negative equity
    try:
        equity = enriched.get("total_equity")
        if equity is not None and float(equity) < 0:
            debt = enriched.get("total_debt", 0)
            assets = enriched.get("total_assets")
            parts = [f"Total equity: {_fmt_cr(equity)}"]
            if assets is not None:
                parts.append(f"Debt: {_fmt_cr(debt)}, Assets: {_fmt_cr(assets)}")
            else:
                parts.append(f"Debt: {_fmt_cr(debt)}")
            add(
                flag="negative_equity",
                severity="critical",
                title="Negative Equity",
                explanation=(
                    "Total liabilities exceed total assets — the company "
                    "technically owes more than it owns."
                ),
                data_point=" · ".join(parts),
                why_it_matters=(
                    "Negative equity makes DCF valuation unreliable and "
                    "signals elevated bankruptcy risk. Common in capital-"
                    "heavy sectors (airlines, infra) — check the reason "
                    "before acting."
                ),
            )
    except Exception:
        pass

    # C2 — Loss-making for 2+ consecutive years (non-financial)
    if not is_financial:
        try:
            income_df = enriched.get("income_df")
            if income_df is not None and "net_income" in income_df.columns:
                recent = income_df["net_income"].dropna().tail(2)
                if len(recent) >= 2 and (recent < 0).all():
                    vals = recent.tolist()
                    add(
                        flag="loss_making",
                        severity="critical",
                        title="Consecutive Losses",
                        explanation=(
                            "Company has reported net losses for 2+ "
                            "consecutive years."
                        ),
                        data_point=(
                            f"Net income last 2 years: "
                            f"{_fmt_cr(vals[0])}, {_fmt_cr(vals[1])}"
                        ),
                        why_it_matters=(
                            "Sustained losses erode equity, increase debt "
                            "dependence, and make DCF valuation based on "
                            "future cash flows unreliable."
                        ),
                    )
        except Exception:
            pass

    # C3 — Very high debt (D/E > 3, non-financial)
    if not is_financial:
        try:
            de = enriched.get("de_ratio")
            if de is None:
                de = enriched.get("debt_to_equity")
            if de is not None and float(de) > 3:
                add(
                    flag="high_debt",
                    severity="critical",
                    title="Very High Debt",
                    explanation=(
                        "Debt is more than 3× equity — a level that "
                        "strains interest payments and limits financial "
                        "flexibility."
                    ),
                    data_point=f"Debt / Equity: {float(de):.1f}x",
                    why_it_matters=(
                        "High leverage amplifies losses in downturns and "
                        "can trigger covenant breaches. WACC rises with "
                        "debt risk."
                    ),
                )
        except Exception:
            pass

    # C4 — Promoter pledge > 25%
    try:
        pledge = enriched.get("promoter_pledge_pct")
        if pledge is not None:
            p = float(pledge)
            if p > 25:
                add(
                    flag="high_promoter_pledge",
                    severity="critical",
                    title="High Promoter Pledge",
                    explanation=(
                        "Promoters have pledged more than 25% of their "
                        "shareholding as loan collateral."
                    ),
                    data_point=f"Promoter pledge: {p:.1f}% of promoter holding",
                    why_it_matters=(
                        "If the stock falls, lenders can force-sell "
                        "pledged shares, triggering a spiral. One of the "
                        "highest-risk signals for Indian retail investors."
                    ),
                )
    except Exception:
        pass

    # ── WARNING ────────────────────────────────────────────────

    # W1 — DCF unreliable
    try:
        if not enriched.get("dcf_reliable", True):
            reason = enriched.get("unreliable_reason") or "Insufficient financial data"
            add(
                flag="dcf_unreliable",
                severity="warning",
                title="DCF Model Limited",
                explanation=(
                    "The discounted cash flow model has reduced "
                    "reliability for this stock."
                ),
                data_point=f"Reason: {reason}",
                why_it_matters=(
                    "Treat the fair value estimate as directional only. "
                    "Cross-check with P/E and P/B multiples before "
                    "acting on the signal."
                ),
            )
    except Exception:
        pass

    # W2 — Declining revenue 3 years running
    try:
        income_df = enriched.get("income_df")
        if income_df is not None and "revenue" in income_df.columns:
            rev = income_df["revenue"].dropna().tail(3)
            if len(rev) >= 3 and (rev.diff().dropna() < 0).all():
                vals = rev.tolist()
                add(
                    flag="declining_revenue",
                    severity="warning",
                    title="Declining Revenue",
                    explanation="Revenue has fallen for 3 consecutive years.",
                    data_point=(
                        f"Revenue: {_fmt_cr(vals[0])} → "
                        f"{_fmt_cr(vals[1])} → {_fmt_cr(vals[2])}"
                    ),
                    why_it_matters=(
                        "Sustained revenue decline suggests structural "
                        "demand loss or competitive pressure. FCF growth "
                        "assumptions in DCF may be optimistic."
                    ),
                )
    except Exception:
        pass

    # W3 — Negative FCF (non-financial, current year)
    if not is_financial:
        try:
            fcf = enriched.get("latest_fcf", 0)
            rev = enriched.get("latest_revenue", 0)
            if fcf is not None and float(fcf) < 0 and rev and float(rev) > 0:
                add(
                    flag="negative_fcf",
                    severity="warning",
                    title="Negative Free Cash Flow",
                    explanation=(
                        "The company is consuming more cash than it "
                        "generates from operations after capex."
                    ),
                    data_point=(
                        f"FCF: {_fmt_cr(fcf)} "
                        f"(FCF margin: {fcf / rev * 100:.1f}%)"
                    ),
                    why_it_matters=(
                        "Negative FCF companies rely on debt or equity "
                        "issuance to fund operations. Sustainable only "
                        "for high-growth businesses with a clear path to "
                        "profitability."
                    ),
                )
        except Exception:
            pass

    # W4 — Very thin net margins (< 5%, non-financial, positive)
    if not is_financial:
        try:
            nm = enriched.get("net_margin")
            if nm is not None:
                nm_pct = float(nm) * 100 if abs(float(nm)) <= 1 else float(nm)
                if 0 < nm_pct < 5:
                    add(
                        flag="thin_margins",
                        severity="warning",
                        title="Very Thin Margins",
                        explanation=(
                            "Net profit margin is below 5%, leaving "
                            "little buffer for cost shocks."
                        ),
                        data_point=f"Net margin: {nm_pct:.1f}%",
                        why_it_matters=(
                            "Thin margins amplify earnings sensitivity to "
                            "input costs, wages, and rates. A 1pp margin "
                            "shock on a 3% margin business eliminates "
                            "~33% of profits."
                        ),
                    )
        except Exception:
            pass

    # W5 — Very high P/E (> 60)
    try:
        pe = enriched.get("pe_ratio")
        if pe is None:
            pe = enriched.get("trailing_pe")
        if pe is not None and isinstance(pe, (int, float)) and float(pe) > 60:
            add(
                flag="high_pe",
                severity="warning",
                title="Very High P/E Ratio",
                explanation=(
                    "Stock trades above 60× earnings — pricing in very "
                    "high future growth."
                ),
                data_point=f"P/E ratio: {float(pe):.1f}x",
                why_it_matters=(
                    "High-P/E stocks are vulnerable to re-rating if "
                    "growth disappoints. Earnings misses can cause sharp "
                    "price declines."
                ),
            )
    except Exception:
        pass

    # W6 — Weak Piotroski (≤ 3)
    try:
        p_score = int(piotroski.get("score", 0)) if piotroski else 0
        if 0 < p_score <= 3:
            add(
                flag="weak_piotroski",
                severity="warning",
                title="Weak Financial Health",
                explanation=(
                    "Piotroski F-Score of 3 or below indicates poor "
                    "financial quality across profitability, leverage, "
                    "and efficiency."
                ),
                data_point=f"Piotroski F-Score: {p_score}/9",
                why_it_matters=(
                    "Low Piotroski scores historically predict "
                    "underperformance — stocks scoring ≤ 3 are "
                    "short-sell candidates in academic research."
                ),
            )
    except Exception:
        pass

    # W7 — Elevated pledge (10% < p ≤ 25%)
    try:
        pledge = enriched.get("promoter_pledge_pct")
        if pledge is not None:
            p = float(pledge)
            if 10 < p <= 25:
                add(
                    flag="elevated_pledge",
                    severity="warning",
                    title="Elevated Promoter Pledge",
                    explanation=(
                        "Promoters have pledged 10–25% of their "
                        "shareholding."
                    ),
                    data_point=f"Promoter pledge: {p:.1f}%",
                    why_it_matters=(
                        "Moderate pledge risk. Monitor if the stock "
                        "falls sharply — forced selling can accelerate "
                        "the decline."
                    ),
                )
    except Exception:
        pass

    # ── INFO / positive signals ────────────────────────────────

    # I1 — Debt-free (< ₹50 Cr treated as effectively zero)
    try:
        debt = enriched.get("total_debt", 0)
        if debt is not None and float(debt) < 50:
            add(
                flag="debt_free",
                severity="info",
                title="Virtually Debt-Free",
                explanation="The company carries minimal or zero long-term debt.",
                data_point=f"Total debt: {_fmt_cr(debt)}",
                why_it_matters=(
                    "Zero debt means all FCF goes to shareholders. Lower "
                    "WACC and higher resilience during credit tightening."
                ),
            )
    except Exception:
        pass

    # I2 — Strong Piotroski (≥ 7)
    try:
        p_score = int(piotroski.get("score", 0)) if piotroski else 0
        if p_score >= 7:
            add(
                flag="strong_piotroski",
                severity="info",
                title="Strong Financial Health",
                explanation=(
                    "Piotroski F-Score of 7+ indicates excellent "
                    "profitability, improving leverage, and operational "
                    "efficiency."
                ),
                data_point=f"Piotroski F-Score: {p_score}/9",
                why_it_matters=(
                    "High Piotroski scores predict outperformance in "
                    "academic research. Signals improving fundamental "
                    "quality."
                ),
            )
    except Exception:
        pass

    # I3 — Wide moat
    try:
        m_score = int(moat_result.get("score", 0)) if moat_result else 0
        m_grade = (moat_result.get("grade") or "") if moat_result else ""
        if m_score > 65 or m_grade == "Wide":
            moat_types = moat_result.get("moat_types", []) if moat_result else []
            type_str = ", ".join(moat_types) if moat_types else "competitive advantages"
            add(
                flag="wide_moat",
                severity="info",
                title="Wide Economic Moat",
                explanation=(
                    "The business has durable competitive advantages "
                    "that protect long-term profitability."
                ),
                data_point=f"Moat score: {m_score}/100 ({type_str})",
                why_it_matters=(
                    "Wide-moat companies maintain returns above cost of "
                    "capital for longer, supporting higher DCF terminal "
                    "values."
                ),
            )
    except Exception:
        pass

    # I4 — High ROE (> 20%)
    try:
        roe = enriched.get("roe")
        if roe is not None:
            roe_pct = float(roe) * 100 if abs(float(roe)) <= 1 else float(roe)
            if roe_pct > 20:
                add(
                    flag="high_roe",
                    severity="info",
                    title="High Return on Equity",
                    explanation=(
                        "The company earns more than 20% return on "
                        "shareholder equity — a hallmark of quality "
                        "businesses."
                    ),
                    data_point=f"ROE: {roe_pct:.1f}%",
                    why_it_matters=(
                        "Sustained high ROE means capital can be "
                        "reinvested at above-average rates, compounding "
                        "value over time."
                    ),
                )
    except Exception:
        pass

    # I5 — Strong FCF margin (> 10%, non-financial)
    if not is_financial:
        try:
            fcf = enriched.get("latest_fcf", 0)
            rev = enriched.get("latest_revenue", 0)
            if fcf and rev and float(fcf) > 0:
                margin_pct = float(fcf) / float(rev) * 100
                if margin_pct > 10:
                    add(
                        flag="strong_fcf",
                        severity="info",
                        title="Strong Free Cash Flow",
                        explanation=(
                            "Business generates healthy free cash flow "
                            "as a percentage of revenue."
                        ),
                        data_point=(
                            f"FCF: {_fmt_cr(fcf)} "
                            f"(FCF margin: {margin_pct:.1f}%)"
                        ),
                        why_it_matters=(
                            "Strong FCF funds dividends, buybacks, debt "
                            "reduction, and growth capex without "
                            "external financing."
                        ),
                    )
        except Exception:
            pass


class TickerNotFoundError(Exception):
    """Raised when the data provider returns no data for a ticker —
    i.e. the ticker symbol is invalid, unlisted, or misspelled.
    The router maps this to HTTP 404; anything else becomes 500."""

    def __init__(self, ticker: str):
        self.ticker = ticker
        super().__init__(f"Ticker not found: {ticker}")


# Track consecutive DB failures. After 3 failures, enter a 60-second
# cooldown (not 5 minutes — that was too aggressive). This allows
# Aiven to wake up from cold start (takes ~10-30s) without blocking
# the entire analysis pipeline for 5 minutes.
import time as _time
_db_fail_count: int = 0
_db_dead_until: float = 0


def _get_pipeline_session():
    """Get a DB session from the data pipeline, or None if unavailable."""
    global _db_fail_count, _db_dead_until
    import logging as _log
    _logger = _log.getLogger("yieldiq.db")

    now = _time.time()
    if now < _db_dead_until:
        return None  # In cooldown — skip instantly
    try:
        from data_pipeline.db import Session as PipelineSession, DATABASE_URL as _db_url
        if PipelineSession is None:
            if _db_url:
                _logger.warning("DB_SESSION: Session is None despite DATABASE_URL being set")
            _db_dead_until = now + 60
            return None
        session = PipelineSession()
        # Success — reset failure counter
        if _db_fail_count > 0:
            _logger.info("DB_SESSION: reconnected after %d failures", _db_fail_count)
        _db_fail_count = 0
        return session
    except Exception as exc:
        _db_fail_count += 1
        # Escalating cooldown: 10s → 30s → 60s
        cooldown = min(60, 10 * _db_fail_count)
        _db_dead_until = now + cooldown
        _logger.warning("DB_SESSION: fail #%d (%s), cooldown %ds",
                        _db_fail_count, str(exc)[:60], cooldown)
        return None


# USD → INR conversion rate for Financials rows tagged `currency = 'USD'`.
# TODO: source from a forex feed (RBI reference rate) rather than a constant.
USD_INR_RATE = 83.5


def _fx_multiplier(currency: str | None) -> float:
    """Return the multiplier to convert a Financials row into INR."""
    if not currency:
        return 1.0
    code = str(currency).strip().upper()
    if code == "USD":
        return USD_INR_RATE
    return 1.0


def _convert_row_to_inr(ticker: str, row) -> tuple[float | None, float | None, float | None]:
    """
    Read fcf / revenue / pat off a Financials row and convert to INR
    based on the row's `currency` column.

    IDEMPOTENCY GUARD: our ingestion layers have historically converted
    USD → INR *before* writing to the Financials table (data/collector.py
    ::_detect_financial_currency multiplies by APPROX_USD_TO_INR for
    HCLTECH, INFY etc). If the migration backfill then tagged the same
    rows as currency='USD', a read-side _fx_multiplier would double-
    convert, producing fcf_base ≈ 83× real (HCLTECH bug, commit b31a7e9
    canary showed FV ₹6,073 vs real ~₹1,500).

    Heuristic: for any large-cap Indian stock, TTM revenue should be
    at least ₹100 crore (₹1 billion = 1e9). If the raw row value already
    exceeds that threshold, treat it as already-INR regardless of the
    currency tag. A genuine USD row would have revenue in the $100M-$10B
    range (1e8–1e10), whereas an INR-already row for the same company
    is 83× larger (1e10–1e12). The boundary is clean.
    """
    ccy = getattr(row, "currency", None) or "INR"
    mult = _fx_multiplier(ccy)

    raw_fcf = row.free_cash_flow
    raw_rev = row.revenue
    raw_pat = row.pat

    if mult != 1.0:
        # Idempotency: if revenue is already in ₹-crore magnitude
        # (> ₹100 crore = 1e9), the ingestion layer already converted.
        # Do NOT multiply again.
        _rev_magnitude = float(raw_rev or 0)
        if _rev_magnitude > 1e10:  # ₹1,000 crore — unmistakably INR-already
            _logger.info(
                "FX_SKIP: %s tagged %s but revenue=%.2e suggests INR-"
                "already (double-convert guard)", ticker, ccy, _rev_magnitude,
            )
            mult = 1.0

    fcf = raw_fcf * mult if raw_fcf is not None else None
    rev = raw_rev * mult if raw_rev is not None else None
    pat = raw_pat * mult if raw_pat is not None else None
    if mult != 1.0:
        _logger.info(
            "FX_CONVERT: %s %s → INR at %.2f (fcf %.2f → %.2f)",
            ticker, ccy, mult, raw_fcf or 0.0, fcf or 0.0,
        )
    return fcf, rev, pat


def _query_ttm_financials(ticker: str):
    """
    Query TTM financials from local DB.
    Returns dict with fcf, revenue, pat (INR-normalised) or None if unavailable.
    """
    db = _get_pipeline_session()
    if db is None:
        return None
    try:
        from data_pipeline.models import Financials
        from sqlalchemy import desc
        # Strip .NS/.BO suffix for DB lookup
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")
        row = (
            db.query(Financials)
            .filter(Financials.ticker == db_ticker, Financials.period_type == "ttm")
            .order_by(desc(Financials.period_end))
            .first()
        )
        if row and row.free_cash_flow is not None:
            fcf, rev, pat = _convert_row_to_inr(ticker, row)
            return {
                "fcf": fcf,
                "revenue": rev,
                "pat": pat,
                "period_end": str(row.period_end) if row.period_end else None,
                "currency": getattr(row, "currency", None) or "INR",
                "source": "ttm",
            }
        return None
    except Exception:
        return None
    finally:
        db.close()


def _query_latest_annual_financials(ticker: str):
    """
    Query latest annual financials from local DB.
    Returns dict with fcf, revenue, pat (INR-normalised) or None if unavailable.
    """
    db = _get_pipeline_session()
    if db is None:
        return None
    try:
        from data_pipeline.models import Financials
        from sqlalchemy import desc
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")
        row = (
            db.query(Financials)
            .filter(Financials.ticker == db_ticker, Financials.period_type == "annual")
            .order_by(desc(Financials.period_end))
            .first()
        )
        if row and row.free_cash_flow is not None:
            fcf, rev, pat = _convert_row_to_inr(ticker, row)
            return {
                "fcf": fcf,
                "revenue": rev,
                "pat": pat,
                "period_end": str(row.period_end) if row.period_end else None,
                "currency": getattr(row, "currency", None) or "INR",
                "source": "annual",
            }
        return None
    except Exception:
        return None
    finally:
        db.close()


def _query_shareholding(ticker: str) -> dict | None:
    """
    Fetch the latest shareholding pattern (promoter / FII / DII /
    public + pledge) from the ShareholdingPattern table. Returns
    ``None`` if the table/row is missing.
    """
    db = _get_pipeline_session()
    if db is None:
        return None
    try:
        from data_pipeline.models import ShareholdingPattern
        from sqlalchemy import desc
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")
        row = (
            db.query(ShareholdingPattern)
            .filter(ShareholdingPattern.ticker == db_ticker)
            .order_by(desc(ShareholdingPattern.quarter_end))
            .first()
        )
        if row is None:
            return None
        return {
            "promoter_pct":        float(row.promoter_pct) if row.promoter_pct is not None else None,
            "promoter_pledge_pct": float(row.promoter_pledge_pct) if row.promoter_pledge_pct is not None else None,
            "fii_pct":             float(row.fii_pct) if row.fii_pct is not None else None,
            "dii_pct":             float(row.dii_pct) if row.dii_pct is not None else None,
            "public_pct":          float(row.public_pct) if row.public_pct is not None else None,
        }
    except Exception:
        return None
    finally:
        db.close()


def _query_promoter_pledge(ticker: str):
    """Legacy shim — red-flag generator calls this by name. Kept so
    we don't break callers that only need the pledge number."""
    data = _query_shareholding(ticker)
    return data.get("promoter_pledge_pct") if data else None


def _fetch_ebit_and_interest(ticker: str) -> tuple[float | None, float | None]:
    """
    Pull the most recent annual EBIT and interest_expense.

    Priority:
      1. ``company_financials`` table (new XBRL pipeline — has explicit EBIT)
      2. ``financials`` table (old pipeline — has EBITDA, use as EBIT proxy)

    Returns (None, None) if neither table has data for this ticker.
    """
    db = _get_pipeline_session()
    if db is None:
        return None, None
    try:
        from sqlalchemy import text
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")

        # Try company_financials first (has real EBIT)
        row = db.execute(text("""
            SELECT ebit, interest_expense
            FROM company_financials
            WHERE ticker_nse = :t
              AND statement_type = 'income'
              AND period_type = 'annual'
              AND period_end_date IS NOT NULL
            ORDER BY period_end_date DESC
            LIMIT 1
        """), {"t": db_ticker}).mappings().first()
        def _f(v):
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        if row:
            ebit = _f(row.get("ebit"))
            interest = _f(row.get("interest_expense"))
            if ebit is not None:
                return ebit, interest

        # Fallback: old financials table has EBITDA (use as EBIT proxy)
        # EBITDA ≈ EBIT + depreciation. Without depreciation data,
        # EBITDA is a reasonable upper-bound proxy for ROCE calculation.
        old_row = db.execute(text("""
            SELECT ebitda, ebit
            FROM financials
            WHERE ticker = :t
              AND period_type = 'annual'
              AND period_end IS NOT NULL
            ORDER BY period_end DESC
            LIMIT 1
        """), {"t": db_ticker}).mappings().first()

        if old_row:
            ebit_val = _f(old_row.get("ebit")) or _f(old_row.get("ebitda"))
            if ebit_val is not None:
                return ebit_val, None  # No interest_expense in old table

        return None, None
    except Exception as exc:
        import logging
        logging.getLogger("yieldiq.analysis").debug(
            "ebit/interest fetch failed for %s: %s", ticker, exc
        )
        return None, None
    finally:
        try:
            db.close()
        except Exception:
            pass


def _debt_ebitda_label(ratio: float | None) -> str | None:
    """Map Debt/EBITDA to a text band. None in → None out."""
    if ratio is None:
        return None
    if ratio < 1.0:
        return "Excellent"
    if ratio < 3.0:
        return "Healthy"
    if ratio < 5.0:
        return "Leveraged"
    return "High Risk"


def _query_earnings_date(ticker: str) -> dict | None:
    """Query next earnings date from UpcomingEarnings table."""
    db = _get_pipeline_session()
    if db is None:
        return None
    try:
        from data_pipeline.sources.nse_earnings import get_next_earnings
        return get_next_earnings(ticker, db)
    except Exception:
        return None
    finally:
        db.close()


def _query_bulk_deals(ticker: str, days: int = 90) -> list[dict]:
    """Query recent bulk/block deals from BulkDeal table."""
    db = _get_pipeline_session()
    if db is None:
        return []
    try:
        from data_pipeline.models import BulkDeal
        from sqlalchemy import desc
        from datetime import timedelta
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")
        cutoff = datetime.now().date() - timedelta(days=days)
        rows = (
            db.query(BulkDeal)
            .filter(BulkDeal.ticker == db_ticker, BulkDeal.trade_date >= cutoff)
            .order_by(desc(BulkDeal.trade_date))
            .limit(10)
            .all()
        )
        deals = []
        for r in rows:
            deals.append({
                "date": str(r.trade_date) if r.trade_date else "",
                "client": r.client_name or "",
                "deal_type": r.deal_type or "",
                "qty_lakh": round(float(r.quantity or 0) / 1e5, 2),
                "price": float(r.price or 0),
                "category": r.deal_category or "",
            })
        return deals
    except Exception:
        return []
    finally:
        db.close()


class AnalysisService:
    """Orchestrates full stock analysis using existing engines."""

    def get_full_analysis(self, ticker: str) -> AnalysisResponse:
        """Public entry — validates output before returning."""
        result = self._get_full_analysis_inner(ticker)
        try:
            from backend.services.validators import validate_analysis, log_validation
            vr = validate_analysis(result)
            log_validation(ticker, vr)
            # Attach validation metadata for frontend (optional, non-breaking)
            if vr.issues:
                # Stuff into data_issues field which is already on the response
                try:
                    existing = list(getattr(result, "data_issues", []) or [])
                    existing.extend([f"[{vr.severity}] {iss}" for iss in vr.issues])
                    result.data_issues = existing
                except Exception:
                    pass
        except Exception as _ve:
            import logging as _vl
            _vl.getLogger("yieldiq.validators").warning(f"Validator crashed for {ticker}: {_ve}")
        return result

    def _get_full_analysis_inner(self, ticker: str) -> AnalysisResponse:
        """
        Main analysis pipeline:
        1. Fetch data (collector)
        2. Validate (validator)
        3. Compute metrics (processor)
        4. Forecast FCF (forecaster)
        5. Run DCF (dcf_engine)
        6. Run quality checks (piotroski, moat, earnings quality)
        7. Run scenarios (scenarios)
        8. Generate insights (valuation_model, reverse_dcf, etc.)
        9. Map to response model
        """
        _ts = datetime.now().isoformat()

        # ── Step 1: Fetch data ────────────────────────────────
        # Try local DB + Parquet first (~100ms). Fall back to
        # yfinance collector (~20-30s) only if local data is
        # insufficient (ticker not in DB, no Parquet file, etc).
        import time as _time
        raw = None
        _data_source = "unknown"

        try:
            from backend.services.local_data_service import assemble_local
            _local_db = _get_pipeline_session()
            if _local_db is not None:
                try:
                    raw = assemble_local(ticker, _local_db)
                    if raw is not None:
                        _data_source = "local_db_parquet"
                        import logging as _lds_log
                        _lds_log.getLogger("yieldiq.analysis").info(
                            "[%s] served from local DB+Parquet (fast path)", ticker
                        )
                finally:
                    try:
                        _local_db.close()
                    except Exception:
                        pass
        except Exception as _local_exc:
            import logging as _lds_log
            _lds_log.getLogger("yieldiq.analysis").warning(
                "[%s] local assembler EXCEPTION: %s: %s",
                ticker, type(_local_exc).__name__, _local_exc
            )

        # Fallback: yfinance collector (slow but comprehensive)
        if raw is None:
            _data_source = "yfinance"
            for _attempt in range(3):
                try:
                    collector = StockDataCollector(ticker)
                    raw = collector.get_all()
                    if raw is not None:
                        break
                except Exception:
                    pass
                if raw is None and _attempt < 2:
                    _time.sleep(3 + _attempt * 3)  # 3s, 6s delays

        # ── Step 2: Validate ──────────────────────────────────
        validation = validate_stock_data(ticker, raw)
        _raw_confidence = validation.confidence if validation else "medium"
        _confidence = _raw_confidence if _raw_confidence in ("high", "medium", "low", "unusable") else "medium"
        _data_issues = (validation.issues + validation.warnings) if validation else []

        # No data at all after 3 retries → ticker doesn't exist on any
        # data provider. Signal the router so it returns 404 instead of
        # producing an all-zeros response that the frontend mistakes
        # for a valid but-terrible stock.
        #
        # yfinance sometimes returns a `raw` dict with every identifying
        # field set to None (observed for TATAMOTORS.NS and ZOMATO.NS
        # after Yahoo 404s) — not actually None. Treat that as "not
        # found" too.
        _has_any_useful = isinstance(raw, dict) and any(
            raw.get(k) for k in (
                "currentPrice", "regularMarketPrice", "current_price",
                "shortName", "longName", "company_name", "symbol", "ticker",
            )
        )
        if raw is None or not _has_any_useful:
            raise TickerNotFoundError(ticker)

        # Raw data exists but validation vetoed running DCF (e.g. the
        # company is a bank/NBFC that needs a different model, or data
        # is too incomplete). Return a 200 with a low-confidence
        # response so the frontend can render a degraded card.
        if validation and not validation.show_dcf:
            return AnalysisResponse(
                ticker=ticker,
                company=CompanyInfo(ticker=ticker, company_name=ticker),
                valuation=ValuationOutput(
                    fair_value=0, current_price=0, margin_of_safety=0,
                    verdict="avoid", confidence_score=0, dcf_reliable=False,
                ),
                quality=QualityOutput(),
                insights=InsightCards(),
                data_confidence=_confidence,
                data_issues=_data_issues,
                timestamp=_ts,
            )

        # ── Step 3: Compute metrics ───────────────────────────
        enriched = compute_metrics(raw)
        price = enriched.get("price", 0) or 0
        is_indian = ticker.endswith(".NS") or ticker.endswith(".BO")

        # ── Data-quality sanity checks ────────────────────────
        # Trip "unavailable" when yfinance returned partial/stale data
        # that would render as ₹0 cards. Covers:
        #   (a) Missing/zero/tiny price (classic)
        #   (b) Price exists but no fundamentals at all (delisted /
        #       renamed tickers — e.g. ZOMATO→ETERNAL, stale cache)
        _shares = enriched.get("shares", 0) or 0
        _latest_revenue = enriched.get("latest_revenue", 0) or 0
        _latest_pat = enriched.get("latest_pat", 0) or 0
        _has_any_fundamentals = (
            _latest_revenue > 0 or _latest_pat != 0 or _shares > 0
        )
        if not price or price < 1 or not _has_any_fundamentals:
            _issue = (
                "Price data unavailable \u2014 try again in 60 seconds."
                if not price or price < 1
                else "Financial data unavailable for this ticker. "
                "It may be delisted, renamed, or data may be stale."
            )
            return AnalysisResponse(
                ticker=ticker,
                company=CompanyInfo(
                    ticker=ticker,
                    company_name=raw.get("company_name", ticker) if raw else ticker,
                ),
                valuation=ValuationOutput(
                    fair_value=0, current_price=0, margin_of_safety=0,
                    verdict="unavailable", confidence_score=0, dcf_reliable=False,
                ),
                quality=QualityOutput(),
                insights=InsightCards(),
                data_confidence="unusable",
                data_issues=[_issue],
                timestamp=_ts,
            )

        # Detect financial companies (NBFC/Bank/Insurance)
        clean_ticker = ticker.replace('.NS', '').replace('.BO', '')
        is_financial = clean_ticker in FINANCIAL_COMPANIES

        # ── Step 4: Build company info ────────────────────────
        _raw_sector = enriched.get("sector_name", raw.get("sector_name", ""))
        _display_name = COMPANY_NAME_OVERRIDES.get(ticker, raw.get("company_name", ticker))
        # Exchange detection: .NS → NSE, .BO → BSE
        _exchange = raw.get("exchange", "")
        if not _exchange:
            _exchange = "NSE" if ticker.endswith(".NS") else "BSE" if ticker.endswith(".BO") else ""
        _industry = raw.get("industry", enriched.get("industry", ""))
        _country = "India" if is_indian else raw.get("country", "")

        company = CompanyInfo(
            ticker=ticker,
            company_name=_display_name,
            exchange=_exchange,
            sector=_resolve_sector(_raw_sector, clean_ticker),
            industry=_industry,
            country=_country,
            currency="INR" if is_indian else "USD",
            market_cap=price * enriched.get("shares", 0),
        )

        # ── Step 5: WACC + Forecast ───────────────────────────
        # Try TTM data from local DB first, then annual, then yfinance.
        # USD-reporting tickers (HCLTECH, INFY, WIPRO etc.) used to bypass
        # this path entirely — now the Financials.currency column lets
        # _query_ttm_financials / _query_latest_annual_financials convert
        # USD rows to INR before returning.
        _fcf_data_source = "yfinance"
        _ttm_data = _query_ttm_financials(ticker)
        if _ttm_data:
            _fcf_data_source = "ttm"
            if _ttm_data.get("fcf") is not None:
                enriched["latest_fcf"] = _ttm_data["fcf"]
            if _ttm_data.get("revenue") is not None:
                enriched["latest_revenue"] = _ttm_data["revenue"]
            if _ttm_data.get("pat") is not None:
                enriched["latest_pat"] = _ttm_data["pat"]
        else:
            _annual_data = _query_latest_annual_financials(ticker)
            if _annual_data:
                _fcf_data_source = "annual"
                if _annual_data.get("fcf") is not None and not enriched.get("latest_fcf"):
                    enriched["latest_fcf"] = _annual_data["fcf"]

        # Apply FCF floor for capex-heavy companies (e.g. RELIANCE, MARUTI, TITAN, HUL)
        _pat = None
        _raw_fcf = enriched.get("latest_fcf", 0) or 0

        # 1. income_df net_income (MOST RELIABLE -- always populated by compute_metrics)
        _income_df = enriched.get("income_df")
        if _income_df is not None and hasattr(_income_df, 'empty') and not _income_df.empty:
            if "net_income" in _income_df.columns:
                try:
                    _ni = float(_income_df["net_income"].iloc[-1] or 0)
                    if _ni > 0:
                        _pat = _ni
                except Exception:
                    pass

        # 2. net_margin x revenue
        if not _pat or _pat <= 0:
            _rev = enriched.get("latest_revenue", 0) or 0
            _nm = enriched.get("net_margin", 0) or 0
            if _rev > 0 and _nm > 0:
                _pat = _rev * _nm

        # 3. yahoo_fcf_ttm
        if not _pat or _pat <= 0:
            _yf = raw.get("yahoo_fcf_ttm", 0) or 0
            if _yf > 0:
                _pat = _yf

        # 4. EBITDA x 0.60
        if not _pat or _pat <= 0:
            _eb = raw.get("ebitda") or enriched.get("ebitda", 0) or 0
            if _eb > 0:
                _pat = _eb * 0.60

        # 5. EPS x shares
        if not _pat or _pat <= 0:
            _eps = raw.get("trailingEps") or 0
            _shares = enriched.get("shares") or raw.get("shares", 0) or 0
            if _eps > 0 and _shares > 0:
                _pat = _eps * _shares

        _adjusted_fcf = _get_adjusted_fcf(_raw_fcf, _pat, is_financial)
        if _adjusted_fcf is not None and _adjusted_fcf != _raw_fcf and not is_financial:
            enriched["latest_fcf"] = _adjusted_fcf

        forecaster = FCFForecaster()
        try:
            from models.forecaster import compute_wacc as _compute_wacc
            wacc_data = _compute_wacc(raw, is_indian, enriched=enriched)
            wacc = wacc_data.get("wacc", 0.10)
        except Exception:
            wacc_data = {"beta": 1.0, "beta_source": "fallback"}
            wacc = 0.10

        country = get_active_country()
        terminal_g = country.get("default_terminal_growth", 0.025)
        if terminal_g >= wacc:
            terminal_g = wacc - 0.02

        forecast_yrs = 10

        # ── Step 6: Valuation (P/B for financials, DCF for others) ──
        if is_financial:
            # Defaults — always defined regardless of which P/B path runs
            bear_iv = round(price * 0.75, 2) if price > 0 else 0
            bull_iv = round(price * 1.25, 2) if price > 0 else 0
            iv = round(price, 2) if price > 0 else 0

            # --- P/B RATIO VALUATION for banks/NBFCs/insurance ---
            _sub_type = _get_financial_sub_type(clean_ticker)
            _pb_median = _PB_MEDIANS.get(_sub_type, 2.5)
            _val_method = ""

            # Method 1: Derive BVPS from priceToBook (most reliable)
            # collector.py never puts "bookValue" into raw — derive it
            _pb_live = raw.get("priceToBook") or enriched.get("pb_ratio")
            _bvps = 0
            if _pb_live and _pb_live > 0 and price > 0:
                _bvps = price / _pb_live

            # Method 2: total_equity / shares from balance sheet
            if not _bvps or _bvps <= 0:
                _equity = (enriched.get("total_equity")
                           or raw.get("total_equity") or 0)
                _shares = enriched.get("shares") or raw.get("shares", 0)
                if _equity and _shares and _shares > 0:
                    _bvps = _equity / _shares

            if _bvps and _bvps > 0:
                iv = round(_bvps * _pb_median, 2)
                # PR-BANKSC: bear was hard-coded `_bvps * 1.5` which
                # coincidentally equals base when peer P/B median ≈ 1.5
                # (e.g. HDFCBANK), producing bear=base=₹542 — flat
                # scenario display. Match the bull's structure: discount
                # 30% off base (mirror of bull's +40%).
                bear_iv = round(_bvps * _pb_median * 0.7, 2)
                bull_iv = round(_bvps * _pb_median * 1.4, 2)
                _val_method = f"P/B × {_pb_median} ({_sub_type})"
            else:
                iv = 0

            # Method 3: PE-based fallback if P/B gave 0
            if iv <= 0:
                _eps = (enriched.get("diluted_eps")
                        or raw.get("trailingEps")
                        or enriched.get("eps")
                        or raw.get("fh_eps_ttm") or 0)
                _sector_pe = {"Banking": 15, "NBFC": 20, "Insurance": 18}.get(_sub_type, 15)
                if _eps and _eps > 0:
                    iv = round(_eps * _sector_pe, 2)
                    bear_iv = round(_eps * (_sector_pe * 0.7), 2)
                    bull_iv = round(_eps * (_sector_pe * 1.3), 2)
                    _val_method = f"P/E × {_sector_pe} ({_sub_type})"

            # Method 4: Analyst target
            if iv <= 0:
                _analyst_tgt = ((raw.get("finnhub_price_target") or {}).get("mean", 0)
                                or raw.get("targetMeanPrice", 0))
                if _analyst_tgt and _analyst_tgt > 0:
                    iv = round(_analyst_tgt * 0.85, 2)
                    bear_iv = round(_analyst_tgt * 0.60, 2)
                    bull_iv = round(_analyst_tgt * 1.10, 2)
                    _val_method = "Analyst consensus (adjusted)"

            # Method 5: NEVER ₹0 — use current price = fairly valued
            if iv <= 0 and price > 0:
                iv = round(price, 2)
                bear_iv = round(price * 0.75, 2)
                bull_iv = round(price * 1.25, 2)
                _val_method = "Insufficient data"

            # Safety: ensure bear/bull always defined for financials
            if bear_iv <= 0 and iv > 0:
                bear_iv = round(iv * 0.75, 2)
            if bull_iv <= 0 and iv > 0:
                bull_iv = round(iv * 1.25, 2)

            # ── Sector-appropriate peer-median override ─────────
            # For tickers that belong to a known peer group (psu_banks,
            # private_banks, growth_nbfc, govt_nbfc, life_insurance, etc.)
            # the peer-median P/BV or P/E approach gives a much more
            # realistic fair value than the single hardcoded multiplier
            # used above — and crucially, one that survives the sanity
            # gate in routers/analysis.py for PFC/REC/IRFC/LICI.
            _financial_val_result = None
            try:
                from backend.services.financial_valuation_service import (
                    compute_financial_fair_value,
                )
                _fv_company = {
                    "current_price": price,
                    "shares": enriched.get("shares") or raw.get("shares", 0),
                    "market_cap": price * (enriched.get("shares", 0) or 0),
                }
                _fv_fin = {
                    "priceToBook": raw.get("priceToBook") or enriched.get("pb_ratio"),
                    "total_equity": enriched.get("total_equity") or raw.get("total_equity"),
                    "pat": enriched.get("latest_pat") or _pat,
                    "latest_pat": enriched.get("latest_pat") or _pat,
                    "diluted_eps": enriched.get("diluted_eps"),
                    "eps_diluted": enriched.get("diluted_eps"),
                    "trailingEps": raw.get("trailingEps"),
                    "eps": enriched.get("eps"),
                    "fh_eps_ttm": raw.get("fh_eps_ttm"),
                    "roe": enriched.get("roe") or raw.get("returnOnEquity"),
                    "returnOnEquity": raw.get("returnOnEquity"),
                    "shares": enriched.get("shares") or raw.get("shares", 0),
                }
                _financial_val_result = compute_financial_fair_value(
                    ticker=ticker,
                    company_info=_fv_company,
                    financials=_fv_fin,
                    shareholding=None,
                )
            except Exception as _fv_exc:
                import logging as _fv_log
                _fv_log.getLogger("yieldiq.analysis").warning(
                    "[%s] financial_valuation failed: %s: %s",
                    ticker, type(_fv_exc).__name__, _fv_exc,
                )
                _financial_val_result = None

            if _financial_val_result and _financial_val_result.get("fair_value", 0) > 0:
                iv = float(_financial_val_result["fair_value"])
                bear_iv = float(_financial_val_result.get("bear_case", bear_iv))
                bull_iv = float(_financial_val_result.get("bull_case", bull_iv))
                _val_method = (
                    f"{_financial_val_result.get('method', 'p_bv_peer')} "
                    f"(peer median)"
                )

            iv_raw = iv
            dcf_res = {
                "intrinsic_value_per_share": iv,
                "warnings": [f"Valuation: {_val_method}"] if _val_method else [],
                "reliability_score": 75 if _bvps and _bvps > 0 else 50,
                "tv_pct_of_ev": 0,
                "sum_pv_fcfs": 0,
                "pv_tv": 0,
                "enterprise_value": 0,
                "equity_value": 0,
            }
            projected = []
            growth_schedule = []
            base_growth = 0
        else:
            # --- Standard DCF for non-financials ---
            forecast_result = forecaster.predict(enriched, years=forecast_yrs)
            projected = forecast_result.get("projections", [])
            growth_schedule = forecast_result.get("growth_schedule", [])
            base_growth = forecast_result.get("base_growth", 0)

            if not projected or all(v <= 0 for v in projected):
                projected = [enriched.get("latest_fcf", 1e6)] * forecast_yrs

            terminal_norm = float(sum(projected[-3:]) / 3) if len(projected) >= 3 else projected[-1] if projected else 0

            dcf_engine = DCFEngine(discount_rate=wacc, terminal_growth=terminal_g)
            dcf_res = dcf_engine.intrinsic_value_per_share(
                projected_fcfs=projected,
                terminal_fcf_norm=terminal_norm,
                total_debt=enriched.get("total_debt", 0),
                total_cash=enriched.get("total_cash", 0),
                shares_outstanding=enriched.get("shares", 1),
                current_price=price,
                ticker=ticker,
                beta=wacc_data.get("beta"),
            )
            iv_raw = dcf_res.get("intrinsic_value_per_share", 0)

            # Enrich the DCF_TRACE with upstream context so production
            # blow-ups (HCLTECH FV ₹6,075) can be diagnosed without
            # reproducing locally.
            try:
                from screener.dcf_engine import DCF_TRACES
                if ticker in DCF_TRACES:
                    DCF_TRACES[ticker]["fcf_source"] = _fcf_data_source
                    DCF_TRACES[ticker]["enriched_latest_fcf"] = float(enriched.get("latest_fcf") or 0)
                    DCF_TRACES[ticker]["enriched_latest_revenue"] = float(enriched.get("latest_revenue") or 0)
                    DCF_TRACES[ticker]["enriched_latest_pat"] = float(enriched.get("latest_pat") or 0)
                    DCF_TRACES[ticker]["enriched_op_margin"] = float(enriched.get("op_margin") or 0)
                    DCF_TRACES[ticker]["yahoo_fcf_ttm"] = float(raw.get("yahoo_fcf_ttm") or 0)
                    DCF_TRACES[ticker]["fin_multiplier"] = float(raw.get("fin_multiplier") or 1.0)
                    cands = enriched.get("_fcf_candidates") or {}
                    DCF_TRACES[ticker]["fcf_candidates"] = {k: float(v) for k, v in cands.items()}
                    DCF_TRACES[ticker]["fcf_base_source"] = enriched.get("_fcf_base_source", "unknown")
            except Exception:
                pass

            # PE crosscheck blend
            try:
                eps = get_eps(enriched)
                sector = enriched.get("sector", "general")
                pe_iv = compute_pe_based_iv(eps, sector, "base", enriched.get("revenue_growth", 0))
                iv = blend_dcf_pe(iv_raw, pe_iv, sector)
            except Exception:
                iv = iv_raw

        # ── Growth-stock override ─────────────────────────────
        # For pre-profit companies (FCF<=0 or PAT<=0) with real revenue,
        # the standard DCF produces ~0 fair value. Route to a reverse
        # P/S multiple so users see a principled number, not 'data_limited'.
        # All logging inside the growth module. No external logger refs
        # (previous attempt broke every ticker with NameError).
        try:
            from models.growth_valuation import (
                should_use_growth_path,
                compute_growth_valuation,
            )
            _mcap_for_growth = price * (enriched.get("shares", 0) or 0)
            if should_use_growth_path(enriched, _mcap_for_growth):
                _gv = compute_growth_valuation(
                    enriched=enriched,
                    market_cap=_mcap_for_growth,
                    sector=enriched.get("sector", "general"),
                    ticker=ticker,
                )
                if _gv and (_gv.get("fair_value") or 0) > 0:
                    iv = float(_gv["fair_value"])
        except Exception:
            pass

        mos_pct = margin_of_safety(iv, price) * 100 if price > 0 else 0

        # ── Step 7: Quality checks & insight sub-computes (PARALLEL) ──
        # All of these are pure reads over `enriched` / `raw` / scalar
        # inputs already computed above. They don't mutate self or share
        # state, so we run them concurrently on a ThreadPool to cut
        # cold-path wall-time.
        #
        # Intentional ordering note:
        #   * Scenarios, reverse_dcf, fcf_yield, ev_ebitda are all
        #     independent of quality results → safe to parallelize.
        #   * Moat's IV delta is applied AFTER gather (serially), so
        #     the final displayed `iv` reflects the moat delta.
        #   * mos_pct is computed from the pre-adjustment iv to match
        #     the original sequential behavior exactly.
        #
        # Fallback: if the executor path raises, we fall back to
        # sequential execution (same logic, same order) so production
        # stays correct even if threads misbehave.
        import time as _pt_time
        import logging as _pt_log
        _pt_logger = _pt_log.getLogger("yieldiq.analysis")

        # Prepare inputs for momentum (needs collector price history if
        # yfinance path was used; local path doesn't have a collector).
        try:
            _price_history_for_momentum = (
                collector.get_price_history()
                if "collector" in locals() and hasattr(collector, "get_price_history")
                else None
            )
        except Exception:
            _price_history_for_momentum = None

        # fcf_base for scenarios (non-financial only)
        _fcf_base_for_scen = None
        if not is_financial:
            try:
                _fcf_base_for_scen = (
                    projected[0] / (1 + growth_schedule[0])
                    if projected and growth_schedule and growth_schedule[0] > -1
                    else enriched.get("latest_fcf", 1e6)
                )
            except Exception:
                _fcf_base_for_scen = enriched.get("latest_fcf", 1e6)

        # --- Sequential fallback helpers (pure functions) ---
        def _run_piotroski():
            try:
                return compute_piotroski_fscore(enriched)
            except Exception:
                return {"score": 0, "grade": ""}

        def _run_moat():
            try:
                return compute_moat_score(enriched, wacc)
            except Exception:
                return {"score": 0, "grade": "None"}

        def _run_eq():
            try:
                return compute_earnings_quality(enriched)
            except Exception:
                return {"score": 0, "grade": "N/A"}

        def _run_momentum():
            try:
                return calculate_momentum(_price_history_for_momentum)
            except Exception:
                return {"momentum_score": 0, "grade": "N/A"}

        def _run_fund():
            try:
                return score_fundamentals(enriched)
            except Exception:
                return {"score": 0, "grade": "N/A"}

        def _run_confidence():
            try:
                return compute_confidence_score(enriched)
            except Exception:
                return {"score": 50}

        def _run_scenarios():
            if is_financial:
                return {}
            try:
                return run_scenarios(
                    enriched=enriched, fcf_base=_fcf_base_for_scen,
                    base_growth=base_growth, base_wacc=wacc,
                    base_terminal_g=terminal_g,
                    total_debt=enriched.get("total_debt", 0),
                    total_cash=enriched.get("total_cash", 0),
                    shares=enriched.get("shares", 1),
                    current_price=price, years=forecast_yrs,
                )
            except Exception:
                return {}

        def _run_rdcf():
            try:
                return run_reverse_dcf(enriched, price, wacc, terminal_g)
            except Exception:
                return {}

        def _run_fcf_yield():
            try:
                return compute_fcf_yield_analysis(enriched, price)
            except Exception:
                return {}

        def _run_eveb():
            try:
                return run_ev_ebitda_analysis(enriched, price, fetch_peers=False)
            except Exception:
                return {}

        _sub_jobs = {
            "piotroski": _run_piotroski,
            "moat": _run_moat,
            "eq": _run_eq,
            "momentum": _run_momentum,
            "fund": _run_fund,
            "confidence": _run_confidence,
            "scenarios": _run_scenarios,
            "rdcf": _run_rdcf,
            "fcf_yield": _run_fcf_yield,
            "eveb": _run_eveb,
        }

        _results: dict = {}
        _parallel_ok = False
        _t_par_start = _pt_time.monotonic()
        try:
            from concurrent.futures import ThreadPoolExecutor
            with ThreadPoolExecutor(
                max_workers=min(10, len(_sub_jobs)),
                thread_name_prefix=f"yiq-{ticker}",
            ) as _ex:
                _futs = {k: _ex.submit(fn) for k, fn in _sub_jobs.items()}
                for _k, _f in _futs.items():
                    _results[_k] = _f.result()
            _parallel_ok = True
        except Exception as _par_exc:
            _pt_logger.warning(
                "[%s] parallel sub-compute failed (%s: %s) — falling back sequential",
                ticker, type(_par_exc).__name__, _par_exc,
            )
            _results = {}

        if not _parallel_ok:
            # Sequential fallback — same logic, same order
            _t_seq_start = _pt_time.monotonic()
            for _k, _fn in _sub_jobs.items():
                _results[_k] = _fn()
            _pt_logger.info(
                "[%s] compute_ms_sequential=%d",
                ticker, int((_pt_time.monotonic() - _t_seq_start) * 1000),
            )
        else:
            _pt_logger.info(
                "[%s] compute_ms_parallel=%d",
                ticker, int((_pt_time.monotonic() - _t_par_start) * 1000),
            )

        piotroski = _results["piotroski"]
        moat_result = _results["moat"]
        eq_result = _results["eq"]
        momentum_result = _results["momentum"]
        fund_result = _results["fund"]
        confidence = _results["confidence"]
        scenarios_raw = _results["scenarios"]
        rdcf = _results["rdcf"]
        fcf_yield = _results["fcf_yield"]
        eveb = _results["eveb"]

        # Apply moat IV adjustment for non-financial stocks (serial —
        # mutates iv which feeds yiq_score / inv_plan / mos_pct below).
        if not is_financial and moat_result.get("grade") not in ("None", "N/A (Financial)"):
            try:
                moat_adj = apply_moat_adjustments(
                    moat_result=moat_result, wacc=wacc, base_growth=base_growth,
                    terminal_g=terminal_g, iv=iv_raw,
                    sector=enriched.get("sector", "general"),
                )
                _iv_delta = moat_adj.get("iv_delta_pct", 0) / 100
                iv = round(iv * (1 + _iv_delta), 2)
                iv_raw = iv
            except Exception:
                pass

        # CRITICAL FIX (FIX1): mos_pct MUST be recomputed from the
        # post-adjustment `iv` so that the displayed MoS reconciles
        # with the displayed `fair_value` via (FV-CMP)/CMP. Prior
        # behaviour preserved a "pre-moat" MoS even though the
        # displayed FV reflected the moat delta — users saw e.g.
        # FV ₹3,223 with MoS −0.1% when the math demands +24.8%.
        # Single source of truth: derive MoS from the SAME `iv`
        # field that is shown to the user. Covers both DCF and
        # financial-stock P/BV paths (financials skip the moat
        # adjustment block above, so this is a no-op for them but
        # remains safe).
        mos_pct = ((iv - price) / price * 100) if price > 0 else 0

        # Analyst upside: (target - price) / price * 100
        _analyst_target = (raw.get("finnhub_price_target") or {}).get("mean", 0) or 0
        _analyst_upside = ((_analyst_target - price) / price * 100) if price > 0 and _analyst_target > 0 else 0

        try:
            yiq_score = compute_yieldiq_score(
                mos_pct=mos_pct,
                piotroski=piotroski.get("score", 0),
                moat_grade=moat_result.get("grade", "None"),
                rev_growth=enriched.get("revenue_growth", 0),
                analyst_upside=_analyst_upside,
            )
        except TypeError as _te:
            # Fallback: calculate inline if function signature doesn't match
            _v = max(0, min(40, int((mos_pct + 40) / 80 * 40)))
            _q = max(0, min(30, int(piotroski.get("score", 0) / 9 * 20 + (10 if moat_result.get("grade") == "Wide" else 7 if moat_result.get("grade") == "Narrow" else 0))))
            _g = max(0, min(20, int(enriched.get("revenue_growth", 0) * 100)))
            _total = max(0, min(100, _v + _q + _g))
            yiq_score = {"score": _total, "grade": "A" if _total >= 75 else "B" if _total >= 55 else "C" if _total >= 35 else "D" if _total >= 20 else "F"}

        # ── Step 8: Scenarios ─────────────────────────────────
        # `scenarios_raw` was computed in the parallel wave above
        # (empty dict for financials by design).

        def _sc(key):
            d = scenarios_raw.get(key, {})
            return ScenarioCase(
                iv=d.get("iv", 0), mos_pct=d.get("mos_pct", 0),
                growth=d.get("growth", 0), wacc=d.get("wacc", wacc),
                term_g=d.get("term_g", terminal_g),
            )

        # ── Step 9: Insights ──────────────────────────────────
        try:
            inv_plan = generate_valuation_summary(enriched, price, iv, mos_pct / 100)
            pt = inv_plan.get("price_targets", {})
            hp = inv_plan.get("holding_period", {})
        except Exception:
            inv_plan = {}
            pt = {}
            hp = {}

        # rdcf / fcf_yield / eveb already computed in the parallel wave
        # above — they only need (enriched, price, wacc, terminal_g),
        # none of which change between there and here.

        # Red flags from DCF edge cases
        _red_flags = dcf_res.get("warnings", [])

        # Remove IPO-related flags — they indicate data completeness, not business risk
        _red_flags = [
            f for f in _red_flags
            if not any(kw in f.lower() for kw in ('ipo', 'ipo_date', 'listing_date', 'unknown ipo'))
        ]

        # For financial companies, remove "Loss Company" / negative FCF flags
        if is_financial:
            _red_flags = [
                f for f in _red_flags
                if 'loss company' not in f.lower()
                and 'negative fcf' not in f.lower()
                and 'zero fcf' not in f.lower()
            ]

        if enriched.get("unreliable_reason"):
            _red_flags.append(enriched["unreliable_reason"])

        # Promoter pledge red flags
        _promoter_pledge = raw.get("promoter_pledge_pct")
        if _promoter_pledge is None:
            # Try fetching from enriched data or shareholding
            _promoter_pledge = enriched.get("promoter_pledge_pct")
        if _promoter_pledge is None:
            # Fall back to ShareholdingPattern DB table
            _promoter_pledge = _query_promoter_pledge(ticker)
        if _promoter_pledge is not None:
            try:
                _pledge_val = float(_promoter_pledge)
                if _pledge_val > 25:
                    _red_flags.append(
                        f"CRITICAL: Promoter pledge {_pledge_val:.1f}% — very high risk"
                    )
                elif _pledge_val > 10:
                    _red_flags.append(
                        f"Promoter pledge {_pledge_val:.1f}% — elevated risk"
                    )
            except (ValueError, TypeError):
                pass

        # ── Step 10: Verdict ──────────────────────────────────
        _conf_score = confidence.get("score", 50)

        if is_financial:
            # Financial companies: simple MoS verdict, NEVER "avoid"
            if iv <= 0:
                verdict = "data_limited"
            elif mos_pct > 15:
                verdict = "undervalued"
            elif mos_pct > -15:
                verdict = "fairly_valued"
            else:
                verdict = "overvalued"
        elif _confidence in ("low", "unusable") and abs(mos_pct) > 40 and clean_ticker not in INVENTORY_HEAVY_TICKERS:
            verdict = "data_limited"
        elif _conf_score < 35 and abs(mos_pct) > 40 and clean_ticker not in INVENTORY_HEAVY_TICKERS:
            verdict = "data_limited"
        elif mos_pct > 15:
            verdict = "undervalued"
        elif mos_pct > -15:
            verdict = "fairly_valued"
        elif enriched.get("dcf_reliable", True):
            verdict = "overvalued"
        else:
            verdict = "avoid"

        # ── Earnings date (NSE first, Finnhub fallback) ─────
        _earnings = _query_earnings_date(ticker)
        _earnings_date = (
            _earnings.get("date") if _earnings
            else (raw.get("finnhub_next_earnings") or {}).get("date")
        )
        earnings_days_until = _earnings.get("days_away") if _earnings else None

        # ── Bulk deals for insider activity ──────────────────
        _bulk_deals_raw = _query_bulk_deals(ticker, days=90)
        _bulk_deals = [
            BulkDealItem(
                date=d["date"], client=d["client"], deal_type=d["deal_type"],
                qty_lakh=d["qty_lakh"], price=d["price"], category=d["category"],
            )
            for d in _bulk_deals_raw
        ]

        # ── Assemble response ─────────────────────────────────
        if is_financial:
            _bear_case = bear_iv
            _base_case = round(iv, 2)
            _bull_case = bull_iv
        else:
            _bear_case = _sc("Bear case").iv or _sc("Bear 🐻").iv
            _base_case = round(iv, 2)
            _bull_case = _sc("Bull case").iv or _sc("Bull 🐂").iv

        # ── Dividend data (one yfinance .info call, ~1s) ─────
        # Swallowed — never blocks the main response.
        _dividend_data = None
        try:
            from backend.services.dividend_service import DividendService
            from backend.models.responses import DividendData, DividendFYItem
            # Pass the collector's raw info dict to avoid a duplicate
            # yfinance .info call (~20s saved per cold request).
            _div_result = DividendService().get_dividends(
                ticker=ticker, enriched=enriched, yf_info=raw
            )
            _fy_items = [
                DividendFYItem(**item)
                for item in _div_result.get("fy_history", [])
            ]
            _dividend_kwargs = {
                k: v for k, v in _div_result.items() if k != "fy_history"
            }
            _dividend_data = DividendData(fy_history=_fy_items, **_dividend_kwargs)
        except Exception as _div_exc:
            import logging as _div_log
            _div_log.getLogger("yieldiq.dividends").debug(
                "Dividend embed failed for %s: %s", ticker, _div_exc
            )

        # ── Structured red flags for the deep-dive UI ────────
        try:
            _structured_flags = _build_structured_flags(
                enriched=enriched,
                piotroski=piotroski,
                moat_result=moat_result,
                is_financial=is_financial,
                existing_flags=_red_flags,
                price=price,
            )
        except Exception:
            _structured_flags = []

        # ── Forward-fill fair value history (async) ─────────
        # Writes one row per ticker per day. Runs in a daemon thread so
        # the Aiven DB round-trips (3 queries + 1 write after the DCF
        # smoothing commit) don't block the analysis response. If the
        # thread dies mid-write the response has already been returned;
        # worst case is a missing history row for that tick.
        try:
            if iv and iv > 0 and price and price > 0:
                import threading as _fv_threading
                _fv_args = dict(
                    ticker=ticker,
                    fv=float(iv),
                    price=float(price),
                    mos=float(mos_pct),
                    verdict=str(verdict),
                    wacc=float(wacc),
                    confidence=int(confidence.get("score", 50)),
                )

                def _bg_store_fv():
                    try:
                        from data_pipeline.sources.fv_history import (
                            store_today_fair_value,
                        )
                        _db = _get_pipeline_session()
                        if _db is None:
                            return
                        try:
                            store_today_fair_value(db=_db, **_fv_args)
                        finally:
                            _db.close()
                    except Exception:
                        pass  # already logged by store_today_fair_value

                _fv_threading.Thread(
                    target=_bg_store_fv, daemon=True, name=f"fv-store-{ticker}"
                ).start()
        except Exception as _fv_exc:
            import logging as _fv_log
            _fv_log.getLogger("yieldiq.fv_history").debug(
                "FV history store skipped for %s: %s", ticker, _fv_exc
            )
        # ──────────────────────────────────────────────────────

        # ── Extended quality ratios ───────────────────────────
        # ROCE, Debt/EBITDA (with band label), Interest Coverage,
        # Enterprise Value. Every metric is Optional — None flows
        # through to the frontend which renders "—".
        _ebit_val, _interest_exp = _fetch_ebit_and_interest(ticker)

        _total_assets = enriched.get("total_assets") or 0
        _total_debt = enriched.get("total_debt") or 0
        _total_cash = enriched.get("total_cash") or 0
        _ebitda = enriched.get("ebitda") or 0
        _shares = enriched.get("shares") or 0
        _current_liab = enriched.get("current_liabilities") or 0

        # Sector-based "bank / NBFC / Financial" detection — leverage
        # and interest-coverage ratios are not meaningful for these.
        _sector_str = (company.sector or "").lower()
        _is_bank_like = bool(
            is_financial
            or "bank" in _sector_str
            or "financial" in _sector_str
            or ticker.upper().endswith(("BANK.NS", "BANK.BO"))
        )

        # ROCE uses the textbook capital-employed denominator:
        #   EBIT / (Total Assets − Current Liabilities)  [returns %]
        # Falls back to ebit / total_assets when current_liabilities
        # is missing so we don't regress coverage for tickers lacking
        # that field.
        from backend.services.ratios_service import (
            compute_roce as _compute_roce,
            compute_debt_to_ebitda as _compute_debt_ebitda,
            compute_interest_coverage as _compute_int_cov,
        )
        _roce_val: float | None = _compute_roce(
            _ebit_val, _total_assets, _current_liab
        )
        # Fallback path: primary returned None (often because
        # current_liabilities isn't on file for older `financials`
        # rows). Use the looser EBIT/Total Assets definition so we
        # keep coverage. Must guard against EBIT<=0 though — otherwise
        # tickers with missing/zero EBIT render as misleading "0.0% Weak"
        # (e.g. RELIANCE appeared as 0% on the analysis page).
        if (
            _roce_val is None
            and _ebit_val is not None
            and _ebit_val > 0
            and _total_assets > 0
        ):
            _roce_val = round(_ebit_val / _total_assets * 100, 1)

        # Banks / NBFCs: Debt/EBITDA and Interest Coverage are not
        # meaningful (deposits ≠ debt, interest expense is revenue).
        # Return None so the frontend renders "—" with a banker note.
        if _is_bank_like:
            _debt_ebitda_val = None
            _debt_ebitda_lbl = None
            _interest_cov_val = None
        else:
            _debt_ebitda_val = _compute_debt_ebitda(_total_debt, _ebitda)
            _debt_ebitda_lbl = _debt_ebitda_label(_debt_ebitda_val)
            _interest_cov_val = _compute_int_cov(_ebit_val, _interest_exp)

        # ── Phase 2.1 ratios ─────────────────────────────────
        # All new fields are Optional in QualityOutput; when data is
        # missing they stay None and render as "—" in the frontend.
        from backend.services.ratios_service import (
            compute_current_ratio as _cr,
            compute_asset_turnover as _at,
            compute_revenue_cagr as _rcagr,
        )

        _current_ratio = _cr(
            enriched.get("current_assets"),
            enriched.get("current_liabilities"),
        )
        _asset_turnover = _at(
            enriched.get("latest_revenue") or enriched.get("revenue"),
            _total_assets,
        )
        _rev_cagr_3y = None
        _rev_cagr_5y = None
        try:
            _inc = enriched.get("income_df")
            if _inc is not None and hasattr(_inc, "empty") and not _inc.empty \
                    and "revenue" in _inc.columns:
                _rev_series = _inc["revenue"].dropna().tolist()
                _rev_cagr_3y = _rcagr(_rev_series, 3)
                _rev_cagr_5y = _rcagr(_rev_series, 5)
        except Exception:
            pass

        # Enterprise Value in Crores: market_cap_cr + debt − cash.
        # market_cap not in enriched — derive from price × shares.
        _ent_val_cr: float | None = None
        try:
            _mcap_cr = (float(price) * float(_shares)) / 1e7 if _shares else None
            if _mcap_cr is not None:
                _ent_val_cr = round(_mcap_cr + _total_debt - _total_cash, 0)
        except Exception:
            _ent_val_cr = None

        # ── Shareholding breakdown ────────────────────────────
        # Aiven shareholding_pattern table is the primary source.
        # If promoter_pct is missing, fall back to yfinance
        # `heldPercentInsiders` which maps closely to promoter holding
        # for Indian listings (not a perfect match — US-registered
        # names may report SEC-defined insiders, so only use when the
        # primary source is empty).
        _sh = _query_shareholding(ticker) or {}
        if _sh.get("promoter_pct") is None:
            try:
                _yf_insiders = None
                # 1) already-fetched yfinance info in `raw`
                for _k in ("heldPercentInsiders", "held_percent_insiders"):
                    if raw.get(_k) is not None:
                        _yf_insiders = float(raw.get(_k))
                        break
                # 2) last-resort live yfinance lookup (cheap, cached by yf)
                if _yf_insiders is None:
                    try:
                        import yfinance as _yf
                        _info = _yf.Ticker(ticker).info or {}
                        _v = _info.get("heldPercentInsiders")
                        if _v is not None:
                            _yf_insiders = float(_v)
                    except Exception:
                        _yf_insiders = None
                if _yf_insiders is not None:
                    # yfinance returns decimal (0.623 → 62.3%)
                    _sh["promoter_pct"] = round(_yf_insiders * 100.0, 1)
            except Exception:
                pass

        # Inform downstream consumers that a financial was valued via
        # the peer-band path — helps users interpret the fair value
        # (and disables some FCF-based red flags in the UI).
        if is_financial and locals().get("_financial_val_result"):
            _method = _financial_val_result.get("method", "p_bv_peer")
            _data_issues.append(
                f"[info] Valued via {_method} peer band — DCF not "
                f"meaningful for financials."
            )

        # ── FV stability snapshot (v35) ──────────────────────────
        # Pin every input that shaped the displayed `iv` into the
        # response (and therefore into analysis_cache.payload). Warm
        # cache hits return the cached payload byte-for-byte, so the
        # snapshot lets us reproduce the FV later without re-fetching
        # yfinance/Aiven (which drift between cold computes and were
        # the root cause of ITC/HCLTECH/INFY shifting between cache
        # states). All values are pre-computed scalars already used
        # above — this block does NOT re-fetch or re-derive.
        try:
            _ci_revenue = (
                enriched.get("latest_revenue")
                or enriched.get("revenue")
                or 0
            )
            if hasattr(_ci_revenue, "__iter__") and not isinstance(_ci_revenue, (str, bytes)):
                # `revenue` may be a Series/list — take the most recent
                try:
                    _ci_revenue = float(list(_ci_revenue)[-1])
                except Exception:
                    _ci_revenue = 0
            _computation_inputs = {
                "code_version": "fv-stability-v1",
                "computed_at": _ts,
                "data_source": _data_source,
                "current_price": float(price or 0),
                "shares_outstanding": float(enriched.get("shares") or 0),
                "revenue_ttm": float(_ci_revenue or 0),
                "ebit_ttm": float(enriched.get("ebit") or 0),
                "fcf_ttm": float(enriched.get("latest_fcf") or 0),
                "pat_ttm": float(enriched.get("latest_pat") or 0),
                "total_debt": float(enriched.get("total_debt") or 0),
                "total_cash": float(enriched.get("total_cash") or 0),
                "wacc": float(wacc or 0),
                "terminal_growth": float(terminal_g or 0),
                "base_growth": float(base_growth or 0),
                "iv_raw_pre_moat": float(locals().get("iv_raw") or 0),
                "iv_post_moat": float(iv or 0),
                "moat_grade": moat_result.get("grade", "None"),
                "valuation_model": "pb_ratio" if is_financial else "dcf",
                "is_financial": bool(is_financial),
                "cache_version": CACHE_VERSION,
            }
        except Exception:
            _computation_inputs = None

        return AnalysisResponse(
            ticker=ticker,
            company=company,
            valuation=ValuationOutput(
                fair_value=round(iv, 2),
                current_price=round(price, 2),
                margin_of_safety=round(mos_pct, 1),
                margin_of_safety_display=round(min(mos_pct, 80), 1),
                mos_is_extreme=mos_pct > 80,
                mos_extreme_note=(
                    "Model shows significant undervaluation. "
                    "This may reflect sector-specific factors. "
                    "Verify assumptions before acting."
                ) if mos_pct > 80 else None,
                verdict=verdict,
                bear_case=_bear_case,
                base_case=_base_case,
                bull_case=_bull_case,
                # All rates returned as DECIMALS (0.12 for 12%) — frontend multiplies by 100 for display
                wacc=round(wacc, 4),
                terminal_growth=round(terminal_g, 4),
                fcf_growth_rate=round(enriched.get("fcf_growth", 0), 4),
                confidence_score=(
                    _financial_val_result["confidence_score"]
                    if is_financial and locals().get("_financial_val_result")
                    else confidence.get("score", 50)
                ),
                wacc_industry_min=round(max(0.06, wacc - 0.02), 4),
                wacc_industry_max=round(min(0.16, wacc + 0.02), 4),
                fcf_growth_historical_avg=round(enriched.get("fcf_growth", 0) * 0.9, 4),
                tv_pct_of_ev=round(dcf_res.get("tv_pct_of_ev", 0) * 100, 1),
                dcf_reliable=False if is_financial else enriched.get("dcf_reliable", True),
                valuation_model="pb_ratio" if is_financial else "dcf",
                reliability_score=dcf_res.get("reliability_score", 100),
                pv_fcfs=round(dcf_res.get("sum_pv_fcfs", 0), 0),
                pv_terminal=round(dcf_res.get("pv_tv", 0), 0),
                enterprise_value=round(dcf_res.get("enterprise_value", 0), 0),
                equity_value=round(dcf_res.get("equity_value", 0), 0),
                fcf_data_source=_fcf_data_source,
            ),
            quality=QualityOutput(
                yieldiq_score=yiq_score.get("score", 0),
                grade=yiq_score.get("grade", "C"),
                piotroski_score=piotroski.get("score", 0),
                piotroski_grade=piotroski.get("grade", ""),
                earnings_quality_grade=eq_result.get("grade", "N/A"),
                earnings_quality_score=eq_result.get("score", 0),
                moat=moat_result.get("grade", "None"),
                moat_score=moat_result.get("score", 0),
                momentum_score=momentum_result.get("momentum_score", 0),
                momentum_grade=momentum_result.get("grade", "N/A"),
                fundamental_score=fund_result.get("score", 0),
                fundamental_grade=fund_result.get("grade", "N/A"),
                # ROE/ROCE: return as PERCENTAGE (frontend displays directly with %)
                # yfinance returns decimals (0.23), Aiven sometimes percentages — normalize.
                roe=_normalize_pct(enriched.get("roe") or _compute_roe_fallback(enriched)),
                de_ratio=enriched.get("de_ratio"),
                roce=_normalize_pct(_roce_val),
                debt_ebitda=_debt_ebitda_val,
                debt_ebitda_label=_debt_ebitda_lbl,
                interest_coverage=_interest_cov_val,
                enterprise_value=_ent_val_cr,
                current_ratio=_current_ratio,
                asset_turnover=_asset_turnover,
                revenue_cagr_3y=_rev_cagr_3y,
                revenue_cagr_5y=_rev_cagr_5y,
                promoter_pct=_sh.get("promoter_pct"),
                promoter_pledge_pct=_sh.get("promoter_pledge_pct"),
                fii_pct=_sh.get("fii_pct"),
                dii_pct=_sh.get("dii_pct"),
                public_pct=_sh.get("public_pct"),
            ),
            insights=InsightCards(
                patience_months=hp.get("min_months"),
                red_flag_count=len(_red_flags),
                red_flags=_red_flags[:5],
                red_flags_structured=_structured_flags,
                dividend=_dividend_data,
                earnings_date=_earnings_date,
                earnings_est_eps=raw.get("finnhub_next_earnings", {}).get("eps_estimate"),
                earnings_days_until=earnings_days_until,
                wall_street_avg_target=(raw.get("finnhub_price_target") or {}).get("mean"),
                wall_street_target_count=(raw.get("finnhub_price_target") or {}).get("count"),
                insider_net_sentiment=(raw.get("finnhub_insider") or {}).get("sentiment"),
                market_expectations_growth=rdcf.get("implied_growth"),
                fcf_yield=fcf_yield.get("fcf_yield"),
                ev_ebitda=eveb.get("current_ev_ebitda") or enriched.get("ev_to_ebitda"),
                reverse_dcf_implied_growth=rdcf.get("implied_growth"),
                bulk_deals=_bulk_deals,
            ),
            scenarios=ScenariosOutput(
                bear=ScenarioCase(iv=bear_iv, mos_pct=round((bear_iv - price) / price * 100, 1) if price > 0 else 0, growth=0, wacc=round(wacc, 4), term_g=round(terminal_g, 4)) if is_financial else (_sc("Bear case") if scenarios_raw.get("Bear case") else _sc("Bear 🐻")),
                base=ScenarioCase(iv=round(iv, 2), mos_pct=round(mos_pct, 1), growth=round(base_growth, 4), wacc=round(wacc, 4), term_g=round(terminal_g, 4)),
                bull=ScenarioCase(iv=bull_iv, mos_pct=round((bull_iv - price) / price * 100, 1) if price > 0 else 0, growth=0, wacc=round(wacc, 4), term_g=round(terminal_g, 4)) if is_financial else (_sc("Bull case") if scenarios_raw.get("Bull case") else _sc("Bull 🐂")),
            ),
            price_levels=PriceLevels(
                entry_signal=assign_signal(mos_pct / 100, reliability_score=dcf_res.get("reliability_score", 100)),
                discount_zone=pt.get("buy_price"),
                model_estimate=pt.get("target_price"),
                downside_range=pt.get("stop_loss"),
                risk_reward_ratio=pt.get("rr_ratio"),
                holding_period=hp.get("label"),
            ),
            data_confidence=_confidence,
            data_issues=_data_issues,
            timestamp=_ts,
            computation_inputs=_computation_inputs,
        )

    def get_ai_summary(self, ticker: str, analysis: AnalysisResponse) -> str:
        """Generate AI summary using existing Gemini/Groq integration."""
        import logging
        _log = logging.getLogger("yieldiq.ai_summary")
        try:
            _log.info(f"[{ticker}] Requesting AI summary...")
            from dashboard.utils.data_helpers import generate_ai_summary
            result = generate_ai_summary(
                ticker, analysis.company.company_name,
                analysis.valuation.margin_of_safety,
                analysis.quality.moat,
                analysis.valuation.fcf_growth_rate,
                analysis.valuation.confidence_score,
            )
            if result:
                _log.info(f"[{ticker}] AI summary received ({len(result)} chars)")
                return result
            _log.warning(f"[{ticker}] AI summary returned empty/None")
            return ""
        except Exception as exc:
            _log.error(f"[{ticker}] AI summary failed: {type(exc).__name__}: {exc}")
            return ""

    def get_reverse_dcf(
        self,
        ticker: str,
        wacc_override: float | None = None,
        terminal_g_override: float | None = None,
        years: int = 10,
    ) -> dict:
        """
        Compute reverse DCF analysis for a ticker.
        Optionally allows user-adjustable WACC and terminal growth.
        Runs full analysis pipeline to get enriched data, then
        runs reverse DCF with specified (or default) assumptions.
        """
        # Run full analysis to populate enriched dict (uses cache)
        analysis = self.get_full_analysis(ticker)

        # Get raw enriched data — we need to re-fetch to get the dict
        # since AnalysisResponse doesn't expose it. Use cache.
        import logging as _log
        logger = _log.getLogger("yieldiq.reverse_dcf")

        # Re-run the enrichment step (fast, uses local assembler + cache)
        try:
            from backend.services.local_data_service import assemble_local
            _db = _get_pipeline_session()
            raw = None
            if _db is not None:
                try:
                    raw = assemble_local(ticker, _db)
                except Exception:
                    raw = None
                finally:
                    try:
                        _db.close()
                    except Exception:
                        pass
            if raw is None:
                from data.collector import StockDataCollector
                raw = StockDataCollector(ticker).get_all()
        except Exception as exc:
            logger.warning(f"[{ticker}] Failed to assemble raw data: {exc}")
            return {"ticker": ticker, "error": "Unable to fetch company data"}

        try:
            # compute_metrics is imported at top of this module
            enriched = compute_metrics(raw)
        except Exception as exc:
            logger.warning(f"[{ticker}] compute_metrics failed: {exc}")
            enriched = raw

        # Use override values or pull from analysis
        wacc = wacc_override if wacc_override is not None else analysis.valuation.wacc
        terminal_g = terminal_g_override if terminal_g_override is not None else analysis.valuation.terminal_growth
        current_price = analysis.valuation.current_price

        try:
            result = run_reverse_dcf(enriched, current_price, wacc, terminal_g, years=years)
            return result
        except Exception as exc:
            logger.warning(f"[{ticker}] reverse DCF failed: {exc}")
            return {"ticker": ticker, "error": str(exc)}
