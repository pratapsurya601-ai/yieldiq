# scripts/data_patches/

Paper-trail directory for one-off data fixes applied directly to the prod
Neon `yieldiq` database. Files here are NOT imported by any service code;
they exist purely to document what was run, when, and against what scope.

## Discipline

1. Every patch file MUST be self-describing: include a comment block at
   the top stating the date, branch, scope, and exact row counts touched.
2. Every patch SQL MUST run inside a single `BEGIN; ... COMMIT;` block.
3. **Never commit a DATABASE_URL** into any file in this directory. Load
   it programmatically from `E:/Projects/yieldiq_v7/.env.local` line 2.
4. Patches that change values used by `analysis_cache` must note in their
   PR body that the next analysis-changing PR should bump `CACHE_VERSION`.

## 2026-04-29

| file | purpose |
|---|---|
| `2026-04-29-currency-fix.sql` | Re-tag 408 IT/pharma rows USD -> INR; re-apply v50 INFY annual hardcode (FY23/FY24/FY25); delete bogus FY26 future row. |
| `backfill_pe_pb_top100.py` | Hit yfinance for tickers in top-200 by mcap whose latest market_metrics row has NULL pe/pb. Rate-limited 1/sec. Does not fabricate values when yfinance returns None (loss-making companies). |
| `backfill_pe_pb_top100.log.json` | Per-ticker run log (5 entries from 2026-04-29). |
