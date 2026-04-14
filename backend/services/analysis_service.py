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
    PriceLevels, ScreenerStock,
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
        return {"score": max(0, min(100, _total)), "grade": "A" if _total >= 80 else "B" if _total >= 60 else "C" if _total >= 40 else "D"}


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


def _get_pipeline_session():
    """Get a DB session from the data pipeline, or None if unavailable."""
    try:
        from data_pipeline.db import Session as PipelineSession
        if PipelineSession is not None:
            return PipelineSession()
    except Exception:
        pass
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


def _query_promoter_pledge(ticker: str):
    """Query promoter pledge % from ShareholdingPattern table."""
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
        if row and row.promoter_pledge_pct is not None:
            return float(row.promoter_pledge_pct)
        return None
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

        if raw is None or (validation and not validation.show_dcf):
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
        price = enriched.get("price", 0)
        is_indian = ticker.endswith(".NS") or ticker.endswith(".BO")

        # Detect financial companies (NBFC/Bank/Insurance)
        clean_ticker = ticker.replace('.NS', '').replace('.BO', '')
        is_financial = clean_ticker in FINANCIAL_COMPANIES

        # ── Step 4: Build company info ────────────────────────
        _raw_sector = enriched.get("sector_name", raw.get("sector_name", ""))
        company = CompanyInfo(
            ticker=ticker,
            company_name=raw.get("company_name", ticker),
            sector=_resolve_sector(_raw_sector, clean_ticker),
            currency="INR",  # India-first launch
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

        # Apply FCF floor for capex-heavy companies (e.g. RELIANCE)
        # Try multiple keys for PAT — yfinance uses "net_income", pipeline uses "pat"
        _pat = (
            enriched.get("latest_pat")
            or enriched.get("net_income")
            or enriched.get("pat")
            or raw.get("netIncomeToCommon")
            or raw.get("net_income")
        )
        # Also try to get it from income_df if available
        if not _pat:
            _income_df = raw.get("income_df")
            if _income_df is not None and hasattr(_income_df, 'empty') and not _income_df.empty:
                try:
                    if "net_income" in _income_df.columns:
                        _pat = float(_income_df["net_income"].iloc[-1])
                except Exception:
                    pass

        _raw_fcf = enriched.get("latest_fcf") or enriched.get("yahoo_fcf_ttm")
        _adjusted_fcf = _get_adjusted_fcf(_raw_fcf, _pat, is_financial)
        if _adjusted_fcf is not None and _adjusted_fcf != _raw_fcf and not is_financial:
            enriched["latest_fcf"] = _adjusted_fcf
            import logging
            logging.getLogger("yieldiq.fcf").info(
                f"FCF floor for {ticker}: raw={_raw_fcf}, pat={_pat}, adjusted={_adjusted_fcf}"
            )

        forecaster = FCFForecaster()
        try:
            from models.forecaster import compute_wacc as _compute_wacc
            wacc_data = _compute_wacc(raw, is_indian)
            wacc = wacc_data.get("wacc", 0.10)
        except Exception:
            wacc_data = {}
            wacc = 0.10

        country = get_active_country()
        terminal_g = country.get("default_terminal_growth", 0.025)
        if terminal_g >= wacc:
            terminal_g = wacc - 0.02

        forecast_yrs = 10

        # ── Step 6: Valuation (P/B for financials, DCF for others) ──
        if is_financial:
            # --- P/B RATIO VALUATION for banks/NBFCs/insurance ---
            _sub_type = _get_financial_sub_type(clean_ticker)
            _pb_median = _PB_MEDIANS.get(_sub_type, 2.5)
            _val_method = ""

            # Method 1: P/B based — try multiple book value sources
            _bvps = (
                raw.get("bookValue")
                or enriched.get("book_value")
                or enriched.get("bvps")
            )
            if not _bvps or _bvps <= 0:
                _pb_ratio = raw.get("priceToBook") or enriched.get("pb_ratio")
                if _pb_ratio and _pb_ratio > 0 and price > 0:
                    _bvps = price / _pb_ratio

            if _bvps and _bvps > 0:
                iv = round(_bvps * _pb_median, 2)
                bear_iv = round(_bvps * 1.5, 2)
                bull_iv = round(_bvps * _pb_median * 1.4, 2)
                _val_method = f"P/B × {_pb_median} ({_sub_type})"
            else:
                iv = 0

            # Method 2: PE-based fallback if P/B gave 0
            if iv <= 0:
                _eps = enriched.get("diluted_eps") or raw.get("trailingEps") or enriched.get("eps")
                _sector_pe = {"Banking": 15, "NBFC": 20, "Insurance": 18}.get(_sub_type, 15)
                if _eps and _eps > 0:
                    iv = round(_eps * _sector_pe, 2)
                    bear_iv = round(_eps * (_sector_pe * 0.7), 2)
                    bull_iv = round(_eps * (_sector_pe * 1.3), 2)
                    _val_method = f"P/E × {_sector_pe} ({_sub_type})"

            # Method 3: Analyst target as last resort
            if iv <= 0:
                _analyst_tgt = (raw.get("finnhub_price_target") or {}).get("mean", 0) or raw.get("targetMeanPrice", 0)
                if _analyst_tgt and _analyst_tgt > 0:
                    iv = round(_analyst_tgt * 0.9, 2)
                    bear_iv = round(_analyst_tgt * 0.7, 2)
                    bull_iv = round(_analyst_tgt * 1.1, 2)
                    _val_method = "Analyst consensus (adjusted)"

            # Method 4: Never show ₹0 — use current price as fair value
            if iv <= 0 and price > 0:
                iv = round(price, 2)
                bear_iv = round(price * 0.8, 2)
                bull_iv = round(price * 1.2, 2)
                _val_method = "Insufficient data"

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
            moat_result = {"grade": "N/A (Financial)", "score": 0}
        else:
            moat_result = compute_moat_score(enriched, wacc)
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
            yiq_score = {"score": _total, "grade": "A" if _total >= 75 else "B" if _total >= 55 else "C" if _total >= 35 else "D"}

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
        # Flag as data-limited when confidence is low AND MoS is extreme (>40% either way)
        _conf_score = confidence.get("score", 50)
        if is_financial and iv <= 0:
            verdict = "data_limited"  # Financial with no valuation data
        elif _confidence in ("low", "unusable") and abs(mos_pct) > 40:
            verdict = "data_limited"
        elif _conf_score < 35 and abs(mos_pct) > 40:
            verdict = "data_limited"
        elif mos_pct > 15:
            verdict = "undervalued"
        elif mos_pct > -15:
            verdict = "fairly_valued"
        elif is_financial:
            verdict = "overvalued"  # Never "avoid" for financial companies
        elif enriched.get("dcf_reliable", True):
            verdict = "overvalued"
        else:
            verdict = "avoid"

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
            ),
            insights=InsightCards(
                patience_months=hp.get("min_months"),
                red_flag_count=len(_red_flags),
                red_flags=_red_flags[:5],
                earnings_date=raw.get("finnhub_next_earnings", {}).get("date"),
                earnings_est_eps=raw.get("finnhub_next_earnings", {}).get("eps_estimate"),
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
                bear=_sc("Bear case") if scenarios_raw.get("Bear case") else _sc("Bear 🐻"),
                base=ScenarioCase(iv=round(iv, 2), mos_pct=round(mos_pct, 1), growth=round(base_growth, 4), wacc=round(wacc, 4), term_g=round(terminal_g, 4)),
                bull=_sc("Bull case") if scenarios_raw.get("Bull case") else _sc("Bull 🐂"),
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
