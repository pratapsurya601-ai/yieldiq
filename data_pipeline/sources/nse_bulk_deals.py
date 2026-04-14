# data_pipeline/sources/nse_bulk_deals.py
# Downloads bulk and block deal data from NSE API.
# Uses curl_cffi to impersonate Chrome (NSE blocks plain requests).
from __future__ import annotations

import logging
from datetime import datetime

import pandas as pd
from sqlalchemy.orm import Session

from data_pipeline.models import BulkDeal, DataFreshness

logger = logging.getLogger(__name__)

NSE_BASE = "https://www.nseindia.com"
NSE_BULK_DEALS_URL = "https://www.nseindia.com/api/bulk-deals?type=bulk"
NSE_BLOCK_DEALS_URL = "https://www.nseindia.com/api/bulk-deals?type=block"


def _get_nse_session():
    """Create a curl_cffi session with Chrome impersonation for NSE."""
    from curl_cffi import requests as cffi_requests
    session = cffi_requests.Session(impersonate="chrome")
    # Warm up session cookies from NSE homepage
    session.get(NSE_BASE, timeout=30)
    return session


def _parse_deal(item: dict, deal_category: str) -> BulkDeal | None:
    """Parse a single deal record from NSE API response."""
    try:
        ticker = str(item.get("symbol", "") or "").strip()
        if not ticker:
            return None

        # Parse trade date — NSE uses various formats
        date_str = (
            item.get("dealDate")
            or item.get("date")
            or item.get("BD_DT_DATE")
        )
        if not date_str:
            return None

        try:
            trade_date = pd.to_datetime(date_str, dayfirst=True).date()
        except Exception:
            return None

        client_name = str(
            item.get("clientName")
            or item.get("BD_CLIENT_NAME")
            or item.get("clientname")
            or ""
        ).strip()

        # Deal type: BUY or SELL
        raw_type = str(
            item.get("buySell")
            or item.get("BD_BUY_SELL")
            or item.get("buysell")
            or ""
        ).strip().upper()
        if raw_type in ("BUY", "B"):
            deal_type = "BUY"
        elif raw_type in ("SELL", "S"):
            deal_type = "SELL"
        else:
            deal_type = raw_type or "UNKNOWN"

        # Quantity
        qty_raw = (
            item.get("quantity")
            or item.get("BD_QTY_TRD")
            or item.get("quantityTraded")
            or 0
        )
        try:
            quantity = int(float(str(qty_raw).replace(",", "")))
        except (ValueError, TypeError):
            quantity = 0

        # Price
        price_raw = (
            item.get("avgPrice")
            or item.get("BD_TP_WATP")
            or item.get("weightedAvgPrice")
            or item.get("price")
            or 0
        )
        try:
            price = float(str(price_raw).replace(",", ""))
        except (ValueError, TypeError):
            price = 0.0

        return BulkDeal(
            ticker=ticker,
            trade_date=trade_date,
            client_name=client_name,
            deal_type=deal_type,
            quantity=quantity,
            price=price,
            deal_category=deal_category,
        )

    except Exception as e:
        logger.debug(f"Failed to parse deal item: {e}")
        return None


def _fetch_deals(session, url: str, category: str) -> list[BulkDeal]:
    """Fetch deals from a single NSE endpoint."""
    deals = []
    try:
        response = session.get(url, timeout=30)
        if response.status_code != 200:
            logger.warning(
                f"NSE {category} deals API returned HTTP {response.status_code}"
            )
            return []

        data = response.json()

        # NSE wraps deals in a "data" key or returns a list directly
        if isinstance(data, dict):
            items = data.get("data", []) or data.get("Table", []) or []
        elif isinstance(data, list):
            items = data
        else:
            logger.warning(
                f"Unexpected {category} deals response type: {type(data).__name__}"
            )
            return []

        for item in items:
            deal = _parse_deal(item, category)
            if deal is not None:
                deals.append(deal)

    except Exception as e:
        logger.error(f"NSE {category} deals fetch failed: {e}")

    return deals


def fetch_daily_deals(db: Session) -> int:
    """
    Fetch both bulk and block deals from NSE and store in the database.
    Returns total number of deals stored.
    """
    try:
        session = _get_nse_session()
    except Exception as e:
        logger.error(f"Failed to create NSE session for deals: {e}")
        return 0

    all_deals: list[BulkDeal] = []

    # Fetch bulk deals
    bulk = _fetch_deals(session, NSE_BULK_DEALS_URL, "bulk")
    all_deals.extend(bulk)
    logger.info(f"NSE bulk deals fetched: {len(bulk)}")

    # Fetch block deals
    block = _fetch_deals(session, NSE_BLOCK_DEALS_URL, "block")
    all_deals.extend(block)
    logger.info(f"NSE block deals fetched: {len(block)}")

    if not all_deals:
        logger.info("No deals to store")
        return 0

    stored = 0
    errors = 0

    for deal in all_deals:
        try:
            existing = db.query(BulkDeal).filter_by(
                ticker=deal.ticker,
                trade_date=deal.trade_date,
                client_name=deal.client_name,
                deal_type=deal.deal_type,
                deal_category=deal.deal_category,
            ).first()

            if existing:
                existing.quantity = deal.quantity
                existing.price = deal.price
            else:
                db.add(deal)
            stored += 1
        except Exception as e:
            errors += 1
            logger.debug(f"Skipping deal row: {e}")
            db.rollback()
            continue

    try:
        db.commit()
    except Exception as e:
        logger.error(f"Bulk deals commit failed: {e}")
        db.rollback()
        return 0

    # Update freshness
    try:
        freshness = db.query(DataFreshness).filter_by(
            data_type="bulk_deals"
        ).first()
        if not freshness:
            freshness = DataFreshness(data_type="bulk_deals")
            db.add(freshness)
        freshness.last_updated = datetime.utcnow()
        freshness.records_updated = stored
        freshness.status = "success" if stored > 0 else "no_data"
        db.commit()
    except Exception:
        db.rollback()

    if errors:
        logger.warning(f"Bulk/block deals: {errors} rows skipped")
    logger.info(f"Bulk/block deals: {stored} records stored")
    return stored
