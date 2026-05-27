# backend/services/funds/compute_returns.py
# Trailing returns + CAGR + monthly-anchored rolling windows from NAV.
#
# Pure compute. Takes an in-memory NAV series (dates + nav levels) plus
# the as-of date and returns a structured ReturnsResult. The DB read
# happens in recompute.py — keeping this module pure lets the tests use
# synthetic series with closed-form expected answers.
#
# Conventions:
#   * Returns are stored as decimal fractions (0.12 = 12 percent),
#     matching the equity-side convention.
#   * CAGR for window of N years uses calendar years between the two
#     anchor dates (T-N applied to as_of, with the closest prior trading
#     day used when the exact anniversary is a non-trading day).
#   * "Trailing return" for 1y is identical to CAGR_1y; we keep both
#     names for API readability.
#   * "Since inception" return is the simple price return from the
#     first observed NAV to the as_of NAV; SI CAGR uses fractional
#     years from inception.
#   * Rolling windows are monthly-anchored: for every month-end NAV
#     row, compute the 3y CAGR ending at that anchor. The set of
#     CAGRs forms the rolling distribution.
from __future__ import annotations

from dataclasses import dataclass, asdict
from datetime import date, timedelta
from typing import Optional, Sequence

import numpy as np


# Minimum trading days required to compute each window. AMFI publishes
# NAV on every trading day; we use a conservative ~245 days/year to
# absorb holidays and the occasional missed publication on debt schemes.
MIN_DAYS_1Y = 240
MIN_DAYS_3Y = 720
MIN_DAYS_5Y = 1200
MIN_DAYS_10Y = 2400

# Monthly anchor window minimum count — fewer than 12 rolling windows
# is too thin to summarise; we still report what we have.
MIN_ROLLING_3Y_WINDOWS = 12


@dataclass
class ReturnsResult:
    nav_as_of: Optional[date]
    history_days: int
    ret_1y: Optional[float]
    ret_3y: Optional[float]
    ret_5y: Optional[float]
    ret_10y: Optional[float]
    ret_si: Optional[float]
    cagr_3y: Optional[float]
    cagr_5y: Optional[float]
    cagr_10y: Optional[float]
    rolling_3y_mean: Optional[float]
    rolling_3y_median: Optional[float]
    rolling_3y_min: Optional[float]
    rolling_3y_max: Optional[float]
    rolling_3y_window_count: int
    notes: list[str]

    def to_dict(self) -> dict:
        return asdict(self)


def _to_np(dates: Sequence[date], navs: Sequence[float]) -> tuple[np.ndarray, np.ndarray]:
    d = np.array([np.datetime64(d_, "D") for d_ in dates])
    n = np.asarray(navs, dtype=float)
    order = np.argsort(d)
    return d[order], n[order]


def _nav_on_or_before(dates: np.ndarray, navs: np.ndarray, target: date) -> Optional[float]:
    """Return the NAV at the latest trading day on or before ``target``."""
    t = np.datetime64(target, "D")
    mask = dates <= t
    if not mask.any():
        return None
    idx = np.nonzero(mask)[0][-1]
    return float(navs[idx])


def _cagr(start_nav: float, end_nav: float, years: float) -> Optional[float]:
    if start_nav <= 0 or end_nav <= 0 or years <= 0:
        return None
    return float((end_nav / start_nav) ** (1.0 / years) - 1.0)


def _simple_return(start_nav: float, end_nav: float) -> Optional[float]:
    if start_nav <= 0 or end_nav <= 0:
        return None
    return float(end_nav / start_nav - 1.0)


def _anniversary(as_of: date, years: int) -> date:
    # Subtract N years; clamp Feb-29 to Feb-28 on non-leap targets.
    try:
        return as_of.replace(year=as_of.year - years)
    except ValueError:
        return as_of.replace(year=as_of.year - years, day=28)


def _monthly_anchors(dates: np.ndarray) -> list[int]:
    """Indices of the last trading day of each calendar month present in dates."""
    if dates.size == 0:
        return []
    months = dates.astype("datetime64[M]")
    out: list[int] = []
    for i in range(dates.size - 1):
        if months[i] != months[i + 1]:
            out.append(i)
    out.append(dates.size - 1)
    return out


def compute_returns_for_scheme(
    nav_dates: Sequence[date],
    nav_values: Sequence[float],
    as_of: Optional[date] = None,
) -> ReturnsResult:
    """Compute trailing + CAGR + rolling-window returns from a NAV series.

    ``nav_dates`` and ``nav_values`` must be equal length. Order does not
    matter (we sort). Duplicates on the same date are kept as-is and the
    last one wins for that date's anchor lookup.

    Returns a ReturnsResult with NULL fields where the underlying window
    is too short. ``notes`` lists every NULL reason for diagnostic
    logging in fund_returns_cache.notes.
    """
    notes: list[str] = []
    if len(nav_dates) != len(nav_values):
        raise ValueError("nav_dates and nav_values must have the same length")
    if len(nav_dates) == 0:
        return ReturnsResult(
            nav_as_of=None, history_days=0,
            ret_1y=None, ret_3y=None, ret_5y=None, ret_10y=None, ret_si=None,
            cagr_3y=None, cagr_5y=None, cagr_10y=None,
            rolling_3y_mean=None, rolling_3y_median=None,
            rolling_3y_min=None, rolling_3y_max=None, rolling_3y_window_count=0,
            notes=["empty NAV series"],
        )

    dates, navs = _to_np(nav_dates, nav_values)
    history_days = int(np.unique(dates).size)

    # Pin as_of to the latest available NAV date when not provided.
    if as_of is None:
        as_of = dates[-1].astype("datetime64[D]").astype(object)

    end_nav = _nav_on_or_before(dates, navs, as_of)
    if end_nav is None:
        notes.append(f"no NAV at or before {as_of}")
        return ReturnsResult(
            nav_as_of=None, history_days=history_days,
            ret_1y=None, ret_3y=None, ret_5y=None, ret_10y=None, ret_si=None,
            cagr_3y=None, cagr_5y=None, cagr_10y=None,
            rolling_3y_mean=None, rolling_3y_median=None,
            rolling_3y_min=None, rolling_3y_max=None, rolling_3y_window_count=0,
            notes=notes,
        )

    # Trailing windows.
    def _trailing(years: int, min_days: int) -> Optional[float]:
        if history_days < min_days:
            notes.append(f"history<{years}y ({history_days}<{min_days})")
            return None
        anch = _anniversary(as_of, years)
        n0 = _nav_on_or_before(dates, navs, anch)
        if n0 is None:
            notes.append(f"no NAV on or before T-{years}y anchor {anch}")
            return None
        return _simple_return(n0, end_nav)

    ret_1y = _trailing(1, MIN_DAYS_1Y)
    ret_3y = _trailing(3, MIN_DAYS_3Y)
    ret_5y = _trailing(5, MIN_DAYS_5Y)
    ret_10y = _trailing(10, MIN_DAYS_10Y)

    # CAGR. For 1y the trailing-return is identical to CAGR_1y so we
    # surface only the 3/5/10y CAGR columns separately.
    def _cagr_window(years: int, simple: Optional[float]) -> Optional[float]:
        if simple is None:
            return None
        return (1.0 + simple) ** (1.0 / years) - 1.0

    cagr_3y = _cagr_window(3, ret_3y)
    cagr_5y = _cagr_window(5, ret_5y)
    cagr_10y = _cagr_window(10, ret_10y)

    # Since inception. Use the first observed NAV anywhere in the series.
    first_date = dates[0].astype("datetime64[D]").astype(object)
    si_years = (as_of - first_date).days / 365.25
    ret_si = _simple_return(float(navs[0]), end_nav)
    # If inception is older than 1y, store SI as a CAGR (annualised);
    # else leave the simple cumulative return.
    if ret_si is not None and si_years >= 1.0:
        ret_si = (1.0 + ret_si) ** (1.0 / si_years) - 1.0

    # Monthly-anchored rolling 3y window distribution.
    rolling_count = 0
    rolling_mean = rolling_median = rolling_min = rolling_max = None
    if history_days >= MIN_DAYS_3Y:
        anchors = _monthly_anchors(dates)
        cagrs: list[float] = []
        for idx in anchors:
            anchor_date = dates[idx].astype("datetime64[D]").astype(object)
            anchor_nav = float(navs[idx])
            start_target = _anniversary(anchor_date, 3)
            start_nav = _nav_on_or_before(dates, navs, start_target)
            if start_nav is None:
                continue
            c = _cagr(start_nav, anchor_nav, 3.0)
            if c is not None:
                cagrs.append(c)
        rolling_count = len(cagrs)
        if rolling_count >= MIN_ROLLING_3Y_WINDOWS:
            arr = np.asarray(cagrs)
            rolling_mean = float(np.mean(arr))
            rolling_median = float(np.median(arr))
            rolling_min = float(np.min(arr))
            rolling_max = float(np.max(arr))
        else:
            notes.append(
                f"rolling-3y windows insufficient ({rolling_count}<{MIN_ROLLING_3Y_WINDOWS})"
            )
    else:
        notes.append("history<3y — rolling-3y skipped")

    return ReturnsResult(
        nav_as_of=as_of,
        history_days=history_days,
        ret_1y=ret_1y, ret_3y=ret_3y, ret_5y=ret_5y, ret_10y=ret_10y, ret_si=ret_si,
        cagr_3y=cagr_3y, cagr_5y=cagr_5y, cagr_10y=cagr_10y,
        rolling_3y_mean=rolling_mean,
        rolling_3y_median=rolling_median,
        rolling_3y_min=rolling_min,
        rolling_3y_max=rolling_max,
        rolling_3y_window_count=rolling_count,
        notes=notes,
    )
