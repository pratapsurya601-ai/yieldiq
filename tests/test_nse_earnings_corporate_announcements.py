# tests/test_nse_earnings_corporate_announcements.py
# ════════════════════════════════════════════════════════════════════
# Unit tests for the Phase 1 corporate-announcements ingest path in
# data_pipeline/sources/nse_earnings.py.
#
# Phase 0 finding (redesign/followups/earnings-calendar-ingest-phase0.md):
# `event-calendar` is a 13-row board-meeting agenda slice. The real
# stream of Financial Results intimations lives at
#   https://www.nseindia.com/api/corporate-announcements
#     ?index=equities&category=Financial Results
#
# These tests are hermetic — they monkeypatch the NSE session so no
# live HTTP is made. They assert:
#   1. fetch_from_corporate_announcements parses intimation rows and
#      rejects past-results rows.
#   2. fetch_earnings_dates merges both sources and dedupes on
#      (ticker, event_date), with source="nse_corporate_announcements"
#      winning collisions and confirmed=True.
#   3. When corporate-announcements raises, event-calendar still runs
#      and the sync does not fail.
# ════════════════════════════════════════════════════════════════════
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from data_pipeline.sources import nse_earnings  # noqa: E402


# ── Helpers ─────────────────────────────────────────────────────────


def _future_date(days_from_today: int) -> date:
    return date.today() + timedelta(days=days_from_today)


def _dmy(d: date) -> str:
    """Format date as DD-MM-YYYY (NSE intimation style)."""
    return d.strftime("%d-%m-%Y")


def _fake_response(payload, status_code: int = 200):
    """Return a stub response object matching the curl_cffi shape used."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.json.return_value = payload
    return resp


# ── 1. fetch_from_corporate_announcements parses + filters ──────────


def test_corp_announcements_parses_intimations_and_rejects_past_results(
    monkeypatch,
):
    """
    The parser must accept forward-looking intimations and reject
    rows describing past results (Outcome of Board Meeting / Results
    for the quarter ended …).
    """
    meeting = _future_date(20)

    rows = [
        # 1. Clean intimation — should be accepted.
        {
            "symbol": "RELIANCE",
            "subject": (
                f"Intimation of Board Meeting scheduled to be held on "
                f"{_dmy(meeting)} to consider Financial Results"
            ),
            "desc": "",
            "an_dt": (date.today() - timedelta(days=2)).strftime("%d-%b-%Y"),
        },
        # 2. Past-results row — must be rejected.
        {
            "symbol": "TCS",
            "subject": "Outcome of Board Meeting",
            "desc": "Audited Financial Results for the quarter ended 31-Mar-2026",
            "an_dt": (date.today() - timedelta(days=1)).strftime("%d-%b-%Y"),
        },
        # 3. Intimation with date in desc, not subject — should be accepted.
        {
            "symbol": "INFY",
            "subject": "Intimation under Reg 29",
            "desc": (
                f"Notice of board meeting on {_dmy(_future_date(10))} "
                f"to consider unaudited results"
            ),
            "an_dt": "",
        },
        # 4. Missing symbol — must be rejected.
        {
            "symbol": "",
            "subject": "Intimation of Board Meeting",
            "desc": f"To be held on {_dmy(meeting)}",
            "an_dt": "",
        },
    ]

    session = MagicMock()
    session.get.return_value = _fake_response(rows)

    result = nse_earnings.fetch_from_corporate_announcements(
        session, days_window=90
    )

    tickers = {r["ticker"] for r in result}
    assert "RELIANCE" in tickers, "Clean intimation must be accepted"
    assert "INFY" in tickers, "Date-in-desc intimation must be accepted"
    assert "TCS" not in tickers, "Past-results row must be rejected"
    assert "" not in tickers, "Empty-symbol row must be rejected"

    for r in result:
        assert r["source"] == "nse_corporate_announcements"
        assert r["confirmed"] is True
        assert r["event_type"] == "Financial Results"
        assert isinstance(r["event_date"], date)
        assert r["event_date"] >= date.today()


# ── 2. Merge + dedupe across both sources ──────────────────────────


def test_merge_dedupes_on_ticker_and_event_date_prefers_corp_announcements():
    """
    When the same (ticker, event_date) shows up in both sources, the
    corporate-announcements row wins, confirmed flips to True, and the
    source label is `nse_corporate_announcements`.
    """
    meeting = _future_date(15)

    primary = [
        {
            "ticker": "RELIANCE",
            "event_date": meeting,
            "event_type": "Financial Results",
            "purpose": "Intimation of board meeting",
            "source": "nse_corporate_announcements",
            "confirmed": True,
        },
    ]
    corroborator = [
        {
            # Collides with primary — should be deduped.
            "ticker": "RELIANCE",
            "event_date": meeting,
            "event_type": "Financial Results",
            "purpose": "event-calendar agenda entry",
            "source": "nse_event_calendar",
            "confirmed": False,
        },
        {
            # Unique to corroborator — should pass through.
            "ticker": "HDFCBANK",
            "event_date": _future_date(25),
            "event_type": "Financial Results",
            "purpose": "agenda only",
            "source": "nse_event_calendar",
            "confirmed": False,
        },
    ]

    merged = nse_earnings._merge_and_dedupe(primary, corroborator)
    by_ticker = {(r["ticker"], r["event_date"]): r for r in merged}

    assert len(merged) == 2, "Dedupe must collapse the collision"

    reliance = by_ticker[("RELIANCE", meeting)]
    assert reliance["source"] == "nse_corporate_announcements"
    assert reliance["confirmed"] is True
    assert reliance["purpose"] == "Intimation of board meeting"

    hdfc = by_ticker[("HDFCBANK", _future_date(25))]
    assert hdfc["source"] == "nse_event_calendar"


# ── 3. fetch_earnings_dates end-to-end with both sources mocked ────


def test_fetch_earnings_dates_merges_both_sources_into_db(monkeypatch):
    """
    Mock corporate-announcements + event-calendar at the HTTP boundary;
    use an in-memory SQLite DB for storage. Assert the merged events
    land in upcoming_earnings with the right source/confirmed flags.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from data_pipeline.models import Base, UpcomingEarnings

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    meeting_reliance = _future_date(12)
    meeting_infy = _future_date(20)
    meeting_hdfc = _future_date(8)

    corp_ann_rows = [
        {
            "symbol": "RELIANCE",
            "subject": (
                f"Intimation of Board Meeting on {_dmy(meeting_reliance)} "
                f"to consider Financial Results"
            ),
            "desc": "",
            "an_dt": "",
        },
        {
            "symbol": "INFY",
            "subject": (
                f"Notice of Board Meeting to consider results on "
                f"{_dmy(meeting_infy)}"
            ),
            "desc": "",
            "an_dt": "",
        },
    ]

    event_cal_rows = [
        # Collides with RELIANCE primary → should bump confirmed flag.
        {
            "symbol": "RELIANCE",
            "purpose": "Financial Results",
            "date": meeting_reliance.strftime("%d-%b-%Y"),
        },
        # Unique to event-calendar.
        {
            "symbol": "HDFCBANK",
            "purpose": "Quarterly Results",
            "date": meeting_hdfc.strftime("%d-%b-%Y"),
        },
    ]

    fake_session = MagicMock()

    def _get(url, *args, **kwargs):
        if "corporate-announcements" in url:
            return _fake_response(corp_ann_rows)
        if "event-calendar" in url:
            return _fake_response(event_cal_rows)
        # NSE homepage warm-up / anything else
        return _fake_response({}, status_code=200)

    fake_session.get.side_effect = _get

    monkeypatch.setattr(
        nse_earnings, "_get_nse_session", lambda: fake_session
    )
    # Skip the polite sleep in tests.
    monkeypatch.setattr(nse_earnings.time, "sleep", lambda *_: None)

    stored = nse_earnings.fetch_earnings_dates(db)
    assert stored == 3, f"Expected 3 merged rows, got {stored}"

    rows = {(r.ticker, r.event_date): r for r in db.query(UpcomingEarnings).all()}
    assert len(rows) == 3

    reliance = rows[("RELIANCE", meeting_reliance)]
    assert reliance.source == "nse_corporate_announcements"
    assert reliance.confirmed is True

    infy = rows[("INFY", meeting_infy)]
    assert infy.source == "nse_corporate_announcements"
    assert infy.confirmed is True

    hdfc = rows[("HDFCBANK", meeting_hdfc)]
    assert hdfc.source == "nse_event_calendar"
    # event-calendar alone is a soft agenda hint
    assert hdfc.confirmed is False

    db.close()


# ── 4. Resilience: corp-announcements raises → fall back gracefully ──


def test_fetch_earnings_dates_falls_back_when_corp_announcements_raises(
    monkeypatch,
):
    """
    If corporate-announcements blows up (rate-limit, network), we must
    still ingest from event-calendar. The whole sync must not fail.
    """
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker

    from data_pipeline.models import Base, UpcomingEarnings

    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    Session = sessionmaker(bind=engine)
    db = Session()

    meeting = _future_date(7)
    event_cal_rows = [
        {
            "symbol": "TCS",
            "purpose": "Financial Results",
            "date": meeting.strftime("%d-%b-%Y"),
        },
    ]

    fake_session = MagicMock()

    def _get(url, *args, **kwargs):
        if "event-calendar" in url:
            return _fake_response(event_cal_rows)
        return _fake_response({}, status_code=200)

    fake_session.get.side_effect = _get

    monkeypatch.setattr(
        nse_earnings, "_get_nse_session", lambda: fake_session
    )
    monkeypatch.setattr(nse_earnings.time, "sleep", lambda *_: None)

    def _boom(*_args, **_kwargs):
        raise RuntimeError("simulated upstream failure")

    monkeypatch.setattr(
        nse_earnings, "fetch_from_corporate_announcements", _boom
    )

    stored = nse_earnings.fetch_earnings_dates(db)
    assert stored == 1, f"Expected event-calendar-only row, got {stored}"

    row = db.query(UpcomingEarnings).filter_by(ticker="TCS").one()
    assert row.source == "nse_event_calendar"
    assert row.confirmed is False
    db.close()
