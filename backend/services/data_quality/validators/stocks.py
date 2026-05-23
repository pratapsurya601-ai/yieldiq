"""stocks validator (Phase A.1, 2026-05-23).

Why this table next
-------------------
Day-111a's root cause was that `local_data_service.py` dropped
`industry` from its serializer payload. Downstream consumers fell back
to "Unknown" for 96% of tickers, breaking peer-grouping and the cohort
engine. The fix landed in PR #537, but the populator itself was
correct — the bug was at the serialiser boundary, which a test of
this validator's shape would have caught.

This validator asserts shape AND non-emptiness of the metadata
fields the rest of the pipeline depends on.

Threshold sources
-----------------
- industry null/empty rate < 20%: empirical — A.1 of Day-111a logged
  96% empty before the fix; 20% is a generous bar that absorbs
  legitimate edge-cases (recently-listed tickers awaiting classification)
  while preventing regression back to the broken state.
- sector null/empty rate < 5%: sector is set from a small canonical
  list and should be ~100% populated; 5% is the "noise floor" of
  legitimately uncategorisable rows (SME, REIT-without-sector, etc).
- is_active null rate 0%: this is a NOT NULL invariant the schema
  already encodes, but checking explicitly catches a DB-level
  regression (e.g. a column rename that introduced nulls).
- HDFCBANK industry known-good: "Banks - Private Sector" (or any
  non-empty string starting with "Banks") — the Day-111a regression
  surfaced specifically as banks losing their industry classification,
  so this is the canonical "would the fix-PR have caught it" check.
- Recency < 168h: stocks metadata is updated weekly. A week-and-a-day
  threshold absorbs a missed Sunday run without flapping.
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
)

EXPECTED_INDUSTRY_PREFIX_HDFCBANK = "Banks"


@dataclass
class StocksSample:
    """Pre-fetched inputs for one validator run."""

    row_count: int
    prior_row_count: int
    industry_empty_count: int
    sector_empty_count: int
    is_active_null_count: int
    sample_size: int
    hdfcbank_industry: Optional[str]
    last_update: Optional[datetime]


def _industry_known_good_check(sample: StocksSample) -> CheckResult:
    """HDFCBANK's industry MUST be non-empty and start with 'Banks'.

    This is the canonical Day-111a regression: the serializer dropped
    the field, banks rendered with industry = "" / "Unknown", and the
    cohort engine collapsed all banks into one bucket. Asserting on a
    high-cap, high-stability ticker like HDFCBANK costs nothing and
    catches the broken-pipeline case end-to-end.
    """
    actual = sample.hdfcbank_industry
    threshold = {
        "ticker": "HDFCBANK",
        "column": "industry",
        "actual": actual,
        "expected_prefix": EXPECTED_INDUSTRY_PREFIX_HDFCBANK,
    }
    if not actual or not actual.strip():
        return CheckResult(
            name="known_good.HDFCBANK.industry",
            status="fail",
            details="HDFCBANK.industry is empty (Day-111a regression signature)",
            threshold=threshold,
        )
    if not actual.startswith(EXPECTED_INDUSTRY_PREFIX_HDFCBANK):
        return CheckResult(
            name="known_good.HDFCBANK.industry",
            status="fail",
            details=(
                f"HDFCBANK.industry={actual!r} does not start with "
                f"{EXPECTED_INDUSTRY_PREFIX_HDFCBANK!r}"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name="known_good.HDFCBANK.industry",
        status="pass",
        details=f"HDFCBANK.industry={actual!r}",
        threshold=threshold,
    )


class StocksValidator:
    """Validator for the `stocks` table (ticker metadata)."""

    table = "stocks"
    populator = "data_pipeline.sources.nse_industry_master"

    def __init__(
        self,
        sample_loader: Optional[Callable[[], StocksSample]] = None,
    ) -> None:
        self._sample_loader = sample_loader or self._load_sample_from_db

    def _load_sample_from_db(self) -> StocksSample:
        """Production loader (Phase A.2.1). See daily_prices for the
        same pattern + DATABASE_URL graceful-skip rationale."""
        from ..db_loaders import load_stocks_sample

        sample = load_stocks_sample()
        if sample is None:
            raise NotImplementedError(
                "DATABASE_URL unset; StocksValidator skipped. "
                "Use --dry-run for local smoke without a DB."
            )
        return sample

    def run(self) -> HealthCheckResult:
        sample = self._sample_loader()
        checks: list[CheckResult] = [
            row_count_stability(
                self.table, sample.row_count, sample.prior_row_count
            ),
            null_rate_check(
                self.table,
                "industry",
                sample.industry_empty_count,
                sample.sample_size,
                max_null_pct=20.0,  # empirical: 96% before Day-111a fix
            ),
            null_rate_check(
                self.table,
                "sector",
                sample.sector_empty_count,
                sample.sample_size,
                max_null_pct=5.0,
            ),
            null_rate_check(
                self.table,
                "is_active",
                sample.is_active_null_count,
                sample.sample_size,
                max_null_pct=0.0,  # schema invariant
            ),
            _industry_known_good_check(sample),
            last_update_recency(
                self.table, sample.last_update, max_age_hours=168.0
            ),
        ]
        return HealthCheckResult(
            table=self.table,
            populator=self.populator,
            last_run_at=datetime.now(timezone.utc),
            checks=checks,
        )


__all__ = [
    "StocksValidator",
    "StocksSample",
    "EXPECTED_INDUSTRY_PREFIX_HDFCBANK",
]
