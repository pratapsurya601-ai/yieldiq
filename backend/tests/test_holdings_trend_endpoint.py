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
    """Indian fiscal year runs Apr–Mar and is named by its END year.

    Per ROOT CAUSE #4 fix (2026-06-11) the entire FY shares one
    suffix — Apr 2025 through Mar 2026 all read as FY26. Prior to
    the fix, Q1/Q2 labels rendered with the start year, producing
    an x-axis that went `... Q4 FY25, Q1 FY25, Q2 FY25, Q3 FY26 ...`
    (out of order and visually duplicated).
    """
    label = public_router._quarter_label
    # Mar 2026 closes FY26 — last day of the fiscal year.
    assert label(date(2026, 3, 31)) == "Q4 FY26"
    # Apr-Jun 2025 opens FY26.
    assert label(date(2025, 6, 30)) == "Q1 FY26"
    assert label(date(2025, 9, 30)) == "Q2 FY26"
    assert label(date(2025, 12, 31)) == "Q3 FY26"
    # FY25: Apr 2024 - Mar 2025.
    assert label(date(2024, 6, 30)) == "Q1 FY25"
    assert label(date(2024, 9, 30)) == "Q2 FY25"
    assert label(date(2024, 12, 31)) == "Q3 FY25"
    assert label(date(2025, 3, 31)) == "Q4 FY25"


def test_quarter_label_full_year_never_truncated():
    """The label must always carry the two-digit year suffix.

    Earlier visual reports showed the chart axis rendering ``Q4 FY``
    with the digits missing — a frontend overflow on the rightmost
    tick. Guard the contract: the label serialisation ALWAYS includes
    the year, with a leading zero for FY01–FY09. The frontend may
    still clip pixels, but it cannot blame the payload.
    """
    label = public_router._quarter_label
    for d, expected in (
        (date(2026, 3, 31), "Q4 FY26"),
        (date(2099, 12, 31), "Q3 FY00"),  # FY2100 -> "00"
        (date(2009, 3, 31), "Q4 FY09"),
        (date(2009, 6, 30), "Q1 FY10"),
    ):
        got = label(d)
        # Must match "Q\d FY\d\d" with exactly 2 year digits.
        assert got == expected, f"{d}: expected {expected!r}, got {got!r}"
        assert len(got) == 7, got


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


def test_dedup_collapses_same_label(client, monkeypatch):
    """Two filings whose quarter_ends collapse to the same FY label
    must NOT produce duplicate bars on the chart x-axis.

    ROOT CAUSE #4 (2026-06-11): a re-filing dated 2025-09-29
    coexisting with an original dated 2025-09-30 both map to
    'Q2 FY26'. The endpoint keeps the later (more recent) row and
    drops the earlier — the chart sees one tick per quarter.
    """
    rows = [
        _Row(date(2025, 9, 30), 50.5, 22.0, 17.0, 10.5),
        _Row(date(2025, 9, 29), 50.4, 21.9, 17.1, 10.6),  # re-filing duplicate
        _Row(date(2025, 6, 30), 50.3, 21.5, 17.4, 10.8),
    ]
    _install_rows(monkeypatch, rows=rows)
    r = client.get("/api/v1/public/holdings-trend/RELIANCE")
    assert r.status_code == 200
    body = r.json()
    trend = body["trend"]
    labels = [pt["quarter_label"] for pt in trend]
    assert labels.count("Q2 FY26") == 1, labels
    # The kept Q2 FY26 row is the later filing (Sep 30).
    q2 = [pt for pt in trend if pt["quarter_label"] == "Q2 FY26"][0]
    assert q2["quarter_end"] == "2025-09-30"
    assert q2["promoter_pct"] == 50.5


def test_trend_sorted_by_canonical_date_ascending(client, monkeypatch):
    """Output rows must be ASC by ``quarter_end`` regardless of input
    order — the frontend chart consumes left-to-right.

    Regression guard against ROOT CAUSE #4 where the prior FY-label
    bug caused string-sorted labels to interleave (Q4 FY25 followed
    by Q1 FY25 followed by Q3 FY26).
    """
    # Insert rows in DESC order as the ORM emits them; the endpoint
    # must reverse + sort so the response trend reads oldest -> newest.
    rows = [
        _Row(date(2026, 3, 31), 50.0, 22.0, 17.0, 11.0),
        _Row(date(2025, 12, 31), 50.1, 21.8, 17.2, 10.9),
        _Row(date(2025, 9, 30), 50.2, 21.5, 17.4, 10.9),
        _Row(date(2025, 6, 30), 50.3, 21.2, 17.5, 11.0),
        _Row(date(2025, 3, 31), 50.4, 20.9, 17.6, 11.1),
    ]
    _install_rows(monkeypatch, rows=rows)
    r = client.get("/api/v1/public/holdings-trend/RELIANCE")
    body = r.json()
    ends = [pt["quarter_end"] for pt in body["trend"]]
    assert ends == sorted(ends), ends
    # And the corresponding labels go FY25 -> FY26 monotonically.
    labels = [pt["quarter_label"] for pt in body["trend"]]
    assert labels == ["Q4 FY25", "Q1 FY26", "Q2 FY26", "Q3 FY26", "Q4 FY26"], labels


def test_partial_fii_dii_preserved_per_series(client, monkeypatch):
    """Rows where FII/DII is null must still appear (so promoter and
    public bars render across the full window) — the frontend skips
    the null series per-row, not the whole quarter.
    """
    rows = [
        _Row(date(2026, 3, 31), 50.0, None, None, 11.0),  # FII/DII history gap
        _Row(date(2025, 12, 31), 50.1, 21.8, 17.2, 10.9),
        _Row(date(2025, 9, 30), 50.2, 21.5, 17.4, 10.9),
    ]
    _install_rows(monkeypatch, rows=rows)
    r = client.get("/api/v1/public/holdings-trend/RELIANCE")
    body = r.json()
    trend = body["trend"]
    # Latest quarter is still present with promoter + public, fii/dii=None.
    latest = trend[-1]
    assert latest["quarter_end"] == "2026-03-31"
    assert latest["promoter_pct"] == 50.0
    assert latest["public_pct"] == 11.0
    assert latest["fii_pct"] is None
    assert latest["dii_pct"] is None
