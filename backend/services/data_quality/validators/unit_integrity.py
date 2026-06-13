"""unit_integrity validator (2026-06-13).

Why this validator
------------------
A whole class of production bugs in YieldIQ share one fingerprint: a
single numeric field is silently off by a factor of ~10^N because the
pipeline carried two quantities in mismatched units (raw INR vs Crores)
or applied a currency conversion zero or two times instead of once.
The user never sees an error — they see a *plausible-looking, wrong*
number that flows all the way into a fair value. Documented instances:

- ``₹9.6 trillion`` fair value from a USD-denominated revenue series
  being re-converted to INR (double-convert), or an INR series being
  read as USD-then-converted (half-convert).
- ``asset_turnover = 359,808`` on INDIGO — revenue in raw INR divided by
  total_assets in Crores (off by 1e7).
- ``de_ratio = 0`` on 17/17 tickers of a cohort — the equity denominator
  dropped, so every ratio collapsed to a default zero.
- INDIGO / ANTHEM unit mismatches surfaced as ROCE / current-ratio /
  asset-turnover blowups.

Each of those was patched at the point of computation (sanity gates
inside ``ratios_service.compute_*``). Those gates stop a *single* wrong
number from rendering, but they do NOT tell us how dirty the underlying
data is, and they fire silently per-call. This validator is the
systematic, cohort-level guard: it runs over the whole universe (or a
sample), cross-checks fields against each other, and reports — per
ticker — every magnitude/unit/currency anomaly with field + observed +
expected band + severity, BEFORE any of it reaches a fair value.

Scope discipline
----------------
This is a READ-SIDE / DIAGNOSTIC validator. It does not touch the FV
math, does not change any computed value, and does not justify a
CACHE_VERSION bump (it only observes data already at rest). It plugs
into the existing data-quality framework exactly like the other ~10
validators: a ``run() -> HealthCheckResult`` that the orchestrator
discovers via REGISTRY and the admin endpoint surfaces verbatim.

Checks implemented (all cross-field, all unit-free where possible)
------------------------------------------------------------------
1. asset_turnover band — revenue/total_assets. Real companies sit in
   ~0.05x-5x; >100x is the INDIGO unit-mismatch signature. Sector-aware
   (banks/financials run far lower). Cohort count of out-of-band tickers.
2. de_ratio zero-cohort — fraction of the universe (and of any single
   sector) reading de_ratio EXACTLY 0. One zero is fine; a cohort of
   zeros means a dropped/mis-scaled equity denominator.
3. net_margin band — pat/revenue. A unit mismatch between numerator and
   denominator pushes this far outside [-100%, +100%]; a real company
   cannot earn >100% net margin.
4. market-cap vs revenue — revenue (Cr) wildly exceeding market_cap (Cr)
   is the classic "revenue in raw INR, mcap in Cr" double-unit tell.
5. FCF vs market-cap (DCF-overshoot signature) — free_cash_flow (a
   single year) exceeding the entire market cap means the cash-flow
   series is mis-scaled; a DCF off such a base overshoots by 10^N. This
   is the pv_fcfs > N*mcap fingerprint observed upstream.
6. currency double-convert guard — any ticker whose latest financials
   row is denominated in a non-INR currency (USD) is flagged: every
   downstream consumer that assumes Crore-INR will silently mis-scale it.
   This is the ₹9.6T fingerprint at the source.
7. known-good plausibility — TCS / RELIANCE asset_turnover must stay in
   a tight band; a regression here means a universe-wide unit drift.

Threshold sources
-----------------
All bands are calibrated against the live universe (2,361 annual-period
tickers as of 2026-06-13) so the green state is genuinely green and a
real bug is the only thing that turns it red. See per-band docstrings.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .. import CheckResult, HealthCheckResult
from ..checks import (
    cohort_fraction_check,
    known_good_plausibility,
    last_update_recency,
    ratio_band_check,
    row_count_stability,
)

# ── Sector-aware asset_turnover bands ───────────────────────────────
# (warn_lo, warn_hi, fail_lo, fail_hi). The fail band is the hard
# implausibility envelope (unit-mismatch territory); the warn band is
# the comfortable real-world envelope for that sector.
#
# Banks/Financials carry enormous asset bases against modest revenue, so
# their turnover is structurally tiny (~0.03-0.15x). Capital-light names
# (IT services, FMCG) run higher (up to ~3x). We never expect any listed
# operating company above ~5x; >100x is the INDIGO 1e7 signature.
DEFAULT_ASSET_TURNOVER_BAND = (0.05, 5.0, 0.001, 100.0)
SECTOR_ASSET_TURNOVER_BANDS: dict[str, tuple[float, float, float, float]] = {
    "Bank": (0.01, 0.30, 0.0005, 50.0),
    "Financial Services": (0.01, 1.50, 0.0005, 50.0),
    "IT Services": (0.30, 4.0, 0.01, 100.0),
    "FMCG": (0.30, 4.0, 0.01, 100.0),
    "Energy": (0.10, 3.0, 0.005, 100.0),
    "Metal": (0.10, 4.0, 0.005, 100.0),
}

# net_margin (pat/revenue, percent). A real company cannot clear 100%
# net margin; a unit mismatch between PAT and revenue blows past it.
# Warn band is generous (some holding cos / one-off gains run high).
NET_MARGIN_BAND = (-60.0, 60.0, -100.0, 100.0)

# market_cap vs revenue: revenue (Cr) should not dwarf market cap (Cr).
# A factor of 50x is already extreme for any real business; beyond that
# the most likely cause is revenue carried in raw INR while mcap is Cr.
REVENUE_OVER_MCAP_WARN = 20.0
REVENUE_OVER_MCAP_FAIL = 50.0

# FCF vs market cap (DCF-overshoot signature). A single year's FCF
# exceeding the whole market cap is the pv_fcfs > N*mcap fingerprint —
# almost always a mis-scaled cash-flow series.
FCF_OVER_MCAP_WARN = 0.60
FCF_OVER_MCAP_FAIL = 1.0

# de_ratio zero-cohort thresholds. A handful of genuinely debt-free
# companies is normal; a large fraction reading EXACTLY 0 means the
# equity denominator was dropped. Universe-wide and per-sector.
DE_ZERO_WARN_PCT = 15.0
DE_ZERO_FAIL_PCT = 30.0

# Currency double-convert guard. Any non-INR latest-financials row is a
# downstream-mis-scale risk; even a small fraction is worth attention
# because the ₹9.6T bug needed only one such ticker to reach a fair
# value. Zero non-INR rows is green; any positive count is at least a
# warn; a cohort above the fail fraction is red.
CURRENCY_NON_INR_FAIL_PCT = 2.0   # a cohort of them fails

# Known-good asset_turnover bands (tight — a regression here is a
# universe-wide unit drift, not a per-ticker outlier).
KNOWN_GOOD_ASSET_TURNOVER: dict[str, tuple[float, float]] = {
    "TCS": (0.5, 3.0),
    "RELIANCE": (0.2, 2.0),
    "HDFCBANK": (0.01, 0.30),
}


@dataclass
class TickerAnomaly:
    """One ticker's worst flag for a given check (field + observed + band)."""

    ticker: str
    field: str
    observed: float
    expected_band: tuple[float, float]
    severity: str  # "warn" | "fail"
    sector: Optional[str] = None


@dataclass
class UnitIntegritySample:
    """Pre-fetched, DB-free inputs for one validator run.

    The loader computes all counts/lists; the validator only classifies.
    Every list of anomalies is already filtered to the offending tickers
    so the validator's job is pure threshold logic (trivially testable).
    """

    row_count: int
    prior_row_count: int
    last_update: Optional[datetime]

    # asset_turnover: every ticker whose latest-annual asset_turnover
    # escapes its sector band, classified to warn/fail by the loader.
    asset_turnover_total: int
    asset_turnover_anomalies: list[TickerAnomaly] = field(default_factory=list)

    # de_ratio == 0 cohort
    de_total: int = 0
    de_zero_count: int = 0
    de_zero_by_sector: dict[str, tuple[int, int]] = field(default_factory=dict)

    # net_margin out of band
    net_margin_total: int = 0
    net_margin_anomalies: list[TickerAnomaly] = field(default_factory=list)

    # revenue >> market cap
    rev_mcap_total: int = 0
    rev_mcap_anomalies: list[TickerAnomaly] = field(default_factory=list)

    # fcf >> market cap (DCF overshoot)
    fcf_mcap_total: int = 0
    fcf_mcap_anomalies: list[TickerAnomaly] = field(default_factory=list)

    # currency double-convert
    currency_total: int = 0
    non_inr_count: int = 0
    non_inr_tickers: list[str] = field(default_factory=list)

    # known-good asset_turnover values
    known_good_asset_turnover: dict[str, Optional[float]] = field(default_factory=dict)


def _summarise_anomalies(anomalies: list[TickerAnomaly], limit: int = 8) -> dict:
    """Compact, admin-renderable summary of the offending tickers."""
    worst = sorted(
        anomalies,
        key=lambda a: (0 if a.severity == "fail" else 1, -abs(a.observed)),
    )[:limit]
    return {
        "count": len(anomalies),
        "fail_count": sum(1 for a in anomalies if a.severity == "fail"),
        "warn_count": sum(1 for a in anomalies if a.severity == "warn"),
        "top_offenders": [
            {
                "ticker": a.ticker,
                "field": a.field,
                "observed": round(a.observed, 4),
                "expected_band": list(a.expected_band),
                "severity": a.severity,
                "sector": a.sector,
            }
            for a in worst
        ],
    }


def _anomaly_cohort_check(
    table: str, label: str, total: int, anomalies: list[TickerAnomaly]
) -> CheckResult:
    """Turn a list of per-ticker anomalies into one cohort CheckResult.

    Status is the max severity present: any ``fail`` anomaly → fail;
    else any ``warn`` → warn; else pass. The threshold dict carries the
    full top-offenders summary so the admin board shows exactly which
    tickers to chase.
    """
    summary = _summarise_anomalies(anomalies)
    summary["cohort_total"] = total
    if summary["fail_count"] > 0:
        status = "fail"
    elif summary["warn_count"] > 0:
        status = "warn"
    else:
        status = "pass"

    if status == "pass":
        details = f"{table}: {label} clean across {total} tickers"
    else:
        offenders = ", ".join(
            f"{o['ticker']}={o['observed']:g}" for o in summary["top_offenders"][:5]
        )
        details = (
            f"{table}: {label} flagged {summary['count']}/{total} tickers "
            f"({summary['fail_count']} fail, {summary['warn_count']} warn) — "
            f"top: {offenders}"
        )
    return CheckResult(
        name=f"unit_integrity.{label}",
        status=status,
        details=details,
        threshold=summary,
    )


class UnitIntegrityValidator:
    """Cross-field unit / currency / magnitude integrity validator.

    Target surface is a logical join of ``ratio_history`` (computed
    ratios: asset_turnover, de_ratio, net_margin, market_cap_cr) and
    ``financials`` (raw revenue / free_cash_flow / currency), keyed on
    the latest annual period per ticker. We report under ``ratio_history``
    as the primary table since that's where most of the derived signals
    live and where the admin board already has a row.
    """

    table = "ratio_history"
    # Diagnostic cross-field validator — not tied to a single populator.
    populator = "data_quality.unit_integrity"

    def __init__(
        self,
        sample_loader: Optional[Callable[[], UnitIntegritySample]] = None,
    ) -> None:
        self._sample_loader = sample_loader or self._load_sample_from_db

    def _load_sample_from_db(self) -> UnitIntegritySample:
        from ..db_loaders_unit import load_unit_integrity_sample

        sample = load_unit_integrity_sample()
        if sample is None:
            raise NotImplementedError(
                "DATABASE_URL unset; UnitIntegrityValidator skipped. "
                "Use --dry-run for local smoke without a DB."
            )
        return sample

    def _currency_check(self, s: "UnitIntegritySample") -> CheckResult:
        """Non-INR latest-financials guard with a zero-floor.

        Distinct from the generic cohort_fraction helper: we want EXACTLY
        zero non-INR rows to be green (the desired steady state), any
        positive count to be at least a warn (one ticker is enough to
        produce a ₹9.6T fair value downstream), and a cohort above the
        fail fraction to be red.
        """
        total = s.currency_total
        n = s.non_inr_count
        pct = (n / total * 100.0) if total > 0 else 0.0
        listed = ", ".join(s.non_inr_tickers[:12])
        if len(s.non_inr_tickers) > 12:
            listed += " ..."
        threshold = {
            "label": "currency_non_inr",
            "non_inr_count": n,
            "total": total,
            "pct": round(pct, 3),
            "fail_pct": CURRENCY_NON_INR_FAIL_PCT,
            "non_inr_tickers": s.non_inr_tickers[:50],
        }
        if n == 0:
            status = "pass"
            details = f"{self.table}: all {total} latest-financials rows are INR"
        elif pct >= CURRENCY_NON_INR_FAIL_PCT:
            status = "fail"
            details = (
                f"{self.table}: {n}/{total} ({pct:.2f}%) non-INR latest "
                f"financials (>= {CURRENCY_NON_INR_FAIL_PCT}% fail) — "
                f"downstream mis-scale / double-convert risk; tickers: {listed}"
            )
        else:
            status = "warn"
            details = (
                f"{self.table}: {n}/{total} ({pct:.2f}%) non-INR latest "
                f"financials — downstream mis-scale / double-convert risk; "
                f"tickers: {listed}"
            )
        return CheckResult(
            name="cohort_fraction.currency_non_inr",
            status=status,  # type: ignore[arg-type]
            details=details,
            threshold=threshold,
        )

    def run(self) -> HealthCheckResult:
        s = self._sample_loader()
        checks: list[CheckResult] = [
            row_count_stability(self.table, s.row_count, s.prior_row_count),
            _anomaly_cohort_check(
                self.table, "asset_turnover_band",
                s.asset_turnover_total, s.asset_turnover_anomalies,
            ),
            _anomaly_cohort_check(
                self.table, "net_margin_band",
                s.net_margin_total, s.net_margin_anomalies,
            ),
            _anomaly_cohort_check(
                self.table, "revenue_over_market_cap",
                s.rev_mcap_total, s.rev_mcap_anomalies,
            ),
            _anomaly_cohort_check(
                self.table, "fcf_over_market_cap",
                s.fcf_mcap_total, s.fcf_mcap_anomalies,
            ),
        ]

        # de_ratio == 0 cohort: universe-wide + worst single sector.
        checks.append(
            cohort_fraction_check(
                self.table, "de_ratio_zero_universe",
                s.de_zero_count, s.de_total,
                warn_pct=DE_ZERO_WARN_PCT, fail_pct=DE_ZERO_FAIL_PCT,
                detail_suffix="(exactly-zero de_ratio — dropped-equity signature)",
            )
        )
        for sector, (matched, total) in sorted(s.de_zero_by_sector.items()):
            # Only emit a per-sector check for cohorts large enough to be
            # meaningful (a 1-of-2 zero isn't a cohort signal).
            if total >= 8:
                checks.append(
                    cohort_fraction_check(
                        self.table, f"de_ratio_zero_sector.{sector}",
                        matched, total,
                        warn_pct=DE_ZERO_WARN_PCT, fail_pct=DE_ZERO_FAIL_PCT,
                        detail_suffix=f"(sector={sector})",
                    )
                )

        # Currency double-convert guard. Zero non-INR rows is green; any
        # positive count warns; a cohort above the fail fraction is red.
        checks.append(self._currency_check(s))

        # Known-good asset_turnover plausibility.
        for ticker, (lo, hi) in KNOWN_GOOD_ASSET_TURNOVER.items():
            checks.append(
                known_good_plausibility(
                    self.table, ticker, "asset_turnover",
                    s.known_good_asset_turnover.get(ticker), lo, hi,
                )
            )

        # Recency — ratio_history is rebuilt per financial period; a stale
        # snapshot would make every cross-check above lie. 120d ceiling
        # matches the ratio_history validator's own freshness bar.
        checks.append(
            last_update_recency(self.table, s.last_update, max_age_hours=24.0 * 120)
        )

        return HealthCheckResult(
            table=self.table,
            populator=self.populator,
            last_run_at=datetime.now(timezone.utc),
            checks=checks,
        )


def classify_asset_turnover(
    ticker: str, sector: Optional[str], value: Optional[float]
) -> Optional[TickerAnomaly]:
    """Classify one ticker's asset_turnover against its sector band.

    Returns a TickerAnomaly when the value escapes the sector's warn band
    (severity ``fail`` if it also escapes the fail band), else None. Pure
    function so both the loader and the tests use the identical logic.
    """
    if value is None:
        return None
    warn_lo, warn_hi, fail_lo, fail_hi = SECTOR_ASSET_TURNOVER_BANDS.get(
        sector or "", DEFAULT_ASSET_TURNOVER_BAND
    )
    if value < fail_lo or value > fail_hi:
        return TickerAnomaly(
            ticker, "asset_turnover", value, (fail_lo, fail_hi), "fail", sector
        )
    if value < warn_lo or value > warn_hi:
        return TickerAnomaly(
            ticker, "asset_turnover", value, (warn_lo, warn_hi), "warn", sector
        )
    return None


__all__ = [
    "UnitIntegrityValidator",
    "UnitIntegritySample",
    "TickerAnomaly",
    "classify_asset_turnover",
    "DEFAULT_ASSET_TURNOVER_BAND",
    "SECTOR_ASSET_TURNOVER_BANDS",
    "NET_MARGIN_BAND",
    "REVENUE_OVER_MCAP_WARN",
    "REVENUE_OVER_MCAP_FAIL",
    "FCF_OVER_MCAP_WARN",
    "FCF_OVER_MCAP_FAIL",
    "DE_ZERO_WARN_PCT",
    "DE_ZERO_FAIL_PCT",
    "CURRENCY_NON_INR_FAIL_PCT",
    "KNOWN_GOOD_ASSET_TURNOVER",
]
