"""company_quarterly_results validator (Phase A.2.2, 2026-05-23).

Why this table
--------------
``company_quarterly_results`` is the raw NSE-XBRL-parsed per-quarter
P&L that feeds TTM math and the narrative-engine's quarter-on-quarter
prose. TTM itself is a downstream computation, not a separate table,
so guarding the source is what protects the consumer.

The Day-112 family of regressions taught us that "downstream metric
looks fine" is no defence — the validator must check the inputs, not
recompute and assert on outputs.

This validator asserts:
- Required columns present (period_end, revenue_cr, net_profit_cr,
  is_consolidated)
- Top-10-by-marketcap canaries have a row within the last 100 days
  (a quarter + filing window grace)
- Revenue null rate on the latest 4 quarters of canaries is < 5%
- Net-profit null rate on the latest 4 quarters of canaries is < 5%
- HDFCBANK latest-quarter revenue lands in ₹70K-₹90K Cr band
  (FY25Q4 reported ~₹78K Cr; band absorbs ±15% growth volatility)

Threshold sources
-----------------
- 100-day max age: NSE allows 45 days to file. 100 days = filing
  window + one missed XBRL parser run + safety; tighter would flap.
- 5% null on latest 4 quarters: revenue and net-profit are mandatory
  fields in the XBRL schema — nulls beyond a few % indicate a parser
  regression, not legitimate missingness.
- HDFCBANK revenue band [70K, 90K] Cr: empirical — FY24Q4 ~62K,
  FY25Q4 ~78K Cr. Band is wide enough to absorb 1y growth, tight
  enough to catch unit bugs (paise vs rupees vs Cr) and stale rows
  (a year-old "latest" quarter would have ~62K).
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

EXPECTED_COLUMNS = [
    "ticker",
    "period_end",
    "is_consolidated",
    "revenue_cr",
    "net_profit_cr",
]

# Top-10 names by market cap (rough; we just need stable canaries
# that always file quarterly results).
CANARY_TICKERS = (
    "RELIANCE",
    "TCS",
    "HDFCBANK",
    "INFY",
    "ICICIBANK",
    "HINDUNILVR",
    "ITC",
    "SBIN",
    "BHARTIARTL",
    "KOTAKBANK",
)

# HDFCBANK quarterly revenue plausibility band (₹ Cr).
HDFCBANK_REVENUE_BAND_CR = (70_000.0, 90_000.0)


@dataclass
class CompanyQuarterlyResultsSample:
    row_count: int
    prior_row_count: int
    schema_columns: list[str]
    last_update: Optional[datetime]
    # ticker -> most recent period_end (or None)
    canary_latest_period_end: dict[str, Optional[datetime]] = field(default_factory=dict)
    # Aggregated across canary tickers' latest 4 quarters.
    revenue_null_count: int = 0
    revenue_sample_size: int = 0
    profit_null_count: int = 0
    profit_sample_size: int = 0
    # HDFCBANK latest-period revenue_cr (₹ Cr) or None.
    hdfcbank_latest_revenue_cr: Optional[float] = None


def _canary_recency_check(
    sample: CompanyQuarterlyResultsSample,
    now: Optional[datetime] = None,
    max_age_days: int = 100,
) -> CheckResult:
    """Every canary must have a row within `max_age_days`."""
    now = now or datetime.now(timezone.utc)
    stale: list[str] = []
    detail_parts: list[str] = []
    for ticker in CANARY_TICKERS:
        latest = sample.canary_latest_period_end.get(ticker)
        if latest is None:
            stale.append(f"{ticker}=missing")
            continue
        # period_end is a date — normalise via min-time.
        if isinstance(latest, datetime):
            ts = latest if latest.tzinfo else latest.replace(tzinfo=timezone.utc)
        else:
            # date object
            ts = datetime(latest.year, latest.month, latest.day, tzinfo=timezone.utc)
        age_days = (now - ts).total_seconds() / 86400.0
        detail_parts.append(f"{ticker}={age_days:.0f}d")
        if age_days > max_age_days:
            stale.append(f"{ticker}={age_days:.0f}d")
    threshold = {
        "canary_tickers": list(CANARY_TICKERS),
        "max_age_days": max_age_days,
        "observed_ages": detail_parts,
    }
    if stale:
        return CheckResult(
            name="canary_quarterly_recency",
            status="fail",
            details=(
                "canary tickers missing recent quarterly filing: "
                + ", ".join(stale)
                + f" (>{max_age_days}d — XBRL parser likely broken)"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name="canary_quarterly_recency",
        status="pass",
        details=f"canary quarterly recency OK ({', '.join(detail_parts)})",
        threshold=threshold,
    )


def _hdfcbank_revenue_band_check(
    sample: CompanyQuarterlyResultsSample,
) -> CheckResult:
    lo, hi = HDFCBANK_REVENUE_BAND_CR
    actual = sample.hdfcbank_latest_revenue_cr
    threshold = {
        "ticker": "HDFCBANK",
        "column": "revenue_cr",
        "actual": actual,
        "band_cr": list(HDFCBANK_REVENUE_BAND_CR),
    }
    if actual is None:
        return CheckResult(
            name="hdfcbank_revenue_band",
            status="fail",
            details="HDFCBANK latest-quarter revenue_cr is NULL (parser regression)",
            threshold=threshold,
        )
    if actual < lo or actual > hi:
        return CheckResult(
            name="hdfcbank_revenue_band",
            status="fail",
            details=(
                f"HDFCBANK latest revenue_cr={actual:.0f} outside "
                f"[{lo:.0f}, {hi:.0f}] (unit bug or stale row)"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name="hdfcbank_revenue_band",
        status="pass",
        details=f"HDFCBANK revenue_cr={actual:.0f} in [{lo:.0f}, {hi:.0f}]",
        threshold=threshold,
    )


class CompanyQuarterlyResultsValidator:
    """Validator for the `company_quarterly_results` table."""

    table = "company_quarterly_results"
    populator = "data_pipeline.sources.nse_xbrl"

    def __init__(
        self,
        sample_loader: Optional[Callable[[], CompanyQuarterlyResultsSample]] = None,
    ) -> None:
        self._sample_loader = sample_loader or self._load_sample_from_db

    def _load_sample_from_db(self) -> CompanyQuarterlyResultsSample:
        from ..db_loaders_a2_2 import load_company_quarterly_results_sample

        sample = load_company_quarterly_results_sample()
        if sample is None:
            raise NotImplementedError(
                "DATABASE_URL unset; CompanyQuarterlyResultsValidator skipped."
            )
        return sample

    def run(self) -> HealthCheckResult:
        sample = self._sample_loader()
        checks: list[CheckResult] = [
            schema_columns_present(self.table, EXPECTED_COLUMNS, sample.schema_columns),
            row_count_stability(self.table, sample.row_count, sample.prior_row_count),
            last_update_recency(
                self.table, sample.last_update, max_age_hours=100 * 24.0
            ),
            _canary_recency_check(sample),
            null_rate_check(
                self.table,
                "revenue_cr (canary latest 4Q)",
                sample.revenue_null_count,
                sample.revenue_sample_size,
                max_null_pct=5.0,
            ),
            null_rate_check(
                self.table,
                "net_profit_cr (canary latest 4Q)",
                sample.profit_null_count,
                sample.profit_sample_size,
                max_null_pct=5.0,
            ),
            _hdfcbank_revenue_band_check(sample),
        ]
        return HealthCheckResult(
            table=self.table,
            populator=self.populator,
            last_run_at=datetime.now(timezone.utc),
            checks=checks,
        )


__all__ = [
    "CompanyQuarterlyResultsValidator",
    "CompanyQuarterlyResultsSample",
    "EXPECTED_COLUMNS",
    "CANARY_TICKERS",
    "HDFCBANK_REVENUE_BAND_CR",
]
