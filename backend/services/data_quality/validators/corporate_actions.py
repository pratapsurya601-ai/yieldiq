"""corporate_actions validator (Phase A.2.1, 2026-05-23).

Why this table
--------------
Day-112 traced the adj_close regression to multiple populators silently
writing the wrong value. The other half of that story is corporate
actions themselves: if the SPLIT/BONUS rows aren't in
``corporate_actions``, no adjustment math can possibly work. RELIANCE,
HDFCBANK and INFY have well-known splits/bonuses on record; if a
populator (NSE_CORP_ANN / NSE_ARCHIVE / BSE_CORP_FILE / yfinance) stops
fetching them, downstream adj_close goes silently stale.

This validator asserts:
- Row count stability (no silent zero-population)
- At least one SPLIT or BONUS action exists for each of three canary
  tickers we know have had them in the last 15y
- Required columns (ticker, action_type, ex_date, adjustment_factor)
  are present
- adjustment_factor is non-null for >=95% of SPLIT/BONUS rows
  (DIVIDEND rows legitimately have NULL adjustment_factor)
- Most recent row is within 30 days — corporate actions are sparse,
  but a 30-day gap with no new rows on a 2k-ticker universe means
  fetchers are broken
- data_quality_rank is set for >=90% of rows (Day-111-era invariant
  introduced in migration 025; rows without rank break the precedence
  guard in UPSERT)

Threshold sources
-----------------
- Canary tickers (RELIANCE, INFY, WIPRO): empirical — RELIANCE 1:1
  bonus 2017 + 2009 splits, INFY 1:1 bonus 2018, WIPRO 1:3 bonus 2019.
  All three should always have >=1 SPLIT/BONUS row.
- 95% adjustment_factor non-null on SPLIT/BONUS: empirical — the
  yfinance + NSE fetchers always populate this for those action types;
  failures indicate a parser regression.
- 30-day recency: NSE publishes corporate actions weekly; 30d absorbs
  4 missed runs which is the cron-deadman threshold.
- 90% data_quality_rank populated: needs-baseline — A.3 may tighten
  after a backfill run.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .. import CheckResult, HealthCheckResult
from ..checks import (
    last_update_recency,
    null_rate_check,
    row_count_stability,
    schema_columns_present,
)

CANARY_TICKERS_WITH_ACTIONS = ("RELIANCE", "INFY", "WIPRO")

EXPECTED_COLUMNS = [
    "ticker",
    "action_type",
    "ex_date",
    "adjustment_factor",
    "data_source",
    "data_quality_rank",
]


@dataclass
class CorporateActionsSample:
    row_count: int
    prior_row_count: int
    schema_columns: list[str]
    last_update: Optional[datetime]
    # Per-canary-ticker count of SPLIT-or-BONUS rows ever recorded.
    split_or_bonus_count: dict[str, int] = field(default_factory=dict)
    # Adjustment-factor null rate among SPLIT/BONUS rows
    adj_factor_split_bonus_null_count: int = 0
    adj_factor_split_bonus_sample_size: int = 0
    # data_quality_rank null rate (all rows)
    rank_null_count: int = 0
    rank_sample_size: int = 0


def _canary_actions_present_check(sample: CorporateActionsSample) -> CheckResult:
    """Each canary ticker MUST have >=1 SPLIT/BONUS row on record."""
    missing: list[str] = []
    detail_parts: list[str] = []
    for ticker in CANARY_TICKERS_WITH_ACTIONS:
        count = sample.split_or_bonus_count.get(ticker, 0)
        detail_parts.append(f"{ticker}={count}")
        if count == 0:
            missing.append(ticker)
    threshold = {
        "canary_tickers": list(CANARY_TICKERS_WITH_ACTIONS),
        "observed": sample.split_or_bonus_count,
        "min_required": 1,
    }
    if missing:
        return CheckResult(
            name="canary_actions_present",
            status="fail",
            details=(
                f"no SPLIT/BONUS rows for {', '.join(missing)} "
                "(corp-action fetcher likely broken)"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name="canary_actions_present",
        status="pass",
        details=f"canary tickers have SPLIT/BONUS rows ({', '.join(detail_parts)})",
        threshold=threshold,
    )


class CorporateActionsValidator:
    table = "corporate_actions"
    populator = "data_pipeline.sources.nse_corporate_actions"

    def __init__(
        self,
        sample_loader: Optional[Callable[[], CorporateActionsSample]] = None,
    ) -> None:
        self._sample_loader = sample_loader or self._load_sample_from_db

    def _load_sample_from_db(self) -> CorporateActionsSample:
        from ..db_loaders_a2 import load_corporate_actions_sample

        sample = load_corporate_actions_sample()
        if sample is None:
            raise NotImplementedError(
                "DATABASE_URL unset; CorporateActionsValidator skipped."
            )
        return sample

    def run(self) -> HealthCheckResult:
        sample = self._sample_loader()
        checks: list[CheckResult] = [
            schema_columns_present(self.table, EXPECTED_COLUMNS, sample.schema_columns),
            row_count_stability(self.table, sample.row_count, sample.prior_row_count),
            _canary_actions_present_check(sample),
            null_rate_check(
                self.table,
                "adjustment_factor (SPLIT/BONUS only)",
                sample.adj_factor_split_bonus_null_count,
                sample.adj_factor_split_bonus_sample_size,
                max_null_pct=5.0,
            ),
            null_rate_check(
                self.table,
                "data_quality_rank",
                sample.rank_null_count,
                sample.rank_sample_size,
                max_null_pct=10.0,
            ),
            last_update_recency(self.table, sample.last_update, max_age_hours=720.0),  # 30d
        ]
        return HealthCheckResult(
            table=self.table,
            populator=self.populator,
            last_run_at=datetime.now(timezone.utc),
            checks=checks,
        )


__all__ = [
    "CorporateActionsValidator",
    "CorporateActionsSample",
    "CANARY_TICKERS_WITH_ACTIONS",
    "EXPECTED_COLUMNS",
]
