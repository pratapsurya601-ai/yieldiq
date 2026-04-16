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


# Module-level flag: once we detect the DB is unreachable, stop
# trying for the rest of this process's lifetime. Avoids 8 × 3s
# = 24s of serial timeout on every analysis request when no DB.
_db_confirmed_dead = False


def _get_pipeline_session():
    """Get a DB session from the data pipeline, or None if unavailable.

    After the first connection failure, sets ``_db_confirmed_dead``
    so subsequent calls in the same process return None instantly
    instead of burning 3s each on the dead connection.
    """
    global _db_confirmed_dead
    if _db_confirmed_dead:
        return None
    try:
        from data_pipeline.db import Session as PipelineSession
        if PipelineSession is None:
            _db_confirmed_dead = True
            return None
        session = PipelineSession()
        # Test the connection with a lightweight query
        from sqlalchemy import text
        session.execute(text("SELECT 1"))
        return session
    except Exception:
        _db_confirmed_dead = True
        return None


def _query_ttm_financials(ticker: str):
    """
    Query TTM financials from local DB.
    Returns dict with fcf, revenue, pat or None if unavailable.
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
            return {
                "fcf": row.free_cash_flow,
                "revenue": row.revenue,
                "pat": row.pat,
                "period_end": str(row.period_end) if row.period_end else None,
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
    Returns dict with fcf, revenue, pat or None if unavailable.
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
            return {
                "fcf": row.free_cash_flow,
                "revenue": row.revenue,
                "pat": row.pat,
                "period_end": str(row.period_end) if row.period_end else None,
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
    Pull the most recent annual EBIT and interest_expense for a
    ticker from the ``company_financials`` table (populated by the
    XBRL pipeline). Returns (None, None) if the table is absent or
    the ticker isn't covered.
    """
    db = _get_pipeline_session()
    if db is None:
        return None, None
    try:
        from sqlalchemy import text
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")
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
        if not row:
            return None, None

        def _f(v):
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        return _f(row.get("ebit")), _f(row.get("interest_expense"))
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

        # ── Step 1: Fetch data (with retry for rate-limited .NS stocks) ─
        import time as _time
        raw = None
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
        company = CompanyInfo(
            ticker=ticker,
            company_name=_display_name,
            sector=_resolve_sector(_raw_sector, clean_ticker),
            currency="INR" if is_indian else "USD",
            market_cap=price * enriched.get("shares", 0),
        )

        # ── Step 5: WACC + Forecast ───────────────────────────
        # Try TTM data from local DB first, then annual, then yfinance
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
                bear_iv = round(_bvps * 1.5, 2)
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

            # PE crosscheck blend
            try:
                eps = get_eps(enriched)
                sector = enriched.get("sector", "general")
                pe_iv = compute_pe_based_iv(eps, sector, "base", enriched.get("revenue_growth", 0))
                iv = blend_dcf_pe(iv_raw, pe_iv, sector)
            except Exception:
                iv = iv_raw

        mos_pct = margin_of_safety(iv, price) * 100 if price > 0 else 0

        # ── Step 7: Quality checks ────────────────────────────
        piotroski = compute_piotroski_fscore(enriched)
        if is_financial:
            moat_result = compute_moat_score(enriched, wacc)
        else:
            moat_result = compute_moat_score(enriched, wacc)

        # Apply moat IV adjustment for non-financial stocks
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

        try:
            eq_result = compute_earnings_quality(enriched)
        except Exception:
            eq_result = {"score": 0, "grade": "N/A"}

        try:
            momentum_result = calculate_momentum(
                collector.get_price_history() if hasattr(collector, "get_price_history") else None
            )
        except Exception:
            momentum_result = {"momentum_score": 0, "grade": "N/A"}

        fund_result = score_fundamentals(enriched)
        confidence = compute_confidence_score(enriched)

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
        if is_financial:
            # P/B-based scenarios already computed above
            scenarios_raw = {}
        else:
            try:
                fcf_base = projected[0] / (1 + growth_schedule[0]) if projected and growth_schedule and growth_schedule[0] > -1 else enriched.get("latest_fcf", 1e6)
                scenarios_raw = run_scenarios(
                    enriched=enriched, fcf_base=fcf_base,
                    base_growth=base_growth, base_wacc=wacc,
                    base_terminal_g=terminal_g,
                    total_debt=enriched.get("total_debt", 0),
                    total_cash=enriched.get("total_cash", 0),
                    shares=enriched.get("shares", 1),
                    current_price=price, years=forecast_yrs,
                )
            except Exception:
                scenarios_raw = {}

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

        try:
            rdcf = run_reverse_dcf(enriched, price, wacc, terminal_g)
        except Exception:
            rdcf = {}

        try:
            fcf_yield = compute_fcf_yield_analysis(enriched, price)
        except Exception:
            fcf_yield = {}

        try:
            eveb = run_ev_ebitda_analysis(enriched, price, fetch_peers=False)
        except Exception:
            eveb = {}

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

        # ── Forward-fill fair value history ──────────────────
        # Writes one row per ticker per day to fair_value_history.
        # Never raises — wrapped in try/except so a DB hiccup
        # cannot break the analysis response.
        try:
            if iv and iv > 0 and price and price > 0:
                from data_pipeline.sources.fv_history import (
                    store_today_fair_value,
                )
                _fv_db = _get_pipeline_session()
                if _fv_db is not None:
                    try:
                        store_today_fair_value(
                            ticker=ticker,
                            fv=float(iv),
                            price=float(price),
                            mos=float(mos_pct),
                            verdict=str(verdict),
                            wacc=float(wacc),
                            confidence=int(confidence.get("score", 50)),
                            db=_fv_db,
                        )
                    finally:
                        _fv_db.close()
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

        _roce_val: float | None = None
        if _ebit_val is not None and _total_assets > 0:
            _roce_val = round(_ebit_val / _total_assets * 100, 1)

        _debt_ebitda_val: float | None = None
        if _ebitda > 0:
            _debt_ebitda_val = round(_total_debt / _ebitda, 1)
        _debt_ebitda_lbl = _debt_ebitda_label(_debt_ebitda_val)

        _interest_cov_val: float | None = None
        if (
            _ebit_val is not None
            and _interest_exp is not None
            and _interest_exp > 0
        ):
            _interest_cov_val = round(_ebit_val / _interest_exp, 1)

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
        _sh = _query_shareholding(ticker) or {}

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
                wacc=round(wacc * 100, 1),
                terminal_growth=round(terminal_g * 100, 1),
                fcf_growth_rate=round(enriched.get("fcf_growth", 0) * 100, 1),
                confidence_score=confidence.get("score", 50),
                wacc_industry_min=round(max(6, wacc * 100 - 2), 1),
                wacc_industry_max=round(min(16, wacc * 100 + 2), 1),
                fcf_growth_historical_avg=round(enriched.get("fcf_growth", 0) * 90, 1),
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
                roe=enriched.get("roe"),
                de_ratio=enriched.get("de_ratio"),
                roce=_roce_val,
                debt_ebitda=_debt_ebitda_val,
                debt_ebitda_label=_debt_ebitda_lbl,
                interest_coverage=_interest_cov_val,
                enterprise_value=_ent_val_cr,
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
