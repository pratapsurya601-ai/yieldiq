"""Data-quality validator framework (Phase A.1, 2026-05-23).

Purpose
-------
Four silent data-quality regressions shipped to production in the run-up
to Day-112: industry field dropped at serializer, bank D/E using the
wrong denominator, three independent populators setting adj_close to
close_price, and 32/97 tickers missing compounded_growth.stock. None of
the existing unit tests caught any of them because they all asserted
shape, not plausibility.

This package defines the framework that subsequent validators plug into:
- `CheckResult`: one assertion's pass/warn/fail outcome with structured
  threshold context.
- `HealthCheckResult`: the bundle of CheckResults a Validator emits
  per run, with derived `overall_status` (green / yellow / red).
- `Validator`: structural protocol every validator implements.

The orchestrator (`scripts/run_data_quality_validators.py`) discovers
validators, runs them, and persists each result to the
`data_quality_runs` table (migration 057). A.2 will wire the cron +
admin endpoint + admin UI on top.

Scope discipline
----------------
This module deliberately ships ZERO domain knowledge. All
domain-specific thresholds and known-good values live in
`validators/*.py` so each can be reviewed in isolation. Common helpers
that multiple validators reuse (null-rate, recency, etc.) live in
`checks.py` and take their inputs explicitly so they're trivially
testable without a database.
"""
from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Literal, Optional, Protocol, runtime_checkable

Status = Literal["pass", "warn", "fail"]
OverallStatus = Literal["green", "yellow", "red"]


@dataclass
class CheckResult:
    """One assertion's outcome.

    `threshold` is a free-form dict so each check can record whatever
    context an operator needs to reproduce the decision (expected,
    actual, tolerance, sample_size, etc.). Keep keys short and stable;
    the admin UI in A.2 will render them verbatim.
    """

    name: str
    status: Status
    details: str
    threshold: dict[str, Any] = field(default_factory=dict)


@dataclass
class HealthCheckResult:
    """Output of one Validator.run() call.

    `overall_status` is derived, not stored: any fail in `checks`
    promotes the run to red; any warn (and no fails) makes it yellow;
    all-pass is green. An empty `checks` list is green by convention —
    a validator that runs with zero checks is silently a no-op, which
    we want surfaced via tests, not via a synthetic "red".
    """

    table: str
    populator: str
    last_run_at: Optional[datetime]
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def overall_status(self) -> OverallStatus:
        statuses = {c.status for c in self.checks}
        if "fail" in statuses:
            return "red"
        if "warn" in statuses:
            return "yellow"
        return "green"

    def to_jsonb(self) -> dict[str, Any]:
        """Serialise for the `checks` JSONB column in data_quality_runs.

        The full HealthCheckResult is encoded (not just the checks list)
        so a single SELECT against `data_quality_runs.checks` returns
        everything the admin UI needs without a separate join.
        """
        return {
            "table": self.table,
            "populator": self.populator,
            "last_run_at": self.last_run_at.isoformat() if self.last_run_at else None,
            "checks": [asdict(c) for c in self.checks],
            "overall_status": self.overall_status,
        }


@runtime_checkable
class Validator(Protocol):
    """Structural protocol every validator implements.

    The orchestrator imports validators by module path and instantiates
    them with no arguments — keep __init__ signatures empty (or default
    everything). State (DB connection, sample data) should be acquired
    inside `run()` so tests can stub it cleanly.
    """

    table: str
    populator: str

    def run(self) -> HealthCheckResult: ...


__all__ = [
    "CheckResult",
    "HealthCheckResult",
    "Status",
    "OverallStatus",
    "Validator",
]
