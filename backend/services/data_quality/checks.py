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


def ratio_band_check(
    table: str,
    label: str,
    actual: Optional[float],
    warn_band: tuple[float, float],
    fail_band: tuple[float, float],
    context: Optional[dict[str, Any]] = None,
    require_present: bool = False,
) -> CheckResult:
    """Flag a derived ratio that escapes a plausible magnitude band.

    This is the workhorse for the unit/currency-integrity validator. The
    silent-wrong-number bug class (USD double-convert, asset_turnover=
    359808, INDIGO units) shares one fingerprint: a single field ends up
    off by a factor of ~10^N because revenue/assets/cash were carried in
    mismatched units (raw INR vs Crores) or a currency was double/half-
    applied. A correctly-computed ratio is unit-free, so it lands in a
    tight, sector-stable band; a unit-mangled one explodes by orders of
    magnitude. We catch the explosion, not the specific unit.

    Two nested bands:
    - ``fail_band`` (lo, hi): hard implausibility. A value outside this is
      almost certainly a unit/currency bug — no real listed company lands
      here. Promotes the check to ``fail`` (red).
    - ``warn_band`` (lo, hi): the comfortable real-world envelope. Outside
      ``warn_band`` but inside ``fail_band`` is a yellow ``warn`` — worth
      an eyeball (could be a genuine outlier, could be the early edge of a
      unit drift) but not a stop-the-line red.

    ``fail_band`` MUST be a superset of ``warn_band`` (lo_fail <= lo_warn,
    hi_fail >= hi_warn); the caller owns that contract.

    ``actual is None`` is treated as a pass by default (the field is
    simply absent / not computable — that's the null-rate validator's job,
    not this one). Pass ``require_present=True`` for invariants where a
    missing value is itself a failure.
    """
    lo_warn, hi_warn = warn_band
    lo_fail, hi_fail = fail_band
    threshold: dict[str, Any] = {
        "label": label,
        "actual": actual,
        "warn_band": [lo_warn, hi_warn],
        "fail_band": [lo_fail, hi_fail],
    }
    if context:
        threshold["context"] = context

    if actual is None:
        status: Status = "fail" if require_present else "pass"
        return CheckResult(
            name=f"ratio_band.{label}",
            status=status,
            details=(
                f"{table}: {label} is None"
                + (" (required, treated as fail)" if require_present else " (absent — skipped)")
            ),
            threshold=threshold,
        )

    if actual < lo_fail or actual > hi_fail:
        return CheckResult(
            name=f"ratio_band.{label}",
            status="fail",
            details=(
                f"{table}: {label}={actual:g} outside plausible band "
                f"[{lo_fail:g}, {hi_fail:g}] — unit/currency-mismatch signature"
            ),
            threshold=threshold,
        )
    if actual < lo_warn or actual > hi_warn:
        return CheckResult(
            name=f"ratio_band.{label}",
            status="warn",
            details=(
                f"{table}: {label}={actual:g} outside comfortable band "
                f"[{lo_warn:g}, {hi_warn:g}] (still within hard band "
                f"[{lo_fail:g}, {hi_fail:g}])"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name=f"ratio_band.{label}",
        status="pass",
        details=f"{table}: {label}={actual:g} within [{lo_warn:g}, {hi_warn:g}]",
        threshold=threshold,
    )


def cohort_fraction_check(
    table: str,
    label: str,
    matched: int,
    total: int,
    warn_pct: float,
    fail_pct: float,
    detail_suffix: str = "",
) -> CheckResult:
    """Flag when too large a fraction of a cohort shares a suspicious value.

    Some unit bugs are invisible per-row but obvious in aggregate. The
    canonical example is ``de_ratio == 0`` on 17/17 tickers of a cohort:
    a single zero is plausible (a genuinely debt-free company), but a
    whole cohort reading exactly zero means the denominator (equity) was
    dropped, mis-scaled, or the populator wrote a default. This helper
    fires on the *fraction* exceeding a threshold, not on any single row.

    ``matched`` = rows exhibiting the suspicious signature (e.g. exactly
    0, or NaN, or a sentinel). ``total`` = cohort size. Empty cohort
    (total<=0) is an informational pass.
    """
    threshold: dict[str, Any] = {
        "label": label,
        "matched": matched,
        "total": total,
        "warn_pct": warn_pct,
        "fail_pct": fail_pct,
    }
    if total <= 0:
        return CheckResult(
            name=f"cohort_fraction.{label}",
            status="pass",
            details=f"{table}: {label} cohort empty (total={total})",
            threshold=threshold,
        )
    pct = matched / total * 100.0
    threshold["pct"] = round(pct, 2)
    suffix = f" {detail_suffix}" if detail_suffix else ""
    if pct >= fail_pct:
        return CheckResult(
            name=f"cohort_fraction.{label}",
            status="fail",
            details=(
                f"{table}: {label} {matched}/{total} ({pct:.1f}%) share the "
                f"suspicious value (>= {fail_pct}% fail threshold){suffix}"
            ),
            threshold=threshold,
        )
    if pct >= warn_pct:
        return CheckResult(
            name=f"cohort_fraction.{label}",
            status="warn",
            details=(
                f"{table}: {label} {matched}/{total} ({pct:.1f}%) share the "
                f"suspicious value (>= {warn_pct}% warn threshold){suffix}"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name=f"cohort_fraction.{label}",
        status="pass",
        details=(
            f"{table}: {label} {matched}/{total} ({pct:.1f}%) below "
            f"{warn_pct}% warn threshold{suffix}"
        ),
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
    "ratio_band_check",
    "cohort_fraction_check",
    "last_update_recency",
    "schema_columns_present",
]
