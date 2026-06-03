-- Phase 1 superset migration: ADD nullable columns to the existing
-- fair_value_history table. Preserves existing rows and existing
-- consumers (Alerts at 009_alerts.sql, prism sparkline,
-- backfill_fair_value_history_monthly.py).
--
-- New columns support the /api/valuation-history endpoint
-- annotation logic. Existing rows are tagged provenance='live'
-- because they were written by the production backfill cron and
-- match the spec's "production-faithful only" definition.
--
-- Idempotent: every column add uses IF NOT EXISTS, and the new
-- UNIQUE constraint is added via a DO block guarded by pg_constraint
-- lookup. Safe to re-apply.

BEGIN;

ALTER TABLE fair_value_history
    ADD COLUMN IF NOT EXISTS bear_iv          numeric(14, 4),
    ADD COLUMN IF NOT EXISTS bull_iv          numeric(14, 4),
    ADD COLUMN IF NOT EXISTS scenario_weights jsonb,
    ADD COLUMN IF NOT EXISTS model_version    text,
    ADD COLUMN IF NOT EXISTS provenance       text NOT NULL DEFAULT 'live',
    ADD COLUMN IF NOT EXISTS manifest_id      text,
    ADD COLUMN IF NOT EXISTS written_at       timestamptz NOT NULL DEFAULT now();

-- Tighten provenance to the allowed set after default backfill.
ALTER TABLE fair_value_history
    DROP CONSTRAINT IF EXISTS fair_value_history_provenance_check;
ALTER TABLE fair_value_history
    ADD CONSTRAINT fair_value_history_provenance_check
    CHECK (provenance IN ('snapshot', 'golden', 'live'));

-- New uniqueness for the spec semantics: a 'snapshot' row and a
-- 'live' row for the same (ticker, date) coexist. Keep the original
-- UNIQUE(ticker, date) too — existing consumers expect it, and they
-- only write provenance='live' rows so they never collide with
-- backfilled snapshot/golden rows.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1 FROM pg_constraint
        WHERE conname = 'fair_value_history_ticker_date_provenance_key'
    ) THEN
        ALTER TABLE fair_value_history
            ADD CONSTRAINT fair_value_history_ticker_date_provenance_key
            UNIQUE (ticker, date, provenance);
    END IF;
END $$;

CREATE INDEX IF NOT EXISTS idx_fvh_manifest_id
    ON fair_value_history (manifest_id)
    WHERE manifest_id IS NOT NULL;

COMMENT ON COLUMN fair_value_history.provenance IS
    'snapshot = scripts/snapshots/*.json. golden = scripts/dcf_golden.json. '
    'live = written by the recompute hook OR pre-existing monthly backfill.';
COMMENT ON COLUMN fair_value_history.model_version IS
    'Engine version slug at compute time. NULL for rows written before this column existed.';
COMMENT ON COLUMN fair_value_history.scenario_weights IS
    'Triplet {bear, base, bull}. NULL for rows from the monthly backfill which did not capture them.';

COMMIT;
