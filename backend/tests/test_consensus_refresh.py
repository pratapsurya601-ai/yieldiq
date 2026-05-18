"""Tests for the Benchmark Reconciliation PR 1 refresh path.

These tests are pure offline — yfinance and Finnhub are mocked.
The database is an in-memory SQLite (sqlalchemy) with a schema that
matches the Postgres `consensus_estimates` table closely enough for
the upsert / idempotency assertions to be meaningful.

We test:
  1. yfinance fetch_one parses targetMeanPrice etc. correctly.
  2. yfinance fetch_one returns None when no targets are present.
  3. Finnhub fetch_one parses price-target JSON correctly.
  4. Finnhub fetch_one returns None when FINNHUB_API_KEY is unset.
  5. The yfinance refresh pass writes one row per ticker.
  6. The Finnhub refresh pass writes one row per ticker.
  7. Idempotency: re-running the same data with a frozen `now` adds
     zero new rows (the primary key + ON CONFLICT DO NOTHING does its job).
"""
from __future__ import annotations

import os
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from data_pipeline.sources import consensus_finnhub, consensus_yfinance
from scripts import refresh_consensus


# ── Test schema (SQLite-compatible mirror of 044_consensus_estimates.sql) ─

_TEST_SCHEMA_SQL = """
CREATE TABLE consensus_estimates (
    ticker        TEXT    NOT NULL,
    source        TEXT    NOT NULL,
    target_mean   NUMERIC,
    target_median NUMERIC,
    target_high   NUMERIC,
    target_low    NUMERIC,
    analyst_count INTEGER,
    currency      TEXT    DEFAULT 'INR',
    fetched_at    TEXT    NOT NULL DEFAULT '2026-05-18T00:00:00Z',
    PRIMARY KEY (ticker, source, fetched_at)
);
"""


@pytest.fixture()
def sess():
    eng = create_engine("sqlite:///:memory:", future=True)
    with eng.begin() as conn:
        conn.exec_driver_sql(_TEST_SCHEMA_SQL)
    Session = sessionmaker(bind=eng, future=True)
    s = Session()
    try:
        yield s
    finally:
        s.close()


# ── 1. yfinance parse: happy path ───────────────────────────────────


def test_yfinance_fetch_one_parses_targets():
    fake_info = {
        "targetMeanPrice": 305.0,
        "targetMedianPrice": 310.0,
        "targetHighPrice": 380.0,
        "targetLowPrice": 240.0,
        "numberOfAnalystOpinions": 24,
        "currency": "INR",
    }
    fake_yf = SimpleNamespace(
        Ticker=lambda sym: SimpleNamespace(info=fake_info),
    )

    row = consensus_yfinance.fetch_one("POWERGRID", yf_module=fake_yf)

    assert row is not None
    assert row["ticker"] == "POWERGRID"
    assert row["source"] == "yfinance"
    assert row["target_mean"] == 305.0
    assert row["target_median"] == 310.0
    assert row["target_high"] == 380.0
    assert row["target_low"] == 240.0
    assert row["analyst_count"] == 24
    assert row["currency"] == "INR"


# ── 2. yfinance returns None when targets absent ─────────────────────


def test_yfinance_fetch_one_returns_none_when_no_targets():
    fake_yf = SimpleNamespace(
        Ticker=lambda sym: SimpleNamespace(info={"shortName": "Foo"}),
    )
    assert consensus_yfinance.fetch_one("SMALLCAP", yf_module=fake_yf) is None


# ── 3. Finnhub parse: happy path ────────────────────────────────────


class _FakeResp:
    def __init__(self, payload):
        self._payload = payload
    def raise_for_status(self): return None
    def json(self): return self._payload


def test_finnhub_fetch_one_parses_price_target():
    pt_payload = {
        "targetMean": 305.5,
        "targetMedian": 300.0,
        "targetHigh": 410.0,
        "targetLow": 220.0,
        "numberOfAnalysts": 18,
    }
    calls = []

    def fake_get(url, params=None, timeout=None):
        calls.append((url, params))
        return _FakeResp(pt_payload)

    fake_requests = SimpleNamespace(get=fake_get)

    row = consensus_finnhub.fetch_one(
        "POWERGRID", api_key="test-key", requests_module=fake_requests,
    )

    assert row is not None
    assert row["source"] == "finnhub"
    assert row["target_mean"] == 305.5
    assert row["target_median"] == 300.0
    assert row["analyst_count"] == 18
    # Symbol should have been suffixed with .NS for the API call
    assert "POWERGRID.NS" in calls[0][1]["symbol"]


# ── 4. Finnhub returns None when key missing ────────────────────────


def test_finnhub_fetch_one_skips_when_no_api_key(monkeypatch):
    monkeypatch.delenv("FINNHUB_API_KEY", raising=False)
    assert consensus_finnhub.fetch_one("POWERGRID") is None


# ── 5. yfinance pass writes one row per ticker ──────────────────────


def _make_fake_yf_for(targets_by_ticker):
    """Returns a fake yfinance module that hands back a per-ticker info dict."""
    def ticker_factory(sym):
        bare = sym.replace(".NS", "")
        info = targets_by_ticker.get(bare, {})
        return SimpleNamespace(info=info)
    return SimpleNamespace(Ticker=ticker_factory)


def test_pass_yfinance_writes_rows(sess):
    targets = {
        "RELIANCE":  {"targetMeanPrice": 2900.0, "targetMedianPrice": 2950.0,
                      "numberOfAnalystOpinions": 30, "currency": "INR"},
        "TCS":       {"targetMeanPrice": 4100.0, "targetMedianPrice": 4050.0,
                      "numberOfAnalystOpinions": 25, "currency": "INR"},
        "NOCOVERAGE": {"shortName": "No analysts"},
    }
    fake_yf = _make_fake_yf_for(targets)

    stats = refresh_consensus._pass_yfinance(
        sess, ["RELIANCE", "TCS", "NOCOVERAGE"], yf_module=fake_yf, sleep_s=0.0,
    )

    assert stats == {"attempted": 3, "wrote": 2, "skipped": 1}

    rows = sess.execute(text(
        "SELECT ticker, source, target_mean FROM consensus_estimates "
        "ORDER BY ticker"
    )).fetchall()
    assert [(r[0], r[1]) for r in rows] == [
        ("RELIANCE", "yfinance"), ("TCS", "yfinance"),
    ]


# ── 6. Finnhub pass writes one row per ticker ────────────────────────


def test_pass_finnhub_writes_rows(sess):
    payload_by_sym = {
        "RELIANCE.NS": {"targetMean": 2900.0, "targetMedian": 2950.0,
                         "numberOfAnalysts": 30},
        "TCS.NS":      {"targetMean": 4100.0, "targetMedian": 4050.0,
                         "numberOfAnalysts": 25},
    }

    def fake_get(url, params=None, timeout=None):
        sym = params["symbol"]
        return _FakeResp(payload_by_sym.get(sym, {}))

    fake_requests = SimpleNamespace(get=fake_get)

    stats = refresh_consensus._pass_finnhub(
        sess, ["RELIANCE", "TCS"],
        requests_module=fake_requests, api_key="test-key", sleep_s=0.0,
    )
    assert stats == {"attempted": 2, "wrote": 2, "skipped": 0}


# ── 7. Idempotency: same (ticker, source, fetched_at) → no duplicates ─


def test_idempotent_rerun_does_not_duplicate(sess):
    # In Postgres prod, the DEFAULT NOW() bumps fetched_at on each insert
    # and a rerun in the same second hits the PK and is dropped by
    # ON CONFLICT DO NOTHING. In our SQLite test schema the DEFAULT is a
    # fixed literal, so two inserts with identical (ticker, source) MUST
    # collide on PK and the second must be a no-op.
    targets = {"RELIANCE": {"targetMeanPrice": 2900.0,
                             "targetMedianPrice": 2950.0,
                             "numberOfAnalystOpinions": 30}}
    fake_yf = _make_fake_yf_for(targets)

    s1 = refresh_consensus._pass_yfinance(
        sess, ["RELIANCE"], yf_module=fake_yf, sleep_s=0.0,
    )
    assert s1["wrote"] == 1

    s2 = refresh_consensus._pass_yfinance(
        sess, ["RELIANCE"], yf_module=fake_yf, sleep_s=0.0,
    )
    # Second run: row is rejected by ON CONFLICT DO NOTHING (rowcount=0),
    # so it counts as "skipped" rather than "wrote".
    assert s2["wrote"] == 0
    assert s2["skipped"] == 1

    n = sess.execute(text("SELECT COUNT(*) FROM consensus_estimates")).scalar()
    assert n == 1
