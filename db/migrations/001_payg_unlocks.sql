-- ═══════════════════════════════════════════════════════════════
-- Migration 001 — PAYG single-analysis unlocks
--
-- How to run: Supabase dashboard → SQL Editor → paste this file →
-- Run. Idempotent — safe to re-run.
--
-- Purpose: tracks ₹99 single-analysis purchases so the backend knows
-- which tickers a free-tier user has temporary access to, even after
-- their monthly 5-analysis quota is exhausted.
--
-- Unlock TTL is 24h, enforced in app code (no native Postgres row
-- expiry). Cron job can hard-delete rows older than 30d for cleanup.
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS payg_unlocks (
    id                  BIGSERIAL PRIMARY KEY,
    user_email          TEXT NOT NULL,
    ticker              TEXT NOT NULL,
    razorpay_payment_id TEXT,
    razorpay_order_id   TEXT,
    amount_paise        INTEGER,
    unlocked_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    UNIQUE(razorpay_payment_id)
);

CREATE INDEX IF NOT EXISTS idx_payg_user_ticker
    ON payg_unlocks(user_email, ticker, unlocked_at DESC);

-- ─────────────────────────────────────────────────────────────────
-- Row Level Security
--
-- The backend uses service_role (via get_admin_client) for all writes
-- and reads on this table — that bypasses RLS entirely. RLS matters
-- for defence-in-depth against accidental exposure via anon key or
-- future client-side Supabase calls.
--
-- Policy: a caller authenticated with a JWT can SELECT only their own
-- unlocks (matched by email on the JWT's `email` claim). Writes are
-- blocked for anon/authenticated keys — only service_role can insert.
-- ─────────────────────────────────────────────────────────────────

ALTER TABLE payg_unlocks ENABLE ROW LEVEL SECURITY;

-- Drop any pre-existing policy (so this migration is idempotent).
DROP POLICY IF EXISTS "payg_unlocks_self_select" ON payg_unlocks;

CREATE POLICY "payg_unlocks_self_select"
    ON payg_unlocks FOR SELECT
    TO authenticated
    USING (user_email = (auth.jwt() ->> 'email'));

-- No INSERT/UPDATE/DELETE policies for non-service roles — service
-- role bypasses RLS, so backend writes still work. Any other key
-- (anon, authenticated) can't mutate unlocks.
