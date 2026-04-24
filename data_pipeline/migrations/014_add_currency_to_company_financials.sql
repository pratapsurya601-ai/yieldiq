-- 014_add_currency_to_company_financials.sql
--
-- Adds a `currency` column to `company_financials`, matching the
-- sibling `financials` table (which has `currency VARCHAR(3) NOT NULL
-- DEFAULT 'INR'`). USD-reporting tickers (HCLTECH, INFY, WIT, ...)
-- file values in USD millions rather than INR crores; without an
-- explicit currency tag on each row, the downstream FV pipeline
-- cannot tell the two apart and silently double-converts. This is
-- the regression from commit b31a7e9 where HCLTECH FV displayed as
-- Rs.6,073 instead of Rs.1,500. We are about to migrate rows from
-- `financials` into `company_financials`; preserving the currency
-- column on both sides is what prevents that bug from re-appearing.
--
-- No index: currency is almost never a filter predicate (matches
-- the `financials` table convention).
--
-- The DEFAULT 'INR' means every existing row is tagged INR on
-- migration, which is correct for the overwhelming majority of
-- NSE/BSE filings. The transform script that backfills from
-- `financials` is responsible for overwriting 'INR' -> 'USD' on
-- the small set of USD-reporting tickers.
--
-- Idempotent: IF NOT EXISTS guard allows safe re-run.
--
-- Run against: Aiven Postgres (yieldiq Financials DB).
-- Apply with: `psql "$AIVEN_DSN" -f 014_add_currency_to_company_financials.sql`

BEGIN;

ALTER TABLE company_financials
    ADD COLUMN IF NOT EXISTS currency VARCHAR(3) NOT NULL DEFAULT 'INR';

COMMIT;
