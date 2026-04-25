BEGIN;

-- Migration 015: notifications — in-app notification system.
--
-- Replaces the unimplemented "earnings-day morning email digest" Pro
-- feature with a Dhan/Zerodha-style in-app bell + drawer pattern.
--
-- Cost: zero per message (vs SendGrid's per-email cost).
-- Latency: 60s (frontend polls /api/v1/notifications/unread-count).
--
-- Auto-vacuum old read notifications after 90 days to keep the table
-- small. Implement as a cron, not a TRIGGER, to keep DELETEs out of
-- the hot path.
--
-- Idempotent: CREATE TABLE / INDEX IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS notifications (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    type VARCHAR(40) NOT NULL,
    title VARCHAR(120) NOT NULL,
    body TEXT,
    link VARCHAR(500),
    metadata JSONB DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    read_at TIMESTAMPTZ NULL
);

-- Partial index for the bell-badge unread_count() — by far the hottest
-- query (every authenticated user polls this every 60s).
CREATE INDEX IF NOT EXISTS idx_notif_user_unread
  ON notifications (user_id, created_at DESC)
  WHERE read_at IS NULL;

-- Covers list_recent() (read + unread, newest first).
CREATE INDEX IF NOT EXISTS idx_notif_user_recent
  ON notifications (user_id, created_at DESC);

COMMIT;
