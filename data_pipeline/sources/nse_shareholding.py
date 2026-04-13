# data_pipeline/sources/nse_shareholding.py
# Downloads promoter, FII, DII shareholding from NSE API.
# Uses curl_cffi to impersonate Chrome (NSE blocks plain requests).
#
# NSE changed their API -- the old bulk CSV at nsearchives.nseindia.com
# no longer works. The working endpoint is:
#   /api/corporate-share-holdings-master?index=equities  (all stocks, latest quarter)
#   /api/corporate-share-holdings-master?index=equities&symbol=XYZ  (per-symbol history)
# These return promoter % (pr_and_prgrp) and public % (public_val).
# FII/DII breakdown requires parsing the XBRL file (not yet implemented).
from __future__ import annotations

import logging
from datetime import date, datetime

import pandas as pd
from sqlalchemy import text
from sqlalchemy.orm import Session

from data_pipeline.models import ShareholdingPattern, DataFreshness

logger = logging.getLogger(__name__)

NSE_BASE = "https://www.nseindia.com"

# NSE API: bulk shareholding master (latest quarter for all stocks)
NSE_SHP_MASTER_URL = (
    "https://www.nseindia.com/api/corporate-share-holdings-master"
    "?index=equities"
)

# NSE API: per-symbol shareholding history
NSE_SHP_SYMBOL_URL = (
    "https://www.nseindia.com/api/corporate-share-holdings-master"
    "?index=equities&symbol={symbol}"
)


def _get_nse_session():
    """Create a curl_cffi session with Chrome impersonation for NSE."""
    from curl_cffi import requests as cffi_requests
    session = cffi_requests.Session(impersonate="chrome")
    # Warm up session cookies from NSE homepage
    session.get(NSE_BASE, timeout=30)
    return session


def _parse_master_item(item: dict) -> ShareholdingPattern | None:
    """
    Parse a shareholding record from the NSE master API.
    Fields: symbol, date, pr_and_prgrp, public_val, employeeTrusts
    """
    try:
        ticker = str(item.get("symbol", "") or "").strip()
        if not ticker:
            return None

        date_str = item.get("date")
        if not date_str:
            return None
        quarter_end = pd.to_datetime(date_str, dayfirst=True).date()

        sh = ShareholdingPattern(
            ticker=ticker,
            quarter_end=quarter_end,
            promoter_pct=_pct(item.get("pr_and_prgrp")),
            promoter_pledge_pct=None,   # not in master API
            fii_pct=None,               # not in master API (requires XBRL)
            dii_pct=None,               # not in master API (requires XBRL)
            public_pct=_pct(item.get("public_val")),
            total_shares=None,          # not in master API
        )
        return sh
    except Exception as e:
        logger.debug(f"Failed to parse shareholding item for "
                     f"{item.get('symbol', '?')}: {e}")
        return None


def download_bulk_shareholding(year: int = None, quarter: int = None,
                               db: Session = None) -> int:
    """
    Download shareholding pattern for all NSE companies (latest available).
    The NSE master API returns the most recent filing for each stock.
    year/quarter params are accepted for API compatibility but ignored --
    the endpoint always returns latest data.
    """
    try:
        session = _get_nse_session()

        logger.info(f"Fetching bulk shareholding from NSE master API")
        response = session.get(NSE_SHP_MASTER_URL, timeout=60)

        if response.status_code != 200:
            logger.warning(
                f"Shareholding master API returned HTTP {response.status_code}"
            )
            return 0

        data = response.json()
        if not isinstance(data, list):
            logger.warning(
                f"Unexpected shareholding response type: {type(data).__name__}"
            )
            return 0

        stored = 0
        errors = 0

        for item in data:
            sh = _parse_master_item(item)
            if sh is None:
                errors += 1
                continue
            try:
                # Use query + update/insert to handle unique constraint
                existing = db.query(ShareholdingPattern).filter_by(
                    ticker=sh.ticker, quarter_end=sh.quarter_end
                ).first()
                if existing:
                    existing.promoter_pct = sh.promoter_pct
                    existing.promoter_pledge_pct = sh.promoter_pledge_pct
                    existing.fii_pct = sh.fii_pct
                    existing.dii_pct = sh.dii_pct
                    existing.public_pct = sh.public_pct
                    existing.total_shares = sh.total_shares
                else:
                    db.add(sh)
                stored += 1
            except Exception as e:
                errors += 1
                logger.debug(f"Skipping shareholding row: {e}")
                db.rollback()
                continue

        try:
            db.commit()
        except Exception as e:
            logger.error(f"Shareholding commit failed, rolling back: {e}")
            db.rollback()
            return 0

        if errors:
            logger.warning(f"Shareholding bulk: {errors} rows skipped")
        logger.info(f"Shareholding bulk: {stored} records stored")
        return stored

    except Exception as e:
        logger.error(f"Shareholding bulk download failed: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return 0


def download_symbol_shareholding(symbol: str, db: Session) -> int:
    """
    Download shareholding history for a single symbol from NSE API.
    Returns multiple quarters of data.
    """
    try:
        session = _get_nse_session()
        url = NSE_SHP_SYMBOL_URL.format(symbol=symbol)
        logger.info(f"Fetching shareholding for {symbol}")
        response = session.get(url, timeout=30)

        if response.status_code != 200:
            logger.warning(
                f"Shareholding symbol API HTTP {response.status_code} for {symbol}"
            )
            return 0

        data = response.json()
        if not isinstance(data, list):
            logger.warning(
                f"Unexpected response type for {symbol}: {type(data).__name__}"
            )
            return 0

        stored = 0
        for item in data:
            sh = _parse_master_item(item)
            if sh is not None:
                try:
                    existing = db.query(ShareholdingPattern).filter_by(
                        ticker=sh.ticker, quarter_end=sh.quarter_end
                    ).first()
                    if existing:
                        existing.promoter_pct = sh.promoter_pct
                        existing.public_pct = sh.public_pct
                    else:
                        db.add(sh)
                    stored += 1
                except Exception:
                    db.rollback()
                    continue

        try:
            db.commit()
        except Exception as e:
            logger.error(f"Shareholding commit failed for {symbol}: {e}")
            db.rollback()
            return 0

        logger.info(f"Shareholding for {symbol}: {stored} records")
        return stored

    except Exception as e:
        logger.error(f"Shareholding download failed for {symbol}: {e}")
        try:
            db.rollback()
        except Exception:
            pass
        return 0


def run_daily(db: Session):
    """Run daily shareholding update -- downloads latest available data."""
    stored = download_bulk_shareholding(db=db)

    # Update freshness
    freshness = db.query(DataFreshness).filter_by(
        data_type="shareholding"
    ).first()
    if not freshness:
        freshness = DataFreshness(data_type="shareholding")
        db.add(freshness)
    freshness.last_updated = datetime.utcnow()
    freshness.records_updated = stored
    freshness.status = "success" if stored > 0 else "no_data"
    try:
        db.commit()
    except Exception:
        db.rollback()


def _pct(value) -> float | None:
    try:
        if value is None or str(value).strip() in ("", "-"):
            return None
        return float(str(value).replace(",", "").replace("%", ""))
    except Exception:
        return None
