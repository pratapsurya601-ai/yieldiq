-- 076_fair_value_history_quarantine_columns.sql
-- PROPOSAL — do not apply directly. Belongs alongside (or folded into)
-- the Phase 1 Agent A v3 superset migration. See
-- redesign/followups/fv-history-at-rest-disposition.md.
--
-- Adds the at-rest quarantine marker columns to fair_value_history and
-- fills the pre-manifest-epoch slice. Post-epoch step_unverified
-- marking is performed by a one-shot Python runner that calls the
-- gate module (single source of truth), NOT by this SQL.

BEGIN;

-- ---------------------------------------------------------------
-- Column additions
-- ---------------------------------------------------------------
ALTER TABLE fair_value_history
  ADD COLUMN IF NOT EXISTS quarantine_reason  TEXT        NULL,
  ADD COLUMN IF NOT EXISTS quarantined_at     TIMESTAMPTZ NULL,
  ADD COLUMN IF NOT EXISTS quarantine_source  TEXT        NULL;

-- Controlled vocabulary. Not an ENUM type so future additions don't
-- need a type migration; CHECK gives the same safety with less
-- operational cost.
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

-- ---------------------------------------------------------------
-- Served-slice partial index
--
-- Routers and services that serve user-facing data run
--   WHERE ticker = ? AND quarantine_reason IS NULL ORDER BY date
-- A partial index keeps that scan compact even as the quarantined
-- tail grows.
-- ---------------------------------------------------------------
CREATE INDEX IF NOT EXISTS ix_fv_history_served
  ON fair_value_history (ticker, date)
  WHERE quarantine_reason IS NULL;

-- ---------------------------------------------------------------
-- Data-fill: pre-manifest-epoch slice
--
-- Idempotent: the WHERE guard ensures re-runs are no-ops. The count
-- this UPDATE affects on its first run MUST equal 40139 per the
-- diagnosis (see fv-history-at-rest-disposition.md §1.2). The
-- accompanying test asserts this.
-- ---------------------------------------------------------------
UPDATE fair_value_history
SET quarantine_reason = 'pre_manifest_epoch',
    quarantined_at    = NOW(),
    quarantine_source = 'epoch_boundary_init_2026_06_03'
WHERE date < DATE '2026-05-22'
  AND quarantine_reason IS NULL;

COMMIT;

-- ---------------------------------------------------------------
-- Post-step: NOT IN THIS MIGRATION.
--
-- The post-epoch step_unverified and mos_out_of_band marks are
-- applied by scripts/quarantine_fv_history.py (proposed, separate
-- PR) which imports fair_value_history_gate.filter_history_rows so
-- the at-rest marking logic is byte-for-byte the same as the
-- serve-time gate. Keeping that logic in Python (not SQL) avoids
-- duplicating the manifest-window matching rules in two places.
-- ---------------------------------------------------------------
