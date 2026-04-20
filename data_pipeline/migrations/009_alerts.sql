BEGIN;

-- Migration 009: user_alerts — backend-driven alerts engine.
--
-- Context: the frontend /alerts page has always existed but, until now,
-- was backed only by the Supabase-based `price_alerts` table (simple
-- above/below price triggers). This migration introduces a richer,
-- Postgres-native alerts table driven by the SQLAlchemy ORM and
-- evaluated hourly by scripts/alerts_evaluator.py (GH Actions).
--
-- Supported `kind` values:
--   'mos_above'       -- MoS % (from fair_value_history) rises above threshold
--   'mos_below'       -- MoS % falls below threshold
--   'price_above'     -- Last price (from market_metrics / live_quotes) >= threshold
--   'price_below'     -- Last price <= threshold
--   'verdict_change'  -- DCF verdict changed since last_checked_at
--
-- `threshold` is nullable because verdict_change has no numeric target.
-- `last_triggered_at` gates re-notification: evaluator fires only if the
-- condition is met AND (last_triggered_at IS NULL OR last_triggered_at <
-- now() - interval '24h'). This keeps noisy tickers from spamming users.
--
-- `status` transitions:
--   active    -- evaluator will check it
--   paused    -- user snoozed it; evaluator skips
--   triggered -- terminal for one-shot alerts; evaluator skips
--
-- Idempotent: CREATE TABLE IF NOT EXISTS.
--
-- Rollback:
--   DROP TABLE IF EXISTS user_alerts;

CREATE TABLE IF NOT EXISTS user_alerts (
    id                  SERIAL PRIMARY KEY,
    user_id             TEXT NOT NULL,
    ticker              TEXT NOT NULL,
    kind                TEXT NOT NULL,
    threshold           NUMERIC,
    last_checked_at     TIMESTAMPTZ,
    last_triggered_at   TIMESTAMPTZ,
    status              TEXT NOT NULL DEFAULT 'active',
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    notify_email        BOOLEAN NOT NULL DEFAULT TRUE,
    notify_push         BOOLEAN NOT NULL DEFAULT FALSE,
    CONSTRAINT uq_user_alert UNIQUE (user_id, ticker, kind),
    CONSTRAINT ck_user_alert_kind CHECK (
        kind IN ('mos_above', 'mos_below', 'price_above',
                 'price_below', 'verdict_change')
    ),
    CONSTRAINT ck_user_alert_status CHECK (
        status IN ('active', 'paused', 'triggered')
    )
);

-- Evaluator scans WHERE status = 'active' every hour; this index keeps
-- that scan cheap as the table grows.
CREATE INDEX IF NOT EXISTS idx_user_alerts_status_ticker
    ON user_alerts (status, ticker);

-- "List my alerts" on the frontend is keyed by user_id.
CREATE INDEX IF NOT EXISTS idx_user_alerts_user
    ON user_alerts (user_id, created_at DESC);

COMMIT;
