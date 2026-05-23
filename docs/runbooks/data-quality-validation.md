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

## Per-validator reference

A.1 + A.2.1 + A.2.2 ship 10 concrete validators. The signal-to-noise
profile of each one is documented here so triage is fast.

### `daily_prices` (A.1)
**What it checks:** schema columns, row-count stability, close_price
null rate, recency (28h), per-canary `adj_close != close_price` on
pre-2024 rows, plausibility bands on RELIANCE / TCS / HDFCBANK close.

**Common false positives:** none seen yet.

**Suppress when:** never. Any red here is real.

---

### `stocks` (A.1, A.2.2 calibration)
**What it checks:** row-count, industry/sector null rates, is_active
NOT NULL invariant, fuzzy industry canaries (HDFCBANK / TCS /
RELIANCE / NESTLEIND / MARUTI), 168h recency.

**Common false positives:** populator renames a taxonomy label
(e.g. "Banks - Private Sector" → "Nifty Private Bank"). Mitigated in
A.2.2 by the fuzzy token-match — add a new token to
`CANARY_INDUSTRY_TOKENS` if a legitimate new tag surfaces.

**Suppress when:** never. Label changes are a one-line PR to extend
the token list.

---

### `corporate_actions` (A.2.1)
**What it checks:** schema, row-count, recency (30d), known-good
SPLIT/BONUS coverage for RELIANCE/INFY/WIPRO, `adjustment_factor`
null rate on SPLIT/BONUS rows, `data_quality_rank` coverage.

**Common false positives:** `data_quality_rank` may dip after a
backfill before reranking lands; a yellow here for <48h is OK.

**Suppress when:** label PR as `wontfix-known-noise` if the
canary_actions check fires *only* on WIPRO during a known
yfinance-outage window (rare).

**Known A.2.1 finding (filed separately):** INFY missing 2018 bonus.

---

### `consensus_estimates` (A.2.1)
**What it checks:** schema, fresh row count over last 24h, recency
of latest fetched_at, canary coverage (HDFCBANK / TCS / RELIANCE
have ≥1 row in last 7 days), target_mean null rate.

**Common false positives:** weekend gaps shrink `rows_in_last_24h`
below the warn threshold without breaking anything. Already handled
via the warn-vs-fail tier inside the validator.

**Suppress when:** never. Use `force_refresh=true` to bypass the
admin-endpoint cache after a fresh cron lands.

---

### `ratio_history` (A.2.1)
**What it checks:** schema, row-count, recency, pe/de null rates on
latest period, HDFCBANK plausibility on pe_ratio and roe.

**Known A.2.1 finding (filed separately):** `pe_ratio` 50.9% null on
the latest period. Cause is a non-banking-coverage gap in the
ratio populator; tracked as a P1 separately.

---

### `peer_groups` (A.2.1)
**What it checks:** schema, row-count, recency (168h), HDFCBANK and
TCS have ≥3 peers each.

**Common false positives:** a fresh universe pivot can briefly
drop a canary below 3 before the next peer-build run; yellow for
<24h is OK.

---

### `cron_heartbeats` (A.2.2)
**What it checks:** schema, row-count, per-workflow staleness vs
`2 × expected_interval_minutes` for the four workflows listed in
`EXPECTED_WORKFLOWS` (nightly-ingest, weekly-industry-master,
cron-deadman-checker, data-quality-validate).

**Common false positives:** GitHub Actions cron drift — a workflow
fires late by 5-15 min routinely. The 2x multiplier absorbs this.

**Suppress when:** never. A red here is *the* "the populator
silently stopped running" signal this entire framework was built for.

---

### `shareholding_pattern` (A.2.2)
**What it checks:** schema, row-count, quarterly recency (100d),
sum-to-100 ± 1 invariant on five canaries, promoter % bands on
HDFCBANK and KOTAKBANK.

**Common false positives:** during NSE's filing window (within 21d
of quarter end) some tickers may not yet have the latest quarter;
the 100d threshold absorbs this.

**Suppress when:** label `wontfix-known-noise` if a single
non-canary ticker's promoter band fails due to a known corporate
restructuring announced and parsed within the prior week.

---

### `company_quarterly_results` (A.2.2)
**What it checks:** schema, row-count, recency, top-10 canary
quarterly-filing recency (100d), revenue & net_profit null rates on
canaries' latest 4 quarters, HDFCBANK latest revenue band
[₹70K, ₹90K] Cr.

**Common false positives:** during the quarter-end filing window, a
canary may not have filed yet — yellow for <30d is OK.

**Suppress when:** an HDFCBANK band miss is acceptable only with a
postmortem PR retuning the band; do NOT label as noise.

---

### `cagr_service_output` (A.2.2)
**What it checks:** runs `compute_cagr_panel` for 5 canaries
(TCS, INFY, HDFCBANK, RELIANCE, ICICIBANK); ensures ≥3/5 have a
5y CAGR populated, ≥4/5 have a 3y CAGR populated; checks 5y CAGRs
for plausibility (very wide band, [-30%, +50%]).

**Common false positives:** a backfill-in-progress will briefly
drop coverage; yellow for <12h after `rebuild_adj_close.py` is OK.

**Suppress when:** never. Below-floor coverage is exactly the
Day-112 regression signature we built this for.

---

## Triaging red statuses (admin UI)

1. **Open** `/admin/data-quality`.
2. **Sort** is already red-first; the offending table is at the top.
3. **Click** to expand. Read the failing check's `details` field —
   it's designed to paste into Slack.
4. **Open** this runbook to the per-validator section above and
   follow the "common false positives" and "suppress when" hints.
5. **If real regression:** open a PR via the canary-diff harness;
   for data fixes, follow the data-fix discipline in root `CLAUDE.md`.

## Labelling `wontfix-known-noise`

A failure should ONLY be labelled `wontfix-known-noise` if:
- the runbook section above explicitly lists it as a known false
  positive, OR
- a separate postmortem PR documents the root cause and proposes a
  threshold-tuning PR title (`tune: <validator>.<check> threshold`).

Otherwise: treat the red as load-bearing.

## Discipline notes

- This framework is observability-only — it never auto-fixes data.
- No CACHE_VERSION bump required (does not touch model output)
- No manifest entry required (admin/observability scope)
- SEBI: no public surface; admin-only
