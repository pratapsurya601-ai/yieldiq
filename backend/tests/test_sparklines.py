"""Tests for /api/v1/sparklines.

Covers the three contract properties the frontend home-page panels rely
on:

  1. Happy path — batched tickers each get their 7 daily closes
     oldest→newest, with suspended (zero-row) tickers omitted.
  2. Tickers list above the TICKER_CAP cap returns HTTP 400 (defends
     against accidental fan-out loops in the frontend).
  3. Unsupported period values return HTTP 400 rather than silently
     falling back to 7d.

As with `test_today_movers.py`, the SQLAlchemy session is replaced by a
hand-rolled fake so the suite stays offline (no Postgres dependency).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import HTTPException

# Project root on path so `backend.*` and `data_pipeline.*` resolve.
_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    """Captures execute() and replays from a queue. Mirrors the contract
    test_today_movers.py's _FakeSession uses — sparklines.py issues a
    single SQL statement, so the queue is single-entry per call."""

    def __init__(self, rows):
        self._rows = rows
        self.calls = []

    def execute(self, stmt, params=None):
        self.calls.append((str(stmt), params or {}))
        return _FakeResult(self._rows)

    def close(self):
        pass


@pytest.fixture
def patch_session(monkeypatch):
    def _install(rows):
        sess = _FakeSession(rows)

        class _SessionClass:
            def __new__(cls):
                return sess

        import data_pipeline.db as _db
        monkeypatch.setattr(_db, "Session", _SessionClass)
        return sess

    return _install


def _import_router():
    """Late import so monkeypatching of data_pipeline.db lands first."""
    from backend.routers import sparklines as spark
    return spark


def test_fetch_sparklines_returns_ordered_closes_per_ticker(patch_session):
    """Happy path — HDFCBANK + RELIANCE each emit oldest→newest closes."""
    today = date.today()
    # Two tickers, 4 close prices each. The SQL emits one row per
    # (ticker, trade_date) — we hand-roll the result rows the function
    # would have read out of daily_prices.
    rows = []
    for i, tk in enumerate(["HDFCBANK.NS", "RELIANCE.NS"]):
        for d_off in range(4):
            rows.append((tk, today - timedelta(days=3 - d_off), 100.0 + i + d_off))
    sess = patch_session(rows)
    spark = _import_router()

    out = spark._fetch_sparklines(["HDFCBANK", "RELIANCE"], days=7)

    # Both tickers present. The frontend asked for them WITHOUT the .NS
    # suffix — the fetcher matches both forms and keys the result by the
    # input string (so the React component looks them up directly under
    # the same string it requested).
    assert set(out.keys()) == {"HDFCBANK", "RELIANCE"}
    # Each series carries 4 closes (one per row).
    assert len(out["HDFCBANK"]) == 4
    assert len(out["RELIANCE"]) == 4
    # Ordered oldest→newest. HDFCBANK rows had close = 100.0 + 0 + d_off
    # = 100, 101, 102, 103 for d_off=0..3.
    assert out["HDFCBANK"] == [100.0, 101.0, 102.0, 103.0]
    assert out["RELIANCE"] == [101.0, 102.0, 103.0, 104.0]
    # SQL was issued exactly once (single batched query, not N-fan-out).
    assert len(sess.calls) == 1


def test_fetch_sparklines_omits_single_point_tickers(patch_session):
    """Tickers with < 2 closes in the window are absent from the result."""
    today = date.today()
    # SUSP has only one row in the window — Sparkline component renders
    # null for length < 2, so the fetcher should not bother carrying it
    # to the wire. Rows mirror the SQL's `ORDER BY ticker, trade_date`
    # ascending output so our fake-session contract matches production.
    rows = [
        ("LIVE.NS", today - timedelta(days=1), 99.0),
        ("LIVE.NS", today, 100.0),
        ("SUSP.NS", today, 50.0),  # only one row
    ]
    patch_session(rows)
    spark = _import_router()

    out = spark._fetch_sparklines(["LIVE", "SUSP"], days=7)

    # Single-point ticker is dropped; multi-point ticker survives.
    assert "LIVE" in out
    assert "SUSP" not in out
    assert out["LIVE"] == [99.0, 100.0]


def test_get_sparklines_rejects_oversized_ticker_list(patch_session):
    """Asking for > TICKER_CAP tickers returns HTTP 400, not a silent trim."""
    spark = _import_router()
    # Sanity: cap is the value defended by this test. Locked here so a
    # future bump to the cap forces the test to be edited too.
    assert spark.TICKER_CAP == 50

    # Craft a payload of TICKER_CAP + 1 dummy tickers.
    oversized = ",".join(f"TKR{i:03d}" for i in range(spark.TICKER_CAP + 1))

    import asyncio
    with pytest.raises(HTTPException) as exc:
        asyncio.get_event_loop().run_until_complete(
            spark.get_sparklines(user={"sub": "test"}, tickers=oversized, period="7d")
        )
    assert exc.value.status_code == 400
    assert "cap" in str(exc.value.detail).lower()


def test_get_sparklines_rejects_unsupported_period(patch_session):
    """`period` other than 7d/30d returns HTTP 400, never silently 7d."""
    spark = _import_router()
    import asyncio
    with pytest.raises(HTTPException) as exc:
        asyncio.get_event_loop().run_until_complete(
            spark.get_sparklines(user={"sub": "test"}, tickers="HDFCBANK", period="90d")
        )
    assert exc.value.status_code == 400
    assert "period" in str(exc.value.detail).lower()
