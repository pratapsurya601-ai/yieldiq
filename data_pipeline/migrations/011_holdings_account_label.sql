-- Migration 011: multi-account portfolio support
-- ═══════════════════════════════════════════════════════════════
-- Bug context: a user uploaded two CSVs from two different demat
-- accounts (e.g. Zerodha + ICICI). Both contained SILVERBEES.
-- The previous unique key (user_email, ticker) caused the second
-- import to overwrite the first, hiding per-account holdings.
--
-- Fix: add account_label so the same ticker can co-exist under
-- different brokers/accounts. Backfills 'default' for existing rows.
--
-- Defensive: every step is IF NOT EXISTS / DO $$ guarded so
-- re-running this is safe.

-- 1. Add the column with a backfill default for existing rows
ALTER TABLE holdings
  ADD COLUMN IF NOT EXISTS account_label TEXT NOT NULL DEFAULT 'default';

-- 2. Add a quantity column so we know how many shares per holding.
--    (Until now we only stored entry_price; quantity sat in 'notes' as
--    "Imported from zerodha (N shares)" -- not queryable.)
ALTER TABLE holdings
  ADD COLUMN IF NOT EXISTS quantity DOUBLE PRECISION;

-- 3. Drop the old single-column unique constraint (if present) and
--    create the new composite one. Wrapped in DO $$ so it runs cleanly
--    even if the old constraint had a different name on different envs.
DO $$
DECLARE
  old_con TEXT;
BEGIN
  SELECT conname INTO old_con
  FROM pg_constraint
  WHERE conrelid = 'holdings'::regclass
    AND contype = 'u'
    AND pg_get_constraintdef(oid) ILIKE 'UNIQUE (user_email, ticker)%';
  IF old_con IS NOT NULL THEN
    EXECUTE format('ALTER TABLE holdings DROP CONSTRAINT %I', old_con);
  END IF;
END $$;

-- 4. Create the new composite unique constraint
DO $$
BEGIN
  IF NOT EXISTS (
    SELECT 1 FROM pg_constraint
    WHERE conrelid = 'holdings'::regclass
      AND conname = 'holdings_user_ticker_account_unique'
  ) THEN
    ALTER TABLE holdings
      ADD CONSTRAINT holdings_user_ticker_account_unique
      UNIQUE (user_email, ticker, account_label);
  END IF;
END $$;

-- 5. Index for the common per-account list query
CREATE INDEX IF NOT EXISTS idx_holdings_user_account
  ON holdings (user_email, account_label);
