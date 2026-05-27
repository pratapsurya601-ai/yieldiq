"""Unit tests for backend.services.funds.compute_returns.

Synthetic NAV series with closed-form expected answers. The fixture is
a 6-year daily series compounding at exactly 12 percent annualised so
the 1y / 3y / 5y CAGRs are known-good anchors.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from backend.services.funds.compute_returns import (
    compute_returns_for_scheme,
    MIN_ROLLING_3Y_WINDOWS,
)


def _synthetic_compounding_series(
    start: date, days: int, annual_rate: float, start_nav: float = 10.0
):
    """Daily NAV series compounding at ``annual_rate`` per calendar year.

    Use a daily rate r_d = (1 + annual_rate) ** (1/365.25) - 1 so the
    series is closed-form-CAGR=annual_rate over any window. We then sample
    only weekdays so the trading-day count is realistic (~252/yr).
    """
    daily = (1.0 + annual_rate) ** (1.0 / 365.25) - 1.0
    out_d: list[date] = []
    out_n: list[float] = []
    nav = start_nav
    cur = start
    for i in range(days):
        # Skip weekends — synthetic AMFI behaviour.
        if cur.weekday() < 5:
            out_d.append(cur)
            out_n.append(nav)
        nav *= (1.0 + daily)
        cur += timedelta(days=1)
    return out_d, out_n


def test_known_cagr_12pct_six_years():
    start = date(2020, 1, 6)  # Monday
    days = 365 * 6 + 2  # ~6y of calendar days
    d, n = _synthetic_compounding_series(start, days, annual_rate=0.12)
    as_of = d[-1]
    res = compute_returns_for_scheme(d, n, as_of=as_of)

    assert res.nav_as_of == as_of
    assert res.history_days >= 1200  # > 5y of weekdays

    # 1y / 3y / 5y trailing simple returns: (1.12)^N - 1.
    assert res.ret_1y is not None
    assert abs(res.ret_1y - (1.12 - 1.0)) < 0.005
    assert res.ret_3y is not None
    assert abs(res.ret_3y - ((1.12 ** 3) - 1.0)) < 0.01
    assert res.ret_5y is not None
    assert abs(res.ret_5y - ((1.12 ** 5) - 1.0)) < 0.02

    # CAGRs are expected to all be ~12 percent.
    assert res.cagr_3y is not None
    assert abs(res.cagr_3y - 0.12) < 0.005
    assert res.cagr_5y is not None
    assert abs(res.cagr_5y - 0.12) < 0.005

    # Rolling 3y stats: every window is also ~12 percent.
    assert res.rolling_3y_window_count >= MIN_ROLLING_3Y_WINDOWS
    assert res.rolling_3y_mean is not None
    assert abs(res.rolling_3y_mean - 0.12) < 0.01
    assert abs(res.rolling_3y_median - 0.12) < 0.01

    # SI: 6y total → CAGR ~= 12 percent.
    assert res.ret_si is not None
    assert abs(res.ret_si - 0.12) < 0.01


def test_short_history_skips_long_windows():
    start = date(2025, 1, 6)
    d, n = _synthetic_compounding_series(start, 200, annual_rate=0.10)
    res = compute_returns_for_scheme(d, n)
    assert res.ret_1y is None  # < 1y of weekdays
    assert res.ret_3y is None
    assert res.ret_5y is None
    assert res.rolling_3y_mean is None
    # SI is still defined as a simple return on whatever exists.
    assert res.ret_si is not None
    assert any("history<" in note for note in res.notes)


def test_empty_series_returns_empty():
    res = compute_returns_for_scheme([], [])
    assert res.history_days == 0
    assert res.ret_1y is None
    assert res.rolling_3y_window_count == 0
    assert res.notes == ["empty NAV series"]


def test_unsorted_input_is_sorted_internally():
    start = date(2022, 1, 4)
    d, n = _synthetic_compounding_series(start, 800, annual_rate=0.10)
    # Reverse the inputs — function must sort.
    res1 = compute_returns_for_scheme(d, n)
    res2 = compute_returns_for_scheme(list(reversed(d)), list(reversed(n)))
    assert res1.ret_1y == pytest.approx(res2.ret_1y, abs=1e-9)


def test_mismatched_lengths_raise():
    with pytest.raises(ValueError):
        compute_returns_for_scheme([date(2024, 1, 1)], [1.0, 2.0])
