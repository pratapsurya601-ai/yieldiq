"""shareholding_pattern validator (Phase A.2.2, 2026-05-23).

Why this table
--------------
``shareholding_pattern`` carries quarterly promoter/FII/DII/public
ownership splits sourced from NSE (and partly backfilled from BSE
via Phase 2.3). The promoter-pledge and FII-outflow narratives both
read this table directly; stale or arithmetically-broken rows are a
silent failure for those narratives.

This validator asserts:
- Required columns present (promoter_pct, fii_pct, dii_pct, public_pct, quarter_end)
- Quarterly cadence: latest quarter_end is no older than ~100 days
  (one quarter = 90 days + grace for the regulator's filing window)
- Arithmetic: promoter + DII + FII + public sums to 100 ± 1 for the
  latest quarter on top-N canary tickers (catches a populator that
  silently dropped one of the four buckets)
- Plausibility band: HDFCBANK + KOTAKBANK promoter % falls in 15-30%
  (these are widely-held private banks — promoter holding outside
  this band signals a parser bug or a corporate-action that didn't
  flow through the populator)

Threshold sources
-----------------
- 100-day max age: NSE files SHP within 21 days of quarter end; SEBI
  allows 21 days too. 100 days = one quarter + filing grace + one
  missed run; tighter would flap.
- Sum-to-100 ± 1: arithmetic invariant. ±1 absorbs rounding to one
  decimal in the source data.
- HDFCBANK/KOTAKBANK promoter in [15, 30]: empirical — both private
  banks have been in this band for >5 years. Tighter would flap on
  small ESOP-driven shifts.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .. import CheckResult, HealthCheckResult
from ..checks import (
    last_update_recency,
    row_count_stability,
    schema_columns_present,
)

EXPECTED_COLUMNS = [
    "ticker",
    "quarter_end",
    "promoter_pct",
    "fii_pct",
    "dii_pct",
    "public_pct",
]

# Tickers we assert sum-to-100 for. Any high-cap with a stable
# shareholding pattern works; we pick five across sectors.
SUM_CANARY_TICKERS = ("HDFCBANK", "TCS", "RELIANCE", "INFY", "ICICIBANK")

# Plausibility bands for promoter % on widely-held private banks.
PROMOTER_PCT_BANDS: dict[str, tuple[float, float]] = {
    "HDFCBANK": (15.0, 30.0),
    "KOTAKBANK": (15.0, 30.0),
}

SUM_TOLERANCE = 1.0  # absolute % tolerance around 100


@dataclass
class ShareholdingPatternSample:
    row_count: int
    prior_row_count: int
    schema_columns: list[str]
    last_update: Optional[datetime]
    # ticker -> dict of latest-quarter pcts: keys
    # promoter_pct/fii_pct/dii_pct/public_pct (may be None).
    latest_pcts: dict[str, dict[str, Optional[float]]] = field(default_factory=dict)


def _sum_to_100_check(sample: ShareholdingPatternSample) -> CheckResult:
    bad: list[str] = []
    detail_parts: list[str] = []
    for ticker in SUM_CANARY_TICKERS:
        row = sample.latest_pcts.get(ticker)
        if not row:
            bad.append(f"{ticker}=missing")
            continue
        parts = [row.get(k) for k in ("promoter_pct", "fii_pct", "dii_pct", "public_pct")]
        if any(p is None for p in parts):
            bad.append(f"{ticker}=null_bucket({parts})")
            continue
        total = sum(p for p in parts if p is not None)
        detail_parts.append(f"{ticker}={total:.2f}")
        if abs(total - 100.0) > SUM_TOLERANCE:
            bad.append(f"{ticker}={total:.2f}!=100±{SUM_TOLERANCE}")
    threshold = {
        "canary_tickers": list(SUM_CANARY_TICKERS),
        "tolerance": SUM_TOLERANCE,
        "observed": {t: sample.latest_pcts.get(t, {}) for t in SUM_CANARY_TICKERS},
    }
    if bad:
        return CheckResult(
            name="shareholding_sum_to_100",
            status="fail",
            details=(
                f"shareholding pct buckets do not sum to 100±{SUM_TOLERANCE}: "
                + "; ".join(bad)
                + " (populator likely dropped one of promoter/FII/DII/public)"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name="shareholding_sum_to_100",
        status="pass",
        details=f"sum-to-100 OK: {', '.join(detail_parts)}",
        threshold=threshold,
    )


def _promoter_band_check(sample: ShareholdingPatternSample) -> CheckResult:
    bad: list[str] = []
    detail_parts: list[str] = []
    for ticker, (lo, hi) in PROMOTER_PCT_BANDS.items():
        row = sample.latest_pcts.get(ticker, {})
        actual = row.get("promoter_pct")
        if actual is None:
            bad.append(f"{ticker}=null")
            continue
        detail_parts.append(f"{ticker}={actual:.2f}")
        if actual < lo or actual > hi:
            bad.append(f"{ticker}={actual:.2f} outside [{lo}, {hi}]")
    threshold = {
        "bands": {t: list(b) for t, b in PROMOTER_PCT_BANDS.items()},
        "observed": {t: sample.latest_pcts.get(t, {}).get("promoter_pct") for t in PROMOTER_PCT_BANDS},
    }
    if bad:
        return CheckResult(
            name="promoter_pct_plausibility",
            status="fail",
            details=(
                "promoter % outside historical band on private banks: "
                + "; ".join(bad)
                + " (parser bug or stale data — verify against latest SHP filing)"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name="promoter_pct_plausibility",
        status="pass",
        details=f"promoter % in band: {', '.join(detail_parts)}",
        threshold=threshold,
    )


class ShareholdingPatternValidator:
    """Validator for the `shareholding_pattern` table."""

    table = "shareholding_pattern"
    populator = "data_pipeline.sources.nse_shareholding"

    def __init__(
        self,
        sample_loader: Optional[Callable[[], ShareholdingPatternSample]] = None,
    ) -> None:
        self._sample_loader = sample_loader or self._load_sample_from_db

    def _load_sample_from_db(self) -> ShareholdingPatternSample:
        from ..db_loaders_a2_2 import load_shareholding_pattern_sample

        sample = load_shareholding_pattern_sample()
        if sample is None:
            raise NotImplementedError(
                "DATABASE_URL unset; ShareholdingPatternValidator skipped."
            )
        return sample

    def run(self) -> HealthCheckResult:
        sample = self._sample_loader()
        checks: list[CheckResult] = [
            schema_columns_present(self.table, EXPECTED_COLUMNS, sample.schema_columns),
            row_count_stability(self.table, sample.row_count, sample.prior_row_count),
            last_update_recency(
                self.table, sample.last_update, max_age_hours=100 * 24.0  # ~100 days
            ),
            _sum_to_100_check(sample),
            _promoter_band_check(sample),
        ]
        return HealthCheckResult(
            table=self.table,
            populator=self.populator,
            last_run_at=datetime.now(timezone.utc),
            checks=checks,
        )


__all__ = [
    "ShareholdingPatternValidator",
    "ShareholdingPatternSample",
    "EXPECTED_COLUMNS",
    "SUM_CANARY_TICKERS",
    "PROMOTER_PCT_BANDS",
    "SUM_TOLERANCE",
]
