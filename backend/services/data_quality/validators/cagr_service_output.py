"""cagr_service_output validator (Phase A.2.2, 2026-05-23).

Why this is a SERVICE validator, not a table validator
------------------------------------------------------
Every other validator in this framework asserts on a DB table.
``cagr_service_output`` instead exercises the compute path:
`backend.services.cagr_service.compute_cagr_panel`. The pre-Day-112
shape was that 32/97 universe tickers returned `compounded_growth.stock
= None` despite having years of adj_close history — a bug in the
populator's data, not in the service itself. After Day-112 +
PR #541 ("robust adj_close infrastructure") + operator rebuild, the
expected post-fix shape is "≥3 of 5 canaries have a 5y CAGR; ≥4 of 5
have a 3y CAGR".

We embed this as a validator so the admin UI flashes red the moment
that property regresses for ANY reason — adj_close gap, service-level
regression, or stocks-table churn.

The check runs `compute_cagr_panel` for 5 canaries in-process. The
service opens its own DB Session and is happy to receive None
DATABASE_URL (returns `status=db_unavailable`) — so the validator
gracefully skips with a clear log when DATABASE_URL is unset, same
convention as the table validators.

Threshold sources
-----------------
- Canary set: TCS, INFY, HDFCBANK, RELIANCE, ICICIBANK — all in the
  universe since at least 2014, all on every populator's whitelist.
- 5y populated ≥ 3 of 5: post-Day-112 operator rebuild restored
  coverage; 3/5 is the "we didn't go backwards" floor.
- 3y populated ≥ 4 of 5: 3y window is much more forgiving (no need
  to look back past 2023); regression below this is severe.
- CAGR plausibility band [-30%, +50%]: deliberately VERY wide — we
  only want to catch absurd-magnitude bugs (e.g. a unit error giving
  +1300% CAGR). Tight bands here would be a policy call (is +30%
  CAGR over 5y "too high"?) that this validator is not the place to
  litigate.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Optional

from .. import CheckResult, HealthCheckResult

# Canary tickers — all 10y+ in the universe, all on every populator.
CANARY_TICKERS = ("TCS", "INFY", "HDFCBANK", "RELIANCE", "ICICIBANK")

MIN_5Y_POPULATED = 3
MIN_3Y_POPULATED = 4

# Very wide plausibility band — see module docstring.
CAGR_BAND_5Y: dict[str, tuple[float, float]] = {
    "TCS": (-30.0, 50.0),
    "INFY": (-30.0, 50.0),
    "HDFCBANK": (-30.0, 50.0),
}


@dataclass
class CagrServiceOutputSample:
    """Pre-computed CAGR panels per canary.

    Each value is the dict returned by `compute_cagr_panel`. The
    validator only reads ``panel["stock"]["3y"|"5y"|"status"]``.
    """

    panels: dict[str, dict[str, Any]] = field(default_factory=dict)


def _populated_count(sample: CagrServiceOutputSample, window: str) -> tuple[int, list[str]]:
    """Return (n_populated, list_of_missing_tickers) for the given window."""
    missing: list[str] = []
    populated = 0
    for ticker in CANARY_TICKERS:
        panel = sample.panels.get(ticker) or {}
        stock = panel.get("stock") or {}
        val = stock.get(window)
        if val is None:
            missing.append(ticker)
        else:
            populated += 1
    return populated, missing


def _coverage_check(sample: CagrServiceOutputSample, window: str, min_required: int) -> CheckResult:
    populated, missing = _populated_count(sample, window)
    threshold = {
        "window": window,
        "canary_tickers": list(CANARY_TICKERS),
        "populated": populated,
        "min_required": min_required,
        "missing": missing,
    }
    if populated < min_required:
        return CheckResult(
            name=f"cagr_coverage.{window}",
            status="fail",
            details=(
                f"only {populated}/{len(CANARY_TICKERS)} canaries have a {window} "
                f"CAGR (floor: {min_required}); missing={missing} "
                "(Day-112 adj_close regression signature)"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name=f"cagr_coverage.{window}",
        status="pass",
        details=f"{populated}/{len(CANARY_TICKERS)} canaries have {window} CAGR",
        threshold=threshold,
    )


def _plausibility_check(sample: CagrServiceOutputSample) -> CheckResult:
    bad: list[str] = []
    detail_parts: list[str] = []
    for ticker, (lo, hi) in CAGR_BAND_5Y.items():
        panel = sample.panels.get(ticker) or {}
        stock = panel.get("stock") or {}
        val = stock.get("5y")
        if val is None:
            # Coverage check handles missing; here we only band-check populated values.
            continue
        detail_parts.append(f"{ticker}={val:.1f}%")
        if val < lo or val > hi:
            bad.append(f"{ticker}={val:.1f}% outside [{lo}, {hi}]")
    threshold = {
        "bands": {t: list(b) for t, b in CAGR_BAND_5Y.items()},
        "observed": {
            t: (sample.panels.get(t) or {}).get("stock", {}).get("5y")
            for t in CAGR_BAND_5Y
        },
    }
    if bad:
        return CheckResult(
            name="cagr_plausibility_5y",
            status="fail",
            details=(
                "5y stock CAGR outside very-wide plausibility band: "
                + "; ".join(bad)
                + " (likely a unit or adj_close-magnitude bug)"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name="cagr_plausibility_5y",
        status="pass",
        details=f"5y CAGR plausibility OK ({', '.join(detail_parts)})",
        threshold=threshold,
    )


def _default_sample_loader() -> CagrServiceOutputSample:
    """Production loader: call compute_cagr_panel for each canary.

    Imports the service lazily so unit tests with monkeypatched
    sample_loader never trigger DB connections through this path.
    """
    import os

    if not os.environ.get("DATABASE_URL"):
        raise NotImplementedError(
            "DATABASE_URL unset; CagrServiceOutputValidator skipped."
        )
    # Lazy import — cagr_service may pull in heavy deps.
    from backend.services.cagr_service import compute_cagr_panel

    panels: dict[str, dict[str, Any]] = {}
    for ticker in CANARY_TICKERS:
        try:
            panels[ticker] = compute_cagr_panel(ticker)
        except Exception as exc:  # pragma: no cover - defensive
            panels[ticker] = {"stock": {"3y": None, "5y": None, "status": f"error:{exc}"}}
    return CagrServiceOutputSample(panels=panels)


class CagrServiceOutputValidator:
    """Validator for the CAGR compute service (not a DB table)."""

    table = "cagr_service_output"  # virtual "table" name for the runs storage
    populator = "backend.services.cagr_service.compute_cagr_panel"

    def __init__(
        self,
        sample_loader: Optional[Callable[[], CagrServiceOutputSample]] = None,
    ) -> None:
        self._sample_loader = sample_loader or _default_sample_loader

    def _load_sample_from_db(self) -> CagrServiceOutputSample:
        """Indirection kept so the existing skip-when-DB-unset test
        pattern (used by daily_prices / stocks) works here too."""
        return _default_sample_loader()

    def run(self) -> HealthCheckResult:
        sample = self._sample_loader()
        checks: list[CheckResult] = [
            _coverage_check(sample, "5y", MIN_5Y_POPULATED),
            _coverage_check(sample, "3y", MIN_3Y_POPULATED),
            _plausibility_check(sample),
        ]
        return HealthCheckResult(
            table=self.table,
            populator=self.populator,
            last_run_at=datetime.now(timezone.utc),
            checks=checks,
        )


__all__ = [
    "CagrServiceOutputValidator",
    "CagrServiceOutputSample",
    "CANARY_TICKERS",
    "MIN_5Y_POPULATED",
    "MIN_3Y_POPULATED",
    "CAGR_BAND_5Y",
]
