# data_pipeline/sources/nse_bhavcopy.py
# Downloads official NSE Bhavcopy CSV files (daily OHLCV + delivery).
# No scraping — direct CSV download from official NSE archive.
from __future__ import annotations

import io
import logging
import zipfile
from datetime import date, datetime, timedelta

import pandas as pd
import requests
from sqlalchemy.orm import Session

from data_pipeline.models import CorporateAction, DailyPrice, DataFreshness

logger = logging.getLogger(__name__)

BHAVCOPY_URL = (
    "https://nsearchives.nseindia.com/content/historical/EQUITIES/"
    "{year}/{month}/cm{date}bhav.csv.zip"
)

CORPORATE_ACTIONS_URL = (
    "https://nsearchives.nseindia.com/content/equities/CA.csv"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Referer": "https://www.nseindia.com",
}

MONTHS = {
    1: "JAN", 2: "FEB", 3: "MAR", 4: "APR", 5: "MAY", 6: "JUN",
    7: "JUL", 8: "AUG", 9: "SEP", 10: "OCT", 11: "NOV", 12: "DEC",
}


def download_bhavcopy(trade_date: date) -> pd.DataFrame | None:
    """Download and parse NSE Bhavcopy for a specific date."""
    url = BHAVCOPY_URL.format(
        year=trade_date.year,
        month=MONTHS[trade_date.month],
        date=trade_date.strftime("%d%b%Y").upper(),
    )

    try:
        session = requests.Session()
        response = session.get(url, headers=HEADERS, timeout=30)
        if response.status_code == 404:
            logger.info(f"No bhavcopy for {trade_date} (holiday/weekend)")
            return None
        response.raise_for_status()

        with zipfile.ZipFile(io.BytesIO(response.content)) as z:
            csv_name = [n for n in z.namelist() if n.endswith(".csv")][0]
            df = pd.read_csv(z.open(csv_name))

        return _clean_bhavcopy(df, trade_date)

    except Exception as e:
        logger.error(f"Failed to download bhavcopy for {trade_date}: {e}")
        return None


def _clean_bhavcopy(df: pd.DataFrame, trade_date: date) -> pd.DataFrame:
    """Clean and standardise bhavcopy columns."""
    df.columns = df.columns.str.strip().str.upper()

    # Keep only EQ series (regular equity)
    df = df[df["SERIES"] == "EQ"].copy()

    col_map = {
        "SYMBOL": "ticker",
        "OPEN": "open_price",
        "HIGH": "high_price",
        "LOW": "low_price",
        "CLOSE": "close_price",
        "PREVCLOSE": "prev_close",
        "TOTTRDQTY": "volume",
        "TOTTRDVAL": "turnover_cr",
        "TOTALTRADES": "trades",
        "ISIN": "isin",
    }
    df = df.rename(columns={k: v for k, v in col_map.items() if k in df.columns})
    df["trade_date"] = trade_date
    df["turnover_cr"] = df.get("turnover_cr", 0) / 1e7  # Convert to Crore

    # VWAP = Turnover / Volume
    vol = df["volume"].replace(0, 1)
    df["vwap"] = ((df.get("turnover_cr", 0) * 1e7) / vol).round(2)

    return df


def store_bhavcopy(df: pd.DataFrame, db: Session) -> int:
    """Store cleaned bhavcopy data into daily_prices table."""
    stored = 0
    for _, row in df.iterrows():
        try:
            existing = db.query(DailyPrice).filter_by(
                ticker=row["ticker"],
                trade_date=row["trade_date"],
            ).first()

            if existing:
                continue

            price = DailyPrice(
                ticker=row["ticker"],
                trade_date=row["trade_date"],
                open_price=row.get("open_price"),
                high_price=row.get("high_price"),
                low_price=row.get("low_price"),
                close_price=row.get("close_price"),
                prev_close=row.get("prev_close"),
                volume=row.get("volume", 0),
                turnover_cr=row.get("turnover_cr"),
                trades=row.get("trades"),
                vwap=row.get("vwap"),
                adj_close=row.get("close_price"),
            )
            db.add(price)
            stored += 1
        except Exception as e:
            logger.warning(f"Failed to store price for {row.get('ticker')}: {e}")
            continue

    db.commit()
    return stored


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

    while current <= end_date:
        if current.weekday() < 5:
            df = download_bhavcopy(current)
            if df is not None:
                stored = store_bhavcopy(df, db)
                total_stored += stored
                logger.info(f"{current}: stored {stored} price records")
        current += timedelta(days=1)

    logger.info(f"Backfill complete: {total_stored} total records stored")
    return total_stored


def run_daily(db: Session):
    """Run daily update — download recent bhavcopy data."""
    today = date.today()
    for delta in [1, 2, 3]:
        target = today - timedelta(days=delta)
        if target.weekday() < 5:
            df = download_bhavcopy(target)
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
        response = requests.get(CORPORATE_ACTIONS_URL, headers=HEADERS, timeout=30)
        response.raise_for_status()

        df = pd.read_csv(io.StringIO(response.text))
        stored = 0

        for _, row in df.iterrows():
            try:
                ex_date_raw = row.get("EX-DATE") or row.get("Ex Date")
                if not ex_date_raw or pd.isna(ex_date_raw):
                    continue

                action = CorporateAction(
                    ticker=str(row.get("SYMBOL", row.get("Symbol", ""))).strip(),
                    action_type=str(row.get("PURPOSE", row.get("Purpose", ""))).strip().upper(),
                    ex_date=pd.to_datetime(ex_date_raw).date(),
                    ratio=str(row.get("FACE VALUE OLD", row.get("Face Value (Old)", ""))),
                    remarks=str(row.get("PURPOSE", row.get("Purpose", ""))),
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
