# Runbook: Phase I bank-KPI backfill (operator)

**Workflow:** `.github/workflows/bank-kpi-backfill.yml`
**Target table:** `bank_operational_kpis` (migration 061)
**Universe:** `PURE_BANK_TICKERS_FOR_DE` -- 38 commercial banks.

The workflow is `workflow_dispatch` only (no schedule). Open
GitHub Actions -> "Bank KPI Backfill (operator)" -> Run workflow,
then choose:

- **phase:** `xbrl` | `ar` | `all`
- **top_n_banks:** clamp on the AR phase's `--max-rows`; defaults
  to 38 (the full cohort). XBRL phase always walks the full
  cohort regardless.
- **cost_cap_usd:** hard-stop for the AR phase. Default 50 USD --
  enough for ~500 AR pages at the narrow bank-ops prompt (much
  cheaper than the Phase H full-AR extractor).
- **dry_run:** default true. Always run dry-first.
- **quarters:** XBRL history depth; default 20 (~5y).

## Workflow phases

### `xbrl` (free)

Drives `scripts/ingest_bank_kpis_from_xbrl.py` over the full
38-ticker cohort. Pre-flight samples HDFCBANK / SBIN / AXISBANK
and refuses to write unless at least 4 of 6 fields populate on
at least 2 of the 3 tickers.

**Today the default no-op provider is still active** (see
`data_pipeline/sources/bse_bank_xbrl.py` -- the provider-pattern
module). Running the `xbrl` phase right now will produce a clear
"PRE-FLIGHT FAILED: default no-op provider active" diagnostic and
write nothing. That is the expected starting state per the Phase
I-audit. Register a real provider in `bse_bank_xbrl.register_provider()`
before the `xbrl` phase will populate any rows.

Populates these six fields with `source='bse_xbrl'`:

- `gnpa_pct`, `nnpa_pct`, `pcr_pct`
- `casa_pct`, `cost_to_income_pct`, `credit_deposit_pct`

### `ar` (Anthropic-backed; cost-capped)

Drives `scripts/extract_bank_ops_from_ar.py` over the rows in
`company_annual_reports` whose ticker is in the cohort. Per-AR
spend ~$0.05-$0.10 with the narrow 800-token output cap; default
$30 cost cap permits ~300-600 ARs per run.

Populates these three operational fields with `source='ar_anthropic'`:

- `branches_total`, `branches_tier1`, `branches_tier2`, `branches_tier3`
- `atms_total`
- `customers_millions`

The pre-flight gate trips at >50% extraction failures in the first
5 rows (mirror of the Phase H AR-signals extractor).

### `all`

Runs `xbrl` then `ar` sequentially. Cleanest single-button option
once a real XBRL provider is wired -- one operator click fills
both halves of the table over the 38-bank cohort.

## Standard operator flows

### First-time smoke test

1. Inputs: `phase=xbrl`, `top_n_banks=38`, `dry_run=true`,
   `quarters=8`.
2. Expect: pre-flight FAIL diagnostic identifying the missing
   provider. No DB writes.
3. Wire a real provider, then re-run with `dry_run=false`.

### AR-only run (XBRL provider not yet wired)

1. Inputs: `phase=ar`, `top_n_banks=10` (start small),
   `cost_cap_usd=5`, `dry_run=true`.
2. Inspect dry-run log: confirm only bank tickers in the candidate
   list; spend estimate well under cap.
3. Re-run with `dry_run=false` and the same caps to populate the
   first ten banks' branches / ATMs / customers.

### Full backfill (both phases)

After XBRL provider is wired and a 3-bank sample run is clean:

1. Inputs: `phase=all`, `top_n_banks=38`, `cost_cap_usd=50`,
   `dry_run=false`, `quarters=20`.
2. Expected runtime: 15-30 min for xbrl (free), 30-60 min for ar
   (cost-bounded).
3. Validate with the SQL below.

## Validation SQL

```sql
-- Coverage matrix across the 38-ticker cohort -- which banks have
-- which subset of the nine KPI columns populated for their most
-- recent annual row?
WITH latest AS (
    SELECT DISTINCT ON (ticker)
        ticker,
        period_end,
        branches_total IS NOT NULL AS has_branches,
        atms_total     IS NOT NULL AS has_atms,
        customers_millions IS NOT NULL AS has_customers,
        gnpa_pct       IS NOT NULL AS has_gnpa,
        nnpa_pct       IS NOT NULL AS has_nnpa,
        pcr_pct        IS NOT NULL AS has_pcr,
        casa_pct       IS NOT NULL AS has_casa,
        cost_to_income_pct  IS NOT NULL AS has_c2i,
        credit_deposit_pct  IS NOT NULL AS has_c2d
      FROM bank_operational_kpis
     WHERE period_type IN ('annual', 'quarterly')
     ORDER BY ticker, period_end DESC
)
SELECT ticker, period_end,
       has_branches, has_atms, has_customers,
       has_gnpa, has_nnpa, has_pcr,
       has_casa, has_c2i, has_c2d
  FROM latest
 ORDER BY ticker;
```

```sql
-- Source-of-truth split: which path filled how many rows in the
-- last 30 days?
SELECT source, COUNT(*) AS rows_inserted,
       COUNT(DISTINCT ticker) AS distinct_banks
  FROM bank_operational_kpis
 WHERE extracted_at >= now() - INTERVAL '30 days'
 GROUP BY source
 ORDER BY rows_inserted DESC;
```

## Rollback

```sql
-- Drop everything from one source only (the other path's
-- contributions stay):
DELETE FROM bank_operational_kpis WHERE source = 'bse_xbrl';
DELETE FROM bank_operational_kpis WHERE source = 'ar_anthropic';

-- Or wipe the whole table (keeps the schema; safe re-run target):
TRUNCATE bank_operational_kpis;
```

After truncation the frontend `BankKpiPanel` will self-hide on
every bank ticker again -- the panel only renders when there's at
least one populated field or quarterly point in the response.

## Failure-mode table

| Failure | Likely cause | Fix |
|---|---|---|
| `PRE-FLIGHT FAILED: default no-op XBRL provider active` | XBRL provider not wired | Register a provider per `data_pipeline/sources/bse_bank_xbrl.py` docstring |
| `pre-flight: best row has 2/6 KPI fields` | Tag-name map incomplete in provider | Expand `_KPI_TAG_CANDIDATES` after sampling live XBRL |
| `dropping out-of-range gnpa_pct=245` | Provider returned a raw / unnormalised value | Always pass values through `as_percent()` in the provider |
| `PRE-FLIGHT FAILED: 3/5 (60%) extraction failures` (ar phase) | AR PDF URLs are stale or pypdf can't parse | Inspect the failing `ar_id`s in `company_annual_reports`; consider re-ingesting AR URLs from NSE feed |
| `ANTHROPIC_API_KEY not set` | Repo secret missing | Add `ANTHROPIC_API_KEY` at repo level (Settings -> Secrets) |
| `COST CAP HIT` (ar phase) | Cumulative spend exceeded `cost_cap_usd` | Re-run with `--resume-from-id=<last_id>` or raise cap |
| `no resolvable period_end for ar_id=...` | LLM didn't extract a date and `fiscal_year` is NULL on the AR row | Backfill `fiscal_year` upstream, then re-run with `--resume-from-id` |
| Frontend panel doesn't show on /analysis/HDFCBANK after a successful run | Stale browser cache | Hard-reload; the manifest entry `v_phase_i_bank_kpis_2026_05_26` should drop the cached row, but the frontend `staleTime: 6h` may delay refetch |

## Discipline checklist

- [ ] Migration 061 applied to the target Postgres.
- [ ] XBRL provider registered (or `phase=ar` selected) -- otherwise
      pre-flight FAILS by design.
- [ ] First run was `dry_run=true`.
- [ ] AR phase: `cost_cap_usd` set deliberately, not left at
      a value high enough to drain the Anthropic budget.
- [ ] No CACHE_VERSION bump (the v_phase_i_bank_kpis manifest
      entry handles invalidation surgically).
- [ ] Validation SQL ran post-backfill.
