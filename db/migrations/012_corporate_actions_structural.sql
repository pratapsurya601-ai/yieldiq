-- 012_corporate_actions_structural.sql
-- 2026-05-17 — mirror of data_pipeline/migrations/041_corporate_actions_structural.sql.
--
-- The repo maintains migrations in two parallel directories:
--   * data_pipeline/migrations/   (legacy)
--   * db/migrations/              (newer, NSE-first pipeline)
-- Both are kept in sync. Idempotent guards make re-application safe.
--
-- See the canonical file or docs/design/corporate-actions-overlay.md
-- for the rationale. L3 Phase-A is DDL only: no seed data, no service
-- wire-in, no CACHE_VERSION bump.

ALTER TABLE corporate_actions
    ADD COLUMN IF NOT EXISTS multiplier NUMERIC(12,6);

ALTER TABLE corporate_actions
    ADD COLUMN IF NOT EXISTS source_url TEXT;

ALTER TABLE corporate_actions
    ADD COLUMN IF NOT EXISTS source_doc TEXT;

ALTER TABLE corporate_actions
    ADD COLUMN IF NOT EXISTS notes TEXT;

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
