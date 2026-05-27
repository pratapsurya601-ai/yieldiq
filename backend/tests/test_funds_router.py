"""Phase 3-slim — contract tests for backend/routers/funds.py.

The router pulls from `funds`, `fund_nav_history`,
`fund_benchmark_history`, and (optionally) `fund_returns_cache`. The
Phase 3 ship must work even when the returns cache is empty/missing.
These tests pin that graceful-degradation contract with a SQLite
in-memory DB substituted via monkeypatch — same pattern as
test_session_trace_router.py.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routers import funds as funds_router  # noqa: E402


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # SQLite-flavoured DDL: the production schema uses NUMERIC + DATE +
    # partitioning, none of which SQLite needs. The router only relies
    # on column names and ordering, not on column types or partitioning
    # — so a vanilla TEXT/REAL/DATE table works for the contract test.
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE funds (
                scheme_code TEXT PRIMARY KEY,
                isin_growth TEXT,
                isin_div TEXT,
                scheme_name TEXT NOT NULL,
                amc TEXT NOT NULL,
                plan TEXT,
                option TEXT,
                category TEXT,
                sub_category TEXT,
                benchmark_index_code TEXT,
                inception_date DATE,
                riskometer_level TEXT,
                is_active INTEGER DEFAULT 1
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE fund_nav_history (
                scheme_code TEXT NOT NULL,
                nav_date DATE NOT NULL,
                nav REAL NOT NULL,
                aum_cr REAL,
                PRIMARY KEY (scheme_code, nav_date)
            )
            """
        ))
        conn.execute(text(
            """
            CREATE TABLE fund_benchmark_history (
                benchmark_index_code TEXT NOT NULL,
                nav_date DATE NOT NULL,
                tri_value REAL NOT NULL,
                PRIMARY KEY (benchmark_index_code, nav_date)
            )
            """
        ))
        # NOTE: deliberately do NOT create fund_returns_cache here. We
        # want to verify the router degrades gracefully when Phase 2's
        # cache table is missing entirely. One of the tests below
        # creates it on demand to cover the populated path.

        # Seed funds row.
        conn.execute(text(
            """
            INSERT INTO funds (scheme_code, scheme_name, amc, plan, option,
                               category, sub_category, benchmark_index_code,
                               inception_date, riskometer_level, is_active)
            VALUES ('118989', 'HDFC Top 100 Fund - Direct Plan - Growth',
                    'HDFC Mutual Fund', 'Direct', 'Growth',
                    'Equity', 'Large Cap', 'NIFTY_100_TRI',
                    '1996-10-11', 'VeryHigh', 1)
            """
        ))
        # Seed a few NAV rows spanning the chart window.
        today = date.today()
        for i in range(0, 60):
            nav_date = today - timedelta(days=30 * i)
            conn.execute(text(
                "INSERT INTO fund_nav_history "
                "(scheme_code, nav_date, nav) VALUES (:s, :d, :n)"
            ), {"s": "118989", "d": nav_date, "n": 100.0 + i})
        # Seed a couple benchmark rows.
        for i in range(0, 60):
            nav_date = today - timedelta(days=30 * i)
            conn.execute(text(
                "INSERT INTO fund_benchmark_history "
                "(benchmark_index_code, nav_date, tri_value) "
                "VALUES (:b, :d, :v)"
            ), {"b": "NIFTY_100_TRI", "d": nav_date, "v": 20000.0 + i})

    SessionLocal = sessionmaker(bind=engine, future=True)

    monkeypatch.setattr(funds_router, "_open_session", lambda: SessionLocal())

    app = FastAPI()
    app.include_router(funds_router.router)
    return TestClient(app)


def test_list_funds_returns_seeded_fund(client: TestClient) -> None:
    res = client.get("/api/v1/funds")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] == 1
    assert len(body["funds"]) == 1
    assert body["funds"][0]["scheme_code"] == "118989"
    assert body["funds"][0]["riskometer_level"] == "VeryHigh"


def test_get_fund_detail_phase2_cache_absent(client: TestClient) -> None:
    """The hard graceful-degradation contract: when fund_returns_cache
    doesn't exist (Phase 2 hasn't landed), the endpoint must still
    return 200 with metrics=null. The frontend renders em-dashes.
    """
    res = client.get("/api/v1/funds/118989")
    assert res.status_code == 200
    body = res.json()
    assert body["fund"]["scheme_code"] == "118989"
    assert body["fund"]["scheme_name"].startswith("HDFC Top 100")
    assert body["metrics"] is None, "Phase 2 absent → metrics must be null"
    assert len(body["nav_history"]) > 0
    assert len(body["benchmark_history"]) > 0


def test_get_fund_detail_phase2_cache_present(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When Phase 2 has populated the cache, the metrics block must be
    surfaced verbatim (with floats coerced)."""
    # Reach the same engine via the patched factory.
    sess = funds_router._open_session()
    assert sess is not None
    sess.execute(text(
        """
        CREATE TABLE fund_returns_cache (
            scheme_code TEXT PRIMARY KEY,
            ret_1y REAL, ret_3y REAL, ret_5y REAL, ret_10y REAL, ret_si REAL,
            cagr_3y REAL, cagr_5y REAL,
            ter_direct REAL, ter_regular REAL,
            yieldiq_fund_score INTEGER
        )
        """
    ))
    sess.execute(text(
        "INSERT INTO fund_returns_cache VALUES "
        "('118989', 15.2, 18.4, 14.1, 12.0, 13.5, 18.4, 14.1, "
        "1.05, 1.85, 78)"
    ))
    sess.commit()
    sess.close()

    res = client.get("/api/v1/funds/118989")
    assert res.status_code == 200
    body = res.json()
    assert body["metrics"] is not None
    assert body["metrics"]["ret_1y"] == pytest.approx(15.2)
    assert body["metrics"]["ter_direct"] == pytest.approx(1.05)
    assert body["metrics"]["yieldiq_fund_score"] == 78


def test_get_fund_detail_404_for_unknown(client: TestClient) -> None:
    res = client.get("/api/v1/funds/999999")
    assert res.status_code == 404


def test_get_fund_detail_400_for_garbage_code(client: TestClient) -> None:
    res = client.get("/api/v1/funds/abc-123")
    assert res.status_code == 400
