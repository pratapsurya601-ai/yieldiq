# Data-quality validation architecture (Phase A)

Date: 2026-05-24
Status: A.1 + A.2.1 + A.2.2 merged; A.3 deferred.

## End-to-end flow

```
                                  +--------------------+
   GitHub Actions cron (6h)  -->  | run_data_quality_  |
   (.github/workflows/             |  validators.py     |
    data_quality_validate.yml)     +---------+----------+
                                             |
                                             | discovers REGISTRY from
                                             | backend/services/data_quality/
                                             |  validators/__init__.py
                                             v
                            +--------------------------------+
                            | For each Validator in REGISTRY:|
                            |   sample = v._load_sample_..() |
                            |   result = v.run()             |
                            |   write to data_quality_runs   |
                            |   (migration 057)              |
                            +--------------+-----------------+
                                           |
                                           v
                                 +---------------------+
                                 | Postgres / Neon     |
                                 |  data_quality_runs  |
                                 |   id, table_name,   |
                                 |   populator,        |
                                 |   overall_status,   |
                                 |   run_at,           |
                                 |   checks (JSONB)    |
                                 +----------+----------+
                                            |
                                            | DISTINCT ON (table_name, populator)
                                            |  ORDER BY run_at DESC
                                            v
                                 +---------------------+
                                 | FastAPI router      |
                                 | /api/v1/admin/      |
                                 |  data-quality/runs  |
                                 | (5-min process TTL) |
                                 +----------+----------+
                                            |
                                            | JSON
                                            v
                                 +---------------------+
                                 | Next.js admin page  |
                                 | /admin/data-quality |
                                 |   sorted red-first  |
                                 |   click to expand   |
                                 |   recent-failures   |
                                 +---------------------+
```

## Design choice: per-table validators, not one mega-validator

We considered three shapes:

1. **One mega-validator** that loads everything in one shot and emits
   one big CheckResult list. Rejected because: review surface huge,
   one slow query blocks all checks, can't run a subset, the JSONB
   blob in the runs table becomes opaque.

2. **One validator per CheckResult** (hundreds of tiny modules).
   Rejected because: ridiculous import surface, no natural
   "table-level overall_status", can't share a sample between
   related checks.

3. **One validator per (table, populator)** — what we shipped. Each
   validator:
   - Loads its own sample in one pass (cheap because we group all
     SQL for the table in one loader).
   - Emits 4-8 CheckResults from the same sample.
   - Reports a single overall_status (red if any fail, yellow if any
     warn, green otherwise) that the admin UI can sort on.

This shape also matches the human ownership model: "who do I page
when `daily_prices` is red" maps 1:1 to "the daily_prices populator
owner", which is the same person who'd fix the validator.

## Why thresholds live in the validator, not in checks.py

`checks.py` ships only domain-free helpers (`null_rate_check`,
`last_update_recency`, `row_count_stability`, `schema_columns_present`,
`known_good_plausibility`). Every threshold (PE band for HDFCBANK,
30-day recency for corporate actions, 168h recency for stocks) lives
in the validator module that owns the table.

This makes per-table review trivially scoped: a PR titled
`tune: ratio_history.HDFCBANK.pe_ratio threshold` touches exactly
`validators/ratio_history.py` and `test_phase_a*_validators.py`.

## Adding a new validator

Template (≈100 LoC):

```python
# backend/services/data_quality/validators/<table>.py
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Callable, Optional

from .. import CheckResult, HealthCheckResult
from ..checks import row_count_stability, schema_columns_present, last_update_recency

EXPECTED_COLUMNS = ["col_a", "col_b"]

@dataclass
class <Table>Sample:
    row_count: int
    prior_row_count: int
    schema_columns: list[str]
    last_update: Optional[datetime]
    # ... domain-specific fields ...

def _<domain_check>(sample: <Table>Sample) -> CheckResult:
    ...

class <Table>Validator:
    table = "<table>"
    populator = "<dotted.path.to.populator>"

    def __init__(self, sample_loader: Optional[Callable] = None):
        self._sample_loader = sample_loader or self._load_sample_from_db

    def _load_sample_from_db(self) -> <Table>Sample:
        from ..db_loaders_a2_2 import load_<table>_sample  # or a2 / a3 etc.
        sample = load_<table>_sample()
        if sample is None:
            raise NotImplementedError("DATABASE_URL unset; <Table>Validator skipped.")
        return sample

    def run(self) -> HealthCheckResult:
        sample = self._sample_loader()
        checks = [
            schema_columns_present(self.table, EXPECTED_COLUMNS, sample.schema_columns),
            row_count_stability(self.table, sample.row_count, sample.prior_row_count),
            _<domain_check>(sample),
            last_update_recency(self.table, sample.last_update, max_age_hours=...),
        ]
        return HealthCheckResult(
            table=self.table,
            populator=self.populator,
            last_run_at=datetime.now(timezone.utc),
            checks=checks,
        )
```

Then:

1. Add a loader in `db_loaders_a2_2.py` (or new `db_loaders_a3.py`).
2. Register the class in `validators/__init__.py` `REGISTRY`.
3. Add tests in `backend/tests/test_phase_aX_..._validators.py`:
   - one healthy-sample fixture
   - one `test_<table>_healthy_is_green`
   - ≥2 regression-mode fixtures (one per check that can fail)
4. Document the validator in `docs/runbooks/data-quality-validation.md`
   per-validator section.

## Worked example: how this framework would have caught past regressions

### Day-112 `adj_close == close_price` regression

**Bug:** Three independent populators (Day-94 yfinance backfill,
Day-95 NSE bhavcopy script, Day-98 BSE archive ingest) each wrote
`adj_close = close_price` for pre-2024 rows, silently breaking 5y CAGR
for 32/97 tickers.

**Validator that would have fired:**
- File: `validators/daily_prices.py`
- Check name: `adj_close_distinct_from_close`
- Threshold: `max_fraction_equal=0.90` on RELIANCE/TCS/NESTLEIND
  pre-2024 rows.
- The fix-PR would have failed this check because RELIANCE went to
  0.95 fraction-equal post-populator. The check `details` would have
  been: `"adj_close == close_price for too many pre-2024 rows on
  RELIANCE=95% (Day-112 regression signature)"`.

### Day-111a industry serializer regression

**Bug:** `local_data_service.py` dropped `industry` from its
serializer payload; 96% of stocks rendered with `industry = ""` and
the cohort engine collapsed every bank into one bucket.

**Validator that would have fired:**
- File: `validators/stocks.py`
- Two checks would have fired simultaneously:
  1. `null_rate.industry` — threshold `max_null_pct=20.0`, observed
     96%. Fail with `"stocks.industry: 1920/2000 null (96.0% > 20.0%
     threshold)"`.
  2. `known_good.HDFCBANK.industry` — A.2.2's fuzzy match would have
     observed `""` and failed with `"industry calibration failed:
     HDFCBANK.industry='' matches none of [bank, private bank, ...]
     (Day-111a regression signature)"`.
- The peer-groups validator would have fired as a follow-on red
  (HDFCBANK collapsed to <3 peers when industry blanked).

### Day-111b bank D/E denominator regression

**Bug:** The ratio populator was using `total_borrowings` for banks'
debt, ignoring deposits. HDFCBANK D/E plummeted from ~8 to ~0.5.

**Validator that would have fired:**
- File: `validators/ratio_history.py`
- Check name: `plausibility.HDFCBANK.de_ratio` (within the
  `HDFCBANK_BANDS` known-good check).
- The validator's HDFCBANK D/E band is set against bank-side reality
  (D/E for banks is naturally high). 0.5 falls outside the band.
  Fail with `"ratio_history: HDFCBANK.de_ratio=0.5 outside plausible
  band [6.0, 12.0]"`.

In all three cases the validator would have fired on the very next
post-merge cron run (within 6h), giving us a hard signal before any
narrative or sector page rendered the broken value.

## What A.2.2 does NOT include

- The cron workflow file itself (`.github/workflows/data_quality_validate.yml`)
  shipped in A.2.1.
- Slack / email alerting on red transitions — A.3 will wire this
  via the existing Sentry+webhook path; today red is surfaced via
  the admin UI only.
- Auto-remediation. By design. This framework is observability-only.

## Future work (A.3 and beyond)

- More validators: `screener_results`, `narrative_cache`,
  `sector_aggregates`.
- Alerting on red transitions (Slack webhook + Sentry breadcrumb).
- Validator-driven backfills: when `cron_heartbeats` flags a stale
  cron, auto-open a GitHub issue tagged `cron-deadman`.
- Suppress-list with TTL so `wontfix-known-noise` doesn't drift into
  permanent silence.
