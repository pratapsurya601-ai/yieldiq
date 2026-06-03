-- 202606031123_fair_value_history_superset.sql
-- =================================================================
-- Phase 1 — Agent A v3 superset schema migration.
--
-- SCHEMA ONLY. NO DATA FILL on fair_value / mos_pct / wacc /
-- confidence. The 40,139-row pre-epoch quarantine fill is a SEPARATE
-- migration sequenced AFTER this one (see
-- redesign/followups/fv-history-at-rest-disposition.md §3
-- preconditions; PR body of this migration carries the precondition
-- verbatim).
--
-- Adds five nullable / defaulted columns to fair_value_history so:
--   (a) the locked Agent B Pydantic contract
--       (backend/models/fair_value_history.py: Provenance,
--       manifest_id) is satisfied at the DB layer, and
--   (b) the at-rest quarantine-marker columns
--       (quarantine_reason, quarantined_at, quarantine_source)
--       exist for the later data-fill migration to populate via
--       backend.services.fair_value_history_gate.filter_history_rows.
--
-- Also folds in two open-window escalations from the disposition §6:
--   * Drops the two duplicate single-column indexes
--     (ix_fair_value_history_date, ix_fair_value_history_ticker —
--     duplicates of ix_fv_history_date / ix_fv_history_ticker).
--   * Adds a SQL-level DEFAULT NOW() to updated_at so raw INSERTs
--     no longer leave it NULL.
--
-- Canary impact: nullable column adds + partial index + duplicate
-- index drops + a DEFAULT clause. NO UPDATE statements run against
-- existing engine-output columns; fair_value / mos_pct cannot
-- change by construction.
-- =================================================================

BEGIN;

-- ---- Columns -----------------------------------------------------

ALTER TABLE fair_value_history
    ADD COLUMN IF NOT EXISTS provenance         TEXT        NOT NULL DEFAULT 'live',
    ADD COLUMN IF NOT EXISTS manifest_id        TEXT        NULL,
    ADD COLUMN IF NOT EXISTS quarantine_reason  TEXT        NULL,
    ADD COLUMN IF NOT EXISTS quarantined_at     TIMESTAMPTZ NULL,
    ADD COLUMN IF NOT EXISTS quarantine_source  TEXT        NULL;

-- Provenance check — Literal["snapshot", "golden", "live"] from
-- backend/models/fair_value_history.py.
ALTER TABLE fair_value_history
    DROP CONSTRAINT IF EXISTS chk_fv_history_provenance;
ALTER TABLE fair_value_history
    ADD CONSTRAINT chk_fv_history_provenance
    CHECK (provenance IN ('snapshot', 'golden', 'live'));

-- Quarantine-reason controlled vocabulary. NULL = the row is
-- servable. Non-null values come from the gate module's R1/R2/R3
-- rules + the pre-epoch boundary.
ALTER TABLE fair_value_history
    DROP CONSTRAINT IF EXISTS chk_fv_history_quarantine_reason;
ALTER TABLE fair_value_history
    ADD CONSTRAINT chk_fv_history_quarantine_reason
    CHECK (
        quarantine_reason IS NULL
        OR quarantine_reason IN (
            'pre_manifest_epoch',
            'step_unverified',
            'mos_out_of_band',
            'provenance_missing'
        )
    );

-- ---- Partial index on the served slice ---------------------------
-- Serve-time query is "WHERE ticker = ? AND quarantine_reason IS NULL
-- ORDER BY date" — a partial index keeps the served set compact even
-- as the quarantined tail grows.
CREATE INDEX IF NOT EXISTS ix_fv_history_served
    ON fair_value_history (ticker, date)
    WHERE quarantine_reason IS NULL;

-- ---- Folded escalations ------------------------------------------
-- §6.1: duplicate single-column indexes. IF EXISTS keeps this safe
-- on environments where the duplicates were already dropped (or
-- never existed). The remaining ix_fv_history_date /
-- ix_fv_history_ticker pair stays.
DROP INDEX IF EXISTS ix_fair_value_history_date;
DROP INDEX IF EXISTS ix_fair_value_history_ticker;

-- §6.4: updated_at SQL-level default. Without this, a raw INSERT
-- (including the upcoming data-fill migration if it ever needs to
-- INSERT rather than UPDATE) leaves updated_at NULL.
ALTER TABLE fair_value_history
    ALTER COLUMN updated_at SET DEFAULT NOW();

COMMIT;
