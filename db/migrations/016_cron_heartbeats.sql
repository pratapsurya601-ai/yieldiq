-- 016_cron_heartbeats.sql
-- Mirror of data_pipeline/migrations/045_cron_heartbeats.sql.
-- See that file for the design rationale.

CREATE TABLE IF NOT EXISTS cron_heartbeats (
    workflow_name              TEXT      PRIMARY KEY,
    last_success_at            TIMESTAMP NOT NULL,
    expected_interval_minutes  INT       NOT NULL,
    consecutive_misses         INT       NOT NULL DEFAULT 0,
    updated_at                 TIMESTAMP NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_cron_heartbeats_last_success
    ON cron_heartbeats (last_success_at);
