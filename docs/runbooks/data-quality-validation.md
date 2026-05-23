# Runbook — Data-quality validation framework

**Owner:** data-pipeline team
**Introduced:** 2026-05-23 (Phase A.1, PR #TBD)
**Status:** A.1 ships framework + 2 reference validators; A.2 adds cron + admin UI + 9 more validators.

## What this is

A small Python framework that runs a battery of plausibility checks
against our core data tables and writes each run's outcome to
`data_quality_runs` (migration 057). Each run is classified `green` /
`yellow` / `red` so an operator (and, in A.2, the admin UI) can
glance at the system's data health.

Built in response to Day-111 / Day-112: four silent data-quality
regressions had been live in production for weeks because every test
asserted shape, not plausibility (industry serializer dropping the
field, bank D/E using wrong denominator, three populators setting
`adj_close == close_price`, 32/97 tickers missing
`compounded_growth.stock`).

## Architecture

```
backend/services/data_quality/
├── __init__.py              CheckResult, HealthCheckResult, Validator protocol
├── checks.py                reusable helpers (null rate, row count, recency, ...)
└── validators/
    ├── __init__.py          REGISTRY list — discovery point
    ├── daily_prices.py      Day-112 coverage
    └── stocks.py            Day-111a coverage

scripts/run_data_quality_validators.py   orchestrator
data_pipeline/migrations/057_data_quality_runs.sql   storage
backend/tests/test_phase_a1_data_quality_framework.py   42 tests
```

## Running it

### Local smoke (no DB)

```bash
python scripts/run_data_quality_validators.py --dry-run
```

In A.1 every validator's DB loader raises `NotImplementedError`, so
the orchestrator prints a `[SKIP]` line per validator and exits 0.
A.2 wires the live Neon loaders.

### Production (A.2)

```bash
DATABASE_URL=postgres://... python scripts/run_data_quality_validators.py
```

Exit codes:
- `0` — every run green or yellow
- `1` — at least one run red
- `2` — orchestrator-level failure (validator raised, unknown `--table` filter)

### Single validator

```bash
python scripts/run_data_quality_validators.py --table daily_prices --dry-run
```

## Reading a failed CheckResult

A red run's `checks` JSONB column contains the full list. Find the
failing one:

```sql
SELECT checks
FROM data_quality_runs
WHERE overall_status = 'red'
ORDER BY run_at DESC
LIMIT 1;
```

Each check has:

- `name` — stable identifier (e.g. `adj_close_distinct_from_close`)
- `status` — `pass` / `warn` / `fail`
- `details` — human-readable explanation (designed to be paste-able into Slack)
- `threshold` — structured dict with `expected`, `actual`, `tolerance`,
  and whatever other context the helper recorded

Example (Day-112 regression, hypothetical re-occurrence):

```json
{
  "name": "adj_close_distinct_from_close",
  "status": "fail",
  "details": "adj_close == close_price for too many pre-2024 rows on RELIANCE=95% (Day-112 regression signature)",
  "threshold": {
    "tickers": ["NESTLEIND", "TCS", "RELIANCE"],
    "max_fraction_equal": 0.90,
    "pre_date": "2024-01-01",
    "observed": {"NESTLEIND": 0.30, "TCS": 0.25, "RELIANCE": 0.95}
  }
}
```

Triage:
1. Identify the populator (`SELECT populator FROM data_quality_runs WHERE id = ...`)
2. Check the populator's recent commits — did anyone change adj_close logic?
3. Run the canary-diff harness on the affected tickers
4. If real regression: revert or hot-fix; backfill via `scripts/rebuild_adj_close.py`

## Adding a new validator

1. Create `backend/services/data_quality/validators/<table_name>.py`
2. Define a `<TableName>Sample` dataclass (pre-fetched inputs)
3. Define `<TableName>Validator` with:
   - `table: str` class attribute
   - `populator: str` class attribute (the canonical write path)
   - `__init__(self, sample_loader=None)` — default to `self._load_sample_from_db`
   - `run(self) -> HealthCheckResult`
4. Use helpers from `checks.py` where possible; one-off domain checks
   live as private module functions (see `_adj_close_distinctness_check`)
5. Register in `validators/__init__.py` `REGISTRY` list
6. Add tests:
   - one `_healthy_<table>_sample()` fixture
   - one `test_<table>_healthy_input_is_green`
   - one `test_<table>_catches_<specific_regression>` per fail mode

Threshold sources MUST be documented in the validator's module
docstring — either "empirical (parquet observation Y/Z)" or
"needs-baseline (conservative default)". A.2 will retune `needs-baseline`
thresholds against live prod data.

## Threshold tuning protocol

If a validator fires a false positive 3+ times in 30 days:

1. Open a PR titled `tune: <validator>.<check> threshold`
2. Body must include:
   - The three+ run IDs from `data_quality_runs` that fired
   - The justification (what `actual` was observed, why it's legitimately fine)
   - The proposed new threshold and the headroom it provides
3. Update the constant in the validator module + the threshold-source
   comment to reflect the new baseline
4. Add or extend a boundary test in the test file

If a validator fails to catch a real regression that should have
fired:

1. Open a PR titled `tighten: <validator>.<check> threshold` (or
   `add: <validator>.<check>` if it's a missing check)
2. Body must include the diagnostic doc / postmortem of the missed regression
3. Add a regression test that fails before the fix and passes after

## A.2 (deferred — separate PR)

- `.github/workflows/data_quality_validate.yml` cron (4x daily)
- Live DB loaders for the two A.1 validators
- Admin endpoint `GET /admin/data-quality/runs?status=red`
- Admin UI tile (status board + drill-down)
- 9 additional validators: `ttm_quarterly`, `corporate_actions`,
  `analyst_estimates`, `compounded_growth`, `peer_groups`,
  `ratio_history`, `shareholding`, `cron_heartbeats`,
  `nse_industry_master`

## Discipline notes

- This framework is observability-only — it never auto-fixes data.
- No CACHE_VERSION bump required (does not touch model output)
- No manifest entry required (admin/observability scope)
- SEBI: no public surface; admin-only
