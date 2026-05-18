-- 045_cron_heartbeats.sql
-- 2026-05-18 — Cron dead-man monitoring.
--
-- Adds the `cron_heartbeats` table that records the last successful run
-- of each scheduled workflow. Used by the `cron-deadman-checker.yml`
-- workflow (runs every 30 min) to detect silent cron drop-outs:
-- GitHub Actions cron is notoriously unreliable under load, and on
-- 2026-05-18 we discovered `cron-market-live-quotes` was firing only
-- ~1 in 37 expected slots during market hours with no alert.
--
-- This migration is **pure schema** — no application behaviour change,
-- no CACHE_VERSION bump required (heartbeats are pure ops metadata).
--
-- Idempotent: CREATE TABLE / INDEX use IF NOT EXISTS, safe to re-apply.
--
-- Dual-path convention: mirrored at db/migrations/016_cron_heartbeats.sql.
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/045_cron_heartbeats.sql

CREATE TABLE IF NOT EXISTS cron_heartbeats (
    workflow_name              TEXT      PRIMARY KEY,
    last_success_at            TIMESTAMP NOT NULL,
    expected_interval_minutes  INT       NOT NULL,
    consecutive_misses         INT       NOT NULL DEFAULT 0,
    updated_at                 TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_cron_heartbeats_last_success
    ON cron_heartbeats (last_success_at);

COMMENT ON TABLE cron_heartbeats IS
    'Dead-man monitor: one row per scheduled workflow. The wrapper script scripts/write_cron_heartbeat.py upserts last_success_at at the end of each successful run; the cron-deadman-checker workflow flags any workflow whose heartbeat is >2x expected_interval_minutes stale.';
COMMENT ON COLUMN cron_heartbeats.expected_interval_minutes IS
    'Declared cadence of the workflow in minutes (e.g. 5 for */5 cron, 1440 for daily). Source of truth for the dead-man threshold = 2 * this value.';
COMMENT ON COLUMN cron_heartbeats.consecutive_misses IS
    'Reserved for future use by the dead-man checker — currently always reset to 0 on each successful heartbeat write.';
