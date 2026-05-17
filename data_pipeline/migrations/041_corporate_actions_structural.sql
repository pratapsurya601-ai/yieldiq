-- 041_corporate_actions_structural.sql
-- 2026-05-17 — L3 Phase-A DDL for structural-break-aware CAGR overlay.
--
-- Extends the existing `corporate_actions` table (created in earlier
-- migrations and extended by 025_corporate_actions_quality_rank.sql)
-- with the columns needed to record STRUCTURAL events — mergers,
-- demergers, schemes of arrangement, material acquisitions — whose
-- presence inside a CAGR window must short-circuit the CAGR base.
--
-- Why: HDFCBANK reports a phantom ~32.5% revenue CAGR because the
-- HDFC Ltd reverse merger (2023-07-01) doubled reported interest-earned
-- overnight. Naive CAGR across a structural break is meaningless.
-- See docs/design/corporate-actions-overlay.md for the full plan.
--
-- This migration is Phase A — DDL ONLY:
--   * Add three optional columns: multiplier, source_url, source_doc, notes.
--   * Add a CHECK constraint that requires source_url + source_doc on
--     rows whose action_type is one of the structural set. Existing
--     dividend/split/bonus rows are unaffected (their action_type is
--     not in the structural set).
--   * No seed data. No service wire-in. No CACHE_VERSION bump.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, constraint added via
-- DO-block guard so re-application is safe.
--
-- Dual-path convention (see 025_corporate_actions_quality_rank.sql):
-- this file is mirrored at db/migrations/012_corporate_actions_structural.sql.
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/041_corporate_actions_structural.sql

ALTER TABLE corporate_actions
    ADD COLUMN IF NOT EXISTS multiplier NUMERIC(12,6);

ALTER TABLE corporate_actions
    ADD COLUMN IF NOT EXISTS source_url TEXT;

ALTER TABLE corporate_actions
    ADD COLUMN IF NOT EXISTS source_doc TEXT;

ALTER TABLE corporate_actions
    ADD COLUMN IF NOT EXISTS notes TEXT;

-- Structural-row sourcing constraint. Scoped via NOT IN clause so
-- existing dividend / split / bonus rows (which have no source_url
-- today) remain valid. Added through a DO-block so re-running the
-- migration does not raise "constraint already exists".
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_structural_sourced'
          AND conrelid = 'corporate_actions'::regclass
    ) THEN
        ALTER TABLE corporate_actions
            ADD CONSTRAINT ck_structural_sourced
            CHECK (
                action_type NOT IN (
                    'MERGER',
                    'REVERSE_MERGER',
                    'DEMERGER',
                    'SCHEME_OF_ARRANGEMENT',
                    'MATERIAL_ACQUISITION'
                )
                OR (source_url IS NOT NULL AND source_doc IS NOT NULL)
            );
    END IF;
END
$$;

COMMENT ON COLUMN corporate_actions.multiplier IS
    'Structural-event impact multiplier (e.g. ~2.0 for HDFC reverse merger). NULL for non-structural rows.';
COMMENT ON COLUMN corporate_actions.source_url IS
    'Direct link to NSE / BSE / SEBI filing. Required for structural action_types.';
COMMENT ON COLUMN corporate_actions.source_doc IS
    'Short citation (e.g. "NSE Circular NSE/CML/2023/29"). Required for structural action_types.';
COMMENT ON COLUMN corporate_actions.notes IS
    'Free-form ops notes about the structural event.';
