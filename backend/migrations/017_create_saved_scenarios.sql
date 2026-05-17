-- 017_create_saved_scenarios.sql
-- ───────────────────────────────────────────────────────────────────
-- Phase-2 of the editable-assumptions feature: per-user saved DCF
-- scenarios. A "scenario" is a named bundle of {wacc, growth,
-- margin, terminal_growth} overrides for a specific ticker, plus
-- the recompute result captured at save time so the user can
-- compare numbers without re-running the engine.
--
-- Design decisions:
--   * One row per (user, ticker, name) combo. The unique constraint
--     lets us treat "save with same name" as an upsert on the app
--     side without racing.
--   * assumptions_jsonb / result_jsonb keep this future-proof —
--     adding a slider (beta, tax_rate, ...) doesn't require a
--     migration, only an app-side schema bump.
--   * Indexed on (user_id, ticker) so the per-ticker "my scenarios"
--     lookup is O(matched rows). Secondary index on user_id alone
--     supports a future "all my scenarios across tickers" view.
--   * No soft-delete column — saved scenarios are user-owned UX
--     metadata, not data we need an audit trail for. Hard DELETE
--     is fine and matches the user's mental model ("delete means
--     gone").
-- ───────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS saved_scenarios (
    id BIGSERIAL PRIMARY KEY,
    user_id UUID NOT NULL,
    ticker VARCHAR(32) NOT NULL,
    name VARCHAR(80) NOT NULL,
    assumptions JSONB NOT NULL,
    result JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_id, ticker, name)
);

CREATE INDEX IF NOT EXISTS idx_saved_scenarios_user_ticker
  ON saved_scenarios (user_id, ticker);
CREATE INDEX IF NOT EXISTS idx_saved_scenarios_user
  ON saved_scenarios (user_id);
