BEGIN;

-- Migration 050 (Day-101c): pwa_telemetry_events — persistent PWA install funnel.
--
-- Day-100a (#495) shipped POST /api/v1/telemetry/pwa-event which logged
-- funnel events via stdout. Railway log retention is short and the
-- logs are not queryable, so the admin /admin/pwa-funnel dashboard
-- needs a real table to aggregate against.
--
-- Privacy:
--   * Only the four whitelisted event names are written (prompted /
--     installed / dismissed / ios_hint_shown).
--   * `ua_truncated` is already capped at 80 chars by the router so we
--     never store fingerprintable UA strings.
--   * `ip_hash` is sha256(SALT_PWA_TELEMETRY || remote_ip) so we can
--     dedup the same browser hammering the endpoint without ever
--     persisting raw IPs.
--
-- Additive migration — no existing flows touched.
--
-- Rollback:
--   DROP TABLE IF EXISTS pwa_telemetry_events;

CREATE TABLE IF NOT EXISTS pwa_telemetry_events (
    id            SERIAL PRIMARY KEY,
    event         TEXT NOT NULL,
    ua_truncated  TEXT,
    ip_hash       TEXT,
    created_at    TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_pwa_telemetry_events_event_created
    ON pwa_telemetry_events (event, created_at DESC);

COMMIT;
