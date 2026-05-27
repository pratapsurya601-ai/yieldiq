# backend/services/funds/compute_risk.py
# Risk metrics: stdev, beta, Sharpe, Sortino, max drawdown, Jensen
# alpha, information ratio, up/down capture.
#
# Pure compute. Takes a NAV series (the scheme) and a TRI series (the
# benchmark) aligned on calendar dates, plus a risk-free annual rate.
#
# Conventions:
#   * Daily log returns: r_t = ln(p_t / p_{t-1}).
#   * Annualised stdev: stdev(daily) * sqrt(252).
#   * Annualised mean return: mean(daily) * 252.
#   * Sharpe = (mean_ann - rf) / stdev_ann.
#   * Sortino uses downside stdev = stdev of negative daily returns
#     (relative to a zero floor), annualised the same way.
#   * Max drawdown is computed on cumulative-return path, value in the
#     half-open range (-1, 0]; expressed as a negative fraction.
#   * Beta uses cov(scheme, bench) / var(bench) on daily log returns
#     over the overlap window.
#   * Jensen alpha is the regression intercept of excess scheme return
#     on excess benchmark return: r_s - rf = a + b * (r_b - rf).
#     Reported annualised (intercept * 252).
#   * Information ratio = (mean(scheme - bench) * 252) /
#                        (stdev(scheme - bench) * sqrt(252))
#                       = mean(diff) * sqrt(252) / stdev(diff).
#   * Up/down capture ratios use MONTHLY-anchored returns (industry
#     convention) — monthly scheme return divided by monthly benchmark
#     return, averaged over months where benchmark return is >0 (up
#     capture) or <0 (down capture).
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date
from typing import Optional, Sequence

import numpy as np


TRADING_DAYS_PER_YEAR = 252
MIN_DAILY_OVERLAP_3Y = 600   # ~2.4 years of overlap minimum to label as 3y
MIN_MONTHLY_OVERLAP = 18     # at least 18 months for capture ratios


@dataclass
class RiskResult:
    stdev_3y: Optional[float]
    sharpe_3y: Optional[float]
    sortino_3y: Optional[float]
    max_dd_3y: Optional[float]
    max_dd_5y: Optional[float]
    beta_3y: Optional[float]
    alpha_3y: Optional[float]
    info_ratio_3y: Optional[float]
    tracking_error_3y: Optional[float]
    upside_capture_3y: Optional[float]
    downside_capture_3y: Optional[float]
    benchmark_excess_3y: Optional[float]
    notes: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _align(
    s_dates: Sequence[date], s_vals: Sequence[float],
    b_dates: Sequence[date], b_vals: Sequence[float],
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Inner-join the two series on date; return sorted (dates, scheme, bench)."""
    s_map = dict(zip(s_dates, s_vals))
    b_map = dict(zip(b_dates, b_vals))
    common = sorted(set(s_map.keys()) & set(b_map.keys()))
    d = np.array([np.datetime64(c, "D") for c in common])
    s = np.array([float(s_map[c]) for c in common])
    b = np.array([float(b_map[c]) for c in common])
    return d, s, b


def _max_drawdown(level: np.ndarray) -> Optional[float]:
    if level.size < 2:
        return None
    peak = np.maximum.accumulate(level)
    dd = (level - peak) / peak
    return float(np.min(dd))


def _monthly_returns(dates: np.ndarray, level: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """Last-of-month resample → monthly simple returns."""
    if dates.size == 0:
        return np.array([]), np.array([])
    months = dates.astype("datetime64[M]")
    last_idx = []
    for i in range(dates.size - 1):
        if months[i] != months[i + 1]:
            last_idx.append(i)
    last_idx.append(dates.size - 1)
    last_idx = np.array(last_idx)
    m_dates = dates[last_idx]
    m_level = level[last_idx]
    if m_level.size < 2:
        return m_dates[:0], np.array([])
    m_ret = m_level[1:] / m_level[:-1] - 1.0
    return m_dates[1:], m_ret


def compute_risk_for_scheme(
    nav_dates: Sequence[date],
    nav_values: Sequence[float],
    bench_dates: Optional[Sequence[date]] = None,
    bench_values: Optional[Sequence[float]] = None,
    risk_free_annual: float = 0.071,
    as_of: Optional[date] = None,
) -> RiskResult:
    """Compute stdev / Sharpe / Sortino / drawdown / beta / alpha / IR /
    up-down capture / tracking error over the trailing 3y window
    (and 5y for max drawdown only).

    Benchmark inputs may be None — beta/alpha/IR/capture are then NULL.
    Risk-free is an annual rate as a decimal fraction (0.071 = 7.1%).
    """
    notes: list[str] = []
    if len(nav_dates) != len(nav_values):
        raise ValueError("nav_dates and nav_values must match")
    if len(nav_dates) < 2:
        notes.append("NAV series too short for risk math")
        return RiskResult(
            stdev_3y=None, sharpe_3y=None, sortino_3y=None,
            max_dd_3y=None, max_dd_5y=None,
            beta_3y=None, alpha_3y=None, info_ratio_3y=None,
            tracking_error_3y=None,
            upside_capture_3y=None, downside_capture_3y=None,
            benchmark_excess_3y=None,
            notes=notes,
        )

    # Sort + np-ify scheme.
    s_pairs = sorted(zip(nav_dates, nav_values))
    s_d = np.array([np.datetime64(x[0], "D") for x in s_pairs])
    s_v = np.array([float(x[1]) for x in s_pairs])
    if as_of is None:
        as_of = s_d[-1].astype("datetime64[D]").astype(object)

    # Slice to trailing 3y / 5y windows on the scheme series.
    cutoff_3y = np.datetime64(date(as_of.year - 3, as_of.month, max(1, as_of.day - 1)), "D") \
        if as_of.day > 1 else np.datetime64(date(as_of.year - 3, as_of.month, 1), "D")
    cutoff_5y = np.datetime64(date(as_of.year - 5, as_of.month, max(1, as_of.day - 1)), "D") \
        if as_of.day > 1 else np.datetime64(date(as_of.year - 5, as_of.month, 1), "D")

    s_3y_mask = s_d >= cutoff_3y
    s_5y_mask = s_d >= cutoff_5y
    s_3y_v = s_v[s_3y_mask]
    s_5y_v = s_v[s_5y_mask]

    rf_daily = (1.0 + risk_free_annual) ** (1.0 / TRADING_DAYS_PER_YEAR) - 1.0

    # Scheme-only metrics over the 3y window.
    stdev_3y = sharpe_3y = sortino_3y = max_dd_3y = max_dd_5y = None
    if s_3y_v.size >= MIN_DAILY_OVERLAP_3Y:
        log_r = np.diff(np.log(s_3y_v))
        stdev_3y = float(np.std(log_r, ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))
        mean_ann = float(np.mean(log_r) * TRADING_DAYS_PER_YEAR)
        # Convert log mean back to simple-annualised for the Sharpe numerator.
        # For the canonical Sharpe we want excess arithmetic return; we keep
        # the convention that risk_free_annual is a simple rate so a small
        # adjustment between log and simple is absorbed in practice.
        if stdev_3y > 0:
            sharpe_3y = (mean_ann - risk_free_annual) / stdev_3y
        # Downside dev: only negative daily log returns (vs zero MAR).
        downside = log_r[log_r < 0]
        if downside.size >= 5:
            d_stdev = float(np.std(downside, ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))
            if d_stdev > 0:
                sortino_3y = (mean_ann - risk_free_annual) / d_stdev
        max_dd_3y = _max_drawdown(s_3y_v)
    else:
        notes.append(f"history<3y for risk metrics ({s_3y_v.size}<{MIN_DAILY_OVERLAP_3Y})")

    # 5y drawdown — drawdown does not need a long-history exclusion since
    # the value is well-defined for any window, but skip if <1y.
    if s_5y_v.size >= 240:
        max_dd_5y = _max_drawdown(s_5y_v)

    # Benchmark-relative metrics.
    beta_3y = alpha_3y = info_ratio_3y = tracking_error_3y = None
    upside_capture_3y = downside_capture_3y = benchmark_excess_3y = None
    if bench_dates is not None and bench_values is not None and len(bench_dates) > 0:
        d, s, b = _align(
            [x.astype("datetime64[D]").astype(object) for x in s_d],
            list(s_v),
            list(bench_dates),
            list(bench_values),
        )
        m3 = d >= cutoff_3y
        d3, s3, b3 = d[m3], s[m3], b[m3]
        if s3.size >= MIN_DAILY_OVERLAP_3Y:
            r_s = np.diff(np.log(s3))
            r_b = np.diff(np.log(b3))
            var_b = float(np.var(r_b, ddof=1))
            if var_b > 0:
                beta_3y = float(np.cov(r_s, r_b, ddof=1)[0, 1] / var_b)
                # Jensen alpha via OLS on the excess-return form:
                #   (r_s - rf) = a + b (r_b - rf)
                excess_s = r_s - rf_daily
                excess_b = r_b - rf_daily
                # Use beta_3y as the slope (already computed) and derive
                # the intercept from the means, which is the closed-form
                # OLS intercept solution.
                intercept_daily = float(np.mean(excess_s) - beta_3y * np.mean(excess_b))
                alpha_3y = intercept_daily * TRADING_DAYS_PER_YEAR
            # Information ratio + tracking error on active return.
            active = r_s - r_b
            te = float(np.std(active, ddof=1) * np.sqrt(TRADING_DAYS_PER_YEAR))
            tracking_error_3y = te
            if te > 0:
                info_ratio_3y = float(np.mean(active) * TRADING_DAYS_PER_YEAR / te)
            # 3y excess return (annualised log-return diff).
            mean_s_ann = float(np.mean(r_s) * TRADING_DAYS_PER_YEAR)
            mean_b_ann = float(np.mean(r_b) * TRADING_DAYS_PER_YEAR)
            benchmark_excess_3y = mean_s_ann - mean_b_ann

            # Capture ratios on monthly returns.
            m_dates, m_s = _monthly_returns(d3, s3)
            _, m_b = _monthly_returns(d3, b3)
            n_months = min(m_s.size, m_b.size)
            if n_months >= MIN_MONTHLY_OVERLAP:
                m_s = m_s[:n_months]
                m_b = m_b[:n_months]
                up = m_b > 0
                dn = m_b < 0
                if up.sum() >= 3 and float(np.mean(m_b[up])) > 0:
                    upside_capture_3y = float(np.mean(m_s[up]) / np.mean(m_b[up]))
                if dn.sum() >= 3 and float(np.mean(m_b[dn])) < 0:
                    downside_capture_3y = float(np.mean(m_s[dn]) / np.mean(m_b[dn]))
            else:
                notes.append(f"monthly overlap insufficient for capture ({n_months}<{MIN_MONTHLY_OVERLAP})")
        else:
            notes.append(f"benchmark overlap<3y ({s3.size}<{MIN_DAILY_OVERLAP_3Y})")
    else:
        notes.append("no benchmark series supplied")

    return RiskResult(
        stdev_3y=stdev_3y, sharpe_3y=sharpe_3y, sortino_3y=sortino_3y,
        max_dd_3y=max_dd_3y, max_dd_5y=max_dd_5y,
        beta_3y=beta_3y, alpha_3y=alpha_3y, info_ratio_3y=info_ratio_3y,
        tracking_error_3y=tracking_error_3y,
        upside_capture_3y=upside_capture_3y, downside_capture_3y=downside_capture_3y,
        benchmark_excess_3y=benchmark_excess_3y,
        notes=notes,
    )
