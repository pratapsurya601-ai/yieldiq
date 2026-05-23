"""consensus_estimates validator (Phase A.2.1, 2026-05-23).

Why this table
--------------
The Benchmark Reconciliation Framework joins our DCF FVs against
consensus targets pulled nightly from yfinance + Finnhub into the
``consensus_estimates`` table. If the cron silently breaks, the
reconciliation page reports "no data" and we lose our cross-check
against the analyst community — exactly the failure mode that lets
DCF drift go unnoticed (Day-44, Day-71).

The table grows append-only (one row per ticker / source / day) so the
'recent count' metric is what matters, not absolute size.

Threshold sources
-----------------
- >=500 rows fetched in the last 24h: the nightly cron runs both
  yfinance (top-1500 tickers) and Finnhub (top-500). Realistic yield
  is ~800 rows/day (some tickers have no consensus); 500 is the
  conservative floor.
- HDFCBANK + RELIANCE + TCS must each have >=1 fresh row in the last
  7 days: these three are guaranteed to have analyst coverage; a
  miss means the join key is broken (Day-71 had RELIANCE.NS vs
  RELIANCE mismatch that broke the join silently).
- target_mean non-null on >=90% of rows: yfinance occasionally
  returns null targets for thinly-covered tickers; 10% is the noise
  floor.
- Recency < 48h: cron runs daily at 23:30 UTC, so 48h absorbs one
  missed run; tighter than that would flap.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .. import CheckResult, HealthCheckResult
from ..checks import (
    last_update_recency,
    null_rate_check,
    schema_columns_present,
)

CANARY_TICKERS_WITH_COVERAGE = ("HDFCBANK", "RELIANCE", "TCS")
MIN_FRESH_ROWS_24H = 500
RECENCY_HOURS = 48.0

EXPECTED_COLUMNS = [
    "ticker",
    "source",
    "target_mean",
    "fetched_at",
]


@dataclass
class ConsensusEstimatesSample:
    schema_columns: list[str]
    rows_in_last_24h: int
    last_fetched_at: Optional[datetime]
    target_mean_null_count: int
    target_mean_sample_size: int
    # Per-canary-ticker count of rows fetched in the last 7 days.
    fresh_rows_per_canary: dict[str, int] = field(default_factory=dict)


def _fresh_rows_check(sample: ConsensusEstimatesSample) -> CheckResult:
    """Last 24h must yield at least MIN_FRESH_ROWS_24H rows.

    The cron is the canonical writer; an empty 24h window means it
    silently failed. Yellow at half-floor (catch flaky API days),
    fail at zero (catch full outages).
    """
    n = sample.rows_in_last_24h
    threshold = {
        "rows_in_last_24h": n,
        "min_rows": MIN_FRESH_ROWS_24H,
    }
    if n == 0:
        return CheckResult(
            name="fresh_rows_24h",
            status="fail",
            details="zero consensus_estimates rows in last 24h (cron likely broken)",
            threshold=threshold,
        )
    if n < MIN_FRESH_ROWS_24H // 2:
        return CheckResult(
            name="fresh_rows_24h",
            status="fail",
            details=f"only {n} rows in last 24h (expected >= {MIN_FRESH_ROWS_24H})",
            threshold=threshold,
        )
    if n < MIN_FRESH_ROWS_24H:
        return CheckResult(
            name="fresh_rows_24h",
            status="warn",
            details=f"{n} rows in last 24h (below floor {MIN_FRESH_ROWS_24H} but non-zero)",
            threshold=threshold,
        )
    return CheckResult(
        name="fresh_rows_24h",
        status="pass",
        details=f"{n} rows in last 24h (>= {MIN_FRESH_ROWS_24H})",
        threshold=threshold,
    )


def _canary_coverage_check(sample: ConsensusEstimatesSample) -> CheckResult:
    """Each canary ticker must have >=1 row in last 7d."""
    missing: list[str] = []
    detail_parts: list[str] = []
    for ticker in CANARY_TICKERS_WITH_COVERAGE:
        n = sample.fresh_rows_per_canary.get(ticker, 0)
        detail_parts.append(f"{ticker}={n}")
        if n == 0:
            missing.append(ticker)
    threshold = {
        "canary_tickers": list(CANARY_TICKERS_WITH_COVERAGE),
        "observed_7d": sample.fresh_rows_per_canary,
    }
    if missing:
        return CheckResult(
            name="canary_coverage",
            status="fail",
            details=(
                f"no consensus rows in last 7d for {', '.join(missing)} "
                "(check ticker-key match: BHEL vs BHEL.NS — Day-71 signature)"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name="canary_coverage",
        status="pass",
        details=f"canary tickers covered ({', '.join(detail_parts)})",
        threshold=threshold,
    )


class ConsensusEstimatesValidator:
    table = "consensus_estimates"
    populator = "scripts.refresh_consensus"

    def __init__(
        self,
        sample_loader: Optional[Callable[[], ConsensusEstimatesSample]] = None,
    ) -> None:
        self._sample_loader = sample_loader or self._load_sample_from_db

    def _load_sample_from_db(self) -> ConsensusEstimatesSample:
        from ..db_loaders_a2 import load_consensus_estimates_sample

        sample = load_consensus_estimates_sample()
        if sample is None:
            raise NotImplementedError(
                "DATABASE_URL unset; ConsensusEstimatesValidator skipped."
            )
        return sample

    def run(self) -> HealthCheckResult:
        sample = self._sample_loader()
        checks: list[CheckResult] = [
            schema_columns_present(self.table, EXPECTED_COLUMNS, sample.schema_columns),
            _fresh_rows_check(sample),
            _canary_coverage_check(sample),
            null_rate_check(
                self.table,
                "target_mean",
                sample.target_mean_null_count,
                sample.target_mean_sample_size,
                max_null_pct=10.0,
            ),
            last_update_recency(self.table, sample.last_fetched_at, max_age_hours=RECENCY_HOURS),
        ]
        return HealthCheckResult(
            table=self.table,
            populator=self.populator,
            last_run_at=datetime.now(timezone.utc),
            checks=checks,
        )


__all__ = [
    "ConsensusEstimatesValidator",
    "ConsensusEstimatesSample",
    "CANARY_TICKERS_WITH_COVERAGE",
    "MIN_FRESH_ROWS_24H",
    "EXPECTED_COLUMNS",
]
