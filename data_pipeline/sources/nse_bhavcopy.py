# data_pipeline/sources/nse_bhavcopy.py
# Downloads official NSE Bhavcopy CSV files (daily OHLCV + delivery).
# Uses curl_cffi to impersonate Chrome (NSE blocks plain requests).
# URL format: sec_bhavdata_full_DDMMYYYY.csv (new NSE format)
from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy.orm import Session

from data_pipeline.models import CorporateAction, DailyPrice, DataFreshness

logger = logging.getLogger(__name__)

# New NSE Bhavcopy URL format (sec_bhavdata_full)
BHAVCOPY_URL = (
    "https://nsearchives.nseindia.com/products/content/"
    "sec_bhavdata_full_{date}.csv"
)

NSE_BASE = "https://www.nseindia.com"


def _get_nse_session():
    """Create a curl_cffi session with Chrome impersonation for NSE."""
    from curl_cffi import requests as cffi_requests
    session = cffi_requests.Session(impersonate="chrome")
    # Get session cookies from NSE homepage first
    session.get(NSE_BASE, timeout=10)
    return session


def download_bhavcopy(trade_date: date, session=None) -> pd.DataFrame | None:
    """Download and parse NSE Bhavcopy for a specific date."""
    date_str = trade_date.strftime("%d%m%Y")
    url = BHAVCOPY_URL.format(date=date_str)

    try:
        if session is None:
            session = _get_nse_session()

        response = session.get(url, timeout=30)
        if response.status_code == 404:
            logger.info(f"No bhavcopy for {trade_date} (holiday/weekend)")
            return None
        if response.status_code != 200:
            logger.warning(f"Bhavcopy {trade_date}: HTTP {response.status_code}")
            return None

        if len(response.content) < 500:
            logger.info(f"No bhavcopy for {trade_date} (empty response)")
            return None

        df = pd.read_csv(io.StringIO(response.text))
        return _clean_bhavcopy(df, trade_date)

    except Exception as e:
        logger.error(f"Failed to download bhavcopy for {trade_date}: {e}")
        return None


def _clean_bhavcopy(df: pd.DataFrame, trade_date: date) -> pd.DataFrame:
    """Clean and standardise bhavcopy columns."""
    df.columns = df.columns.str.strip().str.upper()

    # Keep only EQ series (regular equity) — NSE has space prefix
    series_col = df.columns[df.columns.str.contains("SERIES", case=False)].tolist()
    if series_col:
        df[series_col[0]] = df[series_col[0]].str.strip()
        df = df[df[series_col[0]] == "EQ"].copy()

    # Map columns to our schema
    col_map = {
        "SYMBOL": "ticker",
        "OPEN_PRICE": "open_price",
        "HIGH_PRICE": "high_price",
        "LOW_PRICE": "low_price",
        "CLOSE_PRICE": "close_price",
        "PREV_CLOSE": "prev_close",
        "TTL_TRD_QNTY": "volume",
        "TURNOVER_LACS": "turnover_cr",
        "NO_OF_TRADES": "trades",
        "DELIV_QTY": "delivery_qty",
        "DELIV_PER": "delivery_pct",
        "AVG_PRICE": "vwap",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    df["trade_date"] = trade_date

    # Convert turnover from Lakhs to Crore
    if "turnover_cr" in df.columns:
        df["turnover_cr"] = pd.to_numeric(df["turnover_cr"], errors="coerce") / 100

    return df


def store_bhavcopy(df: pd.DataFrame, db: Session) -> int:
    """Store cleaned bhavcopy data into daily_prices table."""
    from data_pipeline.models import Stock

    # Get set of known tickers — auto-add new ones from Bhavcopy
    known_tickers = {r[0] for r in db.query(Stock.ticker).all()}

    # Add any new tickers from Bhavcopy to stocks table
    new_tickers = set(df["ticker"].unique()) - known_tickers
    if new_tickers:
        for t in new_tickers:
            stock = Stock(ticker=t, ticker_ns=f"{t}.NS", is_active=True)
            db.merge(stock)
        db.commit()
        known_tickers.update(new_tickers)
        logger.info(f"Auto-added {len(new_tickers)} new stocks from Bhavcopy")

    # Build insert DataFrame with our column names
    insert_df = pd.DataFrame({
        "ticker": df["ticker"],
        "trade_date": df["trade_date"],
        "open_price": df.get("open_price").apply(_safe_float) if "open_price" in df.columns else None,
        "high_price": df.get("high_price").apply(_safe_float) if "high_price" in df.columns else None,
        "low_price": df.get("low_price").apply(_safe_float) if "low_price" in df.columns else None,
        "close_price": df.get("close_price").apply(_safe_float) if "close_price" in df.columns else None,
        "prev_close": df.get("prev_close").apply(_safe_float) if "prev_close" in df.columns else None,
        "volume": df.get("volume", 0).fillna(0).astype(int),
        "turnover_cr": df.get("turnover_cr").apply(_safe_float) if "turnover_cr" in df.columns else None,
        "delivery_qty": df.get("delivery_qty", 0).fillna(0).astype(int) if "delivery_qty" in df.columns else 0,
        "delivery_pct": df.get("delivery_pct").apply(_safe_float) if "delivery_pct" in df.columns else None,
        "trades": df.get("trades", 0).fillna(0).astype(int) if "trades" in df.columns else 0,
        "vwap": df.get("vwap").apply(_safe_float) if "vwap" in df.columns else None,
        "adj_close": df.get("close_price").apply(_safe_float) if "close_price" in df.columns else None,
    })

    # Use pandas to_sql with raw engine connection — fast bulk insert
    from sqlalchemy import text
    engine = db.get_bind()

    try:
        # Write to temp table, then upsert
        insert_df.to_sql("_bhavcopy_staging", engine, if_exists="replace", index=False)
        with engine.begin() as conn:
            result = conn.execute(text("""
                INSERT INTO daily_prices
                    (ticker, trade_date, open_price, high_price, low_price, close_price,
                     prev_close, volume, turnover_cr, delivery_qty, delivery_pct, trades, vwap, adj_close)
                SELECT ticker, trade_date, open_price, high_price, low_price, close_price,
                       prev_close, volume, turnover_cr, delivery_qty, delivery_pct, trades, vwap, adj_close
                FROM _bhavcopy_staging
                ON CONFLICT (ticker, trade_date) DO NOTHING
            """))
            stored = result.rowcount
            conn.execute(text("DROP TABLE IF EXISTS _bhavcopy_staging"))
        return stored
    except Exception as e:
        logger.error(f"Bulk insert failed: {e}")
        try:
            with engine.begin() as conn:
                conn.execute(text("DROP TABLE IF EXISTS _bhavcopy_staging"))
        except Exception:
            pass
        return 0


def _safe_float(val) -> float | None:
    try:
        if val is None or (isinstance(val, str) and val.strip() in ("", "-")):
            return None
        import math
        f = float(val)
        return f if not math.isnan(f) else None
    except Exception:
        return None


def backfill_history(db: Session, days: int = 365 * 3):
    """
    Download and store historical bhavcopy for past N days.
    Run once on setup. Skips weekends and holidays automatically.
    """
    end_date = date.today()
    start_date = end_date - timedelta(days=days)
    current = start_date
    total_stored = 0

    logger.info(f"Starting bhavcopy backfill: {start_date} to {end_date}")

    session = _get_nse_session()
    consecutive_failures = 0

    while current <= end_date:
        if current.weekday() < 5:
            df = download_bhavcopy(current, session=session)
            if df is not None and len(df) > 0:
                stored = store_bhavcopy(df, db)
                total_stored += stored
                consecutive_failures = 0
                logger.info(f"{current}: stored {stored} price records (total: {total_stored})")
            else:
                consecutive_failures += 1
                # Refresh session if too many failures
                if consecutive_failures > 10:
                    logger.info("Refreshing NSE session...")
                    try:
                        session = _get_nse_session()
                    except Exception:
                        pass
                    consecutive_failures = 0

        current += timedelta(days=1)

    # Update freshness
    freshness = db.query(DataFreshness).filter_by(data_type="bhavcopy").first()
    if not freshness:
        freshness = DataFreshness(data_type="bhavcopy")
        db.add(freshness)
    freshness.last_updated = datetime.utcnow()
    freshness.records_updated = total_stored
    freshness.status = "success"
    db.commit()

    logger.info(f"Backfill complete: {total_stored} total records stored")
    return total_stored


def run_daily(db: Session):
    """Run daily update — download recent bhavcopy data."""
    today = date.today()
    session = _get_nse_session()

    for delta in [1, 2, 3]:
        target = today - timedelta(days=delta)
        if target.weekday() < 5:
            df = download_bhavcopy(target, session=session)
            if df is not None:
                stored = store_bhavcopy(df, db)
                logger.info(f"Daily update: stored {stored} records for {target}")

    freshness = db.query(DataFreshness).filter_by(data_type="bhavcopy").first()
    if not freshness:
        freshness = DataFreshness(data_type="bhavcopy")
        db.add(freshness)
    freshness.last_updated = datetime.utcnow()
    freshness.status = "success"
    db.commit()


def download_corporate_actions(db: Session) -> int:
    """Download official NSE corporate actions (splits, bonuses, dividends)."""
    try:
        session = _get_nse_session()
        url = "https://www.nseindia.com/api/corporates-corporateActions?index=equities"
        response = session.get(url, timeout=30)
        if response.status_code != 200:
            logger.warning(f"Corporate actions API: HTTP {response.status_code}")
            return 0

        data = response.json()
        stored = 0

        for item in data:
            try:
                ex_date_str = item.get("exDate")
                if not ex_date_str:
                    continue

                action = CorporateAction(
                    ticker=str(item.get("symbol", "")).strip(),
                    action_type=str(item.get("subject", "")).strip().upper(),
                    ex_date=pd.to_datetime(ex_date_str).date(),
                    remarks=str(item.get("subject", "")),
                    adjustment_factor=1.0,
                )
                db.merge(action)
                stored += 1
            except Exception:
                continue

        db.commit()
        logger.info(f"Corporate actions: stored {stored} records")
        return stored

    except Exception as e:
        logger.error(f"Corporate actions download failed: {e}")
        return 0
