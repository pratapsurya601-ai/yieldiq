-- 076_rollback_fair_value_history_quarantine_columns.sql
-- PROPOSAL — pairs with 076_fair_value_history_quarantine_columns.sql.
-- Drops the at-rest quarantine columns + supporting index/constraint.
--
-- DESTRUCTIVE on the data side: running this rollback loses the
-- quarantine marks. If you intend to reapply 076 immediately, the
-- pre-epoch fill is idempotent and will repopulate, but any
-- step_unverified marks applied via the gate runner will need that
-- runner re-invoked.

BEGIN;

DROP INDEX IF EXISTS ix_fv_history_served;

ALTER TABLE fair_value_history
  DROP CONSTRAINT IF EXISTS chk_fv_history_quarantine_reason;

ALTER TABLE fair_value_history
  DROP COLUMN IF EXISTS quarantine_source,
  DROP COLUMN IF EXISTS quarantined_at,
  DROP COLUMN IF EXISTS quarantine_reason;

COMMIT;
