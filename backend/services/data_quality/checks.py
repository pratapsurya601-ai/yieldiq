"""Reusable check helpers (Phase A.1, 2026-05-23).

Each helper takes its inputs explicitly (no DB / no global state) so
unit tests can exercise boundary conditions without fixtures. Validators
in `validators/*.py` should pull data once, then call these helpers.

Convention: a helper returns exactly one CheckResult. If a single
logical assertion needs multiple thresholds (e.g. warn at 5%, fail at
10%), encode the tiered logic inside the helper rather than spreading
it across the caller — keeps validator code readable.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from . import CheckResult


def row_count_stability(
    table: str,
    current: int,
    prior: int,
    warn_drop_pct: float = 5.0,
    fail_drop_pct: float = 10.0,
) -> CheckResult:
    """Flag a sudden row-count drop between two runs of a populator.

    A populator that silently writes zero rows is the single most
    common data-quality failure mode we've seen. Default thresholds
    (warn >5%, fail >10%) are conservative — they fire on real
    weekend-vs-weekday differences for daily tables, but missing those
    is preferable to missing a populator that broke entirely.
    """
    if prior <= 0:
        # No baseline to compare against; treat as informational pass
        # rather than failing a fresh table.
        return CheckResult(
            name="row_count_stability",
            status="pass",
            details=f"{table}: no prior row count to compare (current={current})",
            threshold={"current": current, "prior": prior},
        )

    drop_pct = max(0.0, (prior - current) / prior * 100.0)
    threshold = {
        "current": current,
        "prior": prior,
        "drop_pct": round(drop_pct, 2),
        "warn_drop_pct": warn_drop_pct,
        "fail_drop_pct": fail_drop_pct,
    }

    if drop_pct >= fail_drop_pct:
        return CheckResult(
            name="row_count_stability",
            status="fail",
            details=f"{table}: row count dropped {drop_pct:.1f}% ({prior} -> {current})",
            threshold=threshold,
        )
    if drop_pct >= warn_drop_pct:
        return CheckResult(
            name="row_count_stability",
            status="warn",
            details=f"{table}: row count dropped {drop_pct:.1f}% ({prior} -> {current})",
            threshold=threshold,
        )
    return CheckResult(
        name="row_count_stability",
        status="pass",
        details=f"{table}: row count stable ({prior} -> {current})",
        threshold=threshold,
    )


def null_rate_check(
    table: str,
    column: str,
    null_count: int,
    sample_size: int,
    max_null_pct: float,
) -> CheckResult:
    """Fail if a column's null/empty rate exceeds `max_null_pct`.

    The caller is responsible for deciding what counts as "null" — for
    text columns we typically include empty strings; for numerics we
    typically include zero only when zero is impossible (e.g. shares
    outstanding). Pass the pre-computed `null_count` to keep this
    helper SQL-free.
    """
    if sample_size <= 0:
        return CheckResult(
            name=f"null_rate.{column}",
            status="fail",
            details=f"{table}.{column}: empty sample (size={sample_size})",
            threshold={"sample_size": sample_size, "max_null_pct": max_null_pct},
        )

    null_pct = null_count / sample_size * 100.0
    threshold = {
        "column": column,
        "null_count": null_count,
        "sample_size": sample_size,
        "null_pct": round(null_pct, 2),
        "max_null_pct": max_null_pct,
    }
    if null_pct > max_null_pct:
        return CheckResult(
            name=f"null_rate.{column}",
            status="fail",
            details=(
                f"{table}.{column}: {null_count}/{sample_size} null "
                f"({null_pct:.1f}% > {max_null_pct}% threshold)"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name=f"null_rate.{column}",
        status="pass",
        details=(
            f"{table}.{column}: {null_count}/{sample_size} null "
            f"({null_pct:.1f}% <= {max_null_pct}% threshold)"
        ),
        threshold=threshold,
    )


def known_good_plausibility(
    table: str,
    ticker: str,
    column: str,
    actual: Optional[float],
    min_value: float,
    max_value: float,
) -> CheckResult:
    """Fail if a known-good ticker's value falls outside a plausible band.

    "Known-good" means a high-cap, high-liquidity name whose value
    we'd notice if it suddenly went off — RELIANCE, TCS, HDFCBANK,
    NESTLEIND. Bands should be wide enough to absorb 1y volatility but
    tight enough to catch unit bugs (paise vs rupees) and stale data.
    """
    threshold = {
        "ticker": ticker,
        "column": column,
        "actual": actual,
        "min_value": min_value,
        "max_value": max_value,
    }
    if actual is None:
        return CheckResult(
            name=f"plausibility.{ticker}.{column}",
            status="fail",
            details=f"{table}: {ticker}.{column} is NULL (expected {min_value}-{max_value})",
            threshold=threshold,
        )
    if actual < min_value or actual > max_value:
        return CheckResult(
            name=f"plausibility.{ticker}.{column}",
            status="fail",
            details=(
                f"{table}: {ticker}.{column}={actual} outside plausible "
                f"band [{min_value}, {max_value}]"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name=f"plausibility.{ticker}.{column}",
        status="pass",
        details=f"{table}: {ticker}.{column}={actual} within [{min_value}, {max_value}]",
        threshold=threshold,
    )


def last_update_recency(
    table: str,
    last_update: Optional[datetime],
    max_age_hours: float,
    now: Optional[datetime] = None,
) -> CheckResult:
    """Fail if the most recent row is older than `max_age_hours`.

    Catches the "populator silently stopped running" failure mode.
    `now` is injectable so tests can pin time without monkeypatching.
    """
    now = now or datetime.now(timezone.utc)
    threshold = {
        "last_update": last_update.isoformat() if last_update else None,
        "max_age_hours": max_age_hours,
        "now": now.isoformat(),
    }
    if last_update is None:
        return CheckResult(
            name="last_update_recency",
            status="fail",
            details=f"{table}: no last_update timestamp recorded",
            threshold=threshold,
        )

    # Coerce naive timestamps to UTC so the subtraction never raises.
    if last_update.tzinfo is None:
        last_update = last_update.replace(tzinfo=timezone.utc)

    age = now - last_update
    age_hours = age.total_seconds() / 3600.0
    threshold["age_hours"] = round(age_hours, 2)

    if age > timedelta(hours=max_age_hours):
        return CheckResult(
            name="last_update_recency",
            status="fail",
            details=(
                f"{table}: last update {age_hours:.1f}h ago "
                f"(threshold {max_age_hours}h)"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name="last_update_recency",
        status="pass",
        details=f"{table}: last update {age_hours:.1f}h ago (threshold {max_age_hours}h)",
        threshold=threshold,
    )


def schema_columns_present(
    table: str,
    expected: list[str],
    actual: list[str],
) -> CheckResult:
    """Fail if any of `expected` columns is absent from `actual`.

    Doesn't fail on EXTRA columns — populators are free to add new
    fields without tripping the validator. Order is irrelevant.
    """
    missing = [c for c in expected if c not in actual]
    threshold = {"expected": expected, "actual": actual, "missing": missing}
    if missing:
        return CheckResult(
            name="schema_columns_present",
            status="fail",
            details=f"{table}: missing columns {missing}",
            threshold=threshold,
        )
    return CheckResult(
        name="schema_columns_present",
        status="pass",
        details=f"{table}: all {len(expected)} expected columns present",
        threshold=threshold,
    )


__all__ = [
    "row_count_stability",
    "null_rate_check",
    "known_good_plausibility",
    "last_update_recency",
    "schema_columns_present",
]
