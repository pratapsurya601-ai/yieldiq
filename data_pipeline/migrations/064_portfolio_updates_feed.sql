-- 064_portfolio_updates_feed.sql
-- 2026-05-25 — P0 #1: per-holding "Updates" feed for the Portfolio page.
--
-- One row per (ticker, event_at, category) event. Populated nightly by
-- scripts/build_updates_feed.py (.github/workflows/cron-updates-feed.yml)
-- which scans corporate_actions / insider_trading / financials_history /
-- manifest history and emits template-generated headlines. NO LLM calls —
-- all copy is template-driven and SEBI-safe (no buy/sell/hold/target).
--
-- The feed is GLOBAL per ticker (not per user). The endpoint joins
-- against the user's portfolio (holdings table, user_email keyed) at
-- read time so each user only sees rows for tickers they own.
--
-- Idempotent: CREATE TABLE / INDEX IF NOT EXISTS, unique constraint
-- (ticker, event_at, category) so the aggregator's UPSERT is safe to
-- re-run nightly.
--
-- Additive change — no CACHE_VERSION bump required.
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/064_portfolio_updates_feed.sql

CREATE TABLE IF NOT EXISTS portfolio_updates_feed (
    id          BIGSERIAL PRIMARY KEY,
    ticker      TEXT        NOT NULL,
    event_at    TIMESTAMPTZ NOT NULL,
    category    TEXT        NOT NULL,
    headline    TEXT        NOT NULL,
    detail      TEXT        NOT NULL,
    source_ref  JSONB,
    created_at  TIMESTAMPTZ DEFAULT now()
);

-- CHECK constraint on category — added through DO-block so re-runs
-- of the migration do not raise "constraint already exists".
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_pufeed_category'
          AND conrelid = 'portfolio_updates_feed'::regclass
    ) THEN
        ALTER TABLE portfolio_updates_feed
            ADD CONSTRAINT ck_pufeed_category
            CHECK (category IN (
                'earnings',
                'valuations',
                'intrinsic_updates',
                'dividends',
                'insider_trading',
                'risk_legal',
                'other'
            ));
    END IF;
END
$$;

-- Idempotency key for the aggregator UPSERT.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_pufeed_ticker_event_category'
          AND conrelid = 'portfolio_updates_feed'::regclass
    ) THEN
        ALTER TABLE portfolio_updates_feed
            ADD CONSTRAINT uq_pufeed_ticker_event_category
            UNIQUE (ticker, event_at, category);
    END IF;
END
$$;

CREATE INDEX IF NOT EXISTS idx_pufeed_ticker_event
    ON portfolio_updates_feed(ticker, event_at DESC);

CREATE INDEX IF NOT EXISTS idx_pufeed_category
    ON portfolio_updates_feed(category, event_at DESC);

COMMENT ON TABLE portfolio_updates_feed IS
    'Per-ticker, categorised event stream surfaced as the Portfolio > Updates tab. Populated nightly by scripts/build_updates_feed.py. Template-driven headlines (no LLM).';
COMMENT ON COLUMN portfolio_updates_feed.category IS
    'One of: earnings, valuations, intrinsic_updates, dividends, insider_trading, risk_legal, other.';
COMMENT ON COLUMN portfolio_updates_feed.source_ref IS
    'JSONB pointer back to the source row (e.g. {"table":"corporate_actions","id":123} or {"table":"manifest","version_id":"v_..."}).';
