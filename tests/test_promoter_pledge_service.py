"""Unit tests for backend.services.promoter_pledge_service.

The service talks to Postgres via a raw psycopg2-style cursor obtained
from `_get_raw_cursor()`. Rather than spinning up a real DB in CI, we
patch that function with a tiny in-memory fake fed from the bundled
JSON fixture (`tests/fixtures/sample_pledges.json`).

This pins the math (latest-snapshot lookup + pp-change vs N days ago)
without taking a DB dependency. Once we wire a real test DB this can
be flipped to use the actual engine — the SQL strings are identical.
"""
from __future__ import annotations

import json
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import promoter_pledge_service as pps  # noqa: E402


FIXTURE = ROOT / "tests" / "fixtures" / "sample_pledges.json"


# ── Fake cursor ───────────────────────────────────────────────


class _FakeCursor:
    """Very small subset of psycopg2 cursor: handles the two queries
    the service issues (latest-by-ticker, latest-on-or-before-cutoff).
    Both queries select the same six columns in the same order."""

    _COLS = (
        "ticker", "as_of_date", "promoter_group_pct",
        "pledged_pct", "pledged_shares", "source_url",
    )

    def __init__(self, rows: list[dict]):
        # Normalize as_of_date to a real date object.
        self._rows = []
        for r in rows:
            r = dict(r)
            if isinstance(r["as_of_date"], str):
                r["as_of_date"] = date.fromisoformat(r["as_of_date"])
            self._rows.append(r)
        self._result: list[tuple] = []

    def execute(self, sql: str, params: tuple) -> None:
        sql_norm = " ".join(sql.split())
        if "as_of_date <= %s" in sql_norm:
            ticker, cutoff = params
            matching = [
                r for r in self._rows
                if r["ticker"] == ticker and r["as_of_date"] <= cutoff
            ]
        else:
            (ticker,) = params
            matching = [r for r in self._rows if r["ticker"] == ticker]
        matching.sort(key=lambda r: r["as_of_date"], reverse=True)

        if "SELECT ticker," in sql_norm:
            self._result = [
                (r["ticker"], r["as_of_date"], r["promoter_group_pct"],
                 r["pledged_pct"], r["pledged_shares"], r["source_url"])
                for r in matching[:1]
            ]
        else:
            # The compute_pledge_change_pp query selects (as_of_date, pledged_pct).
            self._result = [
                (r["as_of_date"], r["pledged_pct"]) for r in matching[:1]
            ]

    def fetchone(self):
        return self._result[0] if self._result else None

    def close(self):
        pass


class _FakeConn:
    def close(self):
        pass


@pytest.fixture
def patched_cursor(monkeypatch):
    rows = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def _factory():
        return _FakeConn(), _FakeCursor(rows)

    monkeypatch.setattr(pps, "_get_raw_cursor", _factory)
    return rows


# ── Tests ─────────────────────────────────────────────────────


def test_get_latest_pledge_returns_most_recent(patched_cursor):
    row = pps.get_latest_pledge("RCOM")
    assert row is not None
    assert row.ticker == "RCOM"
    assert row.as_of_date == date(2026, 1, 31)
    assert row.pledged_pct == pytest.approx(80.0)
    assert row.pledged_shares == 4_400_000_000


def test_get_latest_pledge_unknown_ticker(patched_cursor):
    assert pps.get_latest_pledge("NOPE") is None


def test_get_latest_pledge_returns_zero_pledge(patched_cursor):
    """RELIANCE has a single 0% snapshot — important the service still
    returns a row, not None (None vs 0% is a meaningful UI distinction)."""
    row = pps.get_latest_pledge("RELIANCE")
    assert row is not None
    assert row.pledged_pct == pytest.approx(0.0)


def test_compute_pledge_change_pp_increasing(patched_cursor):
    # RCOM: Oct=65%, Jan=80%. 92 days apart, lookback 90d picks the Oct row.
    delta = pps.compute_pledge_change_pp("RCOM", lookback_days=90)
    assert delta == pytest.approx(15.0)


def test_compute_pledge_change_pp_decreasing(patched_cursor):
    # JINDALSTEL: Oct=22.5%, Jan=20%. Pledge wound down — negative delta.
    delta = pps.compute_pledge_change_pp("JINDALSTEL", lookback_days=90)
    assert delta == pytest.approx(-2.5)


def test_compute_pledge_change_pp_flat(patched_cursor):
    # TATASTEEL: 5% in both snapshots. Delta == 0, NOT None.
    delta = pps.compute_pledge_change_pp("TATASTEEL", lookback_days=90)
    assert delta == pytest.approx(0.0)


def test_compute_pledge_change_pp_no_prior(patched_cursor):
    # RELIANCE only has one row — no comparison point.
    assert pps.compute_pledge_change_pp("RELIANCE", lookback_days=90) is None


def test_compute_pledge_change_pp_unknown_ticker(patched_cursor):
    assert pps.compute_pledge_change_pp("NOPE", lookback_days=90) is None


def test_fetch_from_bse_returns_empty_when_no_bse_code(monkeypatch):
    """Real scraper landed; with no bse_code lookup it returns [] (not raises)."""
    monkeypatch.setattr(pps, "_bse_code_for", lambda t: None)
    assert pps.fetch_from_bse("UNKNOWN") == []


def test_fetch_from_nse_returns_empty_on_test_seam_failure():
    """``fetch_from_nse`` accepts a test seam via fetch_from_nse_bulk; with
    no network and the bulk call returning {}, single-ticker returns []."""
    # The default fetch_from_nse calls fetch_from_nse_bulk which without a
    # test seam tries the real network; we patch it to short-circuit.
    import unittest.mock as mock
    with mock.patch.object(pps, "fetch_from_nse_bulk", return_value={}):
        assert pps.fetch_from_nse("RCOM") == []
