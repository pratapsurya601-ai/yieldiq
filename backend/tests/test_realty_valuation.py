# backend/tests/test_realty_valuation.py
# ═══════════════════════════════════════════════════════════════
# Unit tests for the realty-developer Approach-C engine + admin
# table + sector mistag overrides + routing fall-through.
#
# Covers acceptance criteria from
# docs/design/realty-developers-dcf-fix.md §5:
#
#   - Engine math: BVPS × sector_peer_PB + uplift_per_share
#   - PHOENIXLTD annuity overlay (NOI × cap-rate blend)
#   - Sector mistag overrides (LODHA / OBEROIRLTY / GODREJPROP)
#   - Table CRUD via the SQLite-mirror schema
#   - Routing fall-through: no land-bank row → engine returns None
#     so the caller drops to the existing Tier 2 generic path
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker

from backend.services.realty_valuation_service import (
    compute_realty_fair_value,
    SECTOR_PEER_PB,
    PHOENIXLTD_ANNUITY_SHARE,
    PHOENIXLTD_CAP_RATE,
)
from backend.services.analysis.constants import (
    REALTY_TICKERS,
    TICKER_SECTOR_OVERRIDES,
    is_realty_developer,
    is_reit,
)


# ── SQLite mirror of 047_realty_land_bank.sql (for CRUD tests) ──
_TEST_SCHEMA_SQL = """
CREATE TABLE realty_land_bank_inputs (
    ticker                       TEXT PRIMARY KEY,
    reporting_fy                 TEXT NOT NULL,
    land_bank_acres              NUMERIC,
    land_bank_market_value_cr    NUMERIC NOT NULL,
    land_bank_book_value_cr      NUMERIC,
    unsold_inventory_cr          NUMERIC,
    pre_sales_pipeline_cr        NUMERIC,
    uplift_per_share             NUMERIC NOT NULL,
    source_url                   TEXT,
    entered_by                   TEXT,
    entered_at                   TEXT NOT NULL DEFAULT '2026-05-18T00:00:00Z'
);
"""


@pytest.fixture()
def sess():
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text(_TEST_SCHEMA_SQL))
    Session = sessionmaker(bind=engine)
    s = Session()
    yield s
    s.close()
    engine.dispose()


# ─────────────────────────────────────────────────────────────────
# Engine math
# ─────────────────────────────────────────────────────────────────


def test_engine_math_dlf_basic():
    """DLF with BVPS ₹200, sector P/B 2.0×, uplift ₹100 → FV ₹500."""
    out = compute_realty_fair_value(
        ticker="DLF",
        financials={"bvps": 200.0, "shares": 1_000_000_000, "current_price": 562.0},
        land_bank_input={
            "ticker": "DLF",
            "reporting_fy": "FY25",
            "uplift_per_share": 100.0,
            "land_bank_market_value_cr": 50000.0,
        },
        sector_peer_pb=2.0,
    )
    assert out is not None
    assert out["fair_value"] == pytest.approx(500.0)
    assert out["bear_case"] == pytest.approx(375.0)
    assert out["bull_case"] == pytest.approx(625.0)
    assert out["method"] == "pb_plus_land_bank"
    assert out["_meta"]["bvps"] == pytest.approx(200.0)
    assert out["_meta"]["sector_peer_pb"] == pytest.approx(2.0)
    assert out["_meta"]["reporting_fy"] == "FY25"


def test_engine_bvps_from_pb_and_price():
    """BVPS derivation falls back to priceToBook × price when no
    direct BVPS is provided.
    """
    out = compute_realty_fair_value(
        ticker="LODHA",
        financials={"priceToBook": 2.0, "current_price": 800.0, "shares": 1e9},
        land_bank_input={"uplift_per_share": 50.0, "reporting_fy": "FY25"},
        sector_peer_pb=2.0,
    )
    # bvps = 800 / 2 = 400 → fv = 400×2 + 50 = 850
    assert out is not None
    assert out["fair_value"] == pytest.approx(850.0)


def test_engine_returns_none_without_bvps():
    """No BVPS, no priceToBook, no equity → engine refuses (returns
    None) so caller surfaces data_limited rather than fabricating an FV.
    """
    out = compute_realty_fair_value(
        ticker="DLF",
        financials={"current_price": 562.0},  # no book inputs
        land_bank_input={"uplift_per_share": 100.0, "reporting_fy": "FY25"},
        sector_peer_pb=2.0,
    )
    assert out is None


def test_engine_returns_none_without_land_bank_row():
    """No curation row → engine refuses → caller falls through to Tier 2.
    This is the routing fall-through guarantee.
    """
    out = compute_realty_fair_value(
        ticker="DLF",
        financials={"bvps": 200.0, "shares": 1e9, "current_price": 562.0},
        land_bank_input=None,
        sector_peer_pb=2.0,
    )
    assert out is None


def test_engine_returns_none_when_uplift_missing():
    out = compute_realty_fair_value(
        ticker="DLF",
        financials={"bvps": 200.0},
        land_bank_input={"reporting_fy": "FY25"},  # no uplift_per_share
        sector_peer_pb=2.0,
    )
    assert out is None


# ─────────────────────────────────────────────────────────────────
# PHOENIXLTD annuity overlay
# ─────────────────────────────────────────────────────────────────


def test_phoenixltd_annuity_overlay_blends_60_40():
    """PHOENIXLTD with NOI input gets a 60%-weighted annuity overlay
    blended with the 40%-weighted developer FV.
    """
    # bvps = 100, sector_pb = 2.0 → developer leg = 200 + uplift 30 = 230
    # operating_income = 1000 Cr × 0.60 = 600 Cr NOI
    # annuity_value = 600 / 0.08 = 7500 Cr → /1e9 shares × 1e7 = 75 per share
    # blended = 230 × 0.4 + 75 × 0.6 = 92 + 45 = 137
    out = compute_realty_fair_value(
        ticker="PHOENIXLTD",
        financials={
            "bvps": 100.0,
            "shares": 1_000_000_000,
            "current_price": 1734.0,
            "operating_income_ttm": 1000.0,
        },
        land_bank_input={"uplift_per_share": 30.0, "reporting_fy": "FY25"},
        sector_peer_pb=2.0,
    )
    assert out is not None
    assert out["method"] == "pb_plus_land_bank_with_annuity_overlay"
    assert out["_meta"]["annuity_share"] == pytest.approx(PHOENIXLTD_ANNUITY_SHARE)
    assert out["_meta"]["cap_rate"] == pytest.approx(PHOENIXLTD_CAP_RATE)
    assert out["_meta"]["annuity_fv_per_share"] == pytest.approx(75.0)
    assert out["fair_value"] == pytest.approx(137.0)


def test_phoenixltd_falls_back_to_developer_only_without_noi():
    """If no operating income is available, PHOENIXLTD degrades to
    the plain developer formula rather than failing.
    """
    out = compute_realty_fair_value(
        ticker="PHOENIXLTD",
        financials={"bvps": 100.0, "shares": 1e9, "current_price": 1734.0},
        land_bank_input={"uplift_per_share": 30.0, "reporting_fy": "FY25"},
        sector_peer_pb=2.0,
    )
    assert out is not None
    assert out["method"] == "pb_plus_land_bank"  # no _with_annuity_overlay
    assert out["fair_value"] == pytest.approx(230.0)


# ─────────────────────────────────────────────────────────────────
# Sector mistag overrides
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize("ticker", ["LODHA", "OBEROIRLTY", "GODREJPROP"])
def test_sector_mistag_overrides(ticker):
    """Three known-broken yfinance sector tags must hard-pin to
    'Real Estate' so downstream sector routing works.
    """
    assert TICKER_SECTOR_OVERRIDES.get(ticker) == "Real Estate"
    assert TICKER_SECTOR_OVERRIDES.get(f"{ticker}.NS") == "Real Estate"


# ─────────────────────────────────────────────────────────────────
# Classifier
# ─────────────────────────────────────────────────────────────────


@pytest.mark.parametrize(
    "ticker",
    ["DLF", "GODREJPROP", "LODHA", "OBEROIRLTY", "PRESTIGE",
     "PHOENIXLTD", "SOBHA", "BRIGADE", "MAHLIFE", "KEYSTONE",
     "MACROTECH", "NCC", "SHRIRAMPROP", "SUNTECK"],
)
def test_is_realty_developer_positive(ticker):
    assert is_realty_developer(ticker) is True
    assert is_realty_developer(f"{ticker}.NS") is True


def test_is_realty_developer_excludes_reits():
    """REITs must NOT be classified as developers — they have their
    own engine and the realty branch must never steal them.
    """
    for r in ("EMBASSY", "MINDSPACE", "BROOKFIELD", "NEXUS"):
        assert is_reit(r) is True
        assert is_realty_developer(r) is False


def test_is_realty_developer_negative():
    for t in ("RELIANCE", "TCS", "HDFCBANK", "INFY", "POWERGRID"):
        assert is_realty_developer(t) is False


def test_realty_tickers_set_matches_doc():
    """Locks the 14-ticker cohort against accidental drift."""
    expected = {
        "DLF", "GODREJPROP", "LODHA", "OBEROIRLTY",
        "PRESTIGE", "PHOENIXLTD", "SOBHA", "BRIGADE",
        "MAHLIFE", "KEYSTONE", "MACROTECH", "NCC",
        "SHRIRAMPROP", "SUNTECK",
    }
    assert REALTY_TICKERS == expected


# ─────────────────────────────────────────────────────────────────
# Table CRUD (SQLite mirror of the Postgres migration)
# ─────────────────────────────────────────────────────────────────


def test_table_insert_and_read(sess):
    sess.execute(
        text(
            "INSERT INTO realty_land_bank_inputs ("
            "ticker, reporting_fy, land_bank_market_value_cr, "
            "uplift_per_share, entered_by) "
            "VALUES (:t, :fy, :mv, :u, :by)"
        ),
        {"t": "DLF", "fy": "FY25", "mv": 50000, "u": 300, "by": "tester@example.com"},
    )
    sess.commit()
    row = sess.execute(
        text("SELECT ticker, reporting_fy, uplift_per_share FROM realty_land_bank_inputs WHERE ticker = :t"),
        {"t": "DLF"},
    ).fetchone()
    assert row is not None
    assert row[0] == "DLF"
    assert row[1] == "FY25"
    assert float(row[2]) == 300.0


def test_table_upsert_replaces(sess):
    """The admin POST endpoint uses ON CONFLICT (ticker) DO UPDATE.
    SQLite emulation: insert twice and assert the second wins.
    """
    sess.execute(
        text(
            "INSERT INTO realty_land_bank_inputs (ticker, reporting_fy, "
            "land_bank_market_value_cr, uplift_per_share) "
            "VALUES ('DLF', 'FY24', 40000, 250)"
        )
    )
    sess.execute(
        text(
            "INSERT INTO realty_land_bank_inputs (ticker, reporting_fy, "
            "land_bank_market_value_cr, uplift_per_share) "
            "VALUES ('DLF', 'FY25', 50000, 300) "
            "ON CONFLICT(ticker) DO UPDATE SET "
            "reporting_fy = excluded.reporting_fy, "
            "land_bank_market_value_cr = excluded.land_bank_market_value_cr, "
            "uplift_per_share = excluded.uplift_per_share"
        )
    )
    sess.commit()
    row = sess.execute(
        text("SELECT reporting_fy, uplift_per_share FROM realty_land_bank_inputs WHERE ticker = 'DLF'")
    ).fetchone()
    assert row[0] == "FY25"
    assert float(row[1]) == 300.0


def test_table_delete(sess):
    sess.execute(
        text(
            "INSERT INTO realty_land_bank_inputs (ticker, reporting_fy, "
            "land_bank_market_value_cr, uplift_per_share) "
            "VALUES ('DLF', 'FY25', 50000, 300)"
        )
    )
    sess.execute(
        text("DELETE FROM realty_land_bank_inputs WHERE ticker = 'DLF'")
    )
    sess.commit()
    n = sess.execute(
        text("SELECT COUNT(*) FROM realty_land_bank_inputs")
    ).fetchone()[0]
    assert n == 0


# ─────────────────────────────────────────────────────────────────
# Sanity — sector_peer_pb constant matches the design doc
# ─────────────────────────────────────────────────────────────────


def test_sector_peer_pb_default_in_band():
    """Design doc §5.4 anchors the cohort P/B at 2.5-3.5× live;
    we ship at 2.0 as a conservative FY25 floor. Lock the constant
    so it can't drift silently — any change here must go through
    the canary harness.
    """
    assert SECTOR_PEER_PB == pytest.approx(2.0)
