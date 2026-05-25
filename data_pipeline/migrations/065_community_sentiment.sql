-- 065_community_sentiment.sql
-- 2026-05-25 — Week-3 manifesto: "How do you feel?" voting widget.
--
-- One row per (user, ticker). Users can change their vote — the
-- writer upserts on (user_id, ticker). All counts/percentages are
-- aggregated on read; no materialized view (vote volume is small,
-- aggregation is sub-millisecond at <100k rows per ticker).
--
-- The table is global (not per-tenant). Sentiment values are constrained
-- to ('bearish','neutral','bullish') via CHECK — these labels are
-- SEBI-safe (none appear in backend/services/analysis/sebi_filter.py
-- BANNED_WORDS) and explicitly framed as "view", not "advice".
--
-- Additive change — no CACHE_VERSION bump required. Manifest entry:
-- v_community_sentiment_2026_05_25.
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/065_community_sentiment.sql

CREATE TABLE IF NOT EXISTS community_sentiment_votes (
    id         BIGSERIAL   PRIMARY KEY,
    user_id    TEXT        NOT NULL,
    ticker     TEXT        NOT NULL,
    sentiment  TEXT        NOT NULL,
    voted_at   TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- CHECK on sentiment via DO-block so re-runs of the migration do not
-- raise "constraint already exists".
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'ck_csv_sentiment'
          AND conrelid = 'community_sentiment_votes'::regclass
    ) THEN
        ALTER TABLE community_sentiment_votes
            ADD CONSTRAINT ck_csv_sentiment
            CHECK (sentiment IN ('bearish', 'neutral', 'bullish'));
    END IF;
END
$$;

-- Idempotency key for upsert: one row per (user, ticker). The POST
-- vote endpoint uses ON CONFLICT (user_id, ticker) DO UPDATE so a
-- user changing their mind overwrites their prior vote, not appends.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_csv_user_ticker'
          AND conrelid = 'community_sentiment_votes'::regclass
    ) THEN
        ALTER TABLE community_sentiment_votes
            ADD CONSTRAINT uq_csv_user_ticker
            UNIQUE (user_id, ticker);
    END IF;
END
$$;

-- Aggregation index — supports both the count rollup and the
-- /history?days=N daily time-series.
CREATE INDEX IF NOT EXISTS idx_csv_ticker_voted
    ON community_sentiment_votes(ticker, voted_at DESC);

COMMENT ON TABLE community_sentiment_votes IS
    'Per-user, per-ticker community sentiment votes ("How do you feel?"). One row per (user,ticker); upserted on change. SEBI-safe labels: bearish/neutral/bullish — framed as user view, not investment advice.';
COMMENT ON COLUMN community_sentiment_votes.sentiment IS
    'One of: bearish, neutral, bullish. Enforced by ck_csv_sentiment.';
