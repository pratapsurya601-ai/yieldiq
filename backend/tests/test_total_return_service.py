# backend/tests/test_total_return_service.py
"""Unit tests for the total_return_service.

The compute path is intentionally exercised with hand-rolled price /
dividend fixtures injected via monkeypatching the two loader helpers.
That keeps the test independent of yfinance / Postgres / Parquet —
the dependencies under test are the arithmetic and the curve
assembly, not the I/O.

Coverage:
    1. Price-only return when no dividends in window.
    2. Total return strictly above price return for a high-payout
       fixture (FMCG-shaped: ~5% running yield-on-cost).
    3. Reinvestment uses close-on-ex-date (next trading day on
       ex_date that falls on a weekend).
    4. Empty price data → graceful unavailable result.
    5. Result-dict shape (frontend contract).
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.services import total_return_service as svc


def _build_prices(start: date, end: date, start_px: float, end_px: float) -> dict[date, float]:
    """Linear-interpolated trading-day price series. Mon-Fri only."""
    days: list[date] = []
    cur = start
    while cur <= end:
        if cur.weekday() < 5:
            days.append(cur)
        cur += timedelta(days=1)
    if not days:
        return {}
    n = len(days) - 1 if len(days) > 1 else 1
    return {
        d: start_px + (end_px - start_px) * (i / n)
        for i, d in enumerate(days)
    }


def _patch_loaders(
    monkeypatch: pytest.MonkeyPatch,
    prices: dict[date, float],
    dividends: list[dict],
    div_source: str = "db",
):
    monkeypatch.setattr(svc, "_load_prices", lambda *_a, **_k: prices)
    monkeypatch.setattr(
        svc, "_load_dividend_events", lambda *_a, **_k: (dividends, div_source)
    )


# ── 1. price-only baseline ──────────────────────────────────────────


def test_price_only_when_no_dividends(monkeypatch: pytest.MonkeyPatch):
    today = date.today()
    start = today.replace(year=today.year - 5)
    prices = _build_prices(start - timedelta(days=5), today, 100.0, 150.0)
    _patch_loaders(monkeypatch, prices, [])

    r = svc.compute_total_return("FAKE", years=5, initial_investment=100_000)

    assert r.price_return_pct is not None
    assert r.total_return_pct is not None
    # Same start and end → equal returns
    assert pytest.approx(r.price_return_pct, abs=1e-6) == r.total_return_pct
    assert r.dividend_count == 0
    assert r.dividends_paid_total == 0.0
    # Notional invested * (1 + return) = total return value
    assert r.price_only_value is not None
    assert r.total_return_value is not None
    assert r.price_only_value == pytest.approx(r.total_return_value, abs=1e-2)


# ── 2. total return strictly above price for high-payout fixture ───


def test_total_return_above_price_with_dividends(monkeypatch: pytest.MonkeyPatch):
    today = date.today()
    start = today.replace(year=today.year - 5)
    prices = _build_prices(start - timedelta(days=5), today, 100.0, 150.0)
    # 5 annual dividends of 5/share each ⇒ ~5% running yield-on-cost.
    div_events = [
        {"ex_date": start + timedelta(days=365 * i + 10), "amount": 5.0}
        for i in range(5)
    ]
    _patch_loaders(monkeypatch, prices, div_events)

    r = svc.compute_total_return("FAKE", years=5, initial_investment=100_000)

    assert r.price_return_pct is not None
    assert r.total_return_pct is not None
    assert r.dividend_count == 5
    # The TR pp boost should be strictly positive and material.
    assert r.dividend_boost_pct is not None
    assert r.dividend_boost_pct > 5.0
    assert r.total_return_pct > r.price_return_pct
    # And the rupee-final values respect the same ordering.
    assert r.total_return_value is not None
    assert r.price_only_value is not None
    assert r.total_return_value > r.price_only_value


# ── 3. weekend ex_date snaps to next trade day ──────────────────────


def test_weekend_ex_date_snaps_forward(monkeypatch: pytest.MonkeyPatch):
    today = date.today()
    start = today.replace(year=today.year - 1)
    prices = _build_prices(start - timedelta(days=5), today, 100.0, 110.0)
    # Find a Saturday inside the window.
    sat = start
    while sat.weekday() != 5:
        sat += timedelta(days=1)
    div_events = [{"ex_date": sat, "amount": 4.0}]
    _patch_loaders(monkeypatch, prices, div_events)

    r = svc.compute_total_return("FAKE", years=1, initial_investment=100_000)

    # The single event should have been applied (count = 1) because the
    # forward-search picks up the following Monday's close.
    assert r.dividend_count == 1
    assert r.dividends_paid_total == pytest.approx(4.0)
    assert r.total_return_pct is not None
    assert r.price_return_pct is not None
    assert r.total_return_pct > r.price_return_pct


# ── 4. empty data → graceful unavailable ────────────────────────────


def test_empty_prices_returns_unavailable(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setattr(svc, "_load_prices", lambda *_a, **_k: {})
    monkeypatch.setattr(svc, "_load_dividend_events", lambda *_a, **_k: ([], "unavailable"))

    r = svc.compute_total_return("FAKE", years=5, initial_investment=100_000)
    assert r.price_return_pct is None
    assert r.total_return_pct is None
    assert r.data_source == "unavailable"
    assert r.start_price is None and r.end_price is None
    assert r.curve == []


# ── 5. result dict matches frontend contract ────────────────────────


def test_result_dict_shape(monkeypatch: pytest.MonkeyPatch):
    today = date.today()
    start = today.replace(year=today.year - 5)
    prices = _build_prices(start - timedelta(days=5), today, 100.0, 200.0)
    div_events = [
        {"ex_date": start + timedelta(days=180), "amount": 6.0},
        {"ex_date": start + timedelta(days=540), "amount": 7.0},
    ]
    _patch_loaders(monkeypatch, prices, div_events)

    r = svc.compute_total_return("FAKE", years=5)
    d = svc.result_to_dict(r)

    # Frontend reads these keys verbatim — pin the contract.
    expected_keys = {
        "ticker", "years", "start_date", "end_date",
        "start_price", "end_price",
        "price_return", "total_return",
        "dividends_paid_total", "dividend_count",
        "reinvested_value", "initial_investment",
        "price_only_value", "total_return_value",
        "dividend_boost_pct", "curve",
        "data_source", "notes",
    }
    assert expected_keys.issubset(d.keys())
    assert isinstance(d["curve"], list)
    # Every curve point keeps the (date, price_return, total_return) shape
    for pt in d["curve"]:
        assert set(pt.keys()) == {"date", "price_return", "total_return"}


# ── 6. validation ───────────────────────────────────────────────────


def test_zero_years_raises():
    with pytest.raises(ValueError):
        svc.compute_total_return("FAKE", years=0)
