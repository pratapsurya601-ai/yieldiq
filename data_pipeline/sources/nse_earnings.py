# data_pipeline/sources/nse_earnings.py
# Downloads upcoming earnings / financial results dates from NSE event calendar.
# Uses curl_cffi to impersonate Chrome (NSE blocks plain requests).
from __future__ import annotations

import io
import logging
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy.orm import Session

from data_pipeline.models import DataFreshness, UpcomingEarnings

logger = logging.getLogger(__name__)

NSE_BASE = "https://www.nseindia.com"
NSE_EVENT_CALENDAR_URL = "https://www.nseindia.com/api/event-calendar?index=equities"
NSE_CORP_ACTIONS_CSV = (
    "https://archives.nseindia.com/content/equities/corporateActions.csv"
)


def _get_nse_session():
    """Create a curl_cffi session with Chrome impersonation for NSE."""
    from curl_cffi import requests as cffi_requests

    session = cffi_requests.Session(impersonate="chrome")
    # Warm up session cookies from NSE homepage
    session.get(NSE_BASE, timeout=30)
    return session


def _is_financial_results(purpose: str) -> bool:
    """Check whether the event purpose relates to financial results."""
    if not purpose:
        return False
    lower = purpose.lower()
    keywords = [
        "financial result",
        "financial statement",
        "quarterly result",
        "annual result",
        "audited result",
        "un-audited result",
        "unaudited result",
        "board meeting.*result",
        "results for the quarter",
        "results for the year",
    ]
    import re

    for kw in keywords:
        if re.search(kw, lower):
            return True
    return False


def _fetch_json_calendar(session) -> list[dict]:
    """Fetch events from NSE JSON event calendar API."""
    try:
        resp = session.get(NSE_EVENT_CALENDAR_URL, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"NSE event calendar API returned HTTP {resp.status_code}")
            return []

        data = resp.json()
        if not isinstance(data, list):
            logger.warning(
                f"Unexpected event calendar response type: {type(data).__name__}"
            )
            return []

        return data
    except Exception as e:
        logger.error(f"NSE event calendar JSON fetch failed: {e}")
        return []


def _fetch_csv_fallback(session) -> list[dict]:
    """Fetch corporate actions CSV as fallback for earnings dates."""
    try:
        resp = session.get(NSE_CORP_ACTIONS_CSV, timeout=30)
        if resp.status_code != 200:
            logger.warning(f"NSE corporate actions CSV returned HTTP {resp.status_code}")
            return []

        df = pd.read_csv(io.StringIO(resp.text))
        events = []
        for _, row in df.iterrows():
            purpose = str(row.get("PURPOSE", "") or row.get("Subject", "") or "")
            if not _is_financial_results(purpose):
                continue

            symbol = str(row.get("SYMBOL", "") or row.get("Company", "") or "").strip()
            date_str = str(
                row.get("EX-DATE", "")
                or row.get("RECORD DATE", "")
                or row.get("BC STRT DT", "")
                or ""
            ).strip()
            if not symbol or not date_str:
                continue

            events.append(
                {"symbol": symbol, "date": date_str, "purpose": purpose}
            )

        return events
    except Exception as e:
        logger.error(f"NSE corporate actions CSV fetch failed: {e}")
        return []


def _parse_event_date(date_str: str) -> date | None:
    """Parse event dates from NSE (various formats)."""
    if not date_str:
        return None
    for fmt in ("%d-%b-%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%Y", "%d %b %Y"):
        try:
            return datetime.strptime(date_str.strip(), fmt).date()
        except ValueError:
            continue
    try:
        return pd.to_datetime(date_str, dayfirst=True).date()
    except Exception:
        return None


def fetch_earnings_dates(db: Session) -> int:
    """
    Fetch upcoming earnings dates from NSE and store in the database.
    Tries JSON event calendar first, falls back to CSV.
    Only stores events within the next 90 days.
    Returns total number of earnings events stored.
    """
    try:
        session = _get_nse_session()
    except Exception as e:
        logger.error(f"Failed to create NSE session for earnings: {e}")
        return 0

    today = date.today()
    cutoff = today + timedelta(days=90)
    stored = 0
    errors = 0

    # ── Try JSON calendar first ──────────────────────────────
    events = _fetch_json_calendar(session)
    earnings_items: list[dict] = []

    if events:
        for ev in events:
            purpose = str(ev.get("purpose", "") or ev.get("bm_desc", "") or "")
            if not _is_financial_results(purpose):
                continue

            symbol = str(ev.get("symbol", "") or "").strip()
            date_str = str(ev.get("date", "") or ev.get("bm_date", "") or "").strip()
            if not symbol or not date_str:
                continue

            event_date = _parse_event_date(date_str)
            if event_date is None:
                continue

            # Only store future events within 90 days
            if event_date < today or event_date > cutoff:
                continue

            earnings_items.append(
                {
                    "ticker": symbol,
                    "event_date": event_date,
                    "event_type": "Financial Results",
                    "purpose": purpose[:500],
                }
            )

        logger.info(f"NSE JSON calendar: {len(earnings_items)} earnings events found")

    # ── CSV fallback if JSON yielded nothing ─────────────────
    if not earnings_items:
        logger.info("JSON calendar empty, trying CSV fallback")
        csv_events = _fetch_csv_fallback(session)

        for ev in csv_events:
            symbol = ev["symbol"]
            event_date = _parse_event_date(ev["date"])
            if event_date is None:
                continue
            if event_date < today or event_date > cutoff:
                continue

            earnings_items.append(
                {
                    "ticker": symbol,
                    "event_date": event_date,
                    "event_type": "Financial Results",
                    "purpose": ev.get("purpose", "")[:500],
                }
            )

        logger.info(f"NSE CSV fallback: {len(earnings_items)} earnings events found")

    if not earnings_items:
        logger.info("No upcoming earnings events found")
        return 0

    # ── Store in DB ──────────────────────────────────────────
    for item in earnings_items:
        try:
            existing = (
                db.query(UpcomingEarnings)
                .filter_by(ticker=item["ticker"], event_date=item["event_date"])
                .first()
            )

            if existing:
                existing.event_type = item["event_type"]
                existing.purpose = item["purpose"]
                existing.updated_at = datetime.utcnow()
            else:
                db.add(
                    UpcomingEarnings(
                        ticker=item["ticker"],
                        event_date=item["event_date"],
                        event_type=item["event_type"],
                        purpose=item["purpose"],
                        updated_at=datetime.utcnow(),
                    )
                )
            stored += 1
        except Exception as e:
            errors += 1
            logger.debug(f"Skipping earnings row: {e}")
            db.rollback()
            continue

    try:
        db.commit()
    except Exception as e:
        logger.error(f"Earnings dates commit failed: {e}")
        db.rollback()
        return 0

    # ── Clean up stale events (past dates) ───────────────────
    try:
        db.query(UpcomingEarnings).filter(
            UpcomingEarnings.event_date < today
        ).delete()
        db.commit()
    except Exception:
        db.rollback()

    # ── Update freshness ─────────────────────────────────────
    try:
        freshness = db.query(DataFreshness).filter_by(
            data_type="upcoming_earnings"
        ).first()
        if not freshness:
            freshness = DataFreshness(data_type="upcoming_earnings")
            db.add(freshness)
        freshness.last_updated = datetime.utcnow()
        freshness.records_updated = stored
        freshness.status = "success" if stored > 0 else "no_data"
        db.commit()
    except Exception:
        db.rollback()

    if errors:
        logger.warning(f"Earnings dates: {errors} rows skipped")
    logger.info(f"Earnings dates: {stored} records stored")
    return stored


def get_next_earnings(ticker: str, db: Session) -> dict | None:
    """
    Return the next upcoming earnings date for a ticker.
    Returns dict with 'date', 'days_away', 'purpose' or None if not found.
    """
    # Strip .NS/.BO suffix for DB lookup
    clean_ticker = ticker.replace(".NS", "").replace(".BO", "")
    today = date.today()

    try:
        row = (
            db.query(UpcomingEarnings)
            .filter(
                UpcomingEarnings.ticker == clean_ticker,
                UpcomingEarnings.event_date >= today,
            )
            .order_by(UpcomingEarnings.event_date)
            .first()
        )

        if row:
            days_away = (row.event_date - today).days
            return {
                "date": str(row.event_date),
                "days_away": days_away,
                "purpose": row.purpose or "",
                "event_type": row.event_type or "",
            }
        return None
    except Exception as e:
        logger.debug(f"get_next_earnings({clean_ticker}) failed: {e}")
        return None
