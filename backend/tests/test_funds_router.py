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
    # Mirror the full 075 column set the fetcher now SELECTs (returns +
    # risk + nav_as_of). The router degrades to metrics=null if any
    # referenced column is missing, so the table must carry the risk
    # columns for the populated path to surface.
    sess.execute(text(
        """
        CREATE TABLE fund_returns_cache (
            scheme_code TEXT PRIMARY KEY,
            nav_as_of DATE,
            ret_1y REAL, ret_3y REAL, ret_5y REAL, ret_10y REAL, ret_si REAL,
            cagr_3y REAL, cagr_5y REAL,
            ter_direct REAL, ter_regular REAL,
            yieldiq_fund_score INTEGER,
            stdev_3y REAL, sharpe_3y REAL, sortino_3y REAL,
            max_dd_3y REAL, max_dd_5y REAL,
            beta_3y REAL, alpha_3y REAL, info_ratio_3y REAL, tracking_error_3y REAL,
            upside_capture_3y REAL, downside_capture_3y REAL, benchmark_excess_3y REAL,
            category_percentile_3y REAL
        )
        """
    ))
    sess.execute(text(
        """
        INSERT INTO fund_returns_cache (
            scheme_code, nav_as_of,
            ret_1y, ret_3y, ret_5y, ret_10y, ret_si, cagr_3y, cagr_5y,
            ter_direct, ter_regular, yieldiq_fund_score,
            stdev_3y, sharpe_3y, sortino_3y, max_dd_3y, max_dd_5y,
            beta_3y, alpha_3y, info_ratio_3y, tracking_error_3y,
            upside_capture_3y, downside_capture_3y, benchmark_excess_3y,
            category_percentile_3y
        ) VALUES (
            '118989', '2026-06-13',
            15.2, 18.4, 14.1, 12.0, 13.5, 18.4, 14.1,
            1.05, 1.85, 78,
            0.142, 0.91, 1.22, -0.28, -0.34,
            0.98, 0.012, 0.45, 0.038,
            1.03, 0.96, 0.021,
            0.82
        )
        """
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
    # Additive risk block: re-keyed column names + 0..100 percentile.
    assert body["risk"] is not None
    assert body["risk"]["lookback"] == "3y"
    assert body["risk"]["as_of"] == "2026-06-13"
    assert body["risk"]["max_drawdown_3y"] == pytest.approx(-0.28)
    assert body["risk"]["up_capture_3y"] == pytest.approx(1.03)
    assert body["risk"]["down_capture_3y"] == pytest.approx(0.96)
    # 075 stores 0..1; the block re-scales to 0..100.
    assert body["risk"]["category_percentile_3y"] == pytest.approx(82.0)
    # Columns with no backing 075 column stay null.
    assert body["risk"]["stdev_5y"] is None
    assert body["risk"]["sharpe_5y"] is None
    # Flat metrics block is unchanged (backwards compat) — no risk fields.
    assert "stdev_3y" not in body["metrics"]


def test_get_fund_detail_404_for_unknown(client: TestClient) -> None:
    res = client.get("/api/v1/funds/999999")
    assert res.status_code == 404


def test_get_fund_detail_400_for_garbage_code(client: TestClient) -> None:
    res = client.get("/api/v1/funds/abc-123")
    assert res.status_code == 400


def test_portfolio_empty_state_when_no_holdings_table(client: TestClient) -> None:
    """Holdings scaffold: with no fund_holdings table the portfolio block
    returns the explicit empty 'updating' state (never 500s)."""
    res = client.get("/api/v1/funds/118989")
    assert res.status_code == 200
    p = res.json()["portfolio"]
    assert p is not None
    assert p["updating"] is True
    assert p["as_of_month"] is None
    assert p["holdings_count"] == 0
    assert p["holdings"] == []
    assert p["asset_allocation"] == []
    assert p["sector_allocation"] == []
    assert p["mcap_allocation"] == []


def test_portfolio_surfaces_holdings_and_rollups(
    client: TestClient,
) -> None:
    """Once fund_holdings has rows, the portfolio block surfaces top
    holdings + asset/sector/mcap roll-ups with updating=False."""
    sess = funds_router._open_session()
    assert sess is not None
    sess.execute(text(
        """
        CREATE TABLE fund_holdings (
            scheme_code TEXT NOT NULL,
            as_of_month DATE NOT NULL,
            isin TEXT NOT NULL,
            instrument TEXT,
            weight_pct REAL,
            asset_class TEXT,
            sector TEXT,
            mcap_bucket TEXT,
            change_3m_pct REAL,
            PRIMARY KEY (scheme_code, as_of_month, isin)
        )
        """
    ))
    sess.execute(text(
        "INSERT INTO fund_holdings VALUES "
        "('118989', '2026-05-01', 'INE001', 'Reliance', 8.5, 'Equity', "
        "'Energy', 'Large Cap', 0.4),"
        "('118989', '2026-05-01', 'INE002', 'HDFC Bank', 6.2, 'Equity', "
        "'Financials', 'Large Cap', -0.1),"
        "('118989', '2026-05-01', 'INE003', 'Cash', 2.0, 'Cash', "
        "NULL, NULL, 0.0)"
    ))
    sess.commit()
    sess.close()

    res = client.get("/api/v1/funds/118989")
    assert res.status_code == 200
    p = res.json()["portfolio"]
    assert p["updating"] is False
    assert p["as_of_month"] == "2026-05-01"
    assert p["holdings_count"] == 3
    # Heaviest weight first.
    assert p["holdings"][0]["instrument"] == "Reliance"
    assert p["holdings"][0]["weight_pct"] == pytest.approx(8.5)
    # Asset roll-up: Equity (8.5+6.2=14.7) before Cash (2.0).
    assert p["asset_allocation"][0]["label"] == "Equity"
    assert p["asset_allocation"][0]["weight_pct"] == pytest.approx(14.7)
    # Sector roll-up skips the null-sector Cash row.
    sectors = {s["label"] for s in p["sector_allocation"]}
    assert sectors == {"Energy", "Financials"}


def test_peers_endpoint_with_seeded_peer_and_category_average(
    client: TestClient,
) -> None:
    """/peers returns same-sub_category peers (self excluded) plus a
    trailing category-average pseudo-row when fund_category_stats exists."""
    sess = funds_router._open_session()
    assert sess is not None
    # A same-sub_category peer + a different-sub_category fund (excluded).
    sess.execute(text(
        """
        INSERT INTO funds (scheme_code, scheme_name, amc, plan, option,
                           category, sub_category, riskometer_level, is_active)
        VALUES
          ('200001', 'ICICI Pru Bluechip - Direct - Growth', 'ICICI', 'Direct',
           'Growth', 'Equity', 'Large Cap', 'VeryHigh', 1),
          ('300001', 'SBI Small Cap - Direct - Growth', 'SBI', 'Direct',
           'Growth', 'Equity', 'Small Cap', 'VeryHigh', 1)
        """
    ))
    # Returns cache (full 075 shape) so peer rows carry score/returns/ter.
    sess.execute(text(
        """
        CREATE TABLE fund_returns_cache (
            scheme_code TEXT PRIMARY KEY,
            nav_as_of DATE,
            ret_1y REAL, ret_3y REAL, ret_5y REAL, ret_10y REAL, ret_si REAL,
            cagr_3y REAL, cagr_5y REAL,
            ter_direct REAL, ter_regular REAL,
            yieldiq_fund_score INTEGER,
            stdev_3y REAL, sharpe_3y REAL, sortino_3y REAL,
            max_dd_3y REAL, max_dd_5y REAL,
            beta_3y REAL, alpha_3y REAL, info_ratio_3y REAL, tracking_error_3y REAL,
            upside_capture_3y REAL, downside_capture_3y REAL, benchmark_excess_3y REAL,
            category_percentile_3y REAL
        )
        """
    ))
    sess.execute(text(
        "INSERT INTO fund_returns_cache (scheme_code, ret_1y, ret_3y, "
        "ter_direct, yieldiq_fund_score) VALUES "
        "('200001', 12.5, 14.0, 0.9, 71)"
    ))
    # Category stats → drives the category-average pseudo-row.
    sess.execute(text(
        """
        CREATE TABLE fund_category_stats (
            sub_category TEXT PRIMARY KEY,
            updated_at TEXT, cache_version TEXT,
            median_cagr_1y REAL, median_cagr_3y REAL, median_cagr_5y REAL,
            avg_cagr_1y REAL, avg_cagr_3y REAL, avg_cagr_5y REAL,
            avg_ter REAL, avg_sharpe_3y REAL, avg_stdev_3y REAL,
            avg_max_drawdown_3y REAL, n_funds INTEGER
        )
        """
    ))
    sess.execute(text(
        "INSERT INTO fund_category_stats (sub_category, median_cagr_3y, "
        "avg_cagr_1y, avg_cagr_3y, avg_sharpe_3y, n_funds) VALUES "
        "('Large Cap', 0.13, 0.12, 0.135, 0.88, 12)"
    ))
    sess.commit()
    sess.close()

    res = client.get("/api/v1/funds/118989/peers")
    assert res.status_code == 200
    body = res.json()
    assert body["sub_category"] == "Large Cap"
    rows = body["peers"]
    # One real peer (200001), the Small Cap fund excluded, self excluded.
    real = [r for r in rows if not r["is_category_average"]]
    avg = [r for r in rows if r["is_category_average"]]
    assert len(real) == 1
    assert real[0]["scheme_code"] == "200001"
    assert real[0]["fund_score"] == 71
    assert real[0]["ret_1y"] == pytest.approx(12.5)
    # Category-average pseudo-row present, scheme_code null.
    assert len(avg) == 1
    assert avg[0]["scheme_code"] is None
    assert avg[0]["ret_1y"] == pytest.approx(0.12)


def test_category_stats_block_in_detail(client: TestClient) -> None:
    """The detail response surfaces a category_stats block when the table
    has a row for the fund's sub_category."""
    sess = funds_router._open_session()
    assert sess is not None
    sess.execute(text(
        """
        CREATE TABLE fund_category_stats (
            sub_category TEXT PRIMARY KEY,
            updated_at TEXT, cache_version TEXT,
            median_cagr_1y REAL, median_cagr_3y REAL, median_cagr_5y REAL,
            avg_cagr_1y REAL, avg_cagr_3y REAL, avg_cagr_5y REAL,
            avg_ter REAL, avg_sharpe_3y REAL, avg_stdev_3y REAL,
            avg_max_drawdown_3y REAL, n_funds INTEGER
        )
        """
    ))
    sess.execute(text(
        "INSERT INTO fund_category_stats (sub_category, median_cagr_3y, "
        "avg_cagr_3y, avg_ter, n_funds) VALUES "
        "('Large Cap', 0.131, 0.129, NULL, 12)"
    ))
    sess.commit()
    sess.close()

    res = client.get("/api/v1/funds/118989")
    assert res.status_code == 200
    cs = res.json()["category_stats"]
    assert cs is not None
    assert cs["sub_category"] == "Large Cap"
    assert cs["n_funds"] == 12
    assert cs["median_cagr_3y"] == pytest.approx(0.131)
    # avg_ter stays null — never fabricated.
    assert cs["avg_ter"] is None
