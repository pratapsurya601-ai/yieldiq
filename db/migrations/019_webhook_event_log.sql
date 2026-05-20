-- Day-50 (2026-05-20): webhook event log for ops visibility.
--
-- The existing `webhook_events` table (migration 002) is a DEDUP
-- LOCK — it only records SUCCESSFUL first-time processings because
-- the UNIQUE(provider, event_id) constraint prevents duplicates
-- from being inserted at all. That means we have no visibility
-- into:
--   - how many duplicates Razorpay actually retried (dedup ratio)
--   - which deliveries failed (signature mismatch, parse error,
--     handler crash) and why
--   - the per-type rate (subscription.activated vs .charged vs ...)
--
-- This table is a write-ALL log: one row per webhook delivery
-- attempt, regardless of outcome. The handler in
-- backend/routers/payments.py inserts into it from three places:
--   1. successful first-time processing  → status='processed'
--   2. duplicate retry caught by dedup   → status='duplicate'
--   3. any handler-side failure          → status='failed' + error
--
-- Status enum is enforced via CHECK so a stray write can't fill
-- the dashboard with garbage. RLS-enabled with no policies so
-- only service_role can read/write.

CREATE TABLE IF NOT EXISTS webhook_event_log (
    id            BIGSERIAL PRIMARY KEY,
    provider      TEXT NOT NULL DEFAULT 'razorpay',
    event_id      TEXT,
    event_type    TEXT,
    status        TEXT NOT NULL CHECK (status IN ('processed', 'duplicate', 'failed')),
    error         TEXT,
    received_at   TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- The dashboard query buckets by (status, event_type) over the
-- last 24h — this index keeps that scan cheap as the table grows.
CREATE INDEX IF NOT EXISTS idx_webhook_event_log_received_at
    ON webhook_event_log (received_at DESC);

CREATE INDEX IF NOT EXISTS idx_webhook_event_log_status_received
    ON webhook_event_log (status, received_at DESC);

ALTER TABLE webhook_event_log ENABLE ROW LEVEL SECURITY;
-- No policies → deny-all for anon/authenticated; service_role
-- bypasses RLS so the backend can still write.
