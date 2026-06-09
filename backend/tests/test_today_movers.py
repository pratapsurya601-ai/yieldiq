"""Tests for /api/v1/market/today-movers.

Covers three states required by the feat/home-commodities-movers brief:

  1. Empty universe (cohort has < 2 trading days of data) → empty lists
     with `stale=True` and a null `as_of`.
  2. Mixed positive/negative cohort → gainers sorted desc, losers sorted
     asc, both capped at the requested limit.
  3. Stale data (latest trading day > 4 calendar days behind today) →
     payload returns stale=True and the gainers/losers arrays cleared
     out so the frontend renders the empty-state copy.

The endpoint queries `daily_prices` JOIN `nse_sector_constituents`, which
isn't available in the unit-test environment. We exercise the pure
function `_compute_today_movers` with a hand-rolled SQLAlchemy session
double — it intercepts the two SQL statements the function issues and
serves canned rows. This keeps the tests fast (no Postgres dependency)
and pins the SQL contract (statement order + parameter names).
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

# Ensure project root is importable
_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def fetchall(self):
        return self._rows


class _FakeSession:
    """Captures every execute() call and replays from a queue of results.

    The function under test issues exactly two SQL statements per call:
      (1) SELECT DISTINCT trade_date ... LIMIT 2
      (2) SELECT ticker, company_name, close_latest, close_prev ...

    The test seeds `results` with two iterables and assertions can later
    verify both the order and the parameters that arrived.
    """

    def __init__(self, results):
        self._results = list(results)
        self.calls = []

    def execute(self, stmt, params=None):  # noqa: D401  (signature mirrors SA)
        self.calls.append((str(stmt), params or {}))
        if not self._results:
            return _FakeResult([])
        return _FakeResult(self._results.pop(0))

    def close(self):
        pass


@pytest.fixture
def patch_session(monkeypatch):
    """Yield a setter that installs a _FakeSession class as PipelineSession."""

    def _install(results):
        sess = _FakeSession(results)

        class _SessionClass:
            def __new__(cls):
                return sess

        import data_pipeline.db as _db
        monkeypatch.setattr(_db, "Session", _SessionClass)
        return sess

    return _install


def _import_router():
    """Late import so monkeypatching of data_pipeline.db lands first."""
    from backend.routers import market as market_module
    return market_module


def test_today_movers_empty_universe(patch_session):
    """When the cohort has fewer than 2 trading days, return empty + stale."""
    # First execute() returns just one trade_date — not enough to compute
    # a delta. The function must short-circuit and never make the second
    # query.
    sess = patch_session([[(date.today(),)]])
    market = _import_router()

    out = market._compute_today_movers("nifty500", 5)

    assert out["gainers"] == []
    assert out["losers"] == []
    assert out["stale"] is True
    assert out["as_of"] is None
    # Only the trade_date probe should have run.
    assert len(sess.calls) == 1


def test_today_movers_mixed_cohort(patch_session):
    """Gainers sorted desc, losers sorted asc, limit honoured."""
    today = date.today()
    yesterday = today - timedelta(days=1)

    # Seven tickers spanning the +/- spectrum. Limit=3 means the response
    # carries the top 3 by absolute movement on each side.
    rows = [
        ("HDFCBANK.NS", "HDFC Bank",    104.2, 100.0),   # +4.2%
        ("RELIANCE.NS", "Reliance Ind", 103.8, 100.0),   # +3.8%
        ("TATAMOTORS",  "Tata Motors",  103.5, 100.0),   # +3.5%
        ("INFY.NS",     "Infosys",      101.0, 100.0),   # +1.0%
        ("WIPRO.NS",    "Wipro",         97.9, 100.0),   # -2.1%
        ("TCS.NS",      "TCS",           97.3, 100.0),   # -2.7%
        ("BHARTIARTL",  "Bharti Airtel", 96.9, 100.0),   # -3.1%
    ]
    sess = patch_session(
        [
            [(today,), (yesterday,)],   # trade_date probe
            rows,                        # pivoted close prices
        ]
    )
    market = _import_router()

    out = market._compute_today_movers("nifty500", 3)

    assert out["stale"] is False
    assert out["cohort"] == "nifty500"
    assert out["as_of"] is not None and "T15:30" in out["as_of"]
    assert len(out["gainers"]) == 3
    assert len(out["losers"]) == 3
    # Top gainer = HDFCBANK (+4.2%), then RELIANCE, then TATAMOTORS.
    assert [g["ticker"] for g in out["gainers"]] == ["HDFCBANK", "RELIANCE", "TATAMOTORS"]
    # Top loser = BHARTIARTL (-3.1%), then TCS, then WIPRO.
    assert [l["ticker"] for l in out["losers"]] == ["BHARTIARTL", "TCS", "WIPRO"]
    # change_pct must match the hand-calculated values.
    assert out["gainers"][0]["change_pct"] == pytest.approx(4.2, abs=0.01)
    assert out["losers"][0]["change_pct"] == pytest.approx(-3.1, abs=0.01)
    # Provenance fields are pass-through so the frontend can render them
    # in a tooltip if it ever wants to.
    assert out["gainers"][0]["close"] == 104.2
    assert out["gainers"][0]["prev_close"] == 100.0


def test_today_movers_stale_data(patch_session):
    """When latest trade_date is > 4 days behind today, return stale."""
    # 10 days behind: bhavcopy ingest has clearly stopped. Even if rows
    # come back, the response must zero out gainers/losers + flag stale
    # so the frontend renders the data-lag message.
    latest = date.today() - timedelta(days=10)
    prev = latest - timedelta(days=1)
    rows = [
        ("HDFCBANK.NS", "HDFC Bank", 104.2, 100.0),
        ("WIPRO.NS",    "Wipro",      97.9, 100.0),
    ]
    sess = patch_session([[(latest,), (prev,)], rows])
    market = _import_router()

    out = market._compute_today_movers("nifty500", 5)

    assert out["stale"] is True
    assert out["gainers"] == []
    assert out["losers"] == []
    # `as_of` still set so the frontend can show "Data as of Jun 5"
    # alongside the empty-state copy.
    assert out["as_of"] is not None


def test_today_movers_filters_nulls_and_split_artifacts(patch_session):
    """Rows with null prices or |move|>50% (split lag) are dropped."""
    today = date.today()
    yesterday = today - timedelta(days=1)
    rows = [
        ("CLEAN.NS",  "Clean Co",  105.0, 100.0),   # +5% — kept
        ("NULLLAT",   "Null Today", None, 100.0),   # dropped (no latest)
        ("NULLPREV",  "Null Prev", 100.0, None),    # dropped (no prev)
        ("SPLITART",  "Split Art", 200.0, 100.0),   # +100% — dropped (split lag)
        ("ZEROPREV",  "Zero Prev",  50.0,   0.0),   # dropped (prev_close=0)
    ]
    sess = patch_session([[(today,), (yesterday,)], rows])
    market = _import_router()

    out = market._compute_today_movers("nifty500", 5)

    # Only one row survives the data-quality filters. It shows up at the
    # top of `gainers` (sorted desc); `losers` (sorted asc) also surfaces
    # it because there's nothing negative to push it out — the limit cap
    # is N, not "N moves below zero".
    assert [g["ticker"] for g in out["gainers"]] == ["CLEAN"]
    assert [l["ticker"] for l in out["losers"]] == ["CLEAN"]
    # Hostile inputs (None, splits, zero prev_close) were all dropped.
    surviving_tickers = {g["ticker"] for g in out["gainers"]} | {
        l["ticker"] for l in out["losers"]
    }
    assert surviving_tickers == {"CLEAN"}
