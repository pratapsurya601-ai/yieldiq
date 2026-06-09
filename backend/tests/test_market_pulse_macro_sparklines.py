# backend/tests/test_market_pulse_macro_sparklines.py
"""Tests for the macro sparkline + change_pct enrichment shipped in
fix/markets-strip-macro-sparklines-and-change-pct (2026-06-09).

Covers:
- Happy path: a mocked yfinance returns 7 daily closes per symbol;
  `_build_macro_sparklines()` produces the expected dict with all 5
  non-index keys + SENSEX, and derives usd_inr_change_pct and
  risk_free_change_pct from the last-vs-previous close.
- Degradation path: a yfinance fetch that raises returns None and the
  dict carries the silent-failure shape (key omitted, derived pct
  None) so the response still serializes and the frontend tile
  degrades to "—".
- `_change_pct_from_series` boundary cases (short series, non-positive
  previous close, valid series).
"""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

# Ensure project root on sys.path (same pattern as test_api.py).
_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest  # noqa: E402

from backend.routers import market as market_router  # noqa: E402
from backend.services.cache_service import cache as _cache  # noqa: E402


@pytest.fixture(autouse=True)
def _clear_cache_between_tests():
    """Each test starts with an empty cache so a hit from a prior test
    can't paper over a real fetch-path regression."""
    _cache.clear()
    yield
    _cache.clear()


def _fake_history_df(closes):
    """Build a minimal mock of the pandas DataFrame yfinance returns.

    Only the two attributes the helper touches need to exist:
    `empty` (bool), membership of "Close" (via `__contains__`), and
    `df["Close"].dropna().tolist()`.
    """
    df = MagicMock()
    df.empty = False
    df.__contains__ = lambda self, key: key == "Close"
    series = MagicMock()
    dropped = MagicMock()
    dropped.tolist.return_value = list(closes)
    series.dropna.return_value = dropped
    df.__getitem__ = lambda self, key: series if key == "Close" else None
    return df


# ── _change_pct_from_series ────────────────────────────────────────


def test_change_pct_none_for_empty_or_short_series():
    assert market_router._change_pct_from_series(None) is None
    assert market_router._change_pct_from_series([]) is None
    assert market_router._change_pct_from_series([100.0]) is None


def test_change_pct_none_for_non_positive_prev_close():
    # prev_close <= 0 would either divide-by-zero or invert the sign;
    # the helper returns None rather than emitting a nonsense delta.
    assert market_router._change_pct_from_series([0.0, 100.0]) is None
    assert market_router._change_pct_from_series([-1.0, 100.0]) is None


def test_change_pct_two_points_uses_last_vs_previous():
    # 83.50 → 83.75 = +0.30 %
    assert market_router._change_pct_from_series([83.50, 83.75]) == pytest.approx(0.30, abs=1e-2)
    # Negative move
    assert market_router._change_pct_from_series([100.0, 99.5]) == pytest.approx(-0.50, abs=1e-2)


def test_change_pct_longer_series_only_looks_at_last_two():
    # Series can be any length; only [-2] and [-1] matter.
    assert (
        market_router._change_pct_from_series([90.0, 91.0, 92.0, 100.0, 101.0])
        == pytest.approx(1.0, abs=1e-2)
    )


# ── _macro_sparkline_yf ────────────────────────────────────────────


def test_macro_sparkline_returns_last_n_closes():
    closes = [83.0, 83.1, 83.2, 83.3, 83.4, 83.5, 83.6, 83.7]
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = _fake_history_df(closes)
    with patch("yfinance.Ticker", return_value=fake_ticker) as ticker_cls:
        result = market_router._macro_sparkline_yf("USDINR=X", days=7)
    assert ticker_cls.called
    # Returns the last 7 closes (oldest→newest preserved).
    assert result == closes[-7:]


def test_macro_sparkline_cached_after_first_hit():
    closes = [70.0, 71.0, 72.0, 73.0]
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = _fake_history_df(closes)
    with patch("yfinance.Ticker", return_value=fake_ticker) as ticker_cls:
        first = market_router._macro_sparkline_yf("GC=F", days=7)
        second = market_router._macro_sparkline_yf("GC=F", days=7)
    assert first == closes[-7:]
    # Second call hits the cache, NOT yfinance — exactly one Ticker
    # construction across both invocations.
    assert ticker_cls.call_count == 1
    assert second == first


def test_macro_sparkline_returns_none_on_yfinance_exception():
    with patch("yfinance.Ticker", side_effect=RuntimeError("rate limited")):
        result = market_router._macro_sparkline_yf("USDINR=X", days=7)
    assert result is None


def test_macro_sparkline_returns_none_on_insufficient_data():
    # Only one valid close → series too short to plot a line.
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = _fake_history_df([83.0])
    with patch("yfinance.Ticker", return_value=fake_ticker):
        result = market_router._macro_sparkline_yf("USDINR=X", days=7)
    assert result is None


# ── _build_macro_sparklines ────────────────────────────────────────


def test_build_macro_sparklines_populates_all_keys_when_yfinance_ok():
    """Happy path: every symbol returns 7 closes, the dict carries all
    6 keys (5 non-index + SENSEX), and the derived change_pct dict has
    numeric values for USD/INR + INDIA10Y."""
    # Each yfinance call returns 7 daily closes (oldest→newest) ending
    # in a +1% move on the last day so the derived pct is unambiguous.
    closes = [100.0, 100.5, 100.3, 100.7, 101.0, 101.2, 102.21]  # +1.00% on last day
    fake_ticker = MagicMock()
    fake_ticker.history.return_value = _fake_history_df(closes)
    with patch("yfinance.Ticker", return_value=fake_ticker):
        sparks, derived = market_router._build_macro_sparklines()

    # All 6 keys present (USDINR, INDIA10Y, GOLD, SILVER, CRUDE, SENSEX).
    assert set(sparks.keys()) == {"USDINR", "INDIA10Y", "GOLD", "SILVER", "CRUDE", "SENSEX"}
    for series in sparks.values():
        assert isinstance(series, list)
        assert len(series) == 7
        assert all(isinstance(v, float) for v in series)
    # Derived pct for the two tiles that lacked one pre-fix.
    assert derived["usd_inr_change_pct"] == pytest.approx(1.0, abs=1e-2)
    assert derived["risk_free_change_pct"] == pytest.approx(1.0, abs=1e-2)


def test_build_macro_sparklines_degrades_to_empty_when_yfinance_unavailable():
    """yfinance raises on every Ticker construction → dict is empty
    and both derived pcts are None. The /pulse response still serializes
    (the merge path tolerates an empty dict)."""
    with patch("yfinance.Ticker", side_effect=RuntimeError("rate limited")):
        sparks, derived = market_router._build_macro_sparklines()
    assert sparks == {}
    assert derived == {
        "usd_inr_change_pct": None,
        "risk_free_change_pct": None,
    }


def test_build_macro_sparklines_partial_population_keeps_what_it_can():
    """Mixed yfinance state — some symbols succeed, others rate-limit.
    The dict carries only the keys that succeeded; derived pcts are
    None for the ones whose symbol failed."""
    def _ticker_side_effect(symbol):
        if symbol in {"USDINR=X", "GC=F"}:
            tk = MagicMock()
            tk.history.return_value = _fake_history_df(
                [100.0, 100.5, 100.3, 100.7, 101.0, 101.2, 102.21]
            )
            return tk
        raise RuntimeError(f"yfinance down for {symbol}")

    with patch("yfinance.Ticker", side_effect=_ticker_side_effect):
        sparks, derived = market_router._build_macro_sparklines()

    assert set(sparks.keys()) == {"USDINR", "GOLD"}
    # USD/INR succeeded → derived pct is numeric.
    assert derived["usd_inr_change_pct"] == pytest.approx(1.0, abs=1e-2)
    # India 10Y failed → derived pct stays None (frontend renders "—").
    assert derived["risk_free_change_pct"] is None


# ── Symbol-map sanity (regression guard for the hardcoded map) ────


def test_macro_yf_symbols_covers_every_marketsstrip_tile():
    """The frontend macroSpark() lookup uses these exact keys; if the
    backend ever drops one, the corresponding tile silently loses its
    sparkline. Lock the contract here."""
    expected_keys = {"USDINR", "INDIA10Y", "GOLD", "SILVER", "CRUDE", "SENSEX"}
    assert expected_keys.issubset(market_router._MACRO_YF_SYMBOLS.keys())
    # Symbols are non-empty strings — catches a future typo turning a
    # ticker into the empty string.
    for tile, sym in market_router._MACRO_YF_SYMBOLS.items():
        assert isinstance(sym, str) and sym, f"empty yfinance symbol for {tile}"
