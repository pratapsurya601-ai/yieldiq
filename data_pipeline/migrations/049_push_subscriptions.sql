BEGIN;

-- Migration 049 (Day-98): push_subscriptions — Web Push (PWA) endpoints.
--
-- Context: PWA install was shipped on Day-67/68 with a service worker but
-- without push notifications. This migration adds the table that stores
-- each browser's PushManager subscription so the alerts evaluator
-- (scripts/alerts_evaluator.py, see backend.services.alerts_service) can
-- additionally deliver band-alerts via Web Push when a user has both
-- user_alerts.notify_push = true AND a registered subscription.
--
-- One row per (user_id, endpoint). Endpoint is the unique URL minted by
-- the push service (FCM / Mozilla / WNS) and acts as the natural key.
-- p256dh + auth are the two opaque keys returned by
-- PushSubscription.getKey() — both are base64url-encoded strings.
--
-- Rollback:
--   DROP TABLE IF EXISTS push_subscriptions;

CREATE TABLE IF NOT EXISTS push_subscriptions (
    id          SERIAL PRIMARY KEY,
    user_id     TEXT NOT NULL,
    endpoint    TEXT NOT NULL,
    p256dh      TEXT NOT NULL,
    auth        TEXT NOT NULL,
    user_agent  TEXT,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT now(),
    last_used_at TIMESTAMPTZ,
    CONSTRAINT uq_push_subscription_endpoint UNIQUE (endpoint)
);

CREATE INDEX IF NOT EXISTS idx_push_subscriptions_user
    ON push_subscriptions (user_id, created_at DESC);

COMMIT;
