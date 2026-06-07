# data_pipeline/sources/nse_earnings.py
# Downloads upcoming earnings / financial results dates from NSE.
#
# Phase 1 (2026-06-07): The original `event-calendar` endpoint is structurally
# tiny — a small forward-looking board-meeting agenda slice (13 events total,
# ~4 of which are Financial Results). It is NOT an earnings firehose.
#
# The real earnings stream lives at:
#   https://www.nseindia.com/api/corporate-announcements
#     ?index=equities&category=Financial Results
#
# We now treat `corporate-announcements` as the PRIMARY source (confirmed
# intimations of upcoming results) and `event-calendar` as a CORROBORATOR.
# Both are merged and deduped on (ticker, event_date).
#
# Uses curl_cffi to impersonate Chrome (NSE blocks plain requests).
from __future__ import annotations

import io
import logging
import time
from datetime import date, datetime, timedelta

import pandas as pd
from sqlalchemy.orm import Session

from data_pipeline.models import DataFreshness, UpcomingEarnings

logger = logging.getLogger(__name__)

NSE_BASE = "https://www.nseindia.com"
NSE_EVENT_CALENDAR_URL = "https://www.nseindia.com/api/event-calendar?index=equities"
NSE_CORP_ANNOUNCEMENTS_URL = "https://www.nseindia.com/api/corporate-announcements"
NSE_CORP_ACTIONS_CSV = (
    "https://archives.nseindia.com/content/equities/corporateActions.csv"
)

# Source labels (stored in UpcomingEarnings.source)
SOURCE_EVENT_CALENDAR = "nse_event_calendar"
SOURCE_CORP_ANNOUNCEMENTS = "nse_corporate_announcements"

# Politeness sleep between paginated NSE requests (seconds)
NSE_PAGINATION_SLEEP_SEC = 0.7
# Max pages we will walk before giving up — defensive cap
NSE_CORP_ANN_MAX_PAGES = 50


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


def _is_results_intimation(subject: str, desc: str) -> bool:
    """
    Decide whether a corporate-announcements item is a forward-looking
    Financial Results INTIMATION (board meeting notice) rather than a
    past-results filing.

    NSE marks the same `category=Financial Results` for both:
      * "Intimation of Board Meeting to consider … audited results"
      * "Outcome of Board Meeting" / "Financial Results for the quarter ended …"

    We want the first kind — the upcoming-event signal. Heuristic:
    look for "intimation", "notice", "board meeting", "to consider",
    "schedul" — and reject clear past-results markers ("outcome",
    "results for the quarter ended", "audited financial results for").
    """
    blob = f"{subject or ''} {desc or ''}".lower()
    if not blob.strip():
        return False

    past_markers = (
        "outcome of board",
        "results for the quarter ended",
        "results for the year ended",
        "audited financial results for",
        "unaudited financial results for",
        "un-audited financial results for",
    )
    for m in past_markers:
        if m in blob:
            return False

    intimation_markers = (
        "intimation",
        "notice of board",
        "to consider",
        "scheduled to be held",
        "board meeting",  # broad, but combined with non-past gate above
    )
    return any(m in blob for m in intimation_markers)


def _extract_meeting_date(subject: str, desc: str) -> date | None:
    """
    Try to extract the scheduled board-meeting date from the subject/desc
    of an intimation. NSE intimations typically embed the date as
    "on Monday, May 12, 2025" / "on 12.05.2025" / "on 12/05/2025".

    Returns None when no usable date can be parsed.
    """
    import re

    blob = f"{subject or ''} {desc or ''}"
    if not blob.strip():
        return None

    # Try common date patterns. Order matters (most specific first).
    patterns = [
        # 12-May-2025 / 12 May 2025 / May 12, 2025
        r"\b(\d{1,2})[\s\-/](Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*[\s\-/,]+(\d{4})\b",
        r"\b(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+(\d{1,2}),?\s+(\d{4})\b",
        # 12.05.2025 / 12/05/2025 / 12-05-2025
        r"\b(\d{1,2})[./-](\d{1,2})[./-](\d{4})\b",
        # 2025-05-12
        r"\b(\d{4})-(\d{1,2})-(\d{1,2})\b",
    ]

    for pat in patterns:
        m = re.search(pat, blob, re.IGNORECASE)
        if not m:
            continue
        candidate = m.group(0)
        parsed = _parse_event_date(candidate)
        if parsed is not None:
            return parsed
    return None


def fetch_from_corporate_announcements(
    session, days_window: int = 90
) -> list[dict]:
    """
    Fetch upcoming Financial Results intimations from NSE's
    corporate-announcements endpoint.

    Endpoint:
        GET https://www.nseindia.com/api/corporate-announcements
            ?index=equities
            &category=Financial Results
            &from_date=DD-MM-YYYY
            &to_date=DD-MM-YYYY

    Response shape (each item, observed fields):
        symbol       — NSE symbol
        an_dt        — announcement datetime
        attchmntFile — PDF link
        desc / sm_name / smIndustry — description text
        subject      — short subject line (when present)

    Returns a list of dicts: {ticker, event_date, purpose, source}.
    On any failure returns []. NEVER raises — the caller treats an empty
    list as "fall back to event-calendar only".

    Note: we paginate defensively. If the upstream returns a flat list
    (no pagination marker), we accept it as a single page.
    """
    today = date.today()
    # NSE accepts DD-MM-YYYY for announcement window. We pull a slightly
    # wider lookback (the intimation is typically issued 7–14d before the
    # meeting) so we don't miss imminent events.
    from_date = (today - timedelta(days=14)).strftime("%d-%m-%Y")
    to_date = (today + timedelta(days=days_window)).strftime("%d-%m-%Y")

    collected: list[dict] = []
    cutoff = today + timedelta(days=days_window)

    for page in range(1, NSE_CORP_ANN_MAX_PAGES + 1):
        params = {
            "index": "equities",
            "category": "Financial Results",
            "from_date": from_date,
            "to_date": to_date,
        }
        # Page parameter — some NSE endpoints accept `page`/`pageNo`.
        # We include `page` defensively; if the endpoint ignores it,
        # the same payload comes back and we break out below.
        if page > 1:
            params["page"] = page

        try:
            resp = session.get(
                NSE_CORP_ANNOUNCEMENTS_URL,
                params=params,
                timeout=30,
            )
        except Exception as e:
            logger.error(
                f"NSE corporate-announcements fetch failed on page {page}: {e}"
            )
            break

        if resp.status_code != 200:
            logger.warning(
                f"NSE corporate-announcements returned HTTP "
                f"{resp.status_code} on page {page}"
            )
            break

        try:
            payload = resp.json()
        except Exception as e:
            logger.error(
                f"NSE corporate-announcements JSON parse failed on page "
                f"{page}: {e}"
            )
            break

        # Response can be a bare list or {"rows": [...]} / {"data": [...]}
        if isinstance(payload, dict):
            rows = (
                payload.get("rows")
                or payload.get("data")
                or payload.get("results")
                or []
            )
        elif isinstance(payload, list):
            rows = payload
        else:
            rows = []

        if not rows:
            break

        page_items = 0
        for item in rows:
            if not isinstance(item, dict):
                continue
            symbol = str(item.get("symbol", "") or "").strip().upper()
            if not symbol:
                continue

            subject = str(item.get("subject", "") or item.get("subjectLine", "") or "")
            desc = str(
                item.get("desc", "")
                or item.get("smIndustry", "")
                or item.get("attchmntText", "")
                or ""
            )

            if not _is_results_intimation(subject, desc):
                continue

            event_date = _extract_meeting_date(subject, desc)
            if event_date is None:
                # Fall back to announcement date if we can't parse a
                # meeting date — but only if it's still forward-looking.
                an_dt = str(item.get("an_dt", "") or "").strip()
                event_date = _parse_event_date(an_dt.split(" ")[0]) if an_dt else None
                if event_date is None:
                    continue

            if event_date < today or event_date > cutoff:
                continue

            purpose = (subject or desc or "Financial Results").strip()[:500]
            collected.append(
                {
                    "ticker": symbol,
                    "event_date": event_date,
                    "event_type": "Financial Results",
                    "purpose": purpose,
                    "source": SOURCE_CORP_ANNOUNCEMENTS,
                    "confirmed": True,
                }
            )
            page_items += 1

        # Heuristic stop: if the endpoint doesn't paginate the same payload
        # will repeat. We stop after a page with zero new items OR when
        # fewer rows than a typical page (50) come back.
        if page_items == 0 or len(rows) < 20:
            break

        # Polite delay before next page
        time.sleep(NSE_PAGINATION_SLEEP_SEC)

    logger.info(
        f"NSE corporate-announcements: {len(collected)} intimations found "
        f"(window {from_date} → {to_date})"
    )
    return collected


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


def _collect_event_calendar_items(session, today: date, cutoff: date) -> list[dict]:
    """
    Pull Financial-Results items from the small `event-calendar` agenda.
    Used as a CORROBORATOR to corporate-announcements (Phase 1, 2026-06-07).
    """
    events = _fetch_json_calendar(session)
    items: list[dict] = []
    if not events:
        return items

    for ev in events:
        purpose = str(ev.get("purpose", "") or ev.get("bm_desc", "") or "")
        if not _is_financial_results(purpose):
            continue

        symbol = str(ev.get("symbol", "") or "").strip().upper()
        date_str = str(ev.get("date", "") or ev.get("bm_date", "") or "").strip()
        if not symbol or not date_str:
            continue

        event_date = _parse_event_date(date_str)
        if event_date is None:
            continue

        if event_date < today or event_date > cutoff:
            continue

        items.append(
            {
                "ticker": symbol,
                "event_date": event_date,
                "event_type": "Financial Results",
                "purpose": purpose[:500],
                "source": SOURCE_EVENT_CALENDAR,
                "confirmed": False,  # event-calendar is a soft agenda hint
            }
        )

    logger.info(f"NSE event-calendar: {len(items)} Financial Results items")
    return items


def _merge_and_dedupe(
    primary: list[dict], corroborator: list[dict]
) -> list[dict]:
    """
    Merge two earnings-event lists.

    Dedupe key: (ticker, event_date).
    When the same (ticker, event_date) exists in both:
      * keep the PRIMARY (corporate-announcements) row
      * set confirmed=True (primary is a confirmed intimation; corroborator
        bumps confidence but does not downgrade it)

    Order of arguments matters: `primary` wins on collisions.
    """
    merged: dict[tuple[str, date], dict] = {}
    for item in primary:
        key = (item["ticker"], item["event_date"])
        merged[key] = dict(item)

    for item in corroborator:
        key = (item["ticker"], item["event_date"])
        if key in merged:
            # Both sources agree → confirmed
            merged[key]["confirmed"] = True
            continue
        merged[key] = dict(item)

    return list(merged.values())


def fetch_earnings_dates(db: Session) -> int:
    """
    Fetch upcoming earnings dates from NSE and store in the database.

    Phase 1 (2026-06-07): two-source strategy.
      1. PRIMARY: `corporate-announcements?category=Financial Results`
         — the actual stream of board-meeting intimations.
      2. CORROBORATOR: `event-calendar` — small forward-looking agenda;
         when it agrees with primary on (ticker, event_date), the row is
         marked confirmed=True.

    Only stores events within the next 90 days. Returns total number of
    earnings events stored (insert + update).
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

    # ── PRIMARY: corporate-announcements (Financial Results intimations) ─
    try:
        primary_items = fetch_from_corporate_announcements(session, days_window=90)
    except Exception as e:
        # NEVER fail the whole sync because the new source choked —
        # fall back to event-calendar only, as Phase 0 recommended.
        logger.error(
            f"corporate-announcements fetch raised; falling back to "
            f"event-calendar only: {e}"
        )
        primary_items = []

    # ── CORROBORATOR: event-calendar ─────────────────────────────────────
    corroborator_items = _collect_event_calendar_items(session, today, cutoff)

    earnings_items = _merge_and_dedupe(primary_items, corroborator_items)
    logger.info(
        f"NSE earnings merge: {len(primary_items)} primary + "
        f"{len(corroborator_items)} corroborator → {len(earnings_items)} unique"
    )

    # ── CSV fallback ONLY if both NSE JSON sources yielded nothing ──────
    if not earnings_items:
        logger.info("Both NSE JSON sources empty, trying CSV fallback")
        csv_events = _fetch_csv_fallback(session)

        for ev in csv_events:
            symbol = ev["symbol"].strip().upper()
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
                    "source": "nse_corporate_actions_csv",
                    "confirmed": False,
                }
            )

        logger.info(f"NSE CSV fallback: {len(earnings_items)} earnings events found")

    if not earnings_items:
        logger.info("No upcoming earnings events found")
        return 0

    # ── Store in DB ──────────────────────────────────────────
    now_utc = datetime.utcnow()
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
                existing.updated_at = now_utc
                existing.source = item.get("source")
                existing.confirmed = bool(item.get("confirmed", False))
                existing.fetched_at = now_utc
            else:
                db.add(
                    UpcomingEarnings(
                        ticker=item["ticker"],
                        event_date=item["event_date"],
                        event_type=item["event_type"],
                        purpose=item["purpose"],
                        updated_at=now_utc,
                        source=item.get("source"),
                        confirmed=bool(item.get("confirmed", False)),
                        fetched_at=now_utc,
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
