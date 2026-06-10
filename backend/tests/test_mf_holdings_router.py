"""Contract tests for the public /api/v1/public/mf-holdings/{ticker} endpoint.

The endpoint must:
  1. Return 200 with available=false + empty list when the
     ``mf_holdings_by_stock`` table does not exist (the current
     production state — MF Phase 2 of the pipeline has not
     populated this table yet). This is the empty-state path the
     frontend panel branches on.
  2. Return 200 with available=true + a ranked list when the table
     exists and has rows.
  3. Synthesize a stable ``qoq_change_label`` (added / reduced /
     unchanged) per scheme from the signed ``qoq_change_cr`` delta.
  4. Reject empty / oversized tickers with HTTP 400.

The cache is module-level state in ``backend.services.cache_service``,
so each test clears the relevant key to keep runs independent.
"""
from __future__ import annotations

import sys
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

from backend.routers import public as public_router  # noqa: E402
from backend.services.cache_service import cache  # noqa: E402


def _make_app() -> FastAPI:
    app = FastAPI()
    app.include_router(public_router.router)
    return app


def _clear_cache(ticker: str) -> None:
    try:
        cache.delete(f"public:mf-holdings:{ticker.upper()}")
    except Exception:
        # CacheService may not expose delete in every env — falling
        # back to overwrite with a short TTL keeps tests deterministic.
        try:
            cache.set(f"public:mf-holdings:{ticker.upper()}", None, ttl=1)
        except Exception:
            pass


@pytest.fixture()
def client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    # Default: the table does not exist. ``_get_db_session`` returns
    # a SQLite session with NO mf_holdings_by_stock table — same
    # shape as the current production state.
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, future=True)
    monkeypatch.setattr(public_router, "_get_db_session", lambda: SessionLocal())
    return TestClient(_make_app())


def test_endpoint_returns_empty_state_when_table_missing(client: TestClient) -> None:
    _clear_cache("RELIANCE")
    res = client.get("/api/v1/public/mf-holdings/RELIANCE")
    assert res.status_code == 200, res.text
    body = res.json()
    assert body["ticker"] == "RELIANCE"
    assert body["available"] is False
    assert body["top_mf_holders"] == []
    assert body["total_mf_holding_cr"] is None
    assert body["total_mf_holding_pct"] is None
    assert body["net_qoq_change_cr"] is None
    assert body["as_of"] is None


def test_endpoint_strips_exchange_suffix(client: TestClient) -> None:
    _clear_cache("HDFCBANK")
    res = client.get("/api/v1/public/mf-holdings/HDFCBANK.NS")
    assert res.status_code == 200
    body = res.json()
    # The router normalises away .NS/.BO so the cache and lookup key
    # are exchange-independent. Verifies the frontend's symbol-strip
    # is mirrored on the server.
    assert body["ticker"] == "HDFCBANK"


def test_endpoint_rejects_empty_ticker(client: TestClient) -> None:
    # FastAPI path routing prevents "/mf-holdings/" — use whitespace
    # to exercise the in-handler guard.
    res = client.get("/api/v1/public/mf-holdings/%20")
    assert res.status_code == 400


def test_endpoint_rejects_garbage_ticker(client: TestClient) -> None:
    res = client.get("/api/v1/public/mf-holdings/X;Y'Z")
    assert res.status_code == 400


def test_endpoint_returns_ranked_holders_when_table_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Build an engine that HAS the mf_holdings_by_stock table seeded
    # with three rows for one ticker and ensure the endpoint ranks
    # by aum_in_stock_cr DESC and synthesizes change labels correctly.
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE mf_holdings_by_stock (
                ticker TEXT NOT NULL,
                scheme_code TEXT NOT NULL,
                scheme_name TEXT NOT NULL,
                amc TEXT,
                aum_in_stock_cr REAL,
                pct_of_aum REAL,
                pct_of_aum_held_by_mfs REAL,
                qoq_change_cr REAL,
                as_of_date DATE,
                PRIMARY KEY (ticker, scheme_code, as_of_date)
            )
            """
        ))
        rows = [
            ("RELIANCE", "118989", "HDFC Flexi Cap", "HDFC Mutual Fund",
             1240.0, 4.2, 5.8, 80.0,  "2026-04-30"),
            ("RELIANCE", "118990", "SBI Bluechip",   "SBI Mutual Fund",
             980.0,  3.1, 5.8, -50.0, "2026-04-30"),
            ("RELIANCE", "118991", "Axis Long Term Equity", "Axis Mutual Fund",
             420.0,  2.2, 5.8, 0.5,   "2026-04-30"),
        ]
        for r in rows:
            conn.execute(text(
                "INSERT INTO mf_holdings_by_stock VALUES "
                "(:tk, :sc, :sn, :amc, :aum, :pct, :tot, :qoq, :as_of)"
            ), {
                "tk": r[0], "sc": r[1], "sn": r[2], "amc": r[3],
                "aum": r[4], "pct": r[5], "tot": r[6], "qoq": r[7],
                "as_of": r[8],
            })
    SessionLocal = sessionmaker(bind=engine, future=True)
    monkeypatch.setattr(public_router, "_get_db_session", lambda: SessionLocal())
    _clear_cache("RELIANCE")

    client = TestClient(_make_app())
    res = client.get("/api/v1/public/mf-holdings/RELIANCE")
    assert res.status_code == 200, res.text
    body = res.json()

    assert body["available"] is True
    assert body["ticker"] == "RELIANCE"
    assert len(body["top_mf_holders"]) == 3
    # Ranked by aum_in_stock_cr DESC.
    assert body["top_mf_holders"][0]["scheme_name"] == "HDFC Flexi Cap"
    assert body["top_mf_holders"][1]["scheme_name"] == "SBI Bluechip"
    assert body["top_mf_holders"][2]["scheme_name"] == "Axis Long Term Equity"
    # Change labels: +80 → added, -50 → reduced, +0.5 (within ±1 band)
    # → unchanged.
    assert body["top_mf_holders"][0]["qoq_change_label"] == "added"
    assert body["top_mf_holders"][1]["qoq_change_label"] == "reduced"
    assert body["top_mf_holders"][2]["qoq_change_label"] == "unchanged"
    # Aggregate sums are surfaced.
    assert body["total_mf_holding_cr"] == pytest.approx(1240.0 + 980.0 + 420.0)
    assert body["net_qoq_change_cr"] == pytest.approx(80.0 - 50.0 + 0.5)
    assert body["as_of"] == "2026-04-30"
