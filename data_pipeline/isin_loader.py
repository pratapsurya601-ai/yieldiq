# data_pipeline/isin_loader.py
# Downloads NSE equity master file and builds ISIN map.
# NSE publishes a CSV of all listed equities with ISIN codes.
from __future__ import annotations

import io
import logging
from pathlib import Path

import pandas as pd
import requests
from sqlalchemy.orm import Session

from data_pipeline.models import Stock

logger = logging.getLogger(__name__)

# NSE equity list sources, tried in order. NSE's own server aggressively
# blocks cloud datacenter IPs (GH Actions, Railway, etc.), so we have
# multiple fallbacks:
#   1. Official NSE archives URL — works from India / unblocked IPs
#   2. A committed copy of the CSV at data_pipeline/nse_equity_list.csv —
#      populated manually by running this module from a laptop, then
#      `git commit`. Refreshed whenever the monthly populate_stocks
#      workflow notices a >5% row-count drop.
NSE_EQUITY_LIST_URLS = [
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv",
    "https://www1.nseindia.com/content/equities/EQUITY_L.csv",
]

REPO_FALLBACK_CSV = (
    Path(__file__).resolve().parent / "nse_equity_list.csv"
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Referer": "https://www.nseindia.com/",
    "Accept": "text/csv,application/csv,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
}


def _parse_nse_csv(text: str) -> pd.DataFrame | None:
    """Parse the NSE equity CSV string, tolerant of BOM/whitespace."""
    try:
        df = pd.read_csv(io.StringIO(text))
        df.columns = df.columns.str.strip()
        if len(df) < 100:
            logger.warning(
                "NSE equity CSV parsed but only %d rows — likely partial/error response",
                len(df),
            )
            return None
        return df
    except Exception as exc:
        logger.warning("NSE equity CSV parse failed: %s", exc)
        return None


def download_nse_equity_list() -> pd.DataFrame | None:
    """Fetch the official NSE equity list.

    Tries the live NSE URLs first (requires unblocked IP), then falls
    back to the checked-in CSV at data_pipeline/nse_equity_list.csv so
    the pipeline still works when deployed on cloud infra that NSE
    refuses to serve.
    """
    # Use a session so any cookies set by visiting www.nseindia.com
    # carry through to the archives subdomain.
    sess = requests.Session()
    sess.headers.update(HEADERS)
    try:
        sess.get("https://www.nseindia.com/", timeout=10)
    except Exception:
        pass  # cookie priming best-effort

    for url in NSE_EQUITY_LIST_URLS:
        try:
            r = sess.get(url, timeout=30)
            if r.status_code != 200:
                logger.info("NSE list %s → HTTP %s", url, r.status_code)
                continue
            # NSE sometimes returns a JSON error page masquerading as 200
            if not r.text.lstrip().upper().startswith("SYMBOL"):
                logger.info("NSE list %s → non-CSV response", url)
                continue
            df = _parse_nse_csv(r.text)
            if df is not None:
                logger.info("Downloaded NSE equity list from %s: %d rows", url, len(df))
                return df
        except Exception as exc:
            logger.info("NSE list %s errored: %s", url, exc)

    # Fallback: checked-in CSV
    if REPO_FALLBACK_CSV.exists():
        try:
            df = pd.read_csv(REPO_FALLBACK_CSV)
            df.columns = df.columns.str.strip()
            logger.warning(
                "Using checked-in NSE equity list fallback (%s): %d rows",
                REPO_FALLBACK_CSV.name, len(df),
            )
            return df
        except Exception as exc:
            logger.error("Checked-in fallback CSV unreadable: %s", exc)

    logger.error(
        "Failed to obtain NSE equity list from any source. "
        "Run `python -c \"from data_pipeline.isin_loader import download_nse_equity_list as f; "
        "f().to_csv('data_pipeline/nse_equity_list.csv', index=False)\"` "
        "from a machine with working NSE access, then commit the CSV."
    )
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
