# backend/services/financials_service.py
"""
Financial statements service for the analysis page.

Primary source: the ``company_financials`` table (filled weekly by the
data_pipeline.xbrl pipeline from yfinance + NSE). That table splits each
period into three rows keyed by ``statement_type`` — income /
balance_sheet / cashflow. We query all three for a ticker, merge by
``period_end_date``, and return the same flat shape the frontend has
always consumed.

Fallback: live yfinance pull (annual only), used when the DB has <2
periods for the ticker — e.g. names not covered by the weekly pipeline.

All monetary values are in Crores (the new pipeline converts from raw
rupees before insert).
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date
from typing import Any

from sqlalchemy import text

logger = logging.getLogger("yieldiq.financials")


def _get_pipeline_session():
    """Open a SQLAlchemy session against the shared pipeline engine."""
    try:
        from data_pipeline.db import Session as PipelineSession
        if PipelineSession is not None:
            return PipelineSession()
    except Exception:
        pass
    return None


def _format_period(period_end: date | None, period_type: str) -> str:
    """Indian FY convention — FY2025 for Mar-2025 period_end; Q3FY25 etc."""
    if not period_end:
        return "Unknown"
    year = period_end.year
    month = period_end.month
    fy = year + 1 if month >= 4 else year
    if period_type == "annual":
        return f"FY{fy}"
    if month in (4, 5, 6):
        q = "Q1"
    elif month in (7, 8, 9):
        q = "Q2"
    elif month in (10, 11, 12):
        q = "Q3"
    else:
        q = "Q4"
    return f"{q}FY{str(fy)[2:]}"


def _safe_float(v: Any) -> float | None:
    try:
        if v is None:
            return None
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return None
        return f
    except (TypeError, ValueError):
        return None


def _pct(numerator: Any, denominator: Any) -> float | None:
    n = _safe_float(numerator)
    d = _safe_float(denominator)
    if n is None or d is None or d == 0:
        return None
    return round(n / d * 100, 1)


def _yoy_growth(curr: Any, prev: Any) -> float | None:
    c = _safe_float(curr)
    p = _safe_float(prev)
    if c is None or p is None or p == 0:
        return None
    return round((c - p) / abs(p) * 100, 1)


# ──────────────────────────────────────────────────────────────────────────
# Row model
# ──────────────────────────────────────────────────────────────────────────
@dataclass
class _Row:
    """
    Flat per-period row. Populated from the 3 statement_type rows in
    ``company_financials``, or from the yfinance fallback. Field names
    match the old _Row where possible (pat == net_income, cfo ==
    operating_cf, cash_and_equivalents == cash) so downstream helpers
    don't need to know the source.
    """
    period_end: date | None
    period_type: str
    # Income
    revenue: float | None = None
    gross_profit: float | None = None
    ebitda: float | None = None
    ebit: float | None = None
    depreciation: float | None = None
    interest_expense: float | None = None
    pat: float | None = None                 # net_income
    eps_basic: float | None = None
    eps_diluted: float | None = None
    # Balance Sheet
    total_assets: float | None = None
    total_equity: float | None = None
    total_debt: float | None = None
    cash_and_equivalents: float | None = None
    net_debt: float | None = None
    shares_outstanding: float | None = None  # Lakhs (yfinance fallback only)
    # Cash Flow
    cfo: float | None = None                 # operating_cf
    capex: float | None = None
    free_cash_flow: float | None = None
    # Metadata
    roe: float | None = None
    debt_to_equity: float | None = None
    net_margin: float | None = None          # pct; only used for legacy compat


def _book_value_per_share(equity_cr: float | None,
                          shares_lakhs: float | None) -> float | None:
    """BVPS = equity(Cr)*1e7 / shares(Lakhs)*1e5 = equity/shares*100."""
    e = _safe_float(equity_cr)
    s = _safe_float(shares_lakhs)
    if e is None or s is None or s == 0:
        return None
    return round(e / s * 100, 2)


# ──────────────────────────────────────────────────────────────────────────
# DB query — new company_financials table
# ──────────────────────────────────────────────────────────────────────────
def _fetch_from_db(db, db_ticker: str, period_type: str,
                   limit: int) -> list[_Row]:
    """
    Read up to ``limit`` periods for a ticker from the new table.
    Runs 3 queries (income / balance_sheet / cashflow), merges by
    period_end_date, returns rows newest→oldest.
    """
    # ---- INCOME ------------------------------------------------------
    inc_rows = db.execute(text("""
        SELECT period_end_date, revenue, gross_profit, ebitda, ebit,
               depreciation, interest_expense,
               net_income, eps_basic, eps_diluted
        FROM company_financials
        WHERE ticker_nse = :t
          AND statement_type = 'income'
          AND period_type = :p
          AND period_end_date IS NOT NULL
        ORDER BY period_end_date DESC
        LIMIT :lim
    """), {"t": db_ticker, "p": period_type, "lim": limit}).mappings().all()

    if not inc_rows:
        return []

    # ---- BALANCE SHEET ----------------------------------------------
    bs_rows = db.execute(text("""
        SELECT period_end_date, total_assets, total_debt, cash,
               total_equity, current_assets, fixed_assets,
               net_debt, working_capital
        FROM company_financials
        WHERE ticker_nse = :t
          AND statement_type = 'balance_sheet'
          AND period_type = :p
          AND period_end_date IS NOT NULL
        ORDER BY period_end_date DESC
        LIMIT :lim
    """), {"t": db_ticker, "p": period_type, "lim": limit}).mappings().all()

    # ---- CASH FLOW (annual only in our pipeline) --------------------
    cf_period = "annual"   # our pipeline writes CF as annual only
    cf_rows = db.execute(text("""
        SELECT period_end_date, operating_cf, investing_cf, financing_cf,
               capex, free_cash_flow, dividends_paid
        FROM company_financials
        WHERE ticker_nse = :t
          AND statement_type = 'cashflow'
          AND period_type = :p
          AND period_end_date IS NOT NULL
        ORDER BY period_end_date DESC
        LIMIT :lim
    """), {"t": db_ticker, "p": cf_period, "lim": limit}).mappings().all()

    # Index BS and CF by date for merge
    bs_by_date = {r["period_end_date"]: r for r in bs_rows}
    cf_by_date = {r["period_end_date"]: r for r in cf_rows}

    out: list[_Row] = []
    for inc in inc_rows:
        pend = inc["period_end_date"]
        bs = bs_by_date.get(pend) or {}
        cf = cf_by_date.get(pend) or {}

        row = _Row(
            period_end=pend,
            period_type=period_type,
            # Income
            revenue=_safe_float(inc.get("revenue")),
            gross_profit=_safe_float(inc.get("gross_profit")),
            ebitda=_safe_float(inc.get("ebitda")),
            ebit=_safe_float(inc.get("ebit")),
            depreciation=_safe_float(inc.get("depreciation")),
            interest_expense=_safe_float(inc.get("interest_expense")),
            pat=_safe_float(inc.get("net_income")),
            eps_basic=_safe_float(inc.get("eps_basic")),
            eps_diluted=_safe_float(inc.get("eps_diluted")),
            # Balance sheet
            total_assets=_safe_float(bs.get("total_assets")),
            total_equity=_safe_float(bs.get("total_equity")),
            total_debt=_safe_float(bs.get("total_debt")),
            cash_and_equivalents=_safe_float(bs.get("cash")),
            net_debt=_safe_float(bs.get("net_debt")),
            # Cash flow
            cfo=_safe_float(cf.get("operating_cf")),
            capex=_safe_float(cf.get("capex")),
            free_cash_flow=_safe_float(cf.get("free_cash_flow")),
        )

        # Derived: fill EBITDA from EBIT+Depreciation if missing
        if row.ebitda is None and row.ebit is not None \
                and row.depreciation is not None:
            row.ebitda = round(row.ebit + row.depreciation, 2)

        # Debt/Equity derived
        if row.total_debt is not None and row.total_equity \
                and row.total_equity != 0:
            row.debt_to_equity = round(row.total_debt / row.total_equity, 2)

        out.append(row)

    return out


# ──────────────────────────────────────────────────────────────────────────
# yfinance fallback (annual only)
# ──────────────────────────────────────────────────────────────────────────
def _yfinance_fallback(ticker_ns: str, years: int) -> list[_Row]:
    """Silent annual fallback when DB has no/little data."""
    try:
        import yfinance as yf
    except Exception:
        return []

    try:
        t = yf.Ticker(ticker_ns)
        inc = getattr(t, "income_stmt", None)
        bal = getattr(t, "balance_sheet", None)
        cf = getattr(t, "cashflow", None)
    except Exception as exc:
        logger.warning("yfinance fallback failed for %s: %s", ticker_ns, exc)
        return []

    if inc is None or getattr(inc, "empty", True):
        return []

    def _getv(df, row_name, col):
        try:
            if df is None or row_name not in df.index:
                return None
            v = df.at[row_name, col]
            if v is None:
                return None
            vf = float(v)
            if math.isnan(vf) or math.isinf(vf):
                return None
            return vf
        except Exception:
            return None

    TO_CR = 1e7
    rows: list[_Row] = []
    for col in list(inc.columns)[:years]:
        try:
            pend = col.date() if hasattr(col, "date") else None
            revenue = _getv(inc, "Total Revenue", col)
            gp = _getv(inc, "Gross Profit", col)
            pat = _getv(inc, "Net Income", col)
            ebitda = _getv(inc, "EBITDA", col)
            ebit = _getv(inc, "EBIT", col) or _getv(inc, "Operating Income", col)
            dep = _getv(inc, "Reconciled Depreciation", col) \
                or _getv(inc, "Depreciation", col)
            interest = _getv(inc, "Interest Expense", col)
            eps_d = _getv(inc, "Diluted EPS", col)
            eps_b = _getv(inc, "Basic EPS", col)
            cfo = _getv(cf, "Operating Cash Flow", col)
            capex = _getv(cf, "Capital Expenditure", col)
            fcf = _getv(cf, "Free Cash Flow", col)
            if fcf is None and cfo is not None and capex is not None:
                fcf = cfo - abs(capex)
            total_assets = _getv(bal, "Total Assets", col)
            total_equity = _getv(bal, "Stockholders Equity", col) \
                or _getv(bal, "Total Equity Gross Minority Interest", col)
            total_debt = _getv(bal, "Total Debt", col)
            cash = _getv(bal, "Cash And Cash Equivalents", col)
            shares = _getv(bal, "Ordinary Shares Number", col)

            rows.append(_Row(
                period_end=pend,
                period_type="annual",
                revenue=revenue / TO_CR if revenue else None,
                gross_profit=gp / TO_CR if gp else None,
                ebitda=ebitda / TO_CR if ebitda else None,
                ebit=ebit / TO_CR if ebit else None,
                depreciation=dep / TO_CR if dep else None,
                interest_expense=interest / TO_CR if interest else None,
                pat=pat / TO_CR if pat else None,
                eps_basic=eps_b,
                eps_diluted=eps_d,
                cfo=cfo / TO_CR if cfo else None,
                capex=capex / TO_CR if capex else None,
                free_cash_flow=fcf / TO_CR if fcf else None,
                total_assets=total_assets / TO_CR if total_assets else None,
                total_equity=total_equity / TO_CR if total_equity else None,
                total_debt=total_debt / TO_CR if total_debt else None,
                cash_and_equivalents=cash / TO_CR if cash else None,
                shares_outstanding=(shares / 1e5) if shares else None,
            ))
        except Exception:
            continue
    return rows


# ──────────────────────────────────────────────────────────────────────────
# Year builder (response shape)
# ──────────────────────────────────────────────────────────────────────────
def _build_year(row: _Row, prev: _Row | None) -> dict:
    rev_growth = _yoy_growth(row.revenue, prev.revenue) if prev else None
    pat_growth = _yoy_growth(row.pat, prev.pat) if prev else None

    net_margin_pct = _pct(row.pat, row.revenue)
    gross_margin_pct = _pct(row.gross_profit, row.revenue)
    operating_margin_pct = _pct(row.ebit, row.revenue)
    fcf_margin_pct = _pct(row.free_cash_flow, row.revenue)

    # Debt/Equity
    de = row.debt_to_equity
    if de is None and row.total_debt is not None and row.total_equity \
            and row.total_equity != 0:
        de = round(row.total_debt / row.total_equity, 2)

    # Net debt — prefer stored value, derive if missing
    net_debt = row.net_debt
    if net_debt is None and (
            row.total_debt is not None or row.cash_and_equivalents is not None):
        net_debt = round(
            (row.total_debt or 0) - (row.cash_and_equivalents or 0), 2
        )

    return {
        "year": _format_period(row.period_end, row.period_type),
        "period_end": row.period_end.isoformat() if row.period_end else None,

        # Income Statement
        "revenue": row.revenue,
        "revenue_growth_pct": rev_growth,
        "gross_profit": row.gross_profit,
        "gross_margin_pct": gross_margin_pct,
        "ebitda": row.ebitda,
        "operating_income": row.ebit,
        "operating_margin_pct": operating_margin_pct,
        "net_income": row.pat,
        "net_income_growth_pct": pat_growth,
        "net_margin_pct": net_margin_pct,
        "eps_diluted": row.eps_diluted,

        # Balance Sheet
        "total_assets": row.total_assets,
        "total_equity": row.total_equity,
        "total_debt": row.total_debt,
        "cash": row.cash_and_equivalents,
        "net_debt": net_debt,
        "debt_to_equity": de,
        "book_value_per_share": _book_value_per_share(
            row.total_equity, row.shares_outstanding
        ),

        # Cash Flow
        "operating_cash_flow": row.cfo,
        "capex": row.capex,
        "free_cash_flow": row.free_cash_flow,
        "fcf_margin_pct": fcf_margin_pct,
    }


def _compute_summary(years_data: list[dict]) -> dict:
    """Revenue CAGR (≤3y), avg margins, latest ROE (populated later)."""
    revenue_cagr_3y: float | None = None
    usable = [d for d in years_data if d.get("revenue") is not None]
    if len(usable) >= 2:
        latest = usable[0]["revenue"]
        oldest_idx = min(3, len(usable) - 1)
        oldest = usable[oldest_idx]["revenue"]
        n = oldest_idx
        if latest and oldest and oldest > 0 and n > 0:
            try:
                revenue_cagr_3y = round(
                    ((latest / oldest) ** (1 / n) - 1) * 100, 1
                )
            except (ValueError, ZeroDivisionError):
                revenue_cagr_3y = None

    def _avg(field_name: str) -> float | None:
        vals = [d[field_name] for d in years_data
                if d.get(field_name) is not None]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 1)

    return {
        "revenue_cagr_3y": revenue_cagr_3y,
        "avg_net_margin": _avg("net_margin_pct"),
        "avg_fcf_margin": _avg("fcf_margin_pct"),
        "latest_roe": None,
    }


# ──────────────────────────────────────────────────────────────────────────
# Service
# ──────────────────────────────────────────────────────────────────────────
class FinancialsService:
    """See module docstring."""

    def get_financials(
        self,
        ticker: str,
        period: str = "annual",
        years: int = 5,
    ) -> dict:
        ticker = ticker.upper().strip()
        if period not in ("annual", "quarterly"):
            period = "annual"
        years = max(1, min(int(years or 5), 10))

        limit = years if period == "annual" else 8
        rows: list[_Row] = []
        data_source = "db"

        # DB stores tickers without the .NS / .BO suffix
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")

        db = _get_pipeline_session()
        if db is not None:
            try:
                rows = _fetch_from_db(db, db_ticker, period, limit)
            except Exception as exc:
                logger.warning("DB query failed for %s: %s", ticker, exc)
                rows = []
            finally:
                try:
                    db.close()
                except Exception:
                    pass

        # Annual fallback — only if DB came back almost empty
        if period == "annual" and len(rows) < 2:
            fallback = _yfinance_fallback(ticker, limit)
            if len(fallback) > len(rows):
                rows = fallback
                data_source = "yfinance_fallback"

        has_quarterly_any = self._has_quarterly_rows(db_ticker)

        years_data: list[dict] = []
        for i, r in enumerate(rows):
            prev = rows[i + 1] if i + 1 < len(rows) else None
            years_data.append(_build_year(r, prev))

        summary = _compute_summary(years_data)

        # Latest ROE — derived from newest row's equity + net_income
        if rows and rows[0].total_equity and rows[0].pat is not None \
                and rows[0].total_equity != 0:
            summary["latest_roe"] = round(
                rows[0].pat / rows[0].total_equity * 100, 1
            )

        is_indian = ticker.endswith(".NS") or ticker.endswith(".BO")
        currency = "INR" if is_indian else "USD"
        currency_unit = "Cr" if is_indian else "M"

        return {
            "ticker": ticker,
            "currency": currency,
            "currency_unit": currency_unit,
            "period": period,
            "years_available": len(years_data),
            "has_quarterly": has_quarterly_any,
            "data_source": data_source if years_data else "none",
            "income": years_data,
            "balance_sheet": years_data,
            "cash_flow": years_data,
            "summary": summary,
        }

    def _has_quarterly_rows(self, db_ticker: str) -> bool:
        """Cheap existence check for UI's Quarterly toggle."""
        db = _get_pipeline_session()
        if db is None:
            return False
        try:
            row = db.execute(text("""
                SELECT 1 FROM company_financials
                WHERE ticker_nse = :t
                  AND period_type = 'quarterly'
                  AND statement_type = 'income'
                LIMIT 1
            """), {"t": db_ticker}).first()
            return row is not None
        except Exception:
            return False
        finally:
            try:
                db.close()
            except Exception:
                pass
