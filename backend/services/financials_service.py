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
    # T4.1 (2026-06-10) — Stock-Based Compensation, Crores.
    # Tolerantly populated when the cashflow ingestion carries an SBC
    # column (yfinance / NSE_XBRL); None when missing. Fed to
    # sbc_dilution_service.compute_sbc_adjustment in _build_year so
    # the response can carry sbc_adjusted_fcf + sbc_intensity_label
    # additively (reported free_cash_flow is unchanged).
    sbc_expense: float | None = None
    # T4 batch (2026-06-10) — accounting-normalization source columns.
    # All default None and are tolerantly populated when the underlying
    # ingestion gains the corresponding column. Until then the helper
    # paths in _build_year emit ``None`` adjusted-values + the
    # ``"unavailable"`` intensity label so the FE can suppress the chip
    # cleanly without crashing. Reported fields are byte-identical.
    #
    #   operating_lease_liabilities  (T4.2 IFRS-16) — Crores
    #   rd_expense                   (T4.3 R&D cap) — Crores
    #   contingent_liabilities       (T4.9 litigation) — Crores
    operating_lease_liabilities: float | None = None
    rd_expense: float | None = None
    contingent_liabilities: float | None = None
    # Market cap (Crores) — used by the T4.4 excess-cash helper to
    # express the adjusted EV. Populated by the caller in _build_year
    # only when readily available; defaults to None so the helper can
    # degrade gracefully.
    market_cap_cr: float | None = None
    # Bank format (Schedule III Division I — NSE/NSE_XBRL ingest only)
    # Added 2026-06-07 by fix/financials-source-priority. Banks
    # populate these instead of the GAAP gross_profit / ebit /
    # interest_expense triple. Surfaced in the API so the FE can
    # render bank-format rows when ready. See db_writer.py lines
    # 86-89 for the source-of-truth column list.
    interest_earned: float | None = None
    interest_expended: float | None = None
    total_income: float | None = None
    # Issue #204 (2026-06-07): non-interest income + operating expenses
    # for banks so the service layer can derive operating_income (Banks
    # don't carry a single "operating income" line in Schedule III Div I;
    # the standard derivation is
    #   op_income = (interest_earned - interest_expended)
    #             + non_interest_income - operating_expenses
    # See derive_bank_operating_income() below.)
    non_interest_income: float | None = None    # company_financials.other_income
    operating_expenses: float | None = None     # company_financials.operating_expense
    # Metadata
    roe: float | None = None
    debt_to_equity: float | None = None
    net_margin: float | None = None          # pct; only used for legacy compat


def derive_bank_operating_income(
    *,
    interest_earned: float | None,
    interest_expended: float | None,
    non_interest_income: float | None,
    operating_expenses: float | None,
    total_income: float | None = None,
) -> float | None:
    """Derive operating_income for a bank when the source row doesn't
    carry it directly.

    Schedule III Division I (RBI banking format) does not publish a
    single "operating income" line; the line is constructed from the
    parts. Two equivalent derivations exist:

      (A) op_income = NII + non_interest_income - operating_expenses
          where NII = interest_earned - interest_expended

      (B) op_income = total_income - interest_expended - operating_expenses
          (since total_income = interest_earned + non_interest_income
          for banks under Schedule III Div I)

    This helper applies (A) when the four interest / fee / expense
    fields are all populated, and falls back to (B) when
    non_interest_income is missing but total_income is present.
    Returns ``None`` if any required input is missing (callers should
    surface ``None`` rather than a partial / wrong figure).

    All inputs are in Crores (the DB unit). Output is in Crores.

    Issue #204.
    """
    ie = _safe_float(interest_earned)
    iex = _safe_float(interest_expended)
    nii_other = _safe_float(non_interest_income)
    op_exp = _safe_float(operating_expenses)
    tot = _safe_float(total_income)

    # Path A: NII + non-interest income - opex
    if ie is not None and iex is not None and nii_other is not None and op_exp is not None:
        return round((ie - iex) + nii_other - op_exp, 2)

    # Path B: total_income - interest_expended - opex
    # Useful when ingestion populates total_income but not the
    # interest_earned / non_interest_income split (some older rows).
    if tot is not None and iex is not None and op_exp is not None:
        return round(tot - iex - op_exp, 2)

    return None


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
               COALESCE(yf_interest_earned,    xbrl_interest_earned,    nse_interest_earned)    AS interest_earned,
               COALESCE(yf_interest_expended,  xbrl_interest_expended,  nse_interest_expended)  AS interest_expended,
               COALESCE(yf_total_income,       xbrl_total_income,       nse_total_income)       AS total_income,
               -- Issue #204: non-interest income + operating expenses for the
               -- bank operating_income derivation. ``other_income`` is the
               -- non-interest line for Schedule III Div I banks (fees +
               -- commission + treasury/exchange + misc); ``operating_expense``
               -- is the staff + premises + admin block.
               COALESCE(yf_other_income,       xbrl_other_income,       nse_other_income)       AS non_interest_income,
               COALESCE(yf_operating_expense,  xbrl_operating_expense,  nse_operating_expense)  AS operating_expenses
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
                   MAX(CASE WHEN source='nse'      THEN total_income      END) AS nse_total_income,
                   -- Issue #204: non-interest income (= other_income for banks)
                   -- and operating_expense (the staff/premises/admin block)
                   -- feed derive_bank_operating_income() at the service layer.
                   MAX(CASE WHEN source='yfinance' THEN other_income      END) AS yf_other_income,
                   MAX(CASE WHEN source='NSE_XBRL' THEN other_income      END) AS xbrl_other_income,
                   MAX(CASE WHEN source='nse'      THEN other_income      END) AS nse_other_income,
                   MAX(CASE WHEN source='yfinance' THEN operating_expense END) AS yf_operating_expense,
                   MAX(CASE WHEN source='NSE_XBRL' THEN operating_expense END) AS xbrl_operating_expense,
                   MAX(CASE WHEN source='nse'      THEN operating_expense END) AS nse_operating_expense
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
            # T4.1 — SBC expense. We don't currently project an SBC
            # column out of the cashflow query, so this defaults to
            # None for every DB-sourced row today. The lookup is
            # written tolerantly (``cf.get(...)`` falls back through
            # two common column names) so when the ingestion is
            # extended to carry SBC the wiring is already in place
            # and no further code change is needed here.
            sbc_expense=_safe_float(
                cf.get("stock_based_compensation")
                or cf.get("sbc")
            ),
            # Bank format (Schedule III Division I)
            interest_earned=_safe_float(inc.get("interest_earned")),
            interest_expended=_safe_float(inc.get("interest_expended")),
            total_income=_safe_float(inc.get("total_income")),
            # Issue #204 — bank operating_income inputs.
            non_interest_income=_safe_float(inc.get("non_interest_income")),
            operating_expenses=_safe_float(inc.get("operating_expenses")),
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
# T4.1 (2026-06-10) — SBC dilution adjustment helpers.
#
# The full Munger-style adjustment (forward dilution from issuance,
# intensity classification, sanity warnings) lives in
# ``backend/services/sbc_dilution_service`` and is unit-tested
# separately. Here we only need the two outputs that go onto the
# per-period response dict: an adjusted FCF figure and the coarse
# intensity bucket. Both return ``None`` when the SBC column is
# unavailable for the row so the FE can suppress the chip cleanly.
# ──────────────────────────────────────────────────────────────────────────
def _sbc_adjusted_fcf(row: _Row) -> float | None:
    """reported_fcf − sbc_expense, or None when either input missing."""
    if row.free_cash_flow is None or row.sbc_expense is None:
        return None
    try:
        return round(float(row.free_cash_flow) - float(row.sbc_expense), 2)
    except (TypeError, ValueError):
        return None


def _sbc_intensity_label(row: _Row) -> str | None:
    """Coarse intensity bucket for the SBC-vs-FCF ratio.

    Returns None when SBC is missing or reported FCF is non-positive
    (the ratio is undefined). This is the same gate as
    ``classify_sbc_intensity`` upstream, surfaced here so the
    financials reader doesn't need to import the full service for
    the common short-circuit.
    """
    if row.free_cash_flow is None or row.sbc_expense is None:
        return None
    try:
        fcf = float(row.free_cash_flow)
        sbc = float(row.sbc_expense)
    except (TypeError, ValueError):
        return None
    if fcf <= 0:
        return None
    from backend.services.sbc_dilution_service import classify_sbc_intensity
    pct = (sbc / fcf) * 100.0
    return classify_sbc_intensity(pct)


# ──────────────────────────────────────────────────────────────────────────
# T4 batch (2026-06-10) — accounting normalizations.
#
# Four additive normalizations land in this PR (the higher-impact subset
# of the originally-scoped nine; T4.5/T4.6/T4.7/T4.8/T4.10 are deferred
# to a follow-up PR to keep the diff reviewable and the canary impact
# bounded):
#
#   T4.2 IFRS-16 leases       — treat operating leases as debt-equivalent
#   T4.3 R&D capitalization   — capitalize R&D over a useful life
#   T4.4 Excess cash          — subtract cash above operating need from EV
#   T4.9 Litigation provisions — add disclosed contingent liabilities
#
# Each helper:
#   - Takes a _Row (and ticker, for sector-aware thresholds).
#   - Returns ``(adjusted_value: Optional[float], intensity_label: str)``.
#   - Intensity label is one of:
#       "negligible" | "moderate" | "material" | "heavy" | "unavailable"
#     where ``"unavailable"`` means the source column for this normalization
#     isn't populated for this row (the common case until ingestion is
#     extended). The FE suppresses the chip on "unavailable" the same way
#     it suppresses on a ``None`` adjusted value.
#   - Defensive: bad / non-finite / negative inputs route to ``"unavailable"``
#     plus ``None`` rather than raising.
#   - Sector-aware where applicable: R&D thresholds tighten for pharma /
#     IT / auto; excess cash tightens for IT services.
#
# Reported fields stay byte-identical. None of these helpers mutate
# ``free_cash_flow`` / ``total_debt`` / ``cash`` / etc. — they only
# add new keys to the per-period dict surfaced by ``_build_year``.
# ──────────────────────────────────────────────────────────────────────────

# Sector-tagged ticker sets — small curated lists used by the sector-
# tuned thresholds below. Keeping the data here (vs. importing from
# sector_overrides) avoids a cross-module dependency for what is a
# coarse hint; the lists can be tightened later without touching the
# adjustment math.
_PHARMA_TICKERS: frozenset[str] = frozenset({
    "SUNPHARMA", "DRREDDY", "CIPLA", "LUPIN", "AUROPHARMA", "DIVISLAB",
    "TORNTPHARM", "ZYDUSLIFE", "ALKEM", "BIOCON", "GLENMARK", "IPCALAB",
    "GLAND", "NATCOPHARM", "LAURUSLABS",
})
_IT_SERVICES_TICKERS: frozenset[str] = frozenset({
    "TCS", "INFY", "WIPRO", "HCLTECH", "TECHM", "LTIM", "MPHASIS",
    "PERSISTENT", "COFORGE", "LTTS", "BSOFT", "ZENSARTECH", "KPITTECH",
    "TATAELXSI", "INTELLECT", "HAPPSTMNDS",
})
_AUTO_TICKERS: frozenset[str] = frozenset({
    "MARUTI", "TATAMOTORS", "M&M", "BAJAJ-AUTO", "EICHERMOT", "HEROMOTOCO",
    "TVSMOTOR", "ASHOKLEY", "FORCEMOT", "ESCORTS",
})
_LEASE_HEAVY_TICKERS: frozenset[str] = frozenset({
    # Retail
    "DMART", "TRENT", "ABFRL", "VMART", "SHOPERSTOP", "ARVINDFASN",
    # Airlines
    "INDIGO", "SPICEJET",
    # Hotels
    "INDHOTEL", "EIHOTEL", "CHALET", "LEMONTREE", "MAHINDHEC",
    # Telecom (heavy site / tower lease commitments)
    "BHARTIARTL", "IDEA",
})
_LITIGATION_PRONE_TICKERS: frozenset[str] = frozenset({
    # Pharma — US class actions, FDA matters
    "SUNPHARMA", "DRREDDY", "CIPLA", "LUPIN", "AUROPHARMA",
    # Telecom — AGR overhang
    "BHARTIARTL", "IDEA",
    # IT services — immigration / wage class actions
    "TCS", "INFY", "WIPRO",
})


def _norm_ticker(ticker: str | None) -> str:
    """Bare uppercase ticker for membership tests; '' when None."""
    if not ticker:
        return ""
    return ticker.upper().strip().replace(".NS", "").replace(".BO", "")


# ── T4.2 IFRS-16 lease adjustment ────────────────────────────────────────
def _ifrs16_lease_adjustment(
    row: _Row,
    ticker: str | None,
) -> tuple[float | None, str]:
    """Treat operating leases as debt-equivalent.

    Adjusted EV proxy returned here is ``total_debt + operating_lease_liabilities``
    (Crores). For a stricter EV the caller would also subtract cash;
    keeping it as "debt + leases" matches how IFRS-16 effectively re-
    classifies the operating-lease obligation as a financial liability.

    Materiality (lease as a share of (debt + leases)):
        <  5 %  → "negligible"
        5–10 %  → "moderate"
        10–20 % → "material"
        > 20 %  → "heavy"

    Sectors heavy with leases: retail (DMART, TRENT), airlines
    (INDIGO, SPICEJET), hotels (INDHOTEL, EIHOTEL), telecom
    (BHARTIARTL). When the ticker is in ``_LEASE_HEAVY_TICKERS`` we
    promote a borderline "moderate" reading to "material" — leases for
    these names are usually understated by ingestion timing.

    Returns ``(None, "unavailable")`` whenever the lease liability
    column is not populated for this row (the common case as of
    2026-06-10 until ingestion is extended).
    """
    leases = _safe_float(row.operating_lease_liabilities)
    if leases is None or leases < 0:
        return (None, "unavailable")

    debt = _safe_float(row.total_debt) or 0.0
    if debt < 0:
        debt = 0.0

    adjusted_ev = round(debt + leases, 2)

    denom = debt + leases
    if denom <= 0:
        # No debt and no leases — surface a 0 adjusted EV with the
        # negligible label rather than dividing by zero.
        return (adjusted_ev, "negligible")

    pct = (leases / denom) * 100.0
    if pct < 5.0:
        label = "negligible"
    elif pct < 10.0:
        label = "moderate"
    elif pct < 20.0:
        label = "material"
    else:
        label = "heavy"

    # Sector promote: lease-heavy sectors get a one-bucket lift from
    # "moderate" to "material" because reported leases under IFRS-16
    # routinely understate the true commitment (residual values,
    # variable extensions). No promotion from "material" → "heavy" —
    # we'd rather under-warn than over-warn.
    if label == "moderate" and _norm_ticker(ticker) in _LEASE_HEAVY_TICKERS:
        label = "material"

    return (adjusted_ev, label)


# ── T4.3 R&D capitalization ──────────────────────────────────────────────
# Useful-life assumptions per the brief — these are the buckets where
# the academic literature (Lev / Sougiannis, Damodaran) cluster their
# estimates. 5y for pharma + auto; 3y for IT services (shorter product
# cycle); 4y default for unclassified tickers.
_RD_USEFUL_LIFE_YEARS: dict[str, int] = {
    "pharma": 5,
    "it": 3,
    "auto": 5,
    "default": 4,
}


def _rd_sector_bucket(ticker: str | None) -> str:
    t = _norm_ticker(ticker)
    if t in _PHARMA_TICKERS:
        return "pharma"
    if t in _IT_SERVICES_TICKERS:
        return "it"
    if t in _AUTO_TICKERS:
        return "auto"
    return "default"


def _capitalized_rd_adjustment(
    row: _Row,
    ticker: str | None,
) -> tuple[float | None, str]:
    """Capitalize R&D over a useful life vs. full expensing.

    Adjusted value = ``net_income + rd_expense * (1 - 1/useful_life)``
    (Crores). The intuition: instead of expensing R&D fully in year T,
    treat ``rd / useful_life`` as the "true" amortization charge for
    the period. The complement is added back to net income.

    Materiality (R&D as % of revenue):
        <  2 %  → "negligible"
        2–5 %  → "moderate"
        5–10 % → "material"
        > 10 % → "heavy"

    Sectors: pharma (5y life), IT services (3y life), auto (5y life).
    Material only meaningfully for these three sectors; for other
    sectors we still compute the adjustment when the input is present
    but bias the label down by one bucket.
    """
    rd = _safe_float(row.rd_expense)
    if rd is None or rd < 0:
        return (None, "unavailable")

    ni = _safe_float(row.pat)
    if ni is None:
        return (None, "unavailable")

    bucket = _rd_sector_bucket(ticker)
    life = _RD_USEFUL_LIFE_YEARS.get(bucket, _RD_USEFUL_LIFE_YEARS["default"])
    if life <= 0:
        return (None, "unavailable")

    # Capitalize: only ``rd/life`` is the period charge; the rest is
    # added back to net income (the cash already left the business in
    # this period, but accounting-economically only 1/life "belongs"
    # to this year).
    addback = rd * (1.0 - 1.0 / life)
    adjusted_ni = round(ni + addback, 2)

    revenue = _safe_float(row.revenue)
    if revenue is None or revenue <= 0:
        # Cannot bucket intensity without revenue; surface the number
        # but flag as unavailable for thresholding.
        return (adjusted_ni, "unavailable")

    pct = (rd / revenue) * 100.0
    if pct < 2.0:
        label = "negligible"
    elif pct < 5.0:
        label = "moderate"
    elif pct < 10.0:
        label = "material"
    else:
        label = "heavy"

    # Non-R&D-heavy sectors: bias one bucket down. Pharma / IT / auto
    # report on the raw threshold; everyone else gets a more
    # conservative read because their R&D series tends to be noisier
    # (one-off process improvements vs. structural research spend).
    if bucket == "default":
        downbias = {
            "heavy": "material",
            "material": "moderate",
            "moderate": "negligible",
            "negligible": "negligible",
        }
        label = downbias[label]

    return (adjusted_ni, label)


# ── T4.4 Excess cash adjustment ──────────────────────────────────────────
# Operating-cash need = 3 months of opex (industry-standard proxy).
# Anything above is "excess" and should be netted out of EV.
_EXCESS_CASH_OPEX_MONTHS: float = 3.0


def _excess_cash_adjustment(
    row: _Row,
    ticker: str | None,
) -> tuple[float | None, str]:
    """Net out cash above ~3 months of operating expenses from EV.

    Adjusted EV proxy = ``total_debt - excess_cash`` (Crores). The
    excess-cash leg = ``max(0, cash - operating_need)`` where the
    operating need is ``3/12 * operating_expenses`` (or, when
    operating_expenses is missing, ``3/12 * revenue * 0.7`` as a
    safety-margin proxy that approximates a 70 % opex/revenue ratio).

    Materiality (excess cash as % of revenue — using revenue as a
    proxy for "size" so the threshold is the same across sectors):
        <  2 %  → "negligible"
        2–5 %  → "moderate"
        5–15 % → "material"
        > 15 % → "heavy"

    Sectors heaviest: IT services (TCS, INFY ~Rs 50000Cr excess each).
    We tighten the threshold for IT services so that any positive
    excess of >= 2 % of revenue is already "material" — the cash pile
    on these names is structural, not transitory.
    """
    cash = _safe_float(row.cash_and_equivalents)
    if cash is None or cash < 0:
        return (None, "unavailable")

    opex = _safe_float(row.operating_expenses)
    revenue = _safe_float(row.revenue)

    # Operating need — 3 months of opex, with a revenue-based fallback.
    if opex is not None and opex > 0:
        operating_need = (_EXCESS_CASH_OPEX_MONTHS / 12.0) * opex
    elif revenue is not None and revenue > 0:
        operating_need = (_EXCESS_CASH_OPEX_MONTHS / 12.0) * revenue * 0.7
    else:
        # No reliable opex or revenue — cannot estimate the need;
        # surface raw cash as the "adjustment" with unavailable label.
        return (None, "unavailable")

    excess = max(0.0, cash - operating_need)

    debt = _safe_float(row.total_debt) or 0.0
    if debt < 0:
        debt = 0.0
    adjusted_ev = round(debt - excess, 2)

    # Sizing for intensity — prefer revenue as the denominator (size
    # proxy), fall back to market cap if we ever start populating it.
    size = revenue if revenue is not None and revenue > 0 else (
        _safe_float(row.market_cap_cr) or 0.0
    )
    if size <= 0:
        return (adjusted_ev, "unavailable")

    pct = (excess / size) * 100.0
    if pct < 2.0:
        label = "negligible"
    elif pct < 5.0:
        label = "moderate"
    elif pct < 15.0:
        label = "material"
    else:
        label = "heavy"

    # IT services tighten — for these names, the excess cash is
    # structural and well-documented, so we promote any positive
    # excess >= 2 % of revenue at least one bucket above the default.
    if _norm_ticker(ticker) in _IT_SERVICES_TICKERS and excess > 0:
        upbias = {
            "negligible": "negligible",  # below 2 % stays below noise
            "moderate": "material",
            "material": "heavy",
            "heavy": "heavy",
        }
        label = upbias[label]

    return (adjusted_ev, label)


# ── T4.9 Litigation provisions adjustment ────────────────────────────────
def _litigation_provisions_adjustment(
    row: _Row,
    ticker: str | None,
) -> tuple[float | None, str]:
    """Add disclosed contingent liabilities to debt.

    Adjusted debt = ``total_debt + contingent_liabilities`` (Crores).
    Contingent liabilities live in the annual-report notes ("notes to
    accounts — contingent liabilities not provided for") and capture
    disclosed-but-not-recognized exposures: US class actions for
    pharma, AGR dues for telecom, immigration / wage class actions
    for IT services, plus the long tail of disputed tax claims and
    bank guarantees.

    Materiality (contingent liabilities as % of equity):
        <  5 %  → "negligible"
        5–15 % → "moderate"
        15–30 %→ "material"
        > 30 % → "heavy"

    Sectors prone: pharma (SUNPHARMA, DRREDDY US class actions),
    telecom (BHARTIARTL AGR), IT (TCS / INFY immigration / wage).
    Litigation-prone tickers get a one-bucket promotion from
    "negligible" → "moderate" once a non-zero contingent is disclosed,
    because the disclosure threshold for these names tends to be
    higher than the recognition threshold (only large exposures hit
    the notes).
    """
    cont = _safe_float(row.contingent_liabilities)
    if cont is None or cont < 0:
        return (None, "unavailable")

    debt = _safe_float(row.total_debt) or 0.0
    if debt < 0:
        debt = 0.0
    adjusted_debt = round(debt + cont, 2)

    equity = _safe_float(row.total_equity)
    if equity is None or equity <= 0:
        # Cannot bucket intensity without equity; surface raw value
        # with unavailable label.
        return (adjusted_debt, "unavailable")

    pct = (cont / equity) * 100.0
    if pct < 5.0:
        label = "negligible"
    elif pct < 15.0:
        label = "moderate"
    elif pct < 30.0:
        label = "material"
    else:
        label = "heavy"

    if (cont > 0 and label == "negligible"
            and _norm_ticker(ticker) in _LITIGATION_PRONE_TICKERS):
        label = "moderate"

    return (adjusted_debt, label)


# ──────────────────────────────────────────────────────────────────────────
# Year builder (response shape)
# ──────────────────────────────────────────────────────────────────────────
def _build_year(row: _Row, prev: _Row | None,
                ticker: str | None = None) -> dict:
    rev_growth = _yoy_growth(row.revenue, prev.revenue) if prev else None
    pat_growth = _yoy_growth(row.pat, prev.pat) if prev else None

    # Issue #204 (2026-06-07) — bank operating_income derivation.
    # For commercial banks the source ``ebit`` column is almost
    # always NULL (Schedule III Div I doesn't carry a single
    # operating-income line). Derive it from the four bank inputs
    # and serve the derived value alongside the GAAP-style ``ebit``
    # for non-banks. Detection routes through the existing pure-bank
    # taxonomy (same gate used by the D/E bank fallback).
    operating_income_val = row.ebit
    if operating_income_val is None:
        try:
            from backend.services.analysis.sector_overrides import (
                is_pure_bank_for_de,
            )
        except Exception:  # pragma: no cover — defensive
            is_pure_bank_for_de = lambda _t: False  # noqa: E731
        if ticker is not None and is_pure_bank_for_de(ticker):
            operating_income_val = derive_bank_operating_income(
                interest_earned=row.interest_earned,
                interest_expended=row.interest_expended,
                non_interest_income=row.non_interest_income,
                operating_expenses=row.operating_expenses,
                total_income=row.total_income,
            )

    net_margin_pct = _pct(row.pat, row.revenue)
    gross_margin_pct = _pct(row.gross_profit, row.revenue)
    # Operating margin: use the derived operating_income for banks so
    # the margin populates instead of staying NULL.
    operating_margin_pct = _pct(operating_income_val, row.revenue)
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
        "operating_income": operating_income_val,
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

        # T4.1 (2026-06-10) — Munger-style SBC dilution adjustment.
        # Both fields are ADDITIVE: ``free_cash_flow`` above is the
        # reported GAAP figure and is intentionally unchanged so DCF
        # and every downstream consumer continue to read what they
        # always read (canary-safe). When the cashflow ingestion
        # doesn't carry an SBC column yet (the common case as of
        # 2026-06-10) both fields surface ``None`` rather than fake
        # zero numbers — that's how the FE knows to suppress the
        # SBC-adjustment chip for that ticker.
        "sbc_expense": row.sbc_expense,
        "sbc_adjusted_fcf": _sbc_adjusted_fcf(row),
        "sbc_intensity_label": _sbc_intensity_label(row),

        # T4 batch (2026-06-10) — 4 additional accounting normalizations
        # surfaced as additive per-period fields. Each pair is
        # (adjusted_value, intensity_label). Reported fields above are
        # byte-identical — the helpers only READ row data, never write.
        # Until the upstream ingestion populates the underlying source
        # columns (operating_lease_liabilities, rd_expense,
        # contingent_liabilities) the adjusted value is ``None`` and
        # the label is ``"unavailable"``, which the FE suppresses cleanly.
        # See helper docstrings for the materiality thresholds.
        **_t4_batch_period_keys(row, ticker),

        # Bank format (Schedule III Division I) — only populated for
        # banks; null for non-banks. Added 2026-06-07 by
        # fix/financials-source-priority. FE can ignore until ready.
        "interest_earned": row.interest_earned,
        "interest_expended": row.interest_expended,
        "total_income": row.total_income,
    }


def _t4_batch_period_keys(row: _Row, ticker: str | None) -> dict:
    """Build the 8 T4-batch per-period keys (4 normalizations x 2).

    Kept out-of-line so the ``_build_year`` return dict stays readable.
    Each pair is ``<name>_adjusted_value / <name>_intensity_label``.
    """
    ifrs16_val, ifrs16_label = _ifrs16_lease_adjustment(row, ticker)
    rd_val, rd_label = _capitalized_rd_adjustment(row, ticker)
    cash_val, cash_label = _excess_cash_adjustment(row, ticker)
    lit_val, lit_label = _litigation_provisions_adjustment(row, ticker)
    return {
        # T4.2 IFRS-16 lease adjustment
        "ifrs16_adjusted_ev": ifrs16_val,
        "ifrs16_intensity_label": ifrs16_label,
        # T4.3 R&D capitalization
        "rd_capitalized_value": rd_val,
        "rd_intensity_label": rd_label,
        # T4.4 Excess cash adjustment
        "excess_cash_subtracted": cash_val,
        "excess_cash_intensity_label": cash_label,
        # T4.9 Litigation provisions adjustment
        "litigation_adjusted_debt": lit_val,
        "litigation_intensity_label": lit_label,
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
            # Issue #204: pass ticker so _build_year can route to the
            # bank operating_income derivation when the GAAP ebit line
            # is null (Schedule III Div I banks).
            years_data.append(_build_year(r, prev, ticker=db_ticker))

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
