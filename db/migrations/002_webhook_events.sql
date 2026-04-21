-- ═══════════════════════════════════════════════════════════════
-- Migration 002 — webhook event idempotency log
--
-- How to run: Supabase dashboard → SQL Editor → paste this file →
-- Run. Idempotent — safe to re-run.
--
-- Purpose: dedup webhook deliveries (currently Razorpay; structured
-- for future providers) so a retried delivery can't double-fire our
-- handlers — which today would cause redundant Supabase writes and
-- noisy "demoted X to free" / "promoted X" log pairs for the same
-- logical event.
--
-- Razorpay retries webhooks on any non-2xx response or network
-- timeout, so duplicate deliveries are expected in production, not a
-- malicious replay. We still prefer an on-insert unique-constraint
-- failure as the "already processed" signal over an in-memory dedup
-- — it survives deploys and works across Railway replicas.
--
-- Key design: (provider, event_id). For Razorpay, event_id is the
-- natural composite (account_id, event, created_at) since the
-- payload has no single top-level event-UUID that's guaranteed
-- across retries of the same logical event. Encoded as a string by
-- the handler to keep the schema provider-agnostic.
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS webhook_events (
    id            BIGSERIAL PRIMARY KEY,
    provider      TEXT NOT NULL DEFAULT 'razorpay',
    event_id      TEXT NOT NULL,
    event_type    TEXT,
    processed_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(provider, event_id)
);

-- Lookups are UNIQUE-constraint driven on insert; the index on
-- processed_at helps the cleanup cron (prune rows > 90d) scan quickly.
CREATE INDEX IF NOT EXISTS idx_webhook_events_processed_at
    ON webhook_events(processed_at DESC);

-- ─────────────────────────────────────────────────────────────────
-- Row Level Security
--
-- Only service_role (the backend) ever touches this table. Enable
-- RLS with no policies so anon/authenticated keys can't read or
-- write even if a credential leaks into the frontend build.
-- ─────────────────────────────────────────────────────────────────

ALTER TABLE webhook_events ENABLE ROW LEVEL SECURITY;

-- Explicitly no policies — RLS-enabled + no policy = deny all for
-- non-service-role. service_role bypasses RLS, so backend writes
-- still succeed.
