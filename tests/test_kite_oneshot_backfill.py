"""Tests for scripts/kite_oneshot_backfill.py.

Mocks the KiteConnect SDK and uses an in-memory SQLite engine so the
unit tests are entirely DB- and network-free.
"""
from __future__ import annotations

import importlib.util
import os
import sys
from datetime import date, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy import create_engine, text

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

# Load the script as a module without executing main().
_spec = importlib.util.spec_from_file_location(
    "kite_oneshot_backfill",
    os.path.join(ROOT, "scripts", "kite_oneshot_backfill.py"),
)
kob = importlib.util.module_from_spec(_spec)
sys.modules["kite_oneshot_backfill"] = kob
_spec.loader.exec_module(kob)


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def sqlite_engine():
    """In-memory SQLite engine with daily_prices + live_quotes schemas."""
    engine = create_engine("sqlite:///:memory:")
    with engine.begin() as conn:
        conn.execute(text("""
            CREATE TABLE daily_prices (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                ticker       TEXT NOT NULL,
                trade_date   DATE NOT NULL,
                open_price   REAL,
                high_price   REAL,
                low_price    REAL,
                close_price  REAL,
                volume       INTEGER,
                UNIQUE (ticker, trade_date)
            )
        """))
        conn.execute(text("""
            CREATE TABLE live_quotes (
                ticker TEXT PRIMARY KEY,
                price  REAL NOT NULL,
                as_of  TIMESTAMP NOT NULL
            )
        """))
    return engine


@pytest.fixture()
def fake_instruments():
    """A 3-row NSE instrument master with HDFCBANK as the only EQ match."""
    return [
        {
            "instrument_token": 341249,
            "tradingsymbol": "HDFCBANK",
            "name": "HDFC BANK LTD",
            "segment": "NSE",
            "instrument_type": "EQ",
        },
        # Same symbol but different segment (futures leg) — must NOT match.
        {
            "instrument_token": 99999,
            "tradingsymbol": "HDFCBANK",
            "segment": "NFO-FUT",
            "instrument_type": "FUT",
        },
        {
            "instrument_token": 2953217,
            "tradingsymbol": "TCS",
            "segment": "NSE",
            "instrument_type": "EQ",
        },
    ]


def _synth_bars(start_close: float, n: int = 5) -> list[dict]:
    """Build n consecutive daily bars starting 2026-06-01."""
    out = []
    for i in range(n):
        c = start_close + i  # tiny ramp so we can verify upsert overwrites
        out.append({
            "date": datetime(2026, 6, 1 + i),
            "open": c - 1,
            "high": c + 2,
            "low":  c - 2,
            "close": c,
            "volume": 1_000_000 + i,
        })
    return out


# ---------------------------------------------------------------------------
# instrument lookup
# ---------------------------------------------------------------------------


def test_resolve_instrument_token_picks_eq_not_fut(fake_instruments):
    tok = kob.resolve_instrument_token(fake_instruments, "HDFCBANK")
    assert tok == 341249  # EQ leg, not the FUT one


def test_resolve_instrument_token_unknown_returns_none(fake_instruments):
    assert kob.resolve_instrument_token(fake_instruments, "NOSUCHTICKER") is None


# ---------------------------------------------------------------------------
# sanity filter
# ---------------------------------------------------------------------------


def test_sanity_filter_rejects_floor_and_ceiling():
    bars = [
        kob.KiteBar(date(2026, 6, 1), 1.0,  1.0,  1.0,  0.5,        100),  # below floor
        kob.KiteBar(date(2026, 6, 2), 100., 100., 100., 100.0,      200),  # ok
        kob.KiteBar(date(2026, 6, 3), 1e7,  1e7,  1e7,  2_000_000.0, 300),  # above ceiling
    ]
    kept, rejected = kob._sanity_filter(bars)
    assert rejected == 2
    assert len(kept) == 1
    assert kept[0].close == 100.0


# ---------------------------------------------------------------------------
# end-to-end dry-run vs commit
# ---------------------------------------------------------------------------


def _row_count(engine, ticker):
    with engine.connect() as conn:
        return conn.execute(
            text("SELECT COUNT(*) FROM daily_prices WHERE ticker=:t"),
            {"t": ticker},
        ).scalar()


def test_dry_run_does_not_write(sqlite_engine, fake_instruments):
    kc = MagicMock()
    kc.historical_data.return_value = _synth_bars(2000.0, n=3)

    outcome = kob.run_for_ticker(
        ticker="HDFCBANK",
        instruments=fake_instruments,
        kc=kc,
        engine=sqlite_engine,
        from_date=date(2026, 6, 1),
        to_date=date(2026, 6, 3),
        commit=False,
        update_live_quotes=False,
    )

    assert outcome.bars_fetched == 3
    assert outcome.rows_written == 0
    assert outcome.instrument_token == 341249
    assert _row_count(sqlite_engine, "HDFCBANK") == 0


def test_commit_writes_rows(sqlite_engine, fake_instruments):
    kc = MagicMock()
    kc.historical_data.return_value = _synth_bars(2000.0, n=3)

    outcome = kob.run_for_ticker(
        ticker="HDFCBANK",
        instruments=fake_instruments,
        kc=kc,
        engine=sqlite_engine,
        from_date=date(2026, 6, 1),
        to_date=date(2026, 6, 3),
        commit=True,
        update_live_quotes=False,
    )

    assert outcome.rows_written == 3
    assert _row_count(sqlite_engine, "HDFCBANK") == 3
    # latest close is start + (n-1) = 2002
    with sqlite_engine.connect() as conn:
        last = conn.execute(text(
            "SELECT close_price FROM daily_prices WHERE ticker='HDFCBANK' "
            "ORDER BY trade_date DESC LIMIT 1"
        )).scalar()
    assert last == pytest.approx(2002.0)


def test_idempotent_second_run(sqlite_engine, fake_instruments):
    """Running twice with the same data yields the same row count and closes."""
    kc = MagicMock()
    kc.historical_data.return_value = _synth_bars(2000.0, n=3)

    for _ in range(2):
        kob.run_for_ticker(
            ticker="HDFCBANK",
            instruments=fake_instruments,
            kc=kc,
            engine=sqlite_engine,
            from_date=date(2026, 6, 1),
            to_date=date(2026, 6, 3),
            commit=True,
            update_live_quotes=False,
        )

    assert _row_count(sqlite_engine, "HDFCBANK") == 3


def test_second_run_with_new_closes_updates_in_place(sqlite_engine, fake_instruments):
    """ON CONFLICT DO UPDATE: rerunning with corrected closes overwrites."""
    kc = MagicMock()
    kc.historical_data.return_value = _synth_bars(747.0, n=3)  # stale pre-bonus
    kob.run_for_ticker(
        ticker="HDFCBANK", instruments=fake_instruments, kc=kc,
        engine=sqlite_engine, from_date=date(2026, 6, 1), to_date=date(2026, 6, 3),
        commit=True, update_live_quotes=False,
    )
    assert _row_count(sqlite_engine, "HDFCBANK") == 3

    # Now Kite returns the post-bonus corrected series for the same dates.
    kc.historical_data.return_value = _synth_bars(2000.0, n=3)
    kob.run_for_ticker(
        ticker="HDFCBANK", instruments=fake_instruments, kc=kc,
        engine=sqlite_engine, from_date=date(2026, 6, 1), to_date=date(2026, 6, 3),
        commit=True, update_live_quotes=False,
    )
    # Still 3 rows (no dupes), but closes are the post-bonus values.
    assert _row_count(sqlite_engine, "HDFCBANK") == 3
    with sqlite_engine.connect() as conn:
        closes = [r[0] for r in conn.execute(text(
            "SELECT close_price FROM daily_prices WHERE ticker='HDFCBANK' "
            "ORDER BY trade_date"
        ))]
    assert closes == pytest.approx([2000.0, 2001.0, 2002.0])


def test_sanity_floor_rejects_bad_kite_row(sqlite_engine, fake_instruments):
    """A bar with close=0.1 must be dropped, not written."""
    kc = MagicMock()
    bars = _synth_bars(2000.0, n=2)
    bars.append({  # garbage row, e.g. corrupted Kite response
        "date": datetime(2026, 6, 3),
        "open": 0.1, "high": 0.1, "low": 0.1, "close": 0.1, "volume": 0,
    })
    kc.historical_data.return_value = bars
    outcome = kob.run_for_ticker(
        ticker="HDFCBANK", instruments=fake_instruments, kc=kc,
        engine=sqlite_engine, from_date=date(2026, 6, 1), to_date=date(2026, 6, 3),
        commit=True, update_live_quotes=False,
    )
    assert outcome.rows_rejected == 1
    assert outcome.bars_fetched == 2  # post-filter count
    assert _row_count(sqlite_engine, "HDFCBANK") == 2


def test_update_live_quotes_only_when_commit(sqlite_engine, fake_instruments):
    kc = MagicMock()
    kc.historical_data.return_value = _synth_bars(2000.0, n=3)

    # commit + update_live_quotes
    outcome = kob.run_for_ticker(
        ticker="HDFCBANK", instruments=fake_instruments, kc=kc,
        engine=sqlite_engine, from_date=date(2026, 6, 1), to_date=date(2026, 6, 3),
        commit=True, update_live_quotes=True,
    )
    assert outcome.live_quote_updated is True
    with sqlite_engine.connect() as conn:
        price = conn.execute(text(
            "SELECT price FROM live_quotes WHERE ticker='HDFCBANK'"
        )).scalar()
    assert price == pytest.approx(2002.0)  # last close


def test_dry_run_never_updates_live_quotes(sqlite_engine, fake_instruments):
    kc = MagicMock()
    kc.historical_data.return_value = _synth_bars(2000.0, n=3)
    outcome = kob.run_for_ticker(
        ticker="HDFCBANK", instruments=fake_instruments, kc=kc,
        engine=sqlite_engine, from_date=date(2026, 6, 1), to_date=date(2026, 6, 3),
        commit=False, update_live_quotes=True,  # asked for it, but dry-run
    )
    assert outcome.live_quote_updated is False
    with sqlite_engine.connect() as conn:
        cnt = conn.execute(text("SELECT COUNT(*) FROM live_quotes")).scalar()
    assert cnt == 0


def test_unknown_ticker_records_no_token(sqlite_engine, fake_instruments):
    kc = MagicMock()
    outcome = kob.run_for_ticker(
        ticker="NOSUCH", instruments=fake_instruments, kc=kc,
        engine=sqlite_engine, from_date=date(2026, 6, 1), to_date=date(2026, 6, 3),
        commit=True, update_live_quotes=False,
    )
    assert outcome.instrument_token is None
    assert outcome.rows_written == 0
    # And historical_data must NOT have been called for the unknown ticker.
    kc.historical_data.assert_not_called()
