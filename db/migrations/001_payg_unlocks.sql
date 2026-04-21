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
