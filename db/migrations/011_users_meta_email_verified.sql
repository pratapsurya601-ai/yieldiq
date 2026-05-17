-- 011_users_meta_email_verified.sql
-- 2026-05-17 — additive migration: add email_verified state to users_meta
-- so we can soft-gate sensitive actions (paid upgrade, API key create,
-- Pro-tier export) without blocking login or free-tier analyses.
--
-- Why we don't reuse Supabase auth.users.email_confirmed_at
-- ─────────────────────────────────────────────────────────
-- Today the YieldIQ register flow calls admin.create_user with
-- email_confirm=True (so login works immediately, no double-opt-in).
-- That means auth.users.email_confirmed_at is set the moment the row
-- is created — there is no unverified state to read off Supabase.
--
-- Rather than rip out the auto-confirm (which would break login for
-- everyone with email-confirmation required in the Supabase project),
-- we track our OWN verification state in users_meta. New email/password
-- signups land with email_verified=false; Google OAuth signups land
-- with email_verified=true (Google has already verified the address).
-- A short-lived HMAC token in our own /auth/verify/{send,confirm}
-- endpoints flips the flag.
--
-- The gates (payments.create-subscription, api_keys.create,
-- analysis.export.xlsx) call require_email_verified — see
-- backend/middleware/auth.py. Login, /auth/me, free analyses,
-- portfolio save, and watchlist remain open.

ALTER TABLE users_meta
  ADD COLUMN IF NOT EXISTS email_verified BOOLEAN NOT NULL DEFAULT FALSE,
  ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ;

-- Backfill: every existing user is grandfathered as verified. We are
-- adding this gate to slow signup-spam abuse on the paid upgrade and
-- API-key endpoints, not to retroactively lock out users who created
-- accounts before this column existed.
UPDATE users_meta
   SET email_verified = TRUE,
       email_verified_at = COALESCE(email_verified_at, NOW())
 WHERE email_verified = FALSE;

CREATE INDEX IF NOT EXISTS users_meta_email_verified_idx
  ON users_meta (email_verified)
  WHERE email_verified = FALSE;
