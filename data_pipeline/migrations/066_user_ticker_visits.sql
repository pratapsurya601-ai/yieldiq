-- 066_user_ticker_visits.sql
-- 2026-05-25 — Phase 4 manifesto (Paradigm 11): personal Memory Lane layer.
--
-- Per-user, per-ticker visit history. First visit captures a snapshot of
-- price + fair value + verdict from analysis_cache; subsequent visits bump
-- last_visited_at and visit_count.
--
-- The snapshot lets us tell the user, on every return visit:
--   "You first analyzed this 47 days ago at ₹720. FV moved 1054→1131
--    (+7%). If you'd bought ₹10,000 worth that day, you'd have ₹10,925
--    today."
--
-- Additive change — no CACHE_VERSION bump required. Manifest entry:
-- v_memory_lane_2026_05_25.
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/066_user_ticker_visits.sql

CREATE TABLE IF NOT EXISTS user_ticker_visits (
    id                          BIGSERIAL    PRIMARY KEY,
    user_id                     TEXT         NOT NULL,
    ticker                      TEXT         NOT NULL,
    first_visited_at            TIMESTAMPTZ  NOT NULL DEFAULT now(),
    last_visited_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    visit_count                 INT          NOT NULL DEFAULT 1,
    price_at_first_visit        NUMERIC,
    fair_value_at_first_visit   NUMERIC,
    verdict_at_first_visit      TEXT,
    user_note                   TEXT
);

-- Idempotency key for upsert: one row per (user, ticker). The visit
-- writer uses ON CONFLICT (user_id, ticker) DO UPDATE so re-opening
-- the page bumps the counter instead of appending a new row.
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM pg_constraint
        WHERE conname = 'uq_utv_user_ticker'
          AND conrelid = 'user_ticker_visits'::regclass
    ) THEN
        ALTER TABLE user_ticker_visits
            ADD CONSTRAINT uq_utv_user_ticker
            UNIQUE (user_id, ticker);
    END IF;
END
$$;

-- "What have I been looking at recently?" — supports a future
-- /me/memory-lane index page sorted by last_visited_at.
CREATE INDEX IF NOT EXISTS idx_user_visits_user
    ON user_ticker_visits(user_id, last_visited_at DESC);

COMMENT ON TABLE user_ticker_visits IS
    'Per-user, per-ticker visit history with a first-visit snapshot of price/FV/verdict. One row per (user,ticker), upserted on each visit. Powers the Memory Lane component on the analysis page (Phase 4 manifesto, Paradigm 11).';
COMMENT ON COLUMN user_ticker_visits.price_at_first_visit IS
    'Price captured from analysis_cache.payload->valuation->>current_price at the moment of the first visit. NULL if the cache had no entry.';
COMMENT ON COLUMN user_ticker_visits.fair_value_at_first_visit IS
    'Fair value captured from analysis_cache.payload->valuation->>fair_value at the moment of the first visit. NULL if the cache had no entry.';
COMMENT ON COLUMN user_ticker_visits.verdict_at_first_visit IS
    'Verdict string captured at first visit (e.g. undervalued, fairly_valued, overvalued, under_review). NULL if no cache hit.';
COMMENT ON COLUMN user_ticker_visits.user_note IS
    'Free-form personal note. Auto-saved by the frontend (debounced 1s). NULL until the user writes one.';
