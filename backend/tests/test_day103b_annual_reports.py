"""Day-103b (2026-05-22): annual_reports link-index — contract tests.

Locks the contract for:

  * ``backend.services.annual_reports_service.list_annual_reports`` —
    happy path, empty/unknown ticker, ordering by fiscal_year DESC,
    URL passthrough, NULL filed_date handling, case-insensitive ticker.
  * ``GET /api/v1/public/annual-reports/{ticker}`` — 200 with payload
    shape ``{ticker, annual_reports: [...]}`` whether or not rows
    exist. We deliberately never 404 on an unknown ticker so the UI
    can render a stable "coming soon" empty state.

Uses an in-memory SQLite DB to avoid a live Neon connection. SQLite
``annual_reports`` mirrors migration 052 closely enough for the read
path (SERIAL → INTEGER PRIMARY KEY AUTOINCREMENT, DATE → TEXT).
"""
from __future__ import annotations

import sqlite3
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services import annual_reports_service  # noqa: E402
from backend.routers import public as public_router  # noqa: E402


# ── SQLite shim ───────────────────────────────────────────────
# annual_reports_service calls cur.execute with psycopg2's '%s'
# placeholders. SQLite needs '?'. Wrap the connection so the
# service can stay 100% production code.

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
        CREATE TABLE annual_reports (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker      TEXT NOT NULL,
            fiscal_year INTEGER NOT NULL,
            filed_date  TEXT,
            source_url  TEXT NOT NULL,
            UNIQUE (ticker, fiscal_year)
        )
        """
    )
    return _SqliteConnShim(raw)


def _seed(conn: _SqliteConnShim, rows: list[tuple]) -> None:
    cur = conn._raw.cursor()
    cur.executemany(
        "INSERT INTO annual_reports (ticker, fiscal_year, filed_date, source_url) "
        "VALUES (?, ?, ?, ?)",
        rows,
    )
    conn._raw.commit()


# Note: the service returns iso-format strings for DATE, and SQLite
# already stores DATE as TEXT, so the round-trip is correct without
# extra conversion in the test.


# ── Service-level tests ───────────────────────────────────────

def test_list_annual_reports_happy_path_orders_desc():
    conn = _make_db()
    _seed(conn, [
        ("HDFCBANK.NS", 2022, "2022-05-26", "https://example.com/fy22.pdf"),
        ("HDFCBANK.NS", 2024, "2024-05-22", "https://example.com/fy24.pdf"),
        ("HDFCBANK.NS", 2023, "2023-05-17", "https://example.com/fy23.pdf"),
    ])

    out = annual_reports_service.list_annual_reports("HDFCBANK.NS", conn=conn)
    years = [r["fiscal_year"] for r in out]
    assert years == [2024, 2023, 2022], years

    # URL passthrough — exactly what was inserted.
    assert out[0]["source_url"] == "https://example.com/fy24.pdf"
    # filed_date is iso string.
    assert out[0]["filed_date"] == "2024-05-22"


def test_list_annual_reports_empty_for_unknown_ticker():
    conn = _make_db()
    _seed(conn, [
        ("HDFCBANK.NS", 2024, "2024-05-22", "https://example.com/fy24.pdf"),
    ])

    assert annual_reports_service.list_annual_reports("UNKNOWN.NS", conn=conn) == []
    # Empty string / None must not raise either.
    assert annual_reports_service.list_annual_reports("", conn=conn) == []
    assert annual_reports_service.list_annual_reports(None, conn=conn) == []  # type: ignore[arg-type]


def test_list_annual_reports_case_insensitive_and_null_date():
    conn = _make_db()
    _seed(conn, [
        ("RELIANCE.NS", 2024, None, "https://example.com/reliance_fy24.pdf"),
    ])
    out = annual_reports_service.list_annual_reports("reliance.ns", conn=conn)
    assert len(out) == 1
    assert out[0]["fiscal_year"] == 2024
    assert out[0]["filed_date"] is None
    assert out[0]["source_url"] == "https://example.com/reliance_fy24.pdf"


def test_list_annual_reports_respects_limit():
    conn = _make_db()
    rows = [
        ("TCS.NS", fy, f"{fy}-05-01", f"https://example.com/{fy}.pdf")
        for fy in range(2012, 2025)
    ]
    _seed(conn, rows)
    out = annual_reports_service.list_annual_reports("TCS.NS", limit=5, conn=conn)
    assert len(out) == 5
    assert [r["fiscal_year"] for r in out] == [2024, 2023, 2022, 2021, 2020]


# ── Endpoint-level tests ──────────────────────────────────────

@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    """Build a minimal FastAPI app exposing only the public router and
    monkey-patch annual_reports_service._connect to return our SQLite
    shim. The shim's connection is rebuilt per-test via the seed_db
    fixture so leak between tests is impossible."""
    app = FastAPI()
    app.include_router(public_router.router)
    return TestClient(app)


@pytest.fixture()
def seed_db(monkeypatch: pytest.MonkeyPatch):
    """Returns a helper that swaps the live _connect for a SQLite
    connection seeded with the provided rows."""
    def _seed(rows: list[tuple]) -> _SqliteConnShim:
        conn = _make_db()
        _seed_table(conn, rows)
        monkeypatch.setattr(
            annual_reports_service, "_connect", lambda: _make_test_conn(conn)
        )
        # The endpoint goes through the per-process LRU cache as well
        # — make sure each test starts cold.
        try:
            public_router.cache.clear()  # type: ignore[attr-defined]
        except Exception:
            pass
        return conn
    return _seed


def _seed_table(conn: _SqliteConnShim, rows: list[tuple]) -> None:
    _seed(conn, rows)


def _make_test_conn(shared: _SqliteConnShim):
    """Return a wrapper that delegates cursor() to the shared SQLite
    connection but no-ops .close() so the underlying connection stays
    alive across multiple endpoint calls in a single test."""
    class _NoCloseShim:
        def cursor(self):
            return shared.cursor()

        def close(self):
            pass

    return _NoCloseShim()


def test_endpoint_returns_rows_for_known_ticker(client, seed_db):
    seed_db([
        ("HDFCBANK.NS", 2024, "2024-05-22", "https://example.com/fy24.pdf"),
        ("HDFCBANK.NS", 2023, "2023-05-17", "https://example.com/fy23.pdf"),
    ])
    r = client.get("/api/v1/public/annual-reports/HDFCBANK.NS")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ticker"] == "HDFCBANK.NS"
    years = [row["fiscal_year"] for row in body["annual_reports"]]
    assert years == [2024, 2023]
    assert body["annual_reports"][0]["source_url"] == "https://example.com/fy24.pdf"


def test_endpoint_returns_empty_list_not_404_for_unknown_ticker(client, seed_db):
    seed_db([
        ("HDFCBANK.NS", 2024, "2024-05-22", "https://example.com/fy24.pdf"),
    ])
    r = client.get("/api/v1/public/annual-reports/NOSUCH.NS")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body == {"ticker": "NOSUCH.NS", "annual_reports": []}


def test_endpoint_400_on_blank_ticker(client, seed_db):
    seed_db([])
    # FastAPI path params can't actually be blank, so this guards the
    # whitespace-only case via URL-encoded space.
    r = client.get("/api/v1/public/annual-reports/%20")
    assert r.status_code == 400
