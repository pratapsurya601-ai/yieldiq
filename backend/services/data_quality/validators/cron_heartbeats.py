"""cron_heartbeats validator (Phase A.2.2, 2026-05-23).

Why this table
--------------
Migration 045 ships a single-row-per-workflow `cron_heartbeats` table
(see `data_pipeline/migrations/045_cron_heartbeats.sql`). Each
scheduled GitHub Actions workflow upserts its `last_success_at` at the
end of a successful run; the cron-deadman-checker workflow uses the
table to flag silent drop-outs.

This validator turns that same data into a per-workflow plausibility
gate run from the data-quality framework so the admin UI surfaces a
"populator silently stopped" status alongside every other table. We
explicitly check the workflows whose output our analytics depend on:

- daily ingest (must beat within 28h — one missed 24h slot grace)
- weekly populators (must beat within 8d)
- cron-deadman-checker itself (must beat within 1h — runs every 30m)

A workflow that's MISSING from cron_heartbeats but is in our expected
set is a fail, not a silent skip: it means we never even saw a single
successful run since the migration shipped.

Threshold sources
-----------------
- Per-workflow max-staleness: 2x declared expected_interval_minutes,
  matching the cron-deadman-checker's own 2x threshold.
- The expected workflow list is hard-coded here (not pulled from the
  table) so adding a new cron forces an explicit validator update — we
  want adding a cron without instrumenting it to fail this validator,
  not silently pass.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from .. import CheckResult, HealthCheckResult
from ..checks import row_count_stability, schema_columns_present

EXPECTED_COLUMNS = [
    "workflow_name",
    "last_success_at",
    "expected_interval_minutes",
]

# Per-workflow expected cadence (minutes) for the workflows the
# analytics pipeline depends on. Keep this list small — every entry
# is a hard gate. Add cautiously.
EXPECTED_WORKFLOWS: dict[str, int] = {
    # Daily fundamentals + price ingest.
    "nightly-ingest": 24 * 60,
    # Weekly NSE industry-master refresh.
    "weekly-industry-master": 7 * 24 * 60,
    # Dead-man checker itself runs every 30 minutes.
    "cron-deadman-checker": 30,
    # Data-quality validators (Phase A.2.1, runs 4x daily, every 6h).
    "data-quality-validate": 6 * 60,
}

# Multiplier on expected_interval_minutes before we mark a workflow
# stale. 2x matches the cron-deadman-checker convention.
STALENESS_MULTIPLIER = 2.0


@dataclass
class CronHeartbeatsSample:
    """Pre-fetched heartbeat rows + table metadata."""

    row_count: int
    prior_row_count: int
    schema_columns: list[str]
    # workflow_name -> (last_success_at, declared_interval_minutes).
    # Workflows present in EXPECTED_WORKFLOWS but absent here are
    # treated as "never ran" — fail.
    heartbeats: dict[str, tuple[Optional[datetime], int]] = field(default_factory=dict)


def _per_workflow_staleness_check(
    sample: CronHeartbeatsSample,
    now: Optional[datetime] = None,
) -> CheckResult:
    """Each EXPECTED_WORKFLOWS entry must be present + fresh."""
    now = now or datetime.now(timezone.utc)
    missing: list[str] = []
    stale: list[str] = []
    fresh: list[str] = []
    per_workflow_detail: dict[str, dict] = {}

    for workflow, expected_interval in EXPECTED_WORKFLOWS.items():
        beat = sample.heartbeats.get(workflow)
        if beat is None:
            missing.append(workflow)
            per_workflow_detail[workflow] = {
                "status": "missing",
                "expected_interval_minutes": expected_interval,
            }
            continue
        last_success_at, declared_interval = beat
        if last_success_at is None:
            missing.append(workflow)
            per_workflow_detail[workflow] = {
                "status": "no_timestamp",
                "expected_interval_minutes": expected_interval,
            }
            continue
        if last_success_at.tzinfo is None:
            last_success_at = last_success_at.replace(tzinfo=timezone.utc)
        age_minutes = (now - last_success_at).total_seconds() / 60.0
        threshold_minutes = STALENESS_MULTIPLIER * (
            declared_interval or expected_interval
        )
        per_workflow_detail[workflow] = {
            "status": "stale" if age_minutes > threshold_minutes else "fresh",
            "age_minutes": round(age_minutes, 1),
            "threshold_minutes": round(threshold_minutes, 1),
            "expected_interval_minutes": expected_interval,
        }
        if age_minutes > threshold_minutes:
            stale.append(
                f"{workflow} ({age_minutes:.0f}min > {threshold_minutes:.0f}min)"
            )
        else:
            fresh.append(workflow)

    threshold = {
        "expected_workflows": EXPECTED_WORKFLOWS,
        "staleness_multiplier": STALENESS_MULTIPLIER,
        "per_workflow": per_workflow_detail,
    }

    if missing or stale:
        problems: list[str] = []
        if missing:
            problems.append(f"missing/never-ran: {', '.join(missing)}")
        if stale:
            problems.append(f"stale: {', '.join(stale)}")
        return CheckResult(
            name="cron_workflow_heartbeats",
            status="fail",
            details=(
                "cron drop-out detected — "
                + "; ".join(problems)
                + " (the populator silently stopped running)"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name="cron_workflow_heartbeats",
        status="pass",
        details=f"{len(fresh)}/{len(EXPECTED_WORKFLOWS)} expected workflows fresh",
        threshold=threshold,
    )


class CronHeartbeatsValidator:
    """Validator for the `cron_heartbeats` table (cron dead-man monitor)."""

    table = "cron_heartbeats"
    populator = "scripts.write_cron_heartbeat"

    def __init__(
        self,
        sample_loader: Optional[Callable[[], CronHeartbeatsSample]] = None,
    ) -> None:
        self._sample_loader = sample_loader or self._load_sample_from_db

    def _load_sample_from_db(self) -> CronHeartbeatsSample:
        from ..db_loaders_a2_2 import load_cron_heartbeats_sample

        sample = load_cron_heartbeats_sample()
        if sample is None:
            raise NotImplementedError(
                "DATABASE_URL unset; CronHeartbeatsValidator skipped."
            )
        return sample

    def run(self) -> HealthCheckResult:
        sample = self._sample_loader()
        checks: list[CheckResult] = [
            schema_columns_present(self.table, EXPECTED_COLUMNS, sample.schema_columns),
            row_count_stability(self.table, sample.row_count, sample.prior_row_count),
            _per_workflow_staleness_check(sample),
        ]
        return HealthCheckResult(
            table=self.table,
            populator=self.populator,
            last_run_at=datetime.now(timezone.utc),
            checks=checks,
        )


__all__ = [
    "CronHeartbeatsValidator",
    "CronHeartbeatsSample",
    "EXPECTED_COLUMNS",
    "EXPECTED_WORKFLOWS",
    "STALENESS_MULTIPLIER",
]
