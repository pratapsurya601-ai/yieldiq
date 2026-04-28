BEGIN;

-- Migration 020: shares_outstanding unit standardization.
--
-- Background: `financials.shares_outstanding` is documented as "Lakhs"
-- (data_pipeline/models.py:107) but a non-trivial fraction of rows are
-- stored in crore (or another unit) because XBRL/BSE backfill paths
-- write the source-filing's value without re-scaling.
--
-- Symptom: any consumer that does `price * shares_outstanding * 1e5`
-- produces a 100×-off answer for the wrong-unit half of the universe.
-- See docs/shares_outstanding_units_design.md.
--
-- This migration is the *schema half* of the fix. The data backfill is
-- a separate ops step (scripts/normalize_shares_outstanding.py).
--
-- Strategy: add a new `shares_outstanding_raw` column (canonical raw
-- share count, e.g. 3.62e9 for TCS). Leave the old lakh-typed column
-- in place during the transition so running services do not break.
-- A later PR drops the old column once consumers have cut over.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS.

ALTER TABLE financials
    ADD COLUMN IF NOT EXISTS shares_outstanding_raw DOUBLE PRECISION;

COMMENT ON COLUMN financials.shares_outstanding_raw IS
    'Canonical raw share count (e.g. 3.62e9 for TCS). Populated by '
    'scripts/normalize_shares_outstanding.py. The legacy '
    'shares_outstanding column remains in place (typed Lakhs but '
    'mixed-unit in practice) until consumers cut over.';

-- Index for the diagnose_pe_gap-style queries that filter on
-- "shares present and positive". Predicate index keeps it small.
CREATE INDEX IF NOT EXISTS ix_financials_shares_raw_present
    ON financials (ticker, period_end)
    WHERE shares_outstanding_raw IS NOT NULL
      AND shares_outstanding_raw > 0;

-- Sanity-check constraint: a real NSE-listed company has at least
-- ~10 lakh shares (1_000_000 raw). Anything below that is almost
-- certainly a unit error. We use a CHECK NOT VALID so the constraint
-- applies only to new writes — backfill rows that legitimately fail
-- the check (data error, not unit error) can be fixed in a follow-up
-- without blocking this migration.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'ck_financials_shares_raw_min'
    ) THEN
        ALTER TABLE financials
            ADD CONSTRAINT ck_financials_shares_raw_min
            CHECK (shares_outstanding_raw IS NULL
                   OR shares_outstanding_raw >= 1000000)
            NOT VALID;
    END IF;
END $$;

COMMIT;
