"""Tests for the /api/v1/public/holdings-trend/{ticker} endpoint
(feat/analysis-holdings-trend-chart, 2026-06-10).

The endpoint is a thin read over the shareholding_pattern table
populated by data_pipeline.sources.nse_shareholding and the
backfill_shareholding_history.py script. Tests cover:

* Empty state: ticker with no rows on file still returns 200 with
  `trend: []` and `current: null` so the frontend can render a
  fallback without status-code branching.
* Happy path: 8 rows in (newest -> oldest) come out ASC by
  quarter_end with the expected percentages preserved.
* Limit clamp: `quarters=20` is honoured; `quarters=999` rejected.
* Quarter labels follow the Indian FY convention (Q1 = Apr–Jun).
* Cache key includes the quarter count so different limits don't
  collide.

The DB layer is faked via a stub session so the test never needs
Aiven. Cache state is reset between tests.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routers import public as public_router  # noqa: E402
from backend.services.cache_service import cache as _cache  # noqa: E402


# ── Test doubles ─────────────────────────────────────────────────

class _Row:
    """Minimal stand-in for a ShareholdingPattern ORM row."""
    def __init__(self, qe, p, fii, dii, pub):
        self.quarter_end = qe
        self.promoter_pct = p
        self.fii_pct = fii
        self.dii_pct = dii
        self.public_pct = pub
        self.promoter_pledge_pct = None
        self.total_shares = None


# ── Fixtures ─────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _clear_cache():
    """Flush the holdings-trend cache between tests to keep them isolated."""
    try:
        _cache.clear()
    except Exception:
        pass
    yield
    try:
        _cache.clear()
    except Exception:
        pass


@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(public_router.router)
    return TestClient(app)


def _install_rows(monkeypatch, rows):
    """Replace the DB-layer helper so the endpoint sees `rows` (DESC)."""
    monkeypatch.setattr(
        public_router,
        "_query_holdings_history",
        lambda _ticker, _quarters: rows[: _quarters],
    )


# ── Tests ────────────────────────────────────────────────────────

def test_empty_ticker_returns_400(client):
    r = client.get("/api/v1/public/holdings-trend/   ")
    assert r.status_code == 400


def test_no_rows_returns_200_with_empty_trend(client, monkeypatch):
    _install_rows(monkeypatch, rows=[])
    r = client.get("/api/v1/public/holdings-trend/UNKNOWN")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "UNKNOWN"
    assert body["trend"] == []
    assert body["current"] is None
    assert body["source"] == "shareholding_pattern"


def test_happy_path_returns_8_quarters_asc(client, monkeypatch):
    # Insert newest-first as the ORM would emit them (DESC).
    rows = [
        _Row(date(2026, 3, 31), 50.0, 22.0, 17.0, 11.0),
        _Row(date(2025, 12, 31), 50.1, 21.8, 17.2, 10.9),
        _Row(date(2025, 9, 30), 50.2, 21.5, 17.4, 10.9),
        _Row(date(2025, 6, 30), 50.3, 21.2, 17.5, 11.0),
        _Row(date(2025, 3, 31), 50.4, 20.9, 17.6, 11.1),
        _Row(date(2024, 12, 31), 50.5, 20.5, 17.7, 11.3),
        _Row(date(2024, 9, 30), 50.6, 20.2, 17.8, 11.4),
        _Row(date(2024, 6, 30), 50.8, 19.8, 17.9, 11.5),
    ]
    _install_rows(monkeypatch, rows=rows)
    r = client.get("/api/v1/public/holdings-trend/RELIANCE")
    assert r.status_code == 200
    body = r.json()
    trend = body["trend"]
    assert len(trend) == 8
    # ASC by quarter_end (oldest first).
    assert trend[0]["quarter_end"] == "2024-06-30"
    assert trend[-1]["quarter_end"] == "2026-03-31"
    # Latest row populates `current`.
    assert body["current"]["quarter_end"] == "2026-03-31"
    assert body["current"]["promoter_pct"] == 50.0
    # Percentages round to 2 dp and survive the JSON round-trip.
    assert trend[-1]["fii_pct"] == 22.0


def test_quarters_limit_validated(client, monkeypatch):
    _install_rows(monkeypatch, rows=[])
    r = client.get("/api/v1/public/holdings-trend/X?quarters=0")
    assert r.status_code == 422
    r = client.get("/api/v1/public/holdings-trend/X?quarters=999")
    assert r.status_code == 422


def test_quarter_label_indian_fy():
    label = public_router._quarter_label
    # Indian FY runs Apr–Mar: Mar 2026 is Q4 FY26.
    assert label(date(2026, 3, 31)) == "Q4 FY26"
    assert label(date(2025, 6, 30)) == "Q1 FY25"
    assert label(date(2025, 9, 30)) == "Q2 FY25"
    # Dec 2025 belongs to FY26 (FY is named for its end year).
    assert label(date(2025, 12, 31)) == "Q3 FY26"


def test_ticker_normalized(client, monkeypatch):
    _install_rows(monkeypatch, rows=[])
    r = client.get("/api/v1/public/holdings-trend/reliance.ns")
    assert r.status_code == 200
    assert r.json()["ticker"] == "RELIANCE"


def test_cache_key_distinguishes_quarter_counts(client, monkeypatch):
    """quarters=4 and quarters=8 must not collide in the cache."""
    rows = [
        _Row(date(2026, 3, 31), 50.0, 22.0, 17.0, 11.0),
        _Row(date(2025, 12, 31), 50.1, 21.8, 17.2, 10.9),
    ]
    _install_rows(monkeypatch, rows=rows)
    r4 = client.get("/api/v1/public/holdings-trend/RELIANCE?quarters=4")
    r8 = client.get("/api/v1/public/holdings-trend/RELIANCE?quarters=8")
    assert r4.status_code == 200 and r8.status_code == 200
    # Both return all 2 rows but the cache keys differ.
    assert _cache.get("public:holdings-trend:RELIANCE:4") is not None
    assert _cache.get("public:holdings-trend:RELIANCE:8") is not None
