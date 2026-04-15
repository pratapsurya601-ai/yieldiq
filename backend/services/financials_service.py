# backend/services/financials_service.py
"""
Financial statements service for the analysis page.

Returns 5 years of annual data (or 8 quarters) from the
local ``financials`` table. Falls back to yfinance for
annual data only — quarterly has no fallback.

Units: monetary values are stored in Crores in the DB
(see data_pipeline.sources.yfinance_supplement._to_cr).
shares_outstanding is stored in Lakhs.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from datetime import date
from typing import Any

logger = logging.getLogger("yieldiq.financials")


def _get_pipeline_session():
    """Mirror analysis_service._get_pipeline_session."""
    try:
        from data_pipeline.db import Session as PipelineSession
        if PipelineSession is not None:
            return PipelineSession()
    except Exception:
        pass
    return None


def _format_period(period_end: date | None, period_type: str) -> str:
    """
    Indian financial year convention.
    annual:    "FY2025"  (for period_end in Mar 2025 → FY2025)
    quarterly: "Q3FY25"
    """
    if not period_end:
        return "Unknown"
    year = period_end.year
    month = period_end.month
    # Indian FY runs Apr–Mar. A March-ending period belongs to FY of that year.
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


@dataclass
class _Row:
    """Lightweight row used by both DB path and yfinance fallback."""
    period_end: date | None
    period_type: str
    revenue: float | None = None
    pat: float | None = None
    ebitda: float | None = None
    eps_diluted: float | None = None
    net_margin: float | None = None           # stored as pct (e.g. 27.3) in DB
    cfo: float | None = None
    capex: float | None = None
    free_cash_flow: float | None = None
    total_assets: float | None = None
    total_equity: float | None = None
    total_debt: float | None = None
    cash_and_equivalents: float | None = None
    debt_to_equity: float | None = None
    shares_outstanding: float | None = None   # Lakhs
    roe: float | None = None

    @classmethod
    def from_orm(cls, obj) -> "_Row":
        return cls(
            period_end=obj.period_end,
            period_type=obj.period_type,
            revenue=_safe_float(obj.revenue),
            pat=_safe_float(obj.pat),
            ebitda=_safe_float(obj.ebitda),
            eps_diluted=_safe_float(obj.eps_diluted),
            net_margin=_safe_float(obj.net_margin),
            cfo=_safe_float(obj.cfo),
            capex=_safe_float(obj.capex),
            free_cash_flow=_safe_float(obj.free_cash_flow),
            total_assets=_safe_float(obj.total_assets),
            total_equity=_safe_float(obj.total_equity),
            total_debt=_safe_float(obj.total_debt),
            cash_and_equivalents=_safe_float(obj.cash_and_equivalents),
            debt_to_equity=_safe_float(obj.debt_to_equity),
            shares_outstanding=_safe_float(obj.shares_outstanding),
            roe=_safe_float(obj.roe),
        )


def _book_value_per_share(equity_cr: float | None,
                          shares_lakhs: float | None) -> float | None:
    """
    equity is stored in Crores (1 Cr = 10^7 rupees).
    shares_outstanding is stored in Lakhs (1 L = 10^5 shares).
    BVPS (₹ per share) = (equity * 10^7) / (shares * 10^5)
                       = equity / shares * 100
    """
    e = _safe_float(equity_cr)
    s = _safe_float(shares_lakhs)
    if e is None or s is None or s == 0:
        return None
    return round(e / s * 100, 2)


def _build_year(row: _Row, prev: _Row | None) -> dict:
    rev_growth = _yoy_growth(row.revenue, prev.revenue) if prev else None
    pat_growth = _yoy_growth(row.pat, prev.pat) if prev else None

    # net_margin in DB is already a percentage (not a 0–1 ratio);
    # if it looks like a ratio (abs < 1) treat it as ratio for safety.
    net_margin_pct: float | None = None
    if row.net_margin is not None:
        nm = row.net_margin
        net_margin_pct = round(nm * 100, 1) if abs(nm) <= 1 else round(nm, 1)

    fcf_margin_pct = _pct(row.free_cash_flow, row.revenue)

    de = row.debt_to_equity
    if de is None and row.total_debt is not None and row.total_equity:
        de = round(row.total_debt / row.total_equity, 2) if row.total_equity else None

    net_debt = None
    if row.total_debt is not None or row.cash_and_equivalents is not None:
        net_debt = round(
            (row.total_debt or 0) - (row.cash_and_equivalents or 0), 2
        )

    return {
        "year": _format_period(row.period_end, row.period_type),
        "period_end": row.period_end.isoformat() if row.period_end else None,

        # Income Statement
        "revenue": row.revenue,
        "revenue_growth_pct": rev_growth,
        "gross_profit": None,
        "gross_margin_pct": None,
        "ebitda": row.ebitda,
        "operating_income": None,
        "operating_margin_pct": None,
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


def _yfinance_fallback(ticker_ns: str, years: int) -> list[_Row]:
    """Annual-only fallback. Returns rows newest→oldest."""
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

    TO_CR = 1e7  # rupees → crores (approximation for USD too; UI shows currency)
    rows: list[_Row] = []
    for col in list(inc.columns)[:years]:
        try:
            pend = col.date() if hasattr(col, "date") else None
            revenue = _getv(inc, "Total Revenue", col)
            pat = _getv(inc, "Net Income", col)
            ebitda = _getv(inc, "EBITDA", col)
            eps_d = _getv(inc, "Diluted EPS", col)
            cfo = _getv(cf, "Operating Cash Flow", col)
            capex = _getv(cf, "Capital Expenditure", col)
            fcf = None
            if cfo is not None and capex is not None:
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
                pat=pat / TO_CR if pat else None,
                ebitda=ebitda / TO_CR if ebitda else None,
                eps_diluted=eps_d,  # EPS is per-share, no unit conversion
                net_margin=(pat / revenue * 100) if (pat and revenue) else None,
                cfo=cfo / TO_CR if cfo else None,
                capex=capex / TO_CR if capex else None,
                free_cash_flow=fcf / TO_CR if fcf else None,
                total_assets=total_assets / TO_CR if total_assets else None,
                total_equity=total_equity / TO_CR if total_equity else None,
                total_debt=total_debt / TO_CR if total_debt else None,
                cash_and_equivalents=cash / TO_CR if cash else None,
                shares_outstanding=(shares / 1e5) if shares else None,  # raw → Lakhs
            ))
        except Exception:
            continue
    return rows


def _compute_summary(years_data: list[dict]) -> dict:
    """Revenue CAGR over up-to-3-years, avg margins, latest ROE."""
    revenue_cagr_3y: float | None = None
    usable = [d for d in years_data if d.get("revenue") is not None]
    if len(usable) >= 2:
        latest = usable[0]["revenue"]
        oldest_idx = min(3, len(usable) - 1)   # 3-year span max
        oldest = usable[oldest_idx]["revenue"]
        n = oldest_idx
        if latest and oldest and oldest > 0 and n > 0:
            try:
                revenue_cagr_3y = round(
                    ((latest / oldest) ** (1 / n) - 1) * 100, 1
                )
            except (ValueError, ZeroDivisionError):
                revenue_cagr_3y = None

    def _avg(field: str) -> float | None:
        vals = [d[field] for d in years_data if d.get(field) is not None]
        if not vals:
            return None
        return round(sum(vals) / len(vals), 1)

    return {
        "revenue_cagr_3y": revenue_cagr_3y,
        "avg_net_margin": _avg("net_margin_pct"),
        "avg_fcf_margin": _avg("fcf_margin_pct"),
        "latest_roe": None,  # populated below from raw rows if available
    }


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

        db = _get_pipeline_session()
        if db is not None:
            try:
                from data_pipeline.models import Financials
                db_ticker = ticker.replace(".NS", "").replace(".BO", "")
                orm_rows = (
                    db.query(Financials)
                    .filter(
                        Financials.ticker == db_ticker,
                        Financials.period_type == period,
                    )
                    .order_by(Financials.period_end.desc())
                    .limit(limit)
                    .all()
                )
                rows = [_Row.from_orm(r) for r in orm_rows]
            except Exception as exc:
                logger.warning("DB query failed for %s: %s", ticker, exc)
            finally:
                try:
                    db.close()
                except Exception:
                    pass

        # Fallback — annual only, when DB has < 2 rows
        if period == "annual" and len(rows) < 2:
            fallback = _yfinance_fallback(ticker, limit)
            if len(fallback) > len(rows):
                rows = fallback
                data_source = "yfinance_fallback"

        # Quarterly: no fallback — return empty with graceful flag
        has_quarterly_any = self._has_quarterly_rows(ticker)

        years_data: list[dict] = []
        # rows are newest→oldest; for YoY we need the prior year's data,
        # which is the NEXT index in a desc-ordered list.
        for i, r in enumerate(rows):
            prev = rows[i + 1] if i + 1 < len(rows) else None
            years_data.append(_build_year(r, prev))

        summary = _compute_summary(years_data)
        # Latest ROE — pull off the newest row if available
        if rows and rows[0].roe is not None:
            roe = rows[0].roe
            # DB stores roe as a percentage already (see bse_xbrl.py line 414).
            # If it looks like a ratio, scale up.
            summary["latest_roe"] = round(
                roe if abs(roe) > 1 else roe * 100, 1
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

    def _has_quarterly_rows(self, ticker: str) -> bool:
        """Cheap existence check for UI's 'Quarterly' toggle gating."""
        db = _get_pipeline_session()
        if db is None:
            return False
        try:
            from data_pipeline.models import Financials
            db_ticker = ticker.replace(".NS", "").replace(".BO", "")
            return db.query(Financials).filter(
                Financials.ticker == db_ticker,
                Financials.period_type == "quarterly",
            ).first() is not None
        except Exception:
            return False
        finally:
            try:
                db.close()
            except Exception:
                pass
