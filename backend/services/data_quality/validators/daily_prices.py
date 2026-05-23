"""daily_prices validator (Phase A.1, 2026-05-23).

Why this table first
--------------------
Day-112's root cause was that three independent populators
(`data_pipeline/sources/nse_bhavcopy.py:133`,
`scripts/backfill_daily_prices_gap.py:163`,
`scripts/backfill_daily_prices_legacy.py:219`) all set
`adj_close = close_price`. The bug shipped to production and stayed
there for months because no test asserted "adj_close should diverge
from close_price for tickers that have had splits/bonuses". RELIANCE
rendered a -7.8% 5-year stock CAGR as a result.

This validator would have caught that on its first run.

Threshold sources
-----------------
- Plausibility bands (HDFCBANK ₹400-₹2500, RELIANCE ₹1000-₹4000,
  TCS ₹2000-₹5000): calibrated 2026-05-23 against
  `data_pipeline/nse_prices/parquet/*.parquet` for trade_date >
  2024-06-01. Observed ranges: HDFCBANK 732-1013, RELIANCE 1157-1592,
  TCS 2356-4312. Bands intentionally wider than observed to absorb
  1y volatility without flapping; tighter than 10x to catch unit bugs.
- adj_close distinctness for NESTLEIND / TCS / RELIANCE pre-2024:
  empirical — all three have had splits/bonuses in the last 5y, so
  adj_close == close_price for >90% of those dates is direct evidence
  of the Day-112 bug returning.
- Null rate (`close_price` < 1%): `needs-baseline` — conservative
  default; A.2 retunes against prod Neon once a read connection is
  wired.
- Recency (< 30h): NSE bhavcopy is daily; weekend gap is the longest
  legitimate stretch (~72h Fri close -> Mon publish), but the cron
  runs daily and writes an empty-row sentinel on holidays, so 30h is
  a tight catch-it-fast threshold for the weekday case. A.2 may
  switch to a weekday-aware variant.
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

# Tickers whose adj_close MUST diverge from close_price in the
# pre-2024 window because they all have splits/bonuses on record.
# Day-112 root cause: this assertion didn't exist before today.
ADJ_CLOSE_DISTINCTNESS_TICKERS = ("NESTLEIND", "TCS", "RELIANCE")

# Conservative pre-2024 cutoff: every ticker above has had at least
# one corporate action before this date in the last 10y, so adj_close
# should differ from close_price for >10% of rows.
ADJ_CLOSE_PRE_DATE = "2024-01-01"

# Empirically-calibrated plausibility bands (see module docstring).
PLAUSIBILITY_BANDS: dict[str, tuple[float, float]] = {
    "HDFCBANK": (400.0, 2500.0),
    "RELIANCE": (1000.0, 4000.0),
    "TCS": (2000.0, 5000.0),
}

EXPECTED_COLUMNS = [
    "ticker",
    "trade_date",
    "open_price",
    "high_price",
    "low_price",
    "close_price",
    "adj_close",
    "volume",
]


@dataclass
class DailyPricesSample:
    """All data a single run needs, pre-fetched.

    Validators accept a sample object so they can be unit-tested
    without a DB. The default production data-source builds this from
    Neon; tests construct it in-memory.
    """

    row_count: int
    prior_row_count: int
    close_null_count: int
    sample_size: int
    schema_columns: list[str]
    last_update: Optional[datetime]
    # Per-ticker latest close used for plausibility checks.
    latest_close: dict[str, Optional[float]] = field(default_factory=dict)
    # Per-ticker fraction of pre-2024 rows where adj_close == close_price.
    # 1.0 means "completely broken" (Day-112 bug); ~0 means healthy.
    adj_close_eq_close_fraction: dict[str, float] = field(default_factory=dict)


def _adj_close_distinctness_check(sample: DailyPricesSample) -> CheckResult:
    """Catches the exact Day-112 bug.

    For each canary ticker, if >=90% of pre-2024 rows have
    adj_close == close_price, the populator is writing the buggy
    "set adj_close to close_price" pattern. Anything below 90% means
    real corporate-action math has been applied (some dates won't be
    adjusted because they post-date the most recent action).
    """
    bad_tickers: list[str] = []
    detail_parts: list[str] = []
    for ticker in ADJ_CLOSE_DISTINCTNESS_TICKERS:
        frac = sample.adj_close_eq_close_fraction.get(ticker)
        if frac is None:
            bad_tickers.append(f"{ticker}=NO_DATA")
            continue
        detail_parts.append(f"{ticker}={frac:.0%}")
        if frac > 0.90:
            bad_tickers.append(f"{ticker}={frac:.0%}")

    threshold = {
        "tickers": list(ADJ_CLOSE_DISTINCTNESS_TICKERS),
        "max_fraction_equal": 0.90,
        "pre_date": ADJ_CLOSE_PRE_DATE,
        "observed": sample.adj_close_eq_close_fraction,
    }
    if bad_tickers:
        return CheckResult(
            name="adj_close_distinct_from_close",
            status="fail",
            details=(
                "adj_close == close_price for too many pre-2024 rows on "
                f"{', '.join(bad_tickers)} (Day-112 regression signature)"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name="adj_close_distinct_from_close",
        status="pass",
        details=f"adj_close diverges from close_price as expected ({', '.join(detail_parts)})",
        threshold=threshold,
    )


class DailyPricesValidator:
    """Validator for the `daily_prices` table.

    Constructed by the orchestrator with no args. Override
    `_load_sample` in tests (or pass `sample_loader=...`) to inject a
    synthetic DailyPricesSample without a DB round-trip.
    """

    table = "daily_prices"
    # Three populators write to this table; we attribute the run to
    # the canonical one. The other two (backfill_*) are catch-up jobs.
    populator = "data_pipeline.sources.nse_bhavcopy"

    def __init__(
        self,
        sample_loader: Optional[Callable[[], DailyPricesSample]] = None,
    ) -> None:
        self._sample_loader = sample_loader or self._load_sample_from_db

    def _load_sample_from_db(self) -> DailyPricesSample:  # pragma: no cover
        """Production loader — wired in A.2 alongside the cron.

        A.1 ships the validator logic and tests; A.2 wires the live
        Neon read path. Until then this raises so the orchestrator
        skips the validator cleanly when DATABASE_URL is unset.
        """
        raise NotImplementedError(
            "DailyPricesValidator DB loader is wired in A.2 (cron PR). "
            "For A.1, pass an explicit sample_loader (used by tests and "
            "by `--dry-run` smoke runs)."
        )

    def run(self) -> HealthCheckResult:
        sample = self._sample_loader()
        checks: list[CheckResult] = [
            schema_columns_present(
                self.table, EXPECTED_COLUMNS, sample.schema_columns
            ),
            row_count_stability(
                self.table, sample.row_count, sample.prior_row_count
            ),
            null_rate_check(
                self.table,
                "close_price",
                sample.close_null_count,
                sample.sample_size,
                max_null_pct=1.0,  # needs-baseline; conservative default
            ),
            _adj_close_distinctness_check(sample),
            last_update_recency(
                self.table, sample.last_update, max_age_hours=30.0
            ),
        ]
        for ticker, (lo, hi) in PLAUSIBILITY_BANDS.items():
            checks.append(
                known_good_plausibility(
                    self.table,
                    ticker,
                    "close_price",
                    sample.latest_close.get(ticker),
                    lo,
                    hi,
                )
            )

        return HealthCheckResult(
            table=self.table,
            populator=self.populator,
            last_run_at=datetime.now(timezone.utc),
            checks=checks,
        )


__all__ = [
    "DailyPricesValidator",
    "DailyPricesSample",
    "ADJ_CLOSE_DISTINCTNESS_TICKERS",
    "PLAUSIBILITY_BANDS",
    "EXPECTED_COLUMNS",
]
