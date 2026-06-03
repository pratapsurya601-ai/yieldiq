-- 202606031123_fair_value_history_superset_rollback.sql
-- Rollback for 202606031123_fair_value_history_superset.sql.
--
-- Drops the partial served-slice index, the two CHECK constraints,
-- the five new columns, and the updated_at default. Does NOT
-- re-create the dropped duplicate single-column indexes
-- (ix_fair_value_history_date / ix_fair_value_history_ticker) —
-- they were duplicates of ix_fv_history_date / ix_fv_history_ticker
-- and re-introducing them would re-introduce the write
-- amplification the forward migration removed.

BEGIN;

DROP INDEX IF EXISTS ix_fv_history_served;

ALTER TABLE fair_value_history
    DROP CONSTRAINT IF EXISTS chk_fv_history_quarantine_reason;
ALTER TABLE fair_value_history
    DROP CONSTRAINT IF EXISTS chk_fv_history_provenance;

ALTER TABLE fair_value_history
    DROP COLUMN IF EXISTS quarantine_source,
    DROP COLUMN IF EXISTS quarantined_at,
    DROP COLUMN IF EXISTS quarantine_reason,
    DROP COLUMN IF EXISTS manifest_id,
    DROP COLUMN IF EXISTS provenance;

ALTER TABLE fair_value_history
    ALTER COLUMN updated_at DROP DEFAULT;

COMMIT;
