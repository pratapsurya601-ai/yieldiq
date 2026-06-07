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
    # Bank format (Schedule III Division I — NSE/NSE_XBRL ingest only)
    # Added 2026-06-07 by fix/financials-source-priority. Banks
    # populate these instead of the GAAP gross_profit / ebit /
    # interest_expense triple. Surfaced in the API so the FE can
    # render bank-format rows when ready. See db_writer.py lines
    # 86-89 for the source-of-truth column list.
    interest_earned: float | None = None
    interest_expended: float | None = None
    total_income: float | None = None
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
# Day-111b — Debt/Equity ratio (bank-aware)
# ──────────────────────────────────────────────────────────────────────────
def _compute_de_ratio(
    ticker: str | None,
    *,
    total_debt: float | None,
    total_equity: float | None,
    total_liabilities: float | None,
) -> float | None:
    """Compute D/E with a bank-aware numerator.

    For commercial banks (``is_pure_bank_for_de`` True), deposits +
    borrowings are interest-bearing liabilities that belong in the
    D/E numerator. ``company_financials`` does not yet split these
    out, so we fall back to ``(total_liabilities - total_equity) /
    total_equity`` — a tight proxy because banks' non-equity, non-
    deposit, non-borrowing liabilities (other liab / provisions) are
    a small fraction of the balance sheet. HDFCBANK lands at ~7-8
    via this path, matching Screener.in.

    For non-banks, behaviour is unchanged: ``total_debt / equity``.

    Returns ``None`` when equity is missing / zero, or when the bank
    fallback has no usable ``total_liabilities``.
    """
    eq = _safe_float(total_equity)
    if eq is None or eq == 0:
        return None
    try:
        from backend.services.analysis.sector_overrides import (
            is_pure_bank_for_de,
        )
    except Exception:  # pragma: no cover — defensive import
        is_pure_bank_for_de = lambda _t: False  # noqa: E731

    if is_pure_bank_for_de(ticker):
        tl = _safe_float(total_liabilities)
        if tl is None:
            # Bank with no total_liabilities — return None rather
            # than the misleading total_debt/equity number.
            return None
        return round((tl - eq) / eq, 2)

    td = _safe_float(total_debt)
    if td is None:
        return None
    return round(td / eq, 2)


# ──────────────────────────────────────────────────────────────────────────
# DB query — new company_financials table
# ──────────────────────────────────────────────────────────────────────────
def _fetch_from_db(db, db_ticker: str, period_type: str,
                   limit: int) -> list[_Row]:
    """
    Read up to ``limit`` periods for a ticker from the new table.
    Runs 3 queries (income / balance_sheet / cashflow), merges by
    period_end_date, returns rows newest→oldest.

    Source-priority + field-coalesce (fix/financials-source-priority,
    2026-06-07): ``company_financials`` carries up to 3 rows per
    (ticker, period_end_date, statement_type) because the UNIQUE
    constraint includes ``source``. Sources differ in coverage:

      - ``yfinance`` — rich rows, full GAAP fields (gross_profit,
        ebitda, ebit, interest_expense). Range 2024-09-30 onward.
      - ``NSE_XBRL`` — XBRL ingest; has ebitda/ebit/op_income,
        no gross_profit. Range 2016-12-31 → 2024-12-31.
      - ``nse``     — PAT/EPS-only stubs from corp announcements;
        gross_profit/ebitda/ebit/interest_expense all NULL.
        Also carries bank-format fields (interest_earned,
        interest_expended, total_income) for Schedule III Div I
        banks.

    Old reader did ``DISTINCT ON`` with the wrong priority
    (``nse`` first), so newer yfinance-only quarters were either
    masked by a thin NSE stub or showed the latest insert's source
    arbitrarily. The fix:

      1. Aggregate per ``period_end_date`` with
         ``MAX(CASE WHEN source='X' THEN col END)`` per source.
      2. ``COALESCE(yfinance, NSE_XBRL, nse)`` in the outer SELECT so
         each field is sourced from the highest-priority row that has
         a non-NULL value. yfinance wins by default; missing fields
         fall through to NSE_XBRL then nse.
      3. Bank-format columns (``interest_earned``,
         ``interest_expended``, ``total_income``) are surfaced from
         the nse / NSE_XBRL rows that populate them (yfinance never
         does).
    """
    # ---- INCOME ------------------------------------------------------
    inc_rows = db.execute(text("""
        SELECT period_end_date,
               COALESCE(yf_revenue,           xbrl_revenue,          nse_revenue)          AS revenue,
               COALESCE(yf_gross_profit,      xbrl_gross_profit,     nse_gross_profit)     AS gross_profit,
               COALESCE(yf_ebitda,            xbrl_ebitda,           nse_ebitda)           AS ebitda,
               COALESCE(yf_ebit,              xbrl_ebit,             nse_ebit)             AS ebit,
               COALESCE(yf_depreciation,      xbrl_depreciation,     nse_depreciation)     AS depreciation,
               COALESCE(yf_interest_expense,  xbrl_interest_expense, nse_interest_expense) AS interest_expense,
               COALESCE(yf_net_income,        xbrl_net_income,       nse_net_income)       AS net_income,
               COALESCE(yf_eps_basic,         xbrl_eps_basic,        nse_eps_basic)        AS eps_basic,
               COALESCE(yf_eps_diluted,       xbrl_eps_diluted,      nse_eps_diluted)      AS eps_diluted,
               -- Bank format — surfaced from whichever ingest populates them.
               COALESCE(yf_interest_earned,   xbrl_interest_earned,  nse_interest_earned)   AS interest_earned,
               COALESCE(yf_interest_expended, xbrl_interest_expended, nse_interest_expended) AS interest_expended,
               COALESCE(yf_total_income,      xbrl_total_income,     nse_total_income)      AS total_income
        FROM (
            SELECT period_end_date,
                   MAX(CASE WHEN source='yfinance' THEN revenue           END) AS yf_revenue,
                   MAX(CASE WHEN source='NSE_XBRL' THEN revenue           END) AS xbrl_revenue,
                   MAX(CASE WHEN source='nse'      THEN revenue           END) AS nse_revenue,
                   MAX(CASE WHEN source='yfinance' THEN gross_profit      END) AS yf_gross_profit,
                   MAX(CASE WHEN source='NSE_XBRL' THEN gross_profit      END) AS xbrl_gross_profit,
                   MAX(CASE WHEN source='nse'      THEN gross_profit      END) AS nse_gross_profit,
                   MAX(CASE WHEN source='yfinance' THEN ebitda            END) AS yf_ebitda,
                   MAX(CASE WHEN source='NSE_XBRL' THEN ebitda            END) AS xbrl_ebitda,
                   MAX(CASE WHEN source='nse'      THEN ebitda            END) AS nse_ebitda,
                   MAX(CASE WHEN source='yfinance' THEN ebit              END) AS yf_ebit,
                   MAX(CASE WHEN source='NSE_XBRL' THEN ebit              END) AS xbrl_ebit,
                   MAX(CASE WHEN source='nse'      THEN ebit              END) AS nse_ebit,
                   MAX(CASE WHEN source='yfinance' THEN depreciation      END) AS yf_depreciation,
                   MAX(CASE WHEN source='NSE_XBRL' THEN depreciation      END) AS xbrl_depreciation,
                   MAX(CASE WHEN source='nse'      THEN depreciation      END) AS nse_depreciation,
                   MAX(CASE WHEN source='yfinance' THEN interest_expense  END) AS yf_interest_expense,
                   MAX(CASE WHEN source='NSE_XBRL' THEN interest_expense  END) AS xbrl_interest_expense,
                   MAX(CASE WHEN source='nse'      THEN interest_expense  END) AS nse_interest_expense,
                   MAX(CASE WHEN source='yfinance' THEN net_income        END) AS yf_net_income,
                   MAX(CASE WHEN source='NSE_XBRL' THEN net_income        END) AS xbrl_net_income,
                   MAX(CASE WHEN source='nse'      THEN net_income        END) AS nse_net_income,
                   MAX(CASE WHEN source='yfinance' THEN eps_basic         END) AS yf_eps_basic,
                   MAX(CASE WHEN source='NSE_XBRL' THEN eps_basic         END) AS xbrl_eps_basic,
                   MAX(CASE WHEN source='nse'      THEN eps_basic         END) AS nse_eps_basic,
                   MAX(CASE WHEN source='yfinance' THEN eps_diluted       END) AS yf_eps_diluted,
                   MAX(CASE WHEN source='NSE_XBRL' THEN eps_diluted       END) AS xbrl_eps_diluted,
                   MAX(CASE WHEN source='nse'      THEN eps_diluted       END) AS nse_eps_diluted,
                   MAX(CASE WHEN source='yfinance' THEN interest_earned   END) AS yf_interest_earned,
                   MAX(CASE WHEN source='NSE_XBRL' THEN interest_earned   END) AS xbrl_interest_earned,
                   MAX(CASE WHEN source='nse'      THEN interest_earned   END) AS nse_interest_earned,
                   MAX(CASE WHEN source='yfinance' THEN interest_expended END) AS yf_interest_expended,
                   MAX(CASE WHEN source='NSE_XBRL' THEN interest_expended END) AS xbrl_interest_expended,
                   MAX(CASE WHEN source='nse'      THEN interest_expended END) AS nse_interest_expended,
                   MAX(CASE WHEN source='yfinance' THEN total_income      END) AS yf_total_income,
                   MAX(CASE WHEN source='NSE_XBRL' THEN total_income      END) AS xbrl_total_income,
                   MAX(CASE WHEN source='nse'      THEN total_income      END) AS nse_total_income
            FROM company_financials
            WHERE ticker_nse = :t
              AND statement_type = 'income'
              AND period_type = :p
              AND period_end_date IS NOT NULL
            GROUP BY period_end_date
        ) agg
        ORDER BY period_end_date DESC
        LIMIT :lim
    """), {"t": db_ticker, "p": period_type, "lim": limit}).mappings().all()

    if not inc_rows:
        return []

    # ---- BALANCE SHEET ----------------------------------------------
    bs_rows = db.execute(text("""
        SELECT period_end_date,
               COALESCE(yf_total_assets,       xbrl_total_assets,       nse_total_assets)       AS total_assets,
               COALESCE(yf_total_debt,         xbrl_total_debt,         nse_total_debt)         AS total_debt,
               COALESCE(yf_cash,               xbrl_cash,               nse_cash)               AS cash,
               COALESCE(yf_total_equity,       xbrl_total_equity,       nse_total_equity)       AS total_equity,
               COALESCE(yf_current_assets,     xbrl_current_assets,     nse_current_assets)     AS current_assets,
               COALESCE(yf_fixed_assets,       xbrl_fixed_assets,       nse_fixed_assets)       AS fixed_assets,
               COALESCE(yf_net_debt,           xbrl_net_debt,           nse_net_debt)           AS net_debt,
               COALESCE(yf_working_capital,    xbrl_working_capital,    nse_working_capital)    AS working_capital,
               COALESCE(yf_total_liabilities,  xbrl_total_liabilities,  nse_total_liabilities)  AS total_liabilities
        FROM (
            SELECT period_end_date,
                   MAX(CASE WHEN source='yfinance' THEN total_assets      END) AS yf_total_assets,
                   MAX(CASE WHEN source='NSE_XBRL' THEN total_assets      END) AS xbrl_total_assets,
                   MAX(CASE WHEN source='nse'      THEN total_assets      END) AS nse_total_assets,
                   MAX(CASE WHEN source='yfinance' THEN total_debt        END) AS yf_total_debt,
                   MAX(CASE WHEN source='NSE_XBRL' THEN total_debt        END) AS xbrl_total_debt,
                   MAX(CASE WHEN source='nse'      THEN total_debt        END) AS nse_total_debt,
                   MAX(CASE WHEN source='yfinance' THEN cash              END) AS yf_cash,
                   MAX(CASE WHEN source='NSE_XBRL' THEN cash              END) AS xbrl_cash,
                   MAX(CASE WHEN source='nse'      THEN cash              END) AS nse_cash,
                   MAX(CASE WHEN source='yfinance' THEN total_equity      END) AS yf_total_equity,
                   MAX(CASE WHEN source='NSE_XBRL' THEN total_equity      END) AS xbrl_total_equity,
                   MAX(CASE WHEN source='nse'      THEN total_equity      END) AS nse_total_equity,
                   MAX(CASE WHEN source='yfinance' THEN current_assets    END) AS yf_current_assets,
                   MAX(CASE WHEN source='NSE_XBRL' THEN current_assets    END) AS xbrl_current_assets,
                   MAX(CASE WHEN source='nse'      THEN current_assets    END) AS nse_current_assets,
                   MAX(CASE WHEN source='yfinance' THEN fixed_assets      END) AS yf_fixed_assets,
                   MAX(CASE WHEN source='NSE_XBRL' THEN fixed_assets      END) AS xbrl_fixed_assets,
                   MAX(CASE WHEN source='nse'      THEN fixed_assets      END) AS nse_fixed_assets,
                   MAX(CASE WHEN source='yfinance' THEN net_debt          END) AS yf_net_debt,
                   MAX(CASE WHEN source='NSE_XBRL' THEN net_debt          END) AS xbrl_net_debt,
                   MAX(CASE WHEN source='nse'      THEN net_debt          END) AS nse_net_debt,
                   MAX(CASE WHEN source='yfinance' THEN working_capital   END) AS yf_working_capital,
                   MAX(CASE WHEN source='NSE_XBRL' THEN working_capital   END) AS xbrl_working_capital,
                   MAX(CASE WHEN source='nse'      THEN working_capital   END) AS nse_working_capital,
                   MAX(CASE WHEN source='yfinance' THEN total_liabilities END) AS yf_total_liabilities,
                   MAX(CASE WHEN source='NSE_XBRL' THEN total_liabilities END) AS xbrl_total_liabilities,
                   MAX(CASE WHEN source='nse'      THEN total_liabilities END) AS nse_total_liabilities
            FROM company_financials
            WHERE ticker_nse = :t
              AND statement_type = 'balance_sheet'
              AND period_type = :p
              AND period_end_date IS NOT NULL
            GROUP BY period_end_date
        ) agg
        ORDER BY period_end_date DESC
        LIMIT :lim
    """), {"t": db_ticker, "p": period_type, "lim": limit}).mappings().all()

    # ---- CASH FLOW (annual only in our pipeline) --------------------
    cf_period = "annual"   # our pipeline writes CF as annual only
    cf_rows = db.execute(text("""
        SELECT period_end_date,
               COALESCE(yf_operating_cf,    xbrl_operating_cf,    nse_operating_cf)    AS operating_cf,
               COALESCE(yf_investing_cf,    xbrl_investing_cf,    nse_investing_cf)    AS investing_cf,
               COALESCE(yf_financing_cf,    xbrl_financing_cf,    nse_financing_cf)    AS financing_cf,
               COALESCE(yf_capex,           xbrl_capex,           nse_capex)           AS capex,
               COALESCE(yf_free_cash_flow,  xbrl_free_cash_flow,  nse_free_cash_flow)  AS free_cash_flow,
               COALESCE(yf_dividends_paid,  xbrl_dividends_paid,  nse_dividends_paid)  AS dividends_paid
        FROM (
            SELECT period_end_date,
                   MAX(CASE WHEN source='yfinance' THEN operating_cf   END) AS yf_operating_cf,
                   MAX(CASE WHEN source='NSE_XBRL' THEN operating_cf   END) AS xbrl_operating_cf,
                   MAX(CASE WHEN source='nse'      THEN operating_cf   END) AS nse_operating_cf,
                   MAX(CASE WHEN source='yfinance' THEN investing_cf   END) AS yf_investing_cf,
                   MAX(CASE WHEN source='NSE_XBRL' THEN investing_cf   END) AS xbrl_investing_cf,
                   MAX(CASE WHEN source='nse'      THEN investing_cf   END) AS nse_investing_cf,
                   MAX(CASE WHEN source='yfinance' THEN financing_cf   END) AS yf_financing_cf,
                   MAX(CASE WHEN source='NSE_XBRL' THEN financing_cf   END) AS xbrl_financing_cf,
                   MAX(CASE WHEN source='nse'      THEN financing_cf   END) AS nse_financing_cf,
                   MAX(CASE WHEN source='yfinance' THEN capex          END) AS yf_capex,
                   MAX(CASE WHEN source='NSE_XBRL' THEN capex          END) AS xbrl_capex,
                   MAX(CASE WHEN source='nse'      THEN capex          END) AS nse_capex,
                   MAX(CASE WHEN source='yfinance' THEN free_cash_flow END) AS yf_free_cash_flow,
                   MAX(CASE WHEN source='NSE_XBRL' THEN free_cash_flow END) AS xbrl_free_cash_flow,
                   MAX(CASE WHEN source='nse'      THEN free_cash_flow END) AS nse_free_cash_flow,
                   MAX(CASE WHEN source='yfinance' THEN dividends_paid END) AS yf_dividends_paid,
                   MAX(CASE WHEN source='NSE_XBRL' THEN dividends_paid END) AS xbrl_dividends_paid,
                   MAX(CASE WHEN source='nse'      THEN dividends_paid END) AS nse_dividends_paid
            FROM company_financials
            WHERE ticker_nse = :t
              AND statement_type = 'cashflow'
              AND period_type = :p
              AND period_end_date IS NOT NULL
            GROUP BY period_end_date
        ) agg
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
            # Bank format (Schedule III Division I)
            interest_earned=_safe_float(inc.get("interest_earned")),
            interest_expended=_safe_float(inc.get("interest_expended")),
            total_income=_safe_float(inc.get("total_income")),
        )

        # Derived: fill EBITDA from EBIT+Depreciation if missing
        if row.ebitda is None and row.ebit is not None \
                and row.depreciation is not None:
            row.ebitda = round(row.ebit + row.depreciation, 2)

        # Debt/Equity derived
        # Day-111b: banks are structurally leveraged via deposits +
        # borrowings, which are interest-bearing liabilities that live
        # in ``total_liabilities`` (not ``total_debt``). Computing D/E
        # as total_debt/equity for a bank yields a nonsensical ~0.95
        # for HDFCBANK; the real value (deposits + borrowings) /
        # equity is ~7-8. Banks deliberately route through the
        # fallback formula (total_liab - equity) / equity until the
        # data_pipeline gains separate deposits / borrowings columns
        # (Phase-2 ingestion).
        row.debt_to_equity = _compute_de_ratio(
            db_ticker,
            total_debt=row.total_debt,
            total_equity=row.total_equity,
            total_liabilities=_safe_float(bs.get("total_liabilities")),
        )

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
        # Added 2026-05-25 (feat/sankey-waterfall): surfaces the
        # interest leg for the Revenue Sankey / Earnings Waterfall.
        # Null when the underlying income row doesn't carry it.
        "interest_expense": row.interest_expense,
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

        # Bank format (Schedule III Division I) — only populated for
        # banks; null for non-banks. Added 2026-06-07 by
        # fix/financials-source-priority. FE can ignore until ready.
        "interest_earned": row.interest_earned,
        "interest_expended": row.interest_expended,
        "total_income": row.total_income,
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

        # Currency inference (Cluster B, 2026-06-07).
        #
        # Old code used ``ticker.endswith(".NS")`` which silently
        # fell through to USD/M when the frontend passed a bare canonical
        # ticker (e.g. "BANKBARODA") — the resulting "Values in ₹ M"
        # header on Indian rows read 10× wrong because the underlying
        # numbers are in CRORES (per the module docstring) but were
        # labelled MILLIONS, and ``analysis.chart-data`` then multiplied
        # by 1e6 instead of 1e7.
        #
        # Source of truth: the data_pipeline writes ONLY Indian listings
        # into ``company_financials`` keyed by ``ticker_nse``. So any
        # row served from the DB path is, by construction, INR / Crores.
        # The yfinance fallback path is the only way a non-Indian ticker
        # (e.g. "AAPL") reaches this function — for that we still need
        # a suffix check, but we apply it to the resolved ticker rather
        # than the raw user input.
        is_indian = (
            data_source == "db"
            or ticker.endswith(".NS")
            or ticker.endswith(".BO")
            or not ("." in ticker)  # bare canonical (BANKBARODA, TCS)
                                    # — DB has no fallback for non-Indian
                                    # bare tickers, so this is safe
        )
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
