-- 001_add_currency_column.sql
--
-- Adds a `currency` column to the `financials` table so ingestion can
-- tag USD-denominated XBRL filings (IT services + some pharma file
-- consolidated financials in USD) and the analysis layer can convert
-- back to INR on read.
--
-- Default is 'INR' so every existing row keeps its semantics and the
-- NOT NULL constraint can be applied in a single statement.
--
-- Idempotent: uses IF NOT EXISTS / ON CONFLICT guards where possible
-- so a re-run will not error on a partially applied migration.
--
-- Run against: Aiven Postgres (yieldiq Financials DB).
-- Apply with: `psql "$AIVEN_DSN" -f 001_add_currency_column.sql`

BEGIN;

-- 1. Add the column with a default so the back-fill is implicit for
--    every existing row. Postgres 11+ makes this a metadata-only op.
ALTER TABLE financials
    ADD COLUMN IF NOT EXISTS currency VARCHAR(3) NOT NULL DEFAULT 'INR';

-- 2. Re-tag rows for the 19 known USD reporters. Tickers match the
--    `USD_REPORTERS` set in backend/services/local_data_service.py.
--    Note: the `financials.ticker` column stores the clean symbol
--    (no `.NS` suffix), so we strip it here.
UPDATE financials
SET currency = 'USD'
WHERE ticker IN (
    'INFY', 'WIPRO', 'HCLTECH', 'TECHM', 'MPHASIS',
    'HEXAWARE', 'LTIM', 'LTIMINDTR', 'PERSISTENT',
    'COFORGE', 'KPITTECH', 'TATAELXSI', 'CYIENT',
    'ZENSAR', 'MASTEK', 'NIIT', 'OFSS',
    'DIVISLAB', 'LAURUSLABS'
);

-- 3. Optional index for analytics that filter by currency.
CREATE INDEX IF NOT EXISTS ix_financials_currency
    ON financials (currency);

COMMIT;
