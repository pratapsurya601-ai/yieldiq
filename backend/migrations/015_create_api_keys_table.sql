-- 015_create_api_keys_table.sql
-- ───────────────────────────────────────────────────────────────────
-- Pro-tier programmatic API key system.
--
-- Design decisions:
--   * Raw API keys are NEVER stored. We persist only the SHA-256 hash
--     (CHAR(64)). The user sees the raw key exactly once (at create time).
--     If they lose it, we cannot recover it — they must rotate.
--   * key_prefix stores the first ~10 chars of the raw key in cleartext
--     ("yk_a1b2cd…") so users can identify their own keys in the UI list
--     without us ever needing the raw value.
--   * label is user-supplied free text, capped at 80 chars.
--   * revoked_at is a soft-delete column. Index `idx_apikey_user_active`
--     uses a partial WHERE so the index only covers live keys (small,
--     fast lookups for the per-user "list my active keys" query).
--   * api_key_usage holds the per-key per-day request counter, mirroring
--     the daily_usage pattern in backend/middleware/rate_limit.py. The
--     atomic UPSERT-with-guard implemented in api_keys_service.py keeps
--     the cap real under concurrency.
-- ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS api_keys (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    -- Store SHA-256 hash, NEVER the raw key. The raw key is shown to
    -- the user exactly ONCE at creation time and never again.
    key_hash CHAR(64) NOT NULL UNIQUE,
    -- A short prefix (8-10 chars) of the raw key, stored in cleartext
    -- so the user can identify their key in a list (e.g. "yk_a1b2cd").
    key_prefix VARCHAR(16) NOT NULL,
    label VARCHAR(80) NOT NULL DEFAULT 'Untitled',
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_used_at TIMESTAMPTZ NULL,
    revoked_at TIMESTAMPTZ NULL
);

CREATE INDEX IF NOT EXISTS idx_apikey_user_active
  ON api_keys (user_id) WHERE revoked_at IS NULL;
CREATE INDEX IF NOT EXISTS idx_apikey_hash
  ON api_keys (key_hash) WHERE revoked_at IS NULL;

CREATE TABLE IF NOT EXISTS api_key_usage (
    api_key_id BIGINT NOT NULL,
    usage_date DATE NOT NULL,
    request_count INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (api_key_id, usage_date)
);
