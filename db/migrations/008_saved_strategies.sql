-- ═══════════════════════════════════════════════════════════════
-- Migration 008 — Saved Strategies (backtest UI)
--
-- Apply with: python scripts/apply_migration.py db/migrations/008_saved_strategies.sql
-- Idempotent — safe to re-run.
--
-- Purpose: persist user-defined strategy_def blobs from the Strategy
-- Builder UI (frontend/src/app/(app)/backtest), plus a snapshot of
-- the most recent backtest results so the dashboard renders without
-- a re-run on every page load.
--
-- Public sharing: a saved strategy can be flipped to is_public=true,
-- which exposes it via /api/v1/strategies/public/{slug} (no auth).
--
-- Discipline: ADDITIVE ONLY — no FK to existing tables, no analysis-
-- response math change, no CACHE_VERSION bump.
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS saved_strategies (
    id                    UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    user_email            TEXT NOT NULL,
    name                  TEXT NOT NULL,
    strategy_def          JSONB NOT NULL,
    last_backtest_results JSONB,
    last_backtested_at    TIMESTAMPTZ,
    is_public             BOOLEAN NOT NULL DEFAULT FALSE,
    public_slug           TEXT UNIQUE,
    created_at            TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at            TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_saved_strategies_user
    ON saved_strategies(user_email, created_at DESC);

CREATE INDEX IF NOT EXISTS idx_saved_strategies_public
    ON saved_strategies(public_slug) WHERE is_public = TRUE;

-- updated_at auto-touch trigger (matches pattern used by other tables).
CREATE OR REPLACE FUNCTION saved_strategies_touch_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = NOW();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS trg_saved_strategies_touch ON saved_strategies;
CREATE TRIGGER trg_saved_strategies_touch
    BEFORE UPDATE ON saved_strategies
    FOR EACH ROW
    EXECUTE FUNCTION saved_strategies_touch_updated_at();
