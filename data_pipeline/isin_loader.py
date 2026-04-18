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

    Handles the tricky corporate-action edge case where a company
    renames and the SAME ISIN migrates to a new ticker. Naive
    db.merge() fails in that case because the `stocks.isin` UNIQUE
    constraint forbids two rows sharing an ISIN — so we can't just
    UPDATE the new ticker to point at the ISIN; the old ticker row
    is still holding it.

    Resolution strategy:
      1. Pre-query every (isin, ticker) pair currently in the table.
      2. For each NSE row, if its ISIN is already held by a different
         ticker, null-out the old holder's ISIN and mark it inactive
         (the company effectively moved to the new ticker).
      3. Then upsert the new row normally.

    Also: per-row try/except + flush so a single bad row can't
    poison the whole transaction.
    """
    if df is None:
        df = download_nse_equity_list()
    if df is None:
        return 0

    sym_col = next((c for c in df.columns if "SYMBOL" in c.upper()), None)
    name_col = next((c for c in df.columns if "NAME" in c.upper()), None)
    isin_col = next((c for c in df.columns if "ISIN" in c.upper()), None)
    series_col = next((c for c in df.columns if "SERIES" in c.upper()), None)
    date_col = next(
        (c for c in df.columns if "DATE" in c.upper() and "LIST" in c.upper()),
        None,
    )

    # Snapshot current (isin → ticker) state so we can detect
    # renames / re-listings and clean them up first.
    existing_by_isin: dict[str, str] = {
        isin: tkr
        for (tkr, isin) in db.query(Stock.ticker, Stock.isin).filter(
            Stock.isin.isnot(None)
        ).all()
    }

    stored = 0
    renamed = 0
    failed = 0
    for _, row in df.iterrows():
        try:
            sym = str(row.get(sym_col, "")).strip()
            if not sym:
                continue

            isin_raw = (
                str(row.get(isin_col, "")).strip()
                if isin_col and pd.notna(row.get(isin_col))
                else ""
            )
            isin = isin_raw if isin_raw and len(isin_raw) == 12 else None

            company = (
                str(row.get(name_col, "")).strip() if name_col else sym
            )

            listed_date = None
            if date_col and pd.notna(row.get(date_col)):
                try:
                    listed_date = pd.to_datetime(row[date_col]).date()
                except Exception:
                    pass

            # Rename handling: if ISIN is held by a different ticker,
            # release it from the old row first.
            if isin and existing_by_isin.get(isin) and existing_by_isin[isin] != sym:
                old_tkr = existing_by_isin[isin]
                old_row = db.query(Stock).filter(Stock.ticker == old_tkr).first()
                if old_row is not None:
                    old_row.isin = None
                    old_row.is_active = False
                    db.flush()
                existing_by_isin.pop(isin, None)
                renamed += 1

            stock = Stock(
                ticker=sym,
                ticker_ns=f"{sym}.NS",
                company_name=company,
                isin=isin,
                series=(
                    str(row.get(series_col, "EQ")).strip() if series_col else "EQ"
                ),
                is_active=True,
                listed_date=listed_date,
            )
            db.merge(stock)
            db.flush()
            if isin:
                existing_by_isin[isin] = sym
            stored += 1
        except Exception as exc:
            db.rollback()
            failed += 1
            logger.warning("populate_stocks: skipped %r — %s", sym, exc)

    db.commit()
    logger.info(
        "Populated stocks table: stored=%d renamed=%d failed=%d",
        stored, renamed, failed,
    )
    return stored
