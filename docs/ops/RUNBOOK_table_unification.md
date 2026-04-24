# Runbook: Table Unification (financials -> company_financials)

Applies migrations 013 + 014 and the `financials` -> `company_financials`
transform against prod. Est. wall time: 30-60 min. Requires `psql`, Python 3.11+,
`$DATABASE_URL` pointing at prod Neon, and read access to Railway logs.

Related files (do not paste their contents into psql — run them as specified):
- `data_pipeline/migrations/013_add_cache_version_to_endpoint_cache.sql`
- `data_pipeline/migrations/014_add_currency_to_company_financials.sql`
- `scripts/transform_financials_to_company_financials.py`
- `scripts/verify_canary_recovery.py`

Do the steps in order. Do not skip verification checkpoints. If a checkpoint
fails, STOP and jump to Appendix A (Rollback) rather than improvising.

---

## 0. Preflight (10 min, no writes)

Goal: confirm the environment, grab a backup, and fail fast if anything is off.

### 0.1 Branch + code state

```powershell
git checkout main
git pull
git log --oneline -5
```

Expected: latest commit matches the merge of PR #55. No local modifications
(`git status` clean).

### 0.2 Confirm DATABASE_URL points at prod

```powershell
echo $env:DATABASE_URL
```

Expected: a `postgresql://...@...neon.tech/...` URL for the prod project.
If it points at a branch DB or localhost, export the correct one before
continuing. Never paste the full URL with password into chat, logs, or commits.

### 0.3 Backend health

```powershell
curl https://api.yieldiq.in/health
```

Expected: HTTP 200 with `{"status":"ok",...}`. If the service is already
unhealthy, fix that before touching the DB.

### 0.4 psql available

```powershell
psql --version
```

Expected: `psql (PostgreSQL) 15.x` or newer. If missing, install before
continuing (the transform script does not need psql, but the verification
queries do).

### 0.5 Logical backup of affected tables

From a writable working dir (not the repo root — these files are large):

```powershell
$stamp = Get-Date -Format "yyyyMMdd_HHmm"
pg_dump $env:DATABASE_URL `
  -t financials -t company_financials -t endpoint_cache `
  --file="backup_pre_unify_$stamp.sql"
```

Expected: a file of ~200-500 MB depending on `endpoint_cache` payload size.
Confirm the file size is non-zero and note the path. Do not proceed if
`pg_dump` exits non-zero.

### 0.6 Row counts before

```sql
SELECT 'financials' AS t, COUNT(*) FROM financials
UNION ALL SELECT 'company_financials', COUNT(*) FROM company_financials
UNION ALL SELECT 'endpoint_cache', COUNT(*) FROM endpoint_cache;
```

Record these numbers in a scratch file. You'll compare against them after
each step.

---

## 1. Apply migration 013 — cache_version column on endpoint_cache (2 min)

This migration was merged to main via PR #51/#53 but may not have been applied
to prod. It is idempotent (`IF NOT EXISTS`), safe to run either way.

### 1.1 Run

```powershell
psql $env:DATABASE_URL -f data_pipeline/migrations/013_add_cache_version_to_endpoint_cache.sql
```

Expected output (both branches are fine):

```
ALTER TABLE
CREATE INDEX
```

or, if it had already been applied:

```
NOTICE:  column "cache_version" of relation "endpoint_cache" already exists, skipping
ALTER TABLE
```

### 1.2 Verify

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'endpoint_cache'
  AND column_name = 'cache_version';
```

Expected: one row, `cache_version | text` (or `character varying`).

### 1.3 Rollback (if needed)

```sql
ALTER TABLE endpoint_cache DROP COLUMN IF EXISTS cache_version;
```

Only do this if verification fails AND you have not proceeded to step 2.

---

## 2. Apply migration 014 — currency column on company_financials (2 min)

### 2.1 Run

```powershell
psql $env:DATABASE_URL -f data_pipeline/migrations/014_add_currency_to_company_financials.sql
```

Expected: `ALTER TABLE` (and any index/constraint DDL the migration contains).

### 2.2 Verify

```sql
SELECT column_name, data_type
FROM information_schema.columns
WHERE table_name = 'company_financials'
  AND column_name = 'currency';
```

Expected: one row, `currency | text` (or `character varying`).

### 2.3 Rollback

```sql
ALTER TABLE company_financials DROP COLUMN IF EXISTS currency;
```

---

## 3. Dry-run transform on one ticker (3 min)

Pick BPCL as canary — it is in the nightly canary set and has a known CFO
regression.

```powershell
python scripts/transform_financials_to_company_financials.py --ticker BPCL --dry-run
```

Expected output: a counter block like

```
source_rows_scanned=N
target_rows_would_write=~3N   (one each for income / balance_sheet / cashflow)
skipped_empty_income=...
skipped_empty_balance=...
skipped_empty_cashflow=...
errors=0
```

Green-light rules:
- `source_rows_scanned > 0`
- `target_rows_would_write` is roughly 3x source (minus skipped-empty)
- `errors == 0`

If any of the above fail, STOP. Do not run step 4.

---

## 4. Live-run transform on one ticker (3 min)

```powershell
python scripts/transform_financials_to_company_financials.py --ticker BPCL
```

Expected: same counters as the dry-run, plus a `wrote=N` line matching
`target_rows_would_write` from step 3.

### 4.1 DB-level verification

```sql
SELECT statement_type, COUNT(*)
FROM company_financials
WHERE ticker_nse = 'BPCL.NS'
GROUP BY statement_type
ORDER BY statement_type;
```

Expected: three rows — `balance_sheet`, `cashflow`, `income` — each with a
positive count (should roughly equal the per-period count in `financials`).

### 4.2 API-level verification

```powershell
curl "https://api.yieldiq.in/api/v1/analysis/BPCL/financials" | ConvertFrom-Json | Select -ExpandProperty rows | Select -First 1
```

Expected: the latest row has a non-null `cfo` field. (Before this fix, CFO was
null because the reader was hitting `company_financials` where cashflow rows
did not exist.)

If `cfo` is still null, STOP. Do not run step 5. Likely causes:
- transform did not actually write cashflow rows — check step 4 counter output
- reader is still pinned to an older cache — bump `CACHE_VERSION` or clear
  the specific endpoint_cache row

---

## 5. Dry-run full transform (5 min)

```powershell
python scripts/transform_financials_to_company_financials.py --dry-run
```

Expected: counters in the ballpark of

```
source_rows_scanned=~67000
target_rows_would_write=~180000-200000
skipped_empty_income=small (few %)
skipped_empty_balance=small
skipped_empty_cashflow=larger (historically the most-missing sheet)
errors=0
```

Green-light:
- `errors == 0`
- `target_rows_would_write` between 150k and 220k
- `skipped_empty_*` sum to < 20% of source rows

If `errors > 0` or the skip ratio is >50%, STOP and investigate. Do not run
step 6.

---

## 6. Live-run full transform (10-20 min)

```powershell
python scripts/transform_financials_to_company_financials.py
```

Expected runtime: 10-20 min on the Neon free-to-scale tier. The script
upserts in batches; progress is logged per batch.

### 6.1 Mid-run sampling (optional, from a second terminal)

```sql
SELECT COUNT(*) FROM company_financials;
```

Run every 1-2 min. The count should climb monotonically until the script
finishes.

### 6.2 If the script crashes partway

The upsert is idempotent (`ON CONFLICT ... DO UPDATE`). Re-run the same
command. Do not truncate `company_financials` between attempts.

### 6.3 Post-run row counts

```sql
SELECT 'financials' AS t, COUNT(*) FROM financials
UNION ALL SELECT 'company_financials', COUNT(*) FROM company_financials;
```

Compare against step 0.6. `company_financials` should have grown by roughly
the `target_rows_would_write` number from step 5 (minus any rows that
already existed and were updated in place).

---

## 7. Canary verification (5 min)

```powershell
python scripts/verify_canary_recovery.py
```

Expected output: `20/20 pass, 0 regressions`. Historically 5 tickers were
failing the CFO-populated defensive check; they should now pass.

Acceptable outcomes:
- 20/20 pass, 0 regressions — proceed
- 20/20 pass, previously-failing tickers now pass — proceed

STOP conditions:
- Any ticker fails `cfo_populated`
- Any ticker fails `score_in_range`
- Any ticker regressed (was passing, now failing)

If any STOP condition triggers, do not merge PR #52 (cyclical FCF). Capture
the failing ticker list and investigate before proceeding to step 8.

---

## 8. Clear stale endpoint_cache rows (1 min, optional)

Every existing endpoint_cache row is tagged `cache_version = '0'` after
migration 013 and auto-invalidates on read. They will expire via TTL on their
own, but you can reclaim disk now:

```sql
DELETE FROM endpoint_cache WHERE cache_version = '0';
```

Expected: `DELETE <n>` where n is on the order of the original
`endpoint_cache` row count from step 0.6. Reclaims a few hundred MB.

This is safe: readers will repopulate with correctly-versioned rows on the
next request.

---

## 9. Monitor (ongoing, 1 hour + tomorrow morning)

- Tail Railway backend logs for the next hour. Look for unexpected
  `UndefinedColumn`, `KeyError`, or 5xx spikes.
- Check nightly canary results tomorrow morning (GitHub Actions summary).
  Expected: 20/20 pass.
- Spot-check 2-3 ticker analysis pages in the browser. Confirm the
  financials table renders with non-null CFO for recent periods.

---

## Appendix A: Rollback

Use this if any checkpoint fails catastrophically or if the nightly canary
regresses in the 24 hours after deploy.

### A.1 Restore affected tables from the step-0 backup

```powershell
psql $env:DATABASE_URL -f backup_pre_unify_<stamp>.sql
```

Note: `pg_restore` semantics — `pg_dump` with `--file` produces plain SQL,
which `psql` replays. The backup uses `TRUNCATE ... CASCADE` before reloading,
so it fully replaces the current state of the three tables.

### A.2 Revert code

```powershell
git revert <merge-commit-of-PR-55>
git revert <merge-commit-of-PR-53>   # only if PR #53 is also suspect
git push origin main
```

Wait for Railway to redeploy (~3-5 min). Confirm `/health` is 200.

### A.3 Force cache invalidation post-rollback

Bump `CACHE_VERSION` by 1 in the backend env (Railway dashboard → variables).
This guarantees all readers see fresh data after rollback, regardless of
cache_version column state.

### A.4 Announce

Drop a short note in the project log: what was rolled back, when, and the
current prod state.

---

## Appendix B: Red flags

Stop and ask for help if you see any of these, rather than pushing through:

- `UndefinedColumn: column "cache_version" does not exist` — migration 013
  did not land. Re-run step 1 before proceeding.
- `UndefinedColumn: column "currency" does not exist` — migration 014 did
  not land. Re-run step 2.
- `duplicate key value violates unique constraint` errors that do NOT
  decrease across batches — upsert conflict target is wrong. Stop the
  transform; do not keep retrying.
- Script reports `wrote=3` for a ticker but the DB shows 0 rows for that
  ticker in `company_financials` — transaction rollback silently swallowed.
  Check for WARNING lines in the transform output.
- A canary ticker that was passing yesterday now fails CFO or score — the
  transform corrupted data. Go to Appendix A.
- `endpoint_cache` row count after step 8 DELETE is larger than before —
  you deleted in the wrong direction (should only remove rows where
  `cache_version = '0'`).
- Any `ERROR` line in Railway backend logs referencing `company_financials`
  during the hour after deploy.

---

End of runbook.
