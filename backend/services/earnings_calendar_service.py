"""
backend/services/earnings_calendar_service.py
─────────────────────────────────────────────────────────────────────
Single source of truth for "when does this company next report?".

Background
----------
Before feat/earnings-calendar-unification, four surfaces each
reached for earnings dates differently:

  1. Analysis page Summary card  → _query_earnings_date (NSE table)
                                    with finnhub fallback inline in
                                    analysis/service.py
  2. Discover "Earnings This Week"→ /api/v1/public/earnings-calendar
                                    (NSE table only)
  3. Home EarningsWeekStrip       → same public endpoint
  4. Earnings Calendar page       → same public endpoint

That mostly worked, but the analysis-page card would silently fall
through to "Not scheduled" for every Nifty-50 ticker on days when the
NSE event-calendar API blanked (which it does periodically — see
incident on 2026-05-17 where every Nifty-50 row was "Not scheduled"
even though ITC's 21-May filing was indexed by every other surface).

This service is the single chokepoint for all four surfaces. It:

  • prefers the NSE event-calendar row (confirmed=True)
  • falls back to yfinance .info.earningsTimestamp / earningsDate
    (confirmed=False)
  • derives a display-ready days_until + fiscal_period label
  • returns None when there is genuinely no signal — callers MUST
    hide their card rather than render "Not scheduled"

The schema is a thin dataclass (EarningsEvent) so the analysis
service can compose the response without taking a dependency on the
SQLAlchemy model class.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, asdict
from datetime import date, datetime, timedelta
from typing import Optional

from sqlalchemy.orm import Session

logger = logging.getLogger("yieldiq.earnings_calendar")

# yfinance fetches are cached at the service level for 6 hours; the
# DB row written by _persist_yfinance_fallback is the durable cache.
_YF_RECHECK_HOURS = 6


@dataclass
class EarningsEvent:
    """Display-ready earnings event payload. None means "no event"."""
    date: str            # ISO yyyy-mm-dd
    days_until: int      # negative if event is in the past (shouldn't happen)
    confirmed: bool      # True = NSE filing, False = yfinance/finnhub guess
    source: str          # 'nse_event_calendar' | 'yfinance' | 'finnhub' | 'manual_backfill'
    fiscal_period: Optional[str] = None  # e.g. 'Q1FY27'
    event_type: Optional[str] = None
    purpose: Optional[str] = None

    def to_dict(self) -> dict:
        return asdict(self)


# ──────────────────────────────────────────────────────────────────
# Helpers
# ──────────────────────────────────────────────────────────────────
def _indian_fiscal_period(d: date) -> str:
    """Return 'Q1FY27' style label for a calendar date.

    Indian fiscal year runs Apr–Mar; FY27 = Apr 2026 → Mar 2027.
    A filing dated 21-May-2026 reports Q4FY26 (results for Jan–Mar
    2026) most commonly, but we cannot know without the filing
    body — so this label is best understood as the CALENDAR quarter
    of the filing, not the period being reported. Frontend renders
    it as a subtle hint ("Reports in Q1FY27"), never as a contract.
    """
    m = d.month
    y = d.year
    if m <= 3:
        # Jan–Mar → Q4 of FY ending this March
        return f"Q4FY{str(y)[2:]}"
    fy_end = y + 1
    if m <= 6:
        return f"Q1FY{str(fy_end)[2:]}"
    if m <= 9:
        return f"Q2FY{str(fy_end)[2:]}"
    return f"Q3FY{str(fy_end)[2:]}"


def _strip_suffix(ticker: str) -> str:
    return ticker.replace(".NS", "").replace(".BO", "")


# ──────────────────────────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────────────────────────
def get_next_earnings(ticker: str, db: Session) -> Optional[EarningsEvent]:
    """Return the next upcoming earnings event for `ticker`, or None.

    Resolution order:
      1. `upcoming_earnings` row from NSE event calendar (confirmed)
      2. yfinance .info.earningsTimestamp / earningsDate (unconfirmed)
      3. None  — caller MUST hide its UI in this case.

    Never raises — all backend lookups are wrapped in try/except so
    that a flaky NSE or yfinance never breaks the analysis response.
    """
    clean = _strip_suffix(ticker)
    today = date.today()

    # ── 1. NSE event-calendar (preferred) ────────────────────────
    try:
        from data_pipeline.models import UpcomingEarnings
        row = (
            db.query(UpcomingEarnings)
            .filter(
                UpcomingEarnings.ticker == clean,
                UpcomingEarnings.event_date >= today,
            )
            .order_by(UpcomingEarnings.event_date.asc())
            .first()
        )
        if row is not None:
            src = row.source or "nse_event_calendar"
            confirmed = (
                row.confirmed
                if row.confirmed is not None
                # Legacy rows pre-040: NSE cron only wrote confirmed
                # rows, so default to True for back-compat.
                else (src == "nse_event_calendar")
            )
            return EarningsEvent(
                date=str(row.event_date),
                days_until=(row.event_date - today).days,
                confirmed=bool(confirmed),
                source=src,
                fiscal_period=row.fiscal_period or _indian_fiscal_period(row.event_date),
                event_type=row.event_type or "Financial Results",
                purpose=row.purpose or "",
            )
    except Exception as exc:
        logger.debug("NSE earnings lookup failed for %s: %s", clean, exc)

    # ── 2. yfinance fallback (unconfirmed) ───────────────────────
    yf_event = _try_yfinance(ticker, today)
    if yf_event is not None:
        # Persist the fallback so subsequent calls (and other
        # surfaces) hit the DB rather than yfinance. The fallback
        # row is marked confirmed=False so the UI can render a
        # tentative badge.
        try:
            _persist_yfinance_fallback(clean, yf_event, db)
        except Exception as exc:
            logger.debug("persist yf fallback failed for %s: %s", clean, exc)
        return yf_event

    return None


def get_next_earnings_dict(ticker: str, db: Session) -> Optional[dict]:
    """Dict-shaped wrapper for callers that want JSON-ready output."""
    ev = get_next_earnings(ticker, db)
    return ev.to_dict() if ev else None


# ──────────────────────────────────────────────────────────────────
# yfinance fallback
# ──────────────────────────────────────────────────────────────────
def _try_yfinance(ticker: str, today: date) -> Optional[EarningsEvent]:
    try:
        import yfinance as yf
    except Exception:
        return None

    yf_ticker = ticker if ticker.endswith((".NS", ".BO")) else f"{ticker}.NS"
    try:
        info = yf.Ticker(yf_ticker).info or {}
    except Exception as exc:
        logger.debug("yfinance .info failed for %s: %s", yf_ticker, exc)
        return None

    ts = info.get("earningsTimestamp") or info.get("earningsTimestampStart")
    ev_date: Optional[date] = None
    if isinstance(ts, (int, float)) and ts > 0:
        try:
            ev_date = datetime.utcfromtimestamp(int(ts)).date()
        except Exception:
            ev_date = None

    # Some sectors only get earningsDate (list of strings)
    if ev_date is None:
        dates = info.get("earningsDate")
        if isinstance(dates, (list, tuple)) and dates:
            try:
                # earningsDate items are sometimes timestamp ints,
                # sometimes 'YYYY-MM-DD' strings, sometimes datetimes.
                first = dates[0]
                if isinstance(first, (int, float)):
                    ev_date = datetime.utcfromtimestamp(int(first)).date()
                elif isinstance(first, str):
                    ev_date = datetime.fromisoformat(first[:10]).date()
                elif isinstance(first, datetime):
                    ev_date = first.date()
            except Exception:
                ev_date = None

    if ev_date is None or ev_date < today:
        return None

    return EarningsEvent(
        date=str(ev_date),
        days_until=(ev_date - today).days,
        confirmed=False,
        source="yfinance",
        fiscal_period=_indian_fiscal_period(ev_date),
        event_type="Financial Results (expected)",
        purpose="yfinance projected earnings date — not yet filed with NSE",
    )


def _persist_yfinance_fallback(
    clean_ticker: str, event: EarningsEvent, db: Session
) -> None:
    """Upsert a yfinance fallback into upcoming_earnings."""
    from data_pipeline.models import UpcomingEarnings
    try:
        ev_date = datetime.fromisoformat(event.date).date()
    except Exception:
        return
    existing = (
        db.query(UpcomingEarnings)
        .filter_by(ticker=clean_ticker, event_date=ev_date)
        .first()
    )
    now = datetime.utcnow()
    if existing:
        # Never downgrade a confirmed NSE row with a yfinance guess.
        if existing.source == "nse_event_calendar" or existing.confirmed:
            return
        existing.source = event.source
        existing.confirmed = event.confirmed
        existing.fiscal_period = event.fiscal_period
        existing.event_type = event.event_type
        existing.purpose = event.purpose
        existing.fetched_at = now
        existing.updated_at = now
    else:
        db.add(
            UpcomingEarnings(
                ticker=clean_ticker,
                event_date=ev_date,
                event_type=event.event_type,
                purpose=event.purpose,
                source=event.source,
                confirmed=event.confirmed,
                fiscal_period=event.fiscal_period,
                fetched_at=now,
                updated_at=now,
            )
        )
    try:
        db.commit()
    except Exception:
        db.rollback()


# ──────────────────────────────────────────────────────────────────
# Backfill helper (used by scripts/backfill_earnings_calendar.py)
# ──────────────────────────────────────────────────────────────────
def refresh_all(tickers: list[str], db: Session) -> dict:
    """Refresh fallback rows for `tickers`. NSE cron handles the
    primary source; this fills gaps with yfinance projections."""
    today = date.today()
    inserted = 0
    skipped_confirmed = 0
    skipped_no_data = 0
    for t in tickers:
        clean = _strip_suffix(t)
        # If a confirmed row already exists in the window, skip yfinance.
        try:
            from data_pipeline.models import UpcomingEarnings
            existing = (
                db.query(UpcomingEarnings)
                .filter(
                    UpcomingEarnings.ticker == clean,
                    UpcomingEarnings.event_date >= today,
                    UpcomingEarnings.event_date <= today + timedelta(days=90),
                )
                .first()
            )
            if existing is not None and (
                existing.source == "nse_event_calendar" or existing.confirmed
            ):
                skipped_confirmed += 1
                continue
        except Exception:
            pass

        yf_event = _try_yfinance(t, today)
        if yf_event is None:
            skipped_no_data += 1
            continue
        try:
            _persist_yfinance_fallback(clean, yf_event, db)
            inserted += 1
        except Exception as exc:
            logger.debug("backfill persist failed for %s: %s", clean, exc)

    return {
        "inserted_or_updated": inserted,
        "skipped_already_confirmed": skipped_confirmed,
        "skipped_no_yfinance_data": skipped_no_data,
        "total": len(tickers),
    }
