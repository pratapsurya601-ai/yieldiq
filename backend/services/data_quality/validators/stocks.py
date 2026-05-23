"""stocks validator (Phase A.1, 2026-05-23; A.2.2 industry calibration).

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

Fuzzy-match philosophy for industry calibration (A.2.2)
-------------------------------------------------------
A.2.1's first live run surfaced that the original `startswith("Banks")`
check on HDFCBANK was too rigid — the actual populated value is
``"Nifty Private Bank"`` (NSE's industry-master tag), so the check
fired a false-positive red.

The fix is to broaden the per-canary check from a single literal prefix
to a list of substring tokens. Our north star is not "label matches
exact taxonomy X" but rather "field is non-empty AND broadly correct
for the sector". A new tagging label rolled out by the populator (e.g.
"Banks - Private Sector" → "Nifty Private Bank") should NOT page us;
only "industry empty" or "industry says 'IT' for HDFCBANK" should.

For each canary ticker we record:
- ``tokens``: substrings any one of which makes the value plausible
  (case-insensitive)
- ``why``: one-sentence rationale visible in the threshold dict

If you need to add a canary, prefer 3-5 tokens covering the populator
taxonomies we know about (NSE industry-master, BSE sector, yfinance).

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
- Canary industries (A.2.2): fuzzy token-match per ticker (HDFCBANK,
  TCS, RELIANCE, NESTLEIND, MARUTI) — see ``CANARY_INDUSTRY_TOKENS``.
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

# LEGACY (kept for backward compat with A.1 tests/imports).
# The Day-111a regression test used `startswith("Banks")`; A.2.2
# replaces this with the fuzzy CANARY_INDUSTRY_TOKENS map below.
EXPECTED_INDUSTRY_PREFIX_HDFCBANK = "Banks"

# A.2.2 fuzzy canary map. Each entry: ticker -> {tokens, why}.
# A check passes if industry is non-empty AND contains ANY of the
# ticker's tokens as a case-insensitive substring.
CANARY_INDUSTRY_TOKENS: dict[str, dict] = {
    "HDFCBANK": {
        "tokens": ["bank", "private bank", "nifty private bank", "banks - private sector"],
        "why": "HDFCBANK is a private-sector bank; populators tag it 'Banks', 'Banks - Private Sector', or 'Nifty Private Bank'.",
    },
    "TCS": {
        "tokens": ["it", "tech", "computer", "software", "services - it", "information technology"],
        "why": "TCS is IT services; tag varies across IT/Tech/Computer-Software/Information Technology.",
    },
    "RELIANCE": {
        "tokens": ["oil", "petroleum", "energy", "refineries", "refinery", "diversified"],
        "why": "RELIANCE is classified under Oil/Petroleum/Energy/Refineries or sometimes Diversified.",
    },
    "NESTLEIND": {
        "tokens": ["fmcg", "consumer", "food", "packaged food"],
        "why": "NESTLEIND is FMCG / packaged food / consumer staples.",
    },
    "MARUTI": {
        "tokens": ["auto", "automobile", "passenger car", "4w", "four wheeler"],
        "why": "MARUTI is auto / passenger 4-wheelers.",
    },
}


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
    # A.2.2: industry values for the broader canary set. Optional —
    # A.1 callers that don't populate this dict still pass via the
    # legacy HDFCBANK-only check path.
    canary_industries: dict[str, Optional[str]] = field(default_factory=dict)


def _industry_fuzzy_match(actual: Optional[str], tokens: list[str]) -> bool:
    """Case-insensitive substring match against any of ``tokens``."""
    if not actual or not actual.strip():
        return False
    needle = actual.strip().lower()
    return any(t.lower() in needle for t in tokens)


def _industry_known_good_check(sample: StocksSample) -> CheckResult:
    """Each canary ticker's industry must non-empty AND fuzzy-match the
    expected token set for that ticker.

    A.2.2 broadens this from A.1's rigid ``startswith("Banks")`` check
    to a token-based fuzzy match. The fuzzy approach was chosen after
    A.2.1's live run flagged HDFCBANK ("Nifty Private Bank") as red
    despite the field being correct — see module docstring for the
    full philosophy.

    The check still fails (red) when:
    - ANY canary's industry is null/empty (Day-111a regression signature)
    - ANY canary's industry doesn't contain ANY of its expected tokens
      (catches a wholesale mis-categorisation, e.g. HDFCBANK → "IT")

    Backwards compat: if ``sample.canary_industries`` is empty
    (A.1-style caller), we fall back to checking only HDFCBANK via
    ``sample.hdfcbank_industry``.
    """
    # Build the per-canary actuals dict, preferring the new
    # canary_industries map but falling back to A.1's hdfcbank_industry.
    actuals: dict[str, Optional[str]] = dict(sample.canary_industries or {})
    if "HDFCBANK" not in actuals:
        actuals["HDFCBANK"] = sample.hdfcbank_industry

    failed: list[tuple[str, Optional[str], list[str]]] = []
    passed_detail: list[str] = []
    for ticker, meta in CANARY_INDUSTRY_TOKENS.items():
        if ticker not in actuals:
            # Caller didn't ask about this one; skip silently.
            continue
        actual = actuals[ticker]
        tokens = meta["tokens"]
        if not _industry_fuzzy_match(actual, tokens):
            failed.append((ticker, actual, tokens))
        else:
            passed_detail.append(f"{ticker}={actual!r}")

    threshold = {
        "canaries": {
            t: {
                "actual": actuals.get(t),
                "expected_any_of": CANARY_INDUSTRY_TOKENS[t]["tokens"],
                "why": CANARY_INDUSTRY_TOKENS[t]["why"],
            }
            for t in actuals
            if t in CANARY_INDUSTRY_TOKENS
        },
        "philosophy": "fuzzy substring match — see stocks.py docstring",
    }

    if failed:
        failed_descs = [
            f"{t}.industry={a!r} matches none of {toks}"
            for (t, a, toks) in failed
        ]
        return CheckResult(
            name="known_good.HDFCBANK.industry",  # name kept for back-compat
            status="fail",
            details=(
                "industry calibration failed: "
                + "; ".join(failed_descs)
                + " (Day-111a regression signature)"
            ),
            threshold=threshold,
        )
    return CheckResult(
        name="known_good.HDFCBANK.industry",  # back-compat name
        status="pass",
        details=f"canary industries OK ({', '.join(passed_detail)})",
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
    "CANARY_INDUSTRY_TOKENS",
]
