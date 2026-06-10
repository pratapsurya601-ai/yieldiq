"""Revenue-segment breakdown — contract tests (task #176-followup, 2026-06-10).

Locks the shape of:

  * ``revenue_segments_service.get_segments_for_ticker`` — bucket
    classification (business vs geography), revenue de-dup,
    percentage normalisation, fastest-growing trend pick.
  * ``GET /api/v1/public/revenue-segments/{ticker}`` — 200 with
    empty lists when no AR extraction exists yet (the frontend
    needs a stable response shape, never a 404), withheld envelope,
    populated path.

Uses an in-memory SQLite DB to avoid a live Neon connection — same
pattern as test_day103b_annual_reports.py. The service's
psycopg2 ``%s`` placeholders are translated to SQLite ``?`` by the
cursor shim.
"""
from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services import revenue_segments_service  # noqa: E402
from backend.routers import public as public_router  # noqa: E402


# ── SQLite shim ───────────────────────────────────────────────


class _SqliteCursorShim:
    def __init__(self, inner):
        self._inner = inner

    def execute(self, sql: str, params=()):
        return self._inner.execute(sql.replace("%s", "?"), params)

    def fetchall(self):
        return self._inner.fetchall()

    def fetchone(self):
        return self._inner.fetchone()

    def close(self):
        return self._inner.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self._inner.close()


class _SqliteConnShim:
    def __init__(self, raw):
        self._raw = raw

    def cursor(self):
        return _SqliteCursorShim(self._raw.cursor())

    def close(self):
        return self._raw.close()


def _make_db() -> _SqliteConnShim:
    raw = sqlite3.connect(":memory:", check_same_thread=False)
    raw.execute(
        """
        CREATE TABLE company_annual_reports (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker        TEXT NOT NULL,
            fiscal_year   INTEGER NOT NULL,
            published_at  TEXT,
            ar_url        TEXT
        )
        """
    )
    raw.execute(
        """
        CREATE TABLE ar_signals (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            annual_report_id  INTEGER NOT NULL,
            segment_data      TEXT,
            quality_flag      TEXT,
            extracted_at      TEXT DEFAULT CURRENT_TIMESTAMP
        )
        """
    )
    return _SqliteConnShim(raw)


def _seed_ar(
    conn: _SqliteConnShim,
    *,
    ticker: str,
    fiscal_year: int,
    published_at: str | None,
    segment_data: list | None,
    quality_flag: str = "ok",
) -> None:
    cur = conn._raw.cursor()
    cur.execute(
        "INSERT INTO company_annual_reports (ticker, fiscal_year, published_at, ar_url) "
        "VALUES (?, ?, ?, ?)",
        (ticker, fiscal_year, published_at, "https://example.com/ar.pdf"),
    )
    ar_id = cur.lastrowid
    cur.execute(
        "INSERT INTO ar_signals (annual_report_id, segment_data, quality_flag) "
        "VALUES (?, ?, ?)",
        (ar_id, json.dumps(segment_data) if segment_data is not None else None,
         quality_flag),
    )
    conn._raw.commit()


# ── Service-level tests ───────────────────────────────────────


def test_classifies_geography_by_keyword():
    conn = _make_db()
    _seed_ar(
        conn,
        ticker="TCS",
        fiscal_year=2024,
        published_at="2024-05-01",
        segment_data=[
            {"segment": "BFSI", "revenue_cr": 90000, "fy": "FY24"},
            {"segment": "Retail & CPG", "revenue_cr": 30000, "fy": "FY24"},
            {"segment": "North America", "revenue_cr": 140000, "fy": "FY24"},
            {"segment": "India", "revenue_cr": 10000, "fy": "FY24"},
            {"segment": "Europe", "revenue_cr": 60000, "fy": "FY24"},
        ],
    )

    out = revenue_segments_service.get_segments_for_ticker("TCS", conn=conn)

    biz_names = [r["name"] for r in out["business_segments"]]
    geo_names = [r["name"] for r in out["geo_segments"]]
    assert biz_names == ["BFSI", "Retail & CPG"]
    assert geo_names == ["North America", "Europe", "India"]

    # Percentages within each bucket sum to ~100.
    assert round(sum(r["pct"] for r in out["business_segments"]), 1) == 100.0
    assert round(sum(r["pct"] for r in out["geo_segments"]), 1) == 100.0
    assert out["fiscal_year"] == 2024
    assert out["published_at"] == "2024-05-01"


def test_explicit_kind_overrides_name_heuristic():
    """An entry tagged kind='business' must NOT be misrouted to geo
    even if its name overlaps the geo vocabulary."""
    conn = _make_db()
    _seed_ar(
        conn,
        ticker="RELIANCE",
        fiscal_year=2024,
        published_at="2024-08-01",
        segment_data=[
            # Tricky: name contains 'India' but explicitly marked business.
            {"segment": "Reliance Jio India Telecom",
             "kind": "business", "revenue_cr": 120000, "fy": "FY24"},
            {"segment": "Retail", "revenue_cr": 80000, "fy": "FY24"},
            {"segment": "Exports", "revenue_cr": 50000, "fy": "FY24"},
        ],
    )
    out = revenue_segments_service.get_segments_for_ticker("RELIANCE", conn=conn)
    biz_names = [r["name"] for r in out["business_segments"]]
    geo_names = [r["name"] for r in out["geo_segments"]]
    assert "Reliance Jio India Telecom" in biz_names
    assert "Retail" in biz_names
    assert geo_names == ["Exports"]


def test_trend_picks_fastest_growing_positive():
    conn = _make_db()
    _seed_ar(
        conn,
        ticker="INFY",
        fiscal_year=2024,
        published_at="2024-06-01",
        segment_data=[
            {"segment": "Financial Services", "revenue_cr": 40000,
             "yoy_growth_pct": 8.0, "fy": "FY24"},
            {"segment": "Hi-Tech", "revenue_cr": 25000,
             "yoy_growth_pct": 22.0, "fy": "FY24"},
            {"segment": "Manufacturing", "revenue_cr": 18000,
             "yoy_growth_pct": -3.0, "fy": "FY24"},
        ],
    )
    out = revenue_segments_service.get_segments_for_ticker("INFY", conn=conn)
    assert out["trend"] == {"name": "Hi-Tech", "yoy_growth_pct": 22.0}


def test_trend_is_none_when_no_yoy_present():
    conn = _make_db()
    _seed_ar(
        conn,
        ticker="WIPRO",
        fiscal_year=2024,
        published_at="2024-05-01",
        segment_data=[
            {"segment": "IT Services", "revenue_cr": 80000, "fy": "FY24"},
            {"segment": "IT Products", "revenue_cr": 5000, "fy": "FY24"},
        ],
    )
    out = revenue_segments_service.get_segments_for_ticker("WIPRO", conn=conn)
    assert out["trend"] is None
    # Bucket still computed.
    assert len(out["business_segments"]) == 2


def test_empty_when_no_ar_extraction():
    conn = _make_db()
    out = revenue_segments_service.get_segments_for_ticker("UNKNOWN", conn=conn)
    assert out["business_segments"] == []
    assert out["geo_segments"] == []
    assert out["fiscal_year"] is None
    assert out["trend"] is None
    assert out["withheld"] is False


def test_withheld_quality_flag_returns_empty_with_flag():
    conn = _make_db()
    _seed_ar(
        conn,
        ticker="ACME",
        fiscal_year=2024,
        published_at="2024-05-01",
        segment_data=[{"segment": "Segment A", "revenue_cr": 100}],
        quality_flag="sebi_withheld",
    )
    out = revenue_segments_service.get_segments_for_ticker("ACME", conn=conn)
    assert out["withheld"] is True
    assert out["business_segments"] == []
    assert out["fiscal_year"] == 2024


def test_picks_most_recent_ar_published_at_desc():
    conn = _make_db()
    _seed_ar(
        conn,
        ticker="HDFCBANK",
        fiscal_year=2023,
        published_at="2023-05-01",
        segment_data=[{"segment": "Treasury", "revenue_cr": 30000}],
    )
    _seed_ar(
        conn,
        ticker="HDFCBANK",
        fiscal_year=2024,
        published_at="2024-05-01",
        segment_data=[
            {"segment": "Retail Banking", "revenue_cr": 110000},
            {"segment": "Wholesale Banking", "revenue_cr": 60000},
        ],
    )
    out = revenue_segments_service.get_segments_for_ticker("HDFCBANK", conn=conn)
    assert out["fiscal_year"] == 2024
    biz_names = [r["name"] for r in out["business_segments"]]
    assert biz_names == ["Retail Banking", "Wholesale Banking"]


def test_falls_back_to_older_ar_when_latest_blob_is_empty():
    conn = _make_db()
    # Latest AR has segment_data = [] (extraction succeeded but found nothing).
    _seed_ar(
        conn,
        ticker="EICHERMOT",
        fiscal_year=2024,
        published_at="2024-08-01",
        segment_data=[],
    )
    _seed_ar(
        conn,
        ticker="EICHERMOT",
        fiscal_year=2023,
        published_at="2023-08-01",
        segment_data=[{"segment": "Royal Enfield", "revenue_cr": 17000}],
    )
    out = revenue_segments_service.get_segments_for_ticker("EICHERMOT", conn=conn)
    assert out["fiscal_year"] == 2023
    assert len(out["business_segments"]) == 1


def test_strips_ns_bo_suffix_on_ticker():
    conn = _make_db()
    _seed_ar(
        conn,
        ticker="LT",
        fiscal_year=2024,
        published_at="2024-06-01",
        segment_data=[{"segment": "Infrastructure Projects", "revenue_cr": 80000}],
    )
    out_ns = revenue_segments_service.get_segments_for_ticker("LT.NS", conn=conn)
    out_bo = revenue_segments_service.get_segments_for_ticker("LT.BO", conn=conn)
    assert len(out_ns["business_segments"]) == 1
    assert len(out_bo["business_segments"]) == 1


def test_dedups_segment_by_name():
    conn = _make_db()
    _seed_ar(
        conn,
        ticker="DEDUP",
        fiscal_year=2024,
        published_at="2024-05-01",
        segment_data=[
            {"segment": "Mobile Services", "revenue_cr": 80000},
            {"segment": "mobile services", "revenue_cr": 5000},  # dupe
            {"segment": "Home Broadband", "revenue_cr": 12000},
        ],
    )
    out = revenue_segments_service.get_segments_for_ticker("DEDUP", conn=conn)
    biz = out["business_segments"]
    assert len(biz) == 2
    # 80k + 5k merged.
    mobile = next(r for r in biz if r["name"].casefold() == "mobile services")
    assert mobile["revenue_cr"] == 85000.0


def test_ignores_rows_with_zero_or_missing_revenue():
    conn = _make_db()
    _seed_ar(
        conn,
        ticker="EDGE",
        fiscal_year=2024,
        published_at="2024-05-01",
        segment_data=[
            {"segment": "Zero-rev",   "revenue_cr": 0},
            {"segment": "Negative",   "revenue_cr": -10},
            {"segment": "No revenue", "ebit_cr": 50},
            {"segment": "Valid",      "revenue_cr": 500},
        ],
    )
    out = revenue_segments_service.get_segments_for_ticker("EDGE", conn=conn)
    biz = out["business_segments"]
    assert len(biz) == 1
    assert biz[0]["name"] == "Valid"
    assert biz[0]["pct"] == 100.0


# ── Endpoint-level tests ──────────────────────────────────────


@pytest.fixture()
def client_and_seed(monkeypatch: pytest.MonkeyPatch):
    """Spin up a minimal FastAPI app exposing only the public router
    and swap revenue_segments_service._connect to return our shared
    SQLite shim. Returns (TestClient, seed_fn)."""
    app = FastAPI()
    app.include_router(public_router.router)
    client = TestClient(app)

    shared = _make_db()

    def _make_test_conn():
        class _NoCloseShim:
            def cursor(self):
                return shared.cursor()

            def close(self):
                pass

        return _NoCloseShim()

    monkeypatch.setattr(revenue_segments_service, "_connect", _make_test_conn)
    try:
        public_router.cache.clear()
    except Exception:
        pass
    return client, shared


def test_endpoint_empty_payload_when_no_extraction(client_and_seed):
    client, _ = client_and_seed
    resp = client.get("/api/v1/public/revenue-segments/NOSUCH")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "NOSUCH"
    assert body["business_segments"] == []
    assert body["geo_segments"] == []
    assert body["withheld"] is False


def test_endpoint_populated_payload(client_and_seed):
    client, shared = client_and_seed
    _seed_ar(
        shared,
        ticker="BHARTIARTL",
        fiscal_year=2024,
        published_at="2024-06-01",
        segment_data=[
            {"segment": "Mobile Services", "revenue_cr": 100000,
             "yoy_growth_pct": 12.0, "fy": "FY24"},
            {"segment": "Home Broadband", "revenue_cr": 8000,
             "yoy_growth_pct": 28.0, "fy": "FY24"},
            {"segment": "India", "revenue_cr": 90000, "fy": "FY24"},
            {"segment": "Africa", "revenue_cr": 50000, "fy": "FY24"},
        ],
    )

    resp = client.get("/api/v1/public/revenue-segments/BHARTIARTL")
    assert resp.status_code == 200
    body = resp.json()
    assert body["ticker"] == "BHARTIARTL"
    assert body["fiscal_year"] == 2024
    assert [r["name"] for r in body["business_segments"]] == [
        "Mobile Services",
        "Home Broadband",
    ]
    assert [r["name"] for r in body["geo_segments"]] == ["India", "Africa"]
    assert body["trend"] == {"name": "Home Broadband", "yoy_growth_pct": 28.0}
    # Cache-Control header present.
    assert "Cache-Control" in resp.headers


def test_endpoint_400_on_empty_ticker(client_and_seed):
    client, _ = client_and_seed
    resp = client.get("/api/v1/public/revenue-segments/ ")
    assert resp.status_code == 400


def test_endpoint_withheld_envelope(client_and_seed):
    client, shared = client_and_seed
    _seed_ar(
        shared,
        ticker="WITHHELD",
        fiscal_year=2024,
        published_at="2024-05-01",
        segment_data=[{"segment": "X", "revenue_cr": 100}],
        quality_flag="sebi_withheld",
    )
    resp = client.get("/api/v1/public/revenue-segments/WITHHELD")
    assert resp.status_code == 200
    body = resp.json()
    assert body["withheld"] is True
    assert body["business_segments"] == []
