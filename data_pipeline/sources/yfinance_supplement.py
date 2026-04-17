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

        # Store market metrics — upsert to avoid unique constraint violations
        today = date.today()
        existing_metric = db.query(MarketMetrics).filter_by(
            ticker=ticker, trade_date=today
        ).first()
        # yfinance now returns dividendYield as a percentage (e.g. 4.8).
        # Guard against an accidental double-multiplication (e.g. 480)
        # by dividing values > 50 back down. Matches the defensive
        # pattern used in backend/services/dividend_service.py.
        _raw_yield = info.get("dividendYield") or 0
        _dividend_yield = _raw_yield if _raw_yield <= 50 else _raw_yield / 100

        if existing_metric:
            existing_metric.market_cap_cr = _to_cr(info.get("marketCap"))
            existing_metric.pe_ratio = info.get("trailingPE")
            existing_metric.pb_ratio = info.get("priceToBook")
            existing_metric.dividend_yield = _dividend_yield
            existing_metric.beta_1yr = info.get("beta")
            existing_metric.ev_cr = _to_cr(info.get("enterpriseValue"))
        else:
            db.add(MarketMetrics(
                ticker=ticker,
                trade_date=today,
                market_cap_cr=_to_cr(info.get("marketCap")),
                pe_ratio=info.get("trailingPE"),
                pb_ratio=info.get("priceToBook"),
                dividend_yield=_dividend_yield,
                beta_1yr=info.get("beta"),
                ev_cr=_to_cr(info.get("enterpriseValue")),
            ))

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
                            # yfinance normalises all `.NS` / `.BO` financials
                            # to INR regardless of how the issuer files, so
                            # we always tag INR here.
                            currency="INR",
                        )

                        if revenue and revenue > 0:
                            existing_fin = db.query(Financials).filter_by(
                                ticker=ticker, period_end=period_date, period_type="annual"
                            ).first()
                            if existing_fin:
                                for attr in ["revenue", "pat", "ebitda", "cfo", "capex",
                                             "free_cash_flow", "total_debt", "cash_and_equivalents",
                                             "total_equity", "total_assets", "shares_outstanding",
                                             "roe", "roa", "net_margin"]:
                                    val = getattr(fin, attr, None)
                                    if val is not None:
                                        setattr(existing_fin, attr, val)
                            else:
                                db.add(fin)
                    except Exception:
                        continue
        except Exception as e:
            logger.warning(f"Financial statements failed for {ticker}: {e}")

        db.commit()
        return True

    except Exception as e:
        logger.error(f"yfinance fetch failed for {ticker_ns}: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return False


def fetch_price_history(ticker_ns: str, ticker: str, db: Session,
                        period: str = "3y") -> int:
    """
    Download price history from yfinance and store in daily_prices.
    Uses Ticker.history() which worked for the first 50 stocks.
    """
    try:
        stock = yf.Ticker(ticker_ns)

        # Try auto_adjust=True first (newer yfinance), fall back to False
        df = None
        for auto_adj in [True, False]:
            try:
                df = stock.history(period=period, auto_adjust=auto_adj)
                if df is not None and not df.empty:
                    break
            except Exception:
                continue

        if df is None or df.empty:
            logger.warning(f"No price history for {ticker_ns}")
            return 0

        logger.info(f"{ticker}: got {len(df)} rows, columns={list(df.columns)}")

        stored = 0
        for idx, row in df.iterrows():
            try:
                trade_date = idx.date() if hasattr(idx, "date") else idx

                # Try multiple column name variants
                close = _safe_float(
                    row.get("Close") or row.get("Adj Close") or row.get("close")
                )
                if close is None or close <= 0:
                    continue

                existing = db.query(DailyPrice).filter_by(
                    ticker=ticker, trade_date=trade_date,
                ).first()
                if existing:
                    continue

                price = DailyPrice(
                    ticker=ticker,
                    trade_date=trade_date,
                    open_price=_safe_float(row.get("Open") or row.get("open")),
                    high_price=_safe_float(row.get("High") or row.get("high")),
                    low_price=_safe_float(row.get("Low") or row.get("low")),
                    close_price=close,
                    volume=int(row.get("Volume") or row.get("volume") or 0),
                    adj_close=close,
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
    Resilient: retries on failure, skips already-loaded stocks,
    saves progress every 10 stocks.
    """
    success = 0
    total_records = 0

    # Skip tickers that already have price data
    tickers_to_fetch = []
    for ticker in tickers:
        existing = db.query(DailyPrice).filter_by(ticker=ticker).first()
        if existing:
            success += 1
            logger.info(f"Skipping {ticker} — already has price data")
        else:
            tickers_to_fetch.append(ticker)

    logger.info(f"Prices: {len(tickers_to_fetch)} to fetch, {success} already loaded")

    for i, ticker in enumerate(tickers_to_fetch):
        ticker_ns = f"{ticker}.NS"
        try:
            records = fetch_price_history(ticker_ns, ticker, db, period)
            if records > 0:
                success += 1
                total_records += records
                logger.info(f"[{i+1}/{len(tickers_to_fetch)}] {ticker}: {records} price records")
            else:
                logger.warning(f"[{i+1}/{len(tickers_to_fetch)}] {ticker}: no price data")
        except Exception as e:
            logger.error(f"[{i+1}/{len(tickers_to_fetch)}] {ticker} FAILED: {e}")
            # On rate limit, wait longer then retry once
            if "Too Many Requests" in str(e) or "429" in str(e):
                logger.info("Rate limited — waiting 30s before retry")
                time.sleep(30)
                try:
                    records = fetch_price_history(ticker_ns, ticker, db, period)
                    if records > 0:
                        success += 1
                        total_records += records
                except Exception:
                    pass

        # Rate limit — 2s between calls to avoid yfinance blocking
        time.sleep(2)

        # Save progress every 10 stocks
        if (i + 1) % 10 == 0:
            _update_freshness(db, "prices_yfinance", total_records, "in_progress")
            logger.info(f"Progress: {i+1}/{len(tickers_to_fetch)} stocks, {total_records} total records")

    _update_freshness(db, "prices_yfinance", total_records, "success")
    logger.info(f"Batch prices: {success}/{len(tickers)} stocks, {total_records} records")
    return success, total_records


def batch_fetch_fundamentals(tickers: list[str], db: Session) -> tuple[int, int]:
    """
    Download fundamentals for a batch of tickers.
    Resilient: retries on rate limit, saves progress.
    """
    success = 0
    failed = 0

    for i, ticker in enumerate(tickers):
        ticker_ns = f"{ticker}.NS"
        try:
            ok = fetch_and_store_yfinance(ticker_ns, ticker, db)
            if ok:
                success += 1
            else:
                failed += 1
        except Exception as e:
            logger.error(f"Fundamentals failed for {ticker}: {e}")
            failed += 1
            if "Too Many Requests" in str(e) or "429" in str(e):
                logger.info("Rate limited — waiting 30s")
                time.sleep(30)

        # Rate limit — 1s between calls
        time.sleep(1)

        if (i + 1) % 10 == 0:
            _update_freshness(db, "fundamentals_yfinance", success, "in_progress")
            logger.info(f"Fundamentals progress: {i+1}/{len(tickers)} ({success} ok, {failed} failed)")

    _update_freshness(db, "fundamentals_yfinance", success, "success")
    logger.info(f"Batch fundamentals: {success} ok, {failed} failed out of {len(tickers)}")
    return success, failed


def _update_freshness(db: Session, data_type: str, count: int, status: str):
    """Update DataFreshness tracker (called periodically during batch)."""
    try:
        freshness = db.query(DataFreshness).filter_by(data_type=data_type).first()
        if not freshness:
            freshness = DataFreshness(data_type=data_type)
            db.add(freshness)
        freshness.last_updated = datetime.utcnow()
        freshness.records_updated = count
        freshness.status = status
        db.commit()
    except Exception as e:
        logger.warning(f"Freshness update failed: {e}")


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
