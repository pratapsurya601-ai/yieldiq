# data_pipeline/sources/yfinance_supplement.py
# yfinance fills fundamental data gaps that BSE API misses.
# Used as supplementary source — BSE XBRL is primary.
from __future__ import annotations

import logging
from datetime import date

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session

from data_pipeline.models import Financials, MarketMetrics

logger = logging.getLogger(__name__)


def fetch_and_store_yfinance(ticker_ns: str, ticker: str, db: Session) -> bool:
    """
    Fetch comprehensive financial data from yfinance for one stock.
    ticker_ns: e.g. "RELIANCE.NS"
    ticker: e.g. "RELIANCE"
    """
    try:
        stock = yf.Ticker(ticker_ns)
        info = stock.info

        if not info or info.get("regularMarketPrice") is None:
            logger.warning(f"No yfinance data for {ticker_ns}")
            return False

        # Store market metrics
        metrics = MarketMetrics(
            ticker=ticker,
            trade_date=date.today(),
            market_cap_cr=_to_cr(info.get("marketCap")),
            pe_ratio=info.get("trailingPE"),
            pb_ratio=info.get("priceToBook"),
            dividend_yield=(info.get("dividendYield") or 0) * 100,
            beta_1yr=info.get("beta"),
            ev_cr=_to_cr(info.get("enterpriseValue")),
        )
        db.merge(metrics)

        # Get financial statements
        try:
            cf = stock.cashflow
            bs = stock.balance_sheet
            inc = stock.income_stmt

            if cf is not None and not cf.empty:
                for col in cf.columns[:5]:
                    try:
                        period_date = col.date() if hasattr(col, "date") else col

                        cfo = _get_val(cf, "Operating Cash Flow", col)
                        capex = _get_val(cf, "Capital Expenditure", col)
                        fcf = (cfo - abs(capex)) if cfo and capex else None
                        revenue = _get_val(inc, "Total Revenue", col) if inc is not None else None
                        pat = _get_val(inc, "Net Income", col) if inc is not None else None

                        fin = Financials(
                            ticker=ticker,
                            period_end=period_date,
                            period_type="annual",
                            revenue=_to_cr(revenue),
                            pat=_to_cr(pat),
                            cfo=_to_cr(cfo),
                            capex=_to_cr(capex),
                            free_cash_flow=_to_cr(fcf),
                            total_debt=_to_cr(
                                _get_val(bs, "Total Debt", col) if bs is not None else None
                            ),
                            cash_and_equivalents=_to_cr(
                                _get_val(bs, "Cash And Cash Equivalents", col) if bs is not None else None
                            ),
                            shares_outstanding=_to_lakhs(
                                info.get("sharesOutstanding")
                            ),
                            data_source="yfinance",
                        )

                        if revenue and revenue > 0:
                            db.merge(fin)
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"Financial statements failed for {ticker}: {e}")

        db.commit()
        return True

    except Exception as e:
        logger.error(f"yfinance fetch failed for {ticker_ns}: {e}")
        return False


def _to_cr(value) -> float | None:
    """Convert from raw rupees to Crore."""
    try:
        if value is None:
            return None
        return float(value) / 1e7
    except Exception:
        return None


def _to_lakhs(value) -> float | None:
    try:
        if value is None:
            return None
        return float(value) / 1e5
    except Exception:
        return None


def _get_val(df: pd.DataFrame, row_name: str, col):
    try:
        if row_name in df.index:
            val = df.loc[row_name, col]
            return float(val) if val is not None and not pd.isna(val) else None
        return None
    except Exception:
        return None
