# data_pipeline/isin_loader.py
# Downloads NSE equity master file and builds ISIN map.
# NSE publishes a CSV of all listed equities with ISIN codes.
from __future__ import annotations

import io
import logging

import pandas as pd
import requests
from sqlalchemy.orm import Session

from data_pipeline.models import Stock

logger = logging.getLogger(__name__)

# Official NSE equity list — CSV download (no scraping)
NSE_EQUITY_LIST_URL = "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Referer": "https://www.nseindia.com",
}


def download_nse_equity_list() -> pd.DataFrame | None:
    """Download the official NSE equity list CSV."""
    try:
        r = requests.get(NSE_EQUITY_LIST_URL, headers=HEADERS, timeout=30)
        r.raise_for_status()
        df = pd.read_csv(io.StringIO(r.text))
        df.columns = df.columns.str.strip()
        logger.info(f"Downloaded NSE equity list: {len(df)} stocks")
        return df
    except Exception as e:
        logger.error(f"Failed to download NSE equity list: {e}")
        return None


def build_isin_map(df: pd.DataFrame | None = None) -> dict[str, str]:
    """
    Build ticker -> ISIN mapping from NSE equity list.
    Returns dict like {"RELIANCE": "INE002A01018", ...}
    """
    if df is None:
        df = download_nse_equity_list()
    if df is None:
        return {}

    # NSE columns: SYMBOL, NAME OF COMPANY, SERIES, DATE OF LISTING, PAID UP VALUE, MARKET LOT, ISIN NUMBER, FACE VALUE
    sym_col = next((c for c in df.columns if "SYMBOL" in c.upper()), None)
    isin_col = next((c for c in df.columns if "ISIN" in c.upper()), None)

    if not sym_col or not isin_col:
        logger.error(f"Could not find SYMBOL/ISIN columns in: {df.columns.tolist()}")
        return {}

    isin_map = {}
    for _, row in df.iterrows():
        sym = str(row[sym_col]).strip()
        isin = str(row[isin_col]).strip()
        if sym and isin and len(isin) == 12:
            isin_map[sym] = isin

    logger.info(f"Built ISIN map: {len(isin_map)} entries")
    return isin_map


def populate_stocks_table(db: Session, df: pd.DataFrame | None = None) -> int:
    """
    Populate the stocks master table from NSE equity list.
    Also builds and returns ISIN map.
    """
    if df is None:
        df = download_nse_equity_list()
    if df is None:
        return 0

    sym_col = next((c for c in df.columns if "SYMBOL" in c.upper()), None)
    name_col = next((c for c in df.columns if "NAME" in c.upper()), None)
    isin_col = next((c for c in df.columns if "ISIN" in c.upper()), None)
    series_col = next((c for c in df.columns if "SERIES" in c.upper()), None)
    date_col = next((c for c in df.columns if "DATE" in c.upper() and "LIST" in c.upper()), None)

    stored = 0
    for _, row in df.iterrows():
        try:
            sym = str(row.get(sym_col, "")).strip()
            if not sym:
                continue

            isin = str(row.get(isin_col, "")).strip() if isin_col else None
            company = str(row.get(name_col, "")).strip() if name_col else sym

            listed_date = None
            if date_col and pd.notna(row.get(date_col)):
                try:
                    listed_date = pd.to_datetime(row[date_col]).date()
                except Exception:
                    pass

            stock = Stock(
                ticker=sym,
                ticker_ns=f"{sym}.NS",
                company_name=company,
                isin=isin if isin and len(isin) == 12 else None,
                series=str(row.get(series_col, "EQ")).strip() if series_col else "EQ",
                is_active=True,
                listed_date=listed_date,
            )
            db.merge(stock)
            stored += 1
        except Exception:
            continue

    db.commit()
    logger.info(f"Populated stocks table: {stored} entries")
    return stored
