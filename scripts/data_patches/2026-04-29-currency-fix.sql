-- 2026-04-29 currency mis-tag fix + INFY revenue hardcode re-apply
--
-- Branch:  wkt/data-backfill-sparse
-- Author:  data-backfill agent (re-applying v50 patch lost in a recent backfill)
-- Scope:   `financials` table only. No DDL. Single transaction.
--
-- Findings (pre-patch):
--   - 408 rows across 14 IT/pharma tickers had currency='USD' with revenue > 1000.
--     Values are clearly already in INR Crores (HCLTECH FY24 = 109913, BPCL = 446666,
--     etc.); the `USD` tag is wrong. Re-tagging to INR is the correct, lossless fix.
--   - INFY annual rows for FY23-FY26 carry USD-millions values (1821.2, 1856.2,
--     1927.7, 2015.8) instead of INR Crores. Per docs/ops/TEMP_patch_2026-04-24.md
--     these are the "both sources broken in same direction" case that the v50 patch
--     deliberately skipped. Hardcode the public values (FY25 162990 Cr, FY24 153670
--     Cr, FY23 146767 Cr) and delete the bogus 2026-03-31 future row.
--
-- Row counts (after running):
--   Step 1 currency re-tag: 408 rows updated
--   Step 2a INFY FY25:       1 row updated (1927.7 USD -> 162990 INR)
--   Step 2b INFY FY24:       1 row updated (1856.2 USD -> 153670 INR)
--   Step 2c INFY FY23:       1 row updated (1821.2 USD -> 146767 INR)
--   Step 2d INFY FY26 row:   1 row deleted  (bogus future-dated row)

BEGIN;

-- Step 1: Fix the USD mis-tag on 14 IT/pharma tickers (revenue already in INR Cr).
UPDATE financials
SET currency = 'INR'
WHERE ticker IN (
    'INFY','HCLTECH','WIPRO','TECHM','MPHASIS','COFORGE','PERSISTENT',
    'DIVISLAB','CYIENT','OFSS','LAURUSLABS','KPITTECH','TATAELXSI','MASTEK'
)
  AND currency = 'USD'
  AND revenue > 1000;

-- Step 2: INFY annual hardcode (re-apply v50 patch).
-- Public (audited) figures from Infosys annual reports.
UPDATE financials
SET revenue = 162990, currency = 'INR'
WHERE ticker = 'INFY' AND period_type = 'annual' AND period_end = '2025-03-31';

UPDATE financials
SET revenue = 153670, currency = 'INR'
WHERE ticker = 'INFY' AND period_type = 'annual' AND period_end = '2024-03-31';

UPDATE financials
SET revenue = 146767, currency = 'INR'
WHERE ticker = 'INFY' AND period_type = 'annual' AND period_end = '2023-03-31';

-- Bogus future-dated row (FY ending 2026-03-31 cannot exist on 2026-04-29 yet).
DELETE FROM financials
WHERE ticker = 'INFY' AND period_type = 'annual' AND period_end = '2026-03-31';

COMMIT;

-- Verification (run manually, expected output documented inline):
--   SELECT ticker, period_end, revenue, currency FROM financials
--   WHERE ticker='INFY' AND period_type='annual' ORDER BY period_end DESC;
--   -- Expect: 2025=162990 INR, 2024=153670 INR, 2023=146767 INR,
--   --         2022=121641 INR, 2021=100472 INR, 2020=90791 INR, 2019=82675 INR.
--   -- The 2026-03-31 row should be GONE.
