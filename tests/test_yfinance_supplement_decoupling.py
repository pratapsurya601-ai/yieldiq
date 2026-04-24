"""Unit tests for the 2026-04-25 three-phase decoupling of
`data_pipeline/sources/yfinance_supplement.py::fetch_and_store_yfinance`.

Regression target: LTIM-class bug where a missing `regularMarketPrice`
silently dropped historical-financials ingest for every ticker in the
batch, even when `ticker_obj.income_stmt` / `.cashflow` / `.balance_sheet`
were all populated.

These tests mock `yfinance.Ticker` so they do not hit the network.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

from data_pipeline.sources import yfinance_supplement as yfs


# --- Fixtures --------------------------------------------------------------


def _make_statement(period_end: date, **rows) -> pd.DataFrame:
    """Build a yfinance-shaped statement DataFrame.

    yfinance returns statements with metric names as the row index and
    period-end timestamps as columns. Values are raw rupees.
    """
    col = pd.Timestamp(period_end)
    return pd.DataFrame({col: rows}).T.T  # keeps the ts-col / str-index shape


def _mock_stock_with_financials_no_price():
    """Simulate the LTIM case: valid historical statements, no live price."""
    stock = MagicMock()

    # `.info` with regularMarketPrice=None is the exact LTIM symptom.
    stock.info = {
        "regularMarketPrice": None,
        "currentPrice": None,
        "previousClose": None,
        "sharesOutstanding": 296_000_000,  # lakh-scaled downstream
    }

    period = date(2025, 3, 31)
    col = pd.Timestamp(period)

    cf = pd.DataFrame(
        index=["Operating Cash Flow", "Capital Expenditure"],
        data={col: [50_000_000_000, -5_000_000_000]},
    )
    bs = pd.DataFrame(
        index=["Total Assets", "Stockholders Equity", "Total Debt", "Cash And Cash Equivalents"],
        data={col: [200_000_000_000, 80_000_000_000, 10_000_000_000, 15_000_000_000]},
    )
    inc = pd.DataFrame(
        index=["Total Revenue", "Net Income", "EBITDA"],
        data={col: [120_000_000_000, 18_000_000_000, 30_000_000_000]},
    )

    stock.cashflow = cf
    stock.balance_sheet = bs
    stock.income_stmt = inc
    stock.quarterly_income_stmt = pd.DataFrame()
    stock.quarterly_balance_sheet = pd.DataFrame()
    stock.quarterly_cashflow = pd.DataFrame()
    return stock


class _FakeSession:
    """Tiny SQLAlchemy-session stand-in.

    Tracks `add`/`commit`/`rollback` calls and returns `None` for every
    `query(...).filter_by(...).first()` lookup (so the code path always
    takes the "insert new row" branch).
    """

    def __init__(self):
        self.added = []
        self.commits = 0
        self.rollbacks = 0

    def query(self, *_a, **_kw):
        return self

    def filter_by(self, *_a, **_kw):
        return self

    def first(self):
        return None

    def add(self, obj):
        self.added.append(obj)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        pass


# --- The LTIM regression test ---------------------------------------------


def test_ltim_case_no_price_but_financials_ingest():
    """Given yfinance returns no `regularMarketPrice` but valid
    `income_stmt` / `cashflow` / `balance_sheet`, the structured result
    must be {price: False, financials: True, quarterly: False} and the
    `financials` table must get at least one row.
    """
    fake_db = _FakeSession()
    fake_stock = _mock_stock_with_financials_no_price()

    with patch.object(yfs.yf, "Ticker", return_value=fake_stock):
        # Bypass the ticker_aliases gate for this unknown ticker.
        result = yfs.fetch_and_store_yfinance("LTIM.NS", "LTIM", fake_db)

    assert result.price is False
    assert result.financials is True
    assert result.quarterly is False
    # At least one Financials row was added (inserted, not updated,
    # because the fake session returns `None` from `.first()`).
    fin_rows = [o for o in fake_db.added if type(o).__name__ == "Financials"]
    assert len(fin_rows) >= 1, "expected at least one Financials row to be added"
    # And NO MarketMetrics row (price phase was gated out).
    mm_rows = [o for o in fake_db.added if type(o).__name__ == "MarketMetrics"]
    assert mm_rows == []


def test_backward_compat_bool_truthiness():
    """Existing callers that do `if fetch_and_store_yfinance(...): ...`
    keep working: any phase success => truthy; all-fail => falsy.
    """
    r = yfs.YfIngestResult(price=False, financials=True, quarterly=False)
    assert bool(r) is True

    r = yfs.YfIngestResult(price=False, financials=False, quarterly=False)
    assert bool(r) is False

    r = yfs.YfIngestResult(price=True, financials=False, quarterly=False)
    assert bool(r) is True


def test_has_live_price_gate():
    assert yfs._has_live_price({"regularMarketPrice": 1234.5}) is True
    assert yfs._has_live_price({"currentPrice": 42}) is True
    assert yfs._has_live_price({"previousClose": 99}) is True
    assert yfs._has_live_price({"regularMarketPrice": None}) is False
    assert yfs._has_live_price({}) is False
    assert yfs._has_live_price(None) is False
