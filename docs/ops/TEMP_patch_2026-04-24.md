# TEMP Patch 2026-04-24: XBRL revenue correction from company_financials

Temporary direct-SQL patch applied to prod Neon on 2026-04-24. This file is
the paper trail. Delete this file when the underlying XBRL parser bug is
fixed and the full backfill is re-run (see Section 6).

---

## 1. Summary

First paying YieldIQ subscriber signed up today at Rs. 799/yr. Browser
verification hours later showed blue-chip defensives (HCLTECH, NESTLEIND,
ASIANPAINT, HINDUNILVR, POWERGRID) scoring 22-46 on the 0-100 scale because
the DCF was being fed revenue values 3.5x-9.1x too low. Root cause is a bug
in the XBRL parser that emits OneD (single-quarter) values instead of FourD
(year-to-date full-year) values. This patch copies correct revenue, pat, and
cfo values from `company_financials` (yfinance-sourced, unaffected by the
XBRL bug) into `financials` for the ~1,362 tickers tagged
`data_source='NSE_XBRL'`.

## 2. Exact SQL executed

Run inside a single transaction. No DDL, no DELETEs.

```sql
BEGIN;

-- Fix revenue (2,710 rows across 1,362 tickers)
UPDATE financials f
SET revenue = cf.revenue
FROM company_financials cf
WHERE f.ticker = cf.ticker_nse
  AND f.period_end = cf.period_end_date
  AND f.period_type = cf.period_type
  AND cf.statement_type = 'income'
  AND cf.revenue IS NOT NULL AND cf.revenue > 0
  AND f.data_source LIKE 'NSE_XBRL%'
  AND cf.revenue > COALESCE(f.revenue, 0) * 2;

-- Fix pat/net_income (2,850 rows)
UPDATE financials f
SET pat = cf.net_income
FROM company_financials cf
WHERE f.ticker = cf.ticker_nse
  AND f.period_end = cf.period_end_date
  AND f.period_type = cf.period_type
  AND cf.statement_type = 'income'
  AND cf.net_income IS NOT NULL AND cf.net_income > 0
  AND f.data_source LIKE 'NSE_XBRL%'
  AND cf.net_income > COALESCE(f.pat, 0) * 2;

-- Fix cfo (213 rows)
UPDATE financials f
SET cfo = cf.operating_cf
FROM company_financials cf
WHERE f.ticker = cf.ticker_nse
  AND f.period_end = cf.period_end_date
  AND f.period_type = cf.period_type
  AND cf.statement_type = 'cashflow'
  AND cf.operating_cf IS NOT NULL AND cf.operating_cf > 0
  AND f.data_source LIKE 'NSE_XBRL%'
  AND cf.operating_cf > COALESCE(f.cfo, 0) * 2;

COMMIT;
```

The `cf.X > COALESCE(f.X, 0) * 2` filter deliberately excludes rows where
both sources are broken in the same direction (e.g. INFY). Those rows stay
untouched and need a separate fix.

## 3. Scope / blast radius

- Tickers affected: 1,362 (all with `data_source LIKE 'NSE_XBRL%'`).
- Row updates: ~5,770 total.
  - revenue: 2,710 rows
  - pat: 2,850 rows
  - cfo: 213 rows
- Columns touched: 3 (`revenue`, `pat`, `cfo`) on the `financials` table.
- No schema changes. No deletes. No cache invalidation inside the patch
  itself (see Section 7 for cache handling).

## 4. Verification

Run immediately after `COMMIT`.

```sql
-- HCLTECH FY24 revenue should be ~109,913 (was 12,077).
SELECT ticker, period_end, period_type, revenue
FROM financials
WHERE ticker = 'HCLTECH' AND period_type = 'annual'
ORDER BY period_end DESC LIMIT 3;

-- BPCL FY24 revenue should be ~446,666 (was 132,087).
SELECT ticker, period_end, period_type, revenue
FROM financials
WHERE ticker = 'BPCL' AND period_type = 'annual'
ORDER BY period_end DESC LIMIT 3;
```

Then run the canary regression check:

```powershell
python scripts/verify_canary_recovery.py
```

Expected: regression count drops from the current 4-5 to 0-1.

## 5. Why this patch is TEMPORARY

This patch treats the symptom, not the cause. The cause is a bug in
`data_pipeline/sources/nse_xbrl_fundamentals.py` that picks OneD
(single-quarter) contexts when it should pick FourD (year-to-date) contexts.

Until that parser bug is fixed, any future XBRL backfill run will
re-introduce the broken values, and **this patch will be silently undone**
because the patch's filter (`cf.revenue > f.revenue * 2`) will no longer
hold once `f.revenue` is overwritten with the broken OneD value again.

Do not run `scripts/backfill_from_cache.py` with NSE_XBRL as source
against prod until the parser fix has shipped.

## 6. Removal / permanence plan

When the parser fix ships:

1. Investigate whether re-running the backfill writes correct values
   (expected yes, post-fix).
2. Run a single-ticker backfill dry-run for HCLTECH; verify revenue matches
   the value this patch wrote.
3. Run the full backfill against Neon via the dual-write in
   `scripts/backfill_from_cache.py`.
4. Re-run the Section 4 verification queries. HCLTECH and BPCL FY24 revenue
   must still match.
5. Delete this file (`docs/ops/TEMP_patch_2026-04-24.md`).
6. Commit message must note that the temporary patch is now
   permanent-via-fixed-parser, and reference the parser-fix PR.

## 7. Rollback plan

If this patch introduces a problem (unexpected score movement, broken
validators, etc.):

- A pre-patch `pg_dump` backup was taken:
  `backup_pre_unify_YYYYMMDD_HHMM.sql`.
- Full restore:
  ```bash
  psql "$NEON_URL" -c "TRUNCATE financials;"
  psql "$NEON_URL" -f backup_pre_unify_*.sql
  ```
- Surgical restore: use the backup as the source and restore only the
  affected rows (`data_source LIKE 'NSE_XBRL%'`).
- After any rollback, bump `CACHE_VERSION` by 1 to flush `analysis_cache`.

## 8. Success criteria

- Next morning's nightly canary reports 0-1 failures (currently 4-5).
- HCLTECH, NESTLEIND, ASIANPAINT, HINDUNILVR scores rise from the 22-46
  range into the 55-75 range.
- BPCL fair value drops from ~716 to ~450 range. Full alignment may require
  Fix B (cyclical-FCF) — see Section 5 of `RUNBOOK_table_unification.md`.

## 9. Open questions / follow-ups

- Why did earlier session memory claim the FourD fix was applied and
  verified? What was actually tested, and on which rows?
- Is other XBRL-sourced data also broken? Check `total_debt`, `cash`, and
  any other column the parser writes on `data_source='NSE_XBRL'` rows.
- Add a data sanity validation layer to prevent this class of bug
  (see `docs/design/DATA_SANITY_VALIDATION.md` — to be written).
