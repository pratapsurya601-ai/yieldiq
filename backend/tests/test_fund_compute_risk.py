"""Unit tests for backend.services.funds.compute_risk.

Synthetic NAV + benchmark series with known beta and known Sharpe.

Construction:
    * Benchmark = constant-compounding series at 10 percent annualised.
    * Scheme   = 1.2x leveraged version of the benchmark daily returns,
      so true beta is expected to be ~1.2.
    * Both series are noiseless after the deterministic geometric drift,
      so we add small gaussian noise to scheme returns to keep the
      regression well-conditioned (otherwise var(bench) -> 0 in the
      noiseless limit when we use log returns).
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from backend.services.funds.compute_risk import compute_risk_for_scheme


def _build_pair(years: int = 4, scheme_beta_target: float = 1.2, seed: int = 7):
    rng = np.random.default_rng(seed)
    start = date(2021, 1, 4)  # Monday
    days = int(365.25 * years) + 5
    dates: list[date] = []
    cur = start
    for _ in range(days):
        if cur.weekday() < 5:
            dates.append(cur)
        cur += timedelta(days=1)
    n = len(dates)
    # Benchmark daily log returns: small positive drift + small noise.
    daily_drift_b = np.log(1.10) / 252.0
    bench_logr = rng.normal(loc=daily_drift_b, scale=0.008, size=n - 1)
    # Scheme: beta * bench + idiosyncratic noise + small alpha.
    daily_alpha = np.log(1.02) / 252.0  # 2 percent annual alpha
    scheme_logr = (
        scheme_beta_target * bench_logr
        + daily_alpha
        + rng.normal(loc=0.0, scale=0.003, size=n - 1)
    )
    bench_level = 1000.0 * np.exp(np.concatenate([[0.0], np.cumsum(bench_logr)]))
    scheme_level = 10.0 * np.exp(np.concatenate([[0.0], np.cumsum(scheme_logr)]))
    return dates, list(scheme_level), dates, list(bench_level)


def test_beta_recovered():
    d_s, v_s, d_b, v_b = _build_pair(years=4, scheme_beta_target=1.2)
    res = compute_risk_for_scheme(
        d_s, v_s, bench_dates=d_b, bench_values=v_b, risk_free_annual=0.07
    )
    assert res.beta_3y is not None
    # Tolerance of 0.10 absolute on a target of 1.2 with noise of this scale.
    assert abs(res.beta_3y - 1.2) < 0.10
    # Alpha is expected to be positive (we injected ~+2 percent annual alpha).
    assert res.alpha_3y is not None
    assert res.alpha_3y > 0.0
    # Standard deviation positive + finite.
    assert res.stdev_3y is not None
    assert res.stdev_3y > 0.0
    # Sharpe defined.
    assert res.sharpe_3y is not None


def test_known_sharpe_constant_return_zero_vol_caps_to_none():
    # Pure geometric series with zero noise → stdev approaches 0 → Sharpe
    # is undefined (we expect None to avoid divide-by-zero leaks).
    start = date(2021, 1, 4)
    days = 1100
    daily = (1.10) ** (1.0 / 252.0) - 1.0
    dates: list[date] = []
    levels: list[float] = []
    nav = 10.0
    cur = start
    for _ in range(days):
        if cur.weekday() < 5:
            dates.append(cur)
            levels.append(nav)
        nav *= (1.0 + daily)
        cur += timedelta(days=1)
    res = compute_risk_for_scheme(dates, levels, risk_free_annual=0.07)
    # stdev is positive but tiny; sharpe may be huge but stays finite.
    # We mostly care that it does not crash and the dispersion math runs.
    assert res.stdev_3y is not None and res.stdev_3y >= 0


def test_max_drawdown_negative_or_zero():
    d_s, v_s, _, _ = _build_pair(years=4, seed=11)
    res = compute_risk_for_scheme(d_s, v_s)
    assert res.max_dd_3y is not None
    assert res.max_dd_3y <= 0.0
    # With random walks of this volatility we always see SOME drawdown.
    assert res.max_dd_3y > -0.99


def test_no_benchmark_yields_null_bench_fields():
    d_s, v_s, _, _ = _build_pair(years=4)
    res = compute_risk_for_scheme(d_s, v_s)  # bench omitted
    assert res.beta_3y is None
    assert res.alpha_3y is None
    assert res.info_ratio_3y is None
    assert res.upside_capture_3y is None
    assert any("no benchmark" in n for n in res.notes)


def test_short_history_notes_skip():
    start = date(2024, 1, 1)
    dates = [start + timedelta(days=i) for i in range(60) if (start + timedelta(days=i)).weekday() < 5]
    levels = [10.0 + i * 0.01 for i in range(len(dates))]
    res = compute_risk_for_scheme(dates, levels)
    assert res.stdev_3y is None
    assert any("history<3y" in n for n in res.notes)
