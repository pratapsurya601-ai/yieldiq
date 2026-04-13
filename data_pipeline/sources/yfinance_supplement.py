# data_pipeline/sources/yfinance_supplement.py
# PRIMARY data source — yfinance works from Railway (NSE/BSE block cloud IPs).
# Downloads: prices (3yr history), financials, market metrics, beta.
from __future__ import annotations

import logging
import time
from datetime import date, datetime, timedelta

import pandas as pd
import yfinance as yf
from sqlalchemy.orm import Session

from data_pipeline.models import DailyPrice, DataFreshness, Financials, MarketMetrics

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
                        ebitda = _get_val(inc, "EBITDA", col) if inc is not None else None
                        total_equity = _get_val(bs, "Total Equity Gross Minority Interest", col) if bs is not None else None
                        total_assets = _get_val(bs, "Total Assets", col) if bs is not None else None

                        fin = Financials(
                            ticker=ticker,
                            period_end=period_date,
                            period_type="annual",
                            revenue=_to_cr(revenue),
                            pat=_to_cr(pat),
                            ebitda=_to_cr(ebitda),
                            cfo=_to_cr(cfo),
                            capex=_to_cr(capex),
                            free_cash_flow=_to_cr(fcf),
                            total_debt=_to_cr(
                                _get_val(bs, "Total Debt", col) if bs is not None else None
                            ),
                            cash_and_equivalents=_to_cr(
                                _get_val(bs, "Cash And Cash Equivalents", col) if bs is not None else None
                            ),
                            total_equity=_to_cr(total_equity),
                            total_assets=_to_cr(total_assets),
                            shares_outstanding=_to_lakhs(
                                info.get("sharesOutstanding")
                            ),
                            roe=(_safe_pct(pat, total_equity)) if pat and total_equity else None,
                            roa=(_safe_pct(pat, total_assets)) if pat and total_assets else None,
                            net_margin=(_safe_pct(pat, revenue)) if pat and revenue else None,
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


def fetch_price_history(ticker_ns: str, ticker: str, db: Session,
                        period: str = "3y") -> int:
    """
    Download price history from yfinance and store in daily_prices.
    period: "3y" for 3 years, "1y", "5y", "max"
    Returns count of records stored.
    """
    try:
        stock = yf.Ticker(ticker_ns)
        df = stock.history(period=period, auto_adjust=False)

        if df is None or df.empty:
            logger.warning(f"No price history for {ticker_ns}")
            return 0

        stored = 0
        for idx, row in df.iterrows():
            try:
                trade_date = idx.date() if hasattr(idx, "date") else idx

                # Skip if already exists
                existing = db.query(DailyPrice).filter_by(
                    ticker=ticker, trade_date=trade_date,
                ).first()
                if existing:
                    continue

                price = DailyPrice(
                    ticker=ticker,
                    trade_date=trade_date,
                    open_price=_safe_float(row.get("Open")),
                    high_price=_safe_float(row.get("High")),
                    low_price=_safe_float(row.get("Low")),
                    close_price=_safe_float(row.get("Close")),
                    volume=int(row.get("Volume", 0) or 0),
                    adj_close=_safe_float(row.get("Adj Close") or row.get("Close")),
                )
                db.add(price)
                stored += 1
            except Exception:
                continue

        db.commit()
        return stored

    except Exception as e:
        logger.error(f"Price history failed for {ticker_ns}: {e}")
        return 0


def batch_fetch_prices(tickers: list[str], db: Session,
                       period: str = "3y") -> tuple[int, int]:
    """
    Download price history for a batch of tickers.
    Returns (success_count, total_records).
    """
    success = 0
    total_records = 0

    for i, ticker in enumerate(tickers):
        ticker_ns = f"{ticker}.NS"
        records = fetch_price_history(ticker_ns, ticker, db, period)
        if records > 0:
            success += 1
            total_records += records
            logger.info(f"[{i+1}/{len(tickers)}] {ticker}: {records} price records")
        else:
            logger.warning(f"[{i+1}/{len(tickers)}] {ticker}: no price data")

        # Rate limit — 0.5s between calls
        time.sleep(0.5)

        # Commit every 10 stocks to avoid huge transactions
        if (i + 1) % 10 == 0:
            db.commit()
            logger.info(f"Progress: {i+1}/{len(tickers)} stocks, {total_records} total records")

    db.commit()

    # Update freshness
    freshness = db.query(DataFreshness).filter_by(data_type="prices_yfinance").first()
    if not freshness:
        freshness = DataFreshness(data_type="prices_yfinance")
        db.add(freshness)
    freshness.last_updated = datetime.utcnow()
    freshness.records_updated = total_records
    freshness.status = "success"
    db.commit()

    logger.info(f"Batch prices: {success}/{len(tickers)} stocks, {total_records} records")
    return success, total_records


def batch_fetch_fundamentals(tickers: list[str], db: Session) -> tuple[int, int]:
    """
    Download fundamentals for a batch of tickers.
    Returns (success_count, failed_count).
    """
    success = 0
    failed = 0

    for i, ticker in enumerate(tickers):
        ticker_ns = f"{ticker}.NS"
        ok = fetch_and_store_yfinance(ticker_ns, ticker, db)
        if ok:
            success += 1
        else:
            failed += 1

        # Rate limit
        time.sleep(0.5)

        if (i + 1) % 10 == 0:
            logger.info(f"Fundamentals progress: {i+1}/{len(tickers)} ({success} ok, {failed} failed)")

    # Update freshness
    freshness = db.query(DataFreshness).filter_by(data_type="fundamentals_yfinance").first()
    if not freshness:
        freshness = DataFreshness(data_type="fundamentals_yfinance")
        db.add(freshness)
    freshness.last_updated = datetime.utcnow()
    freshness.records_updated = success
    freshness.status = "success"
    db.commit()

    logger.info(f"Batch fundamentals: {success} ok, {failed} failed out of {len(tickers)}")
    return success, failed


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


def _safe_float(value) -> float | None:
    try:
        if value is None or pd.isna(value):
            return None
        return float(value)
    except Exception:
        return None


def _safe_pct(numerator, denominator) -> float | None:
    try:
        if numerator and denominator and denominator != 0:
            return (numerator / denominator) * 100
        return None
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
