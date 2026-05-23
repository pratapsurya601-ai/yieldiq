"""peer_groups validator (Phase A.2.1, 2026-05-23).

Why this table
--------------
``peer_groups`` is the precomputed neighbour graph used by the
cohort/peer-cap services. Day-96 surfaced that the populator's
sub_sector tag was unreliable; Day-111a surfaced that empty industry
rows in `stocks` collapse all banks into one bucket. If `peer_groups`
silently shrinks or loses coverage for a known-good ticker, every
peer-relative metric (relative PE, cohort percentiles, narrative
peer copy) degrades silently.

This validator asserts:
- Schema is intact
- Row count stable
- HDFCBANK has >=3 peers on record (it should have ~5-8 private bank
  peers; <3 means the cohort builder broke or the industry field on
  HDFCBANK regressed)
- TCS has >=3 peers (IT-services cohort guarantees this)
- Recency < 168h (peer_groups is rebuilt weekly)

Threshold sources
-----------------
- HDFCBANK peers >=3: empirical — Private-Sector Banks cohort
  consistently includes ICICIBANK, AXISBANK, INDUSINDBK, KOTAKBANK,
  BANDHANBNK. <3 is the broken-pipeline signal.
- TCS peers >=3: IT Services cohort includes INFY, WIPRO, HCLTECH,
  TECHM, LTIM. <3 = broken.
- 168h recency: peer_groups is a weekly batch; tighter would flap.
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
    "peer_ticker",
]

CANARY_MIN_PEERS: dict[str, int] = {
    "HDFCBANK": 3,
    "TCS": 3,
}


@dataclass
class PeerGroupsSample:
    row_count: int
    prior_row_count: int
    schema_columns: list[str]
    last_update: Optional[datetime]
    peers_per_canary: dict[str, int] = field(default_factory=dict)


def _canary_peer_count_check(sample: PeerGroupsSample) -> CheckResult:
    bad: list[str] = []
    detail_parts: list[str] = []
    for ticker, min_n in CANARY_MIN_PEERS.items():
        observed = sample.peers_per_canary.get(ticker, 0)
        detail_parts.append(f"{ticker}={observed}/{min_n}")
        if observed < min_n:
            bad.append(f"{ticker}={observed}<{min_n}")
    threshold = {
        "min_peers_required": CANARY_MIN_PEERS,
        "observed": sample.peers_per_canary,
    }
    if bad:
        return CheckResult(
            name="canary_peer_count",
            status="fail",
            details=(
                f"insufficient peers: {', '.join(bad)} "
                "(check stocks.industry for these tickers — Day-111a signature)"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name="canary_peer_count",
        status="pass",
        details=f"canary peer counts OK ({', '.join(detail_parts)})",
        threshold=threshold,
    )


class PeerGroupsValidator:
    table = "peer_groups"
    populator = "scripts.build_peer_groups"

    def __init__(
        self,
        sample_loader: Optional[Callable[[], PeerGroupsSample]] = None,
    ) -> None:
        self._sample_loader = sample_loader or self._load_sample_from_db

    def _load_sample_from_db(self) -> PeerGroupsSample:
        from ..db_loaders_a2 import load_peer_groups_sample

        sample = load_peer_groups_sample()
        if sample is None:
            raise NotImplementedError(
                "DATABASE_URL unset; PeerGroupsValidator skipped."
            )
        return sample

    def run(self) -> HealthCheckResult:
        sample = self._sample_loader()
        checks: list[CheckResult] = [
            schema_columns_present(self.table, EXPECTED_COLUMNS, sample.schema_columns),
            row_count_stability(self.table, sample.row_count, sample.prior_row_count),
            _canary_peer_count_check(sample),
            last_update_recency(self.table, sample.last_update, max_age_hours=168.0),
        ]
        return HealthCheckResult(
            table=self.table,
            populator=self.populator,
            last_run_at=datetime.now(timezone.utc),
            checks=checks,
        )


__all__ = [
    "PeerGroupsValidator",
    "PeerGroupsSample",
    "EXPECTED_COLUMNS",
    "CANARY_MIN_PEERS",
]
