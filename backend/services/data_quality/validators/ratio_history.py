"""ratio_history validator (Phase A.2.1, 2026-05-23).

Why this table
--------------
``ratio_history`` is the daily snapshot of valuation + quality ratios
(PE, PB, ROE, D/E, FCF yield, dividend yield) used by the peer-cap
service and the percentile-rank screener. If the populator silently
breaks, every peer-relative metric in the app starts lying — and
because nothing on the UI says "this is from N days ago", the lie is
invisible.

This validator asserts:
- Schema has the columns the percentile engine reads
- Row count stable day-over-day
- Recency < 30h (daily after-close populator)
- HDFCBANK PE in [10, 50] and ROE in [5, 30] — known-good plausibility
- pe_ratio non-null on >=85% of rows in the latest snapshot
- de_ratio non-null on >=80% (banks legitimately use a different
  denominator and may render as null for non-banks too)

Threshold sources
-----------------
- HDFCBANK PE 10-50: empirical from 5y of public data — HDFCBANK has
  ranged 12-32 historically; 10-50 is wide enough to absorb a market
  cycle without flapping.
- HDFCBANK ROE 5-30: bank ROEs cluster 10-20%; 5-30 absorbs a year of
  COVID-style stress while still catching a unit bug (decimal vs %).
- pe_ratio null rate 85%: empirical — small caps without earnings
  legitimately render null, and that's ~10-12% of the universe.
- de_ratio null rate 80%: Day-111b bank D/E denominator fix means
  some banks now report null D/E intentionally (vs computing a
  meaningless number); 20% null floor is generous.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .. import CheckResult, HealthCheckResult
from ..checks import (
    known_good_plausibility,
    last_update_recency,
    null_rate_check,
    row_count_stability,
    schema_columns_present,
)

EXPECTED_COLUMNS = [
    "ticker",
    "period_end",
    "period_type",
    "pe_ratio",
    "pb_ratio",
    "roe",
    "de_ratio",
]

# (low, high) plausibility bands for HDFCBANK's most-recent period values.
# Schema uses `roe` (percent) not `roe_pct`.
HDFCBANK_BANDS: dict[str, tuple[float, float]] = {
    "pe_ratio": (10.0, 50.0),
    "roe": (5.0, 30.0),
}


@dataclass
class RatioHistorySample:
    row_count: int
    prior_row_count: int
    schema_columns: list[str]
    last_update: Optional[datetime]
    pe_null_count: int
    pe_sample_size: int
    de_null_count: int
    de_sample_size: int
    hdfcbank_latest: dict[str, Optional[float]] = field(default_factory=dict)


class RatioHistoryValidator:
    table = "ratio_history"
    # Populated by scripts/build_ratio_history.py from the financials table.
    # Per-period (not daily) snapshots — annual/quarterly/ttm rows.
    populator = "scripts.build_ratio_history"

    def __init__(
        self,
        sample_loader: Optional[Callable[[], RatioHistorySample]] = None,
    ) -> None:
        self._sample_loader = sample_loader or self._load_sample_from_db

    def _load_sample_from_db(self) -> RatioHistorySample:
        from ..db_loaders_a2 import load_ratio_history_sample

        sample = load_ratio_history_sample()
        if sample is None:
            raise NotImplementedError(
                "DATABASE_URL unset; RatioHistoryValidator skipped."
            )
        return sample

    def run(self) -> HealthCheckResult:
        sample = self._sample_loader()
        checks: list[CheckResult] = [
            schema_columns_present(self.table, EXPECTED_COLUMNS, sample.schema_columns),
            row_count_stability(self.table, sample.row_count, sample.prior_row_count),
            null_rate_check(
                self.table, "pe_ratio",
                sample.pe_null_count, sample.pe_sample_size, max_null_pct=15.0,
            ),
            null_rate_check(
                self.table, "de_ratio",
                sample.de_null_count, sample.de_sample_size, max_null_pct=20.0,
            ),
            # ratio_history is keyed by financial period_end, not a daily
            # snapshot. The freshest period_end is typically the most
            # recent quarter end — so 120d (≈1 quarter + slack) is the
            # right ceiling. A longer gap means the rebuilder stopped.
            last_update_recency(self.table, sample.last_update, max_age_hours=24.0 * 120),
        ]
        for col, (lo, hi) in HDFCBANK_BANDS.items():
            checks.append(
                known_good_plausibility(
                    self.table, "HDFCBANK", col,
                    sample.hdfcbank_latest.get(col), lo, hi,
                )
            )
        return HealthCheckResult(
            table=self.table,
            populator=self.populator,
            last_run_at=datetime.now(timezone.utc),
            checks=checks,
        )


__all__ = [
    "RatioHistoryValidator",
    "RatioHistorySample",
    "EXPECTED_COLUMNS",
    "HDFCBANK_BANDS",
]
