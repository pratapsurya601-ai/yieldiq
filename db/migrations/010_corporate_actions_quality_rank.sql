-- 010_corporate_actions_quality_rank.sql
-- 2026-04-30 — additive migration: per-row source-precedence rank on
-- `corporate_actions`. Mirrors db/migrations/006_data_quality_rank.sql
-- (financials, PR #208) for the splits/bonuses/dividends table.
--
-- Purpose
-- ───────
-- Make NSE-corporate-actions rows always win over yfinance for the
-- same (ticker, ex_date, action_type). The ingest scripts today
-- DELETE-then-INSERT per ticker which means a per-ticker yfinance
-- top-up after an NSE bulk fetch can clobber the NSE row entirely.
-- This migration adds both:
--   * a `data_source` column so the table can carry per-row provenance
--     (today the writers don't tag rows at all),
--   * a `data_quality_rank` column populated from data_source, and
--   * a UNIQUE INDEX on (ticker, ex_date, action_type) so the
--     scripts/data_pipelines/fetch_corporate_actions.py and
--     scripts/backfill_corporate_actions_yf.py UPSERTs can use
--     real ON CONFLICT precedence instead of DELETE-then-INSERT.
--
-- Convention: lower rank = higher quality / wins on conflict.
--   NSE_CORP_ANN  =>  10  (NSE bulk corporates-corporateActions feed)
--   NSE_ARCHIVE   =>  15  (NSE per-symbol historical equityaction)
--   BSE_CORP_FILE =>  30  (BSE corporate filings, future)
--   finnhub       =>  40
--   yfinance      =>  50
--   anything else =>  60
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, default safe for existing
-- rows, UPDATE only touches rows still on the default.
--
-- Apply with:
--   python scripts/apply_migration.py db/migrations/010_corporate_actions_quality_rank.sql

ALTER TABLE corporate_actions
    ADD COLUMN IF NOT EXISTS data_source VARCHAR(50);

ALTER TABLE corporate_actions
    ADD COLUMN IF NOT EXISTS data_quality_rank INTEGER DEFAULT 50;

-- Backfill rank for existing rows based on data_source. Only touch
-- rows still sitting on the default to avoid clobbering any explicit
-- rank a future patch may have set. Existing rows have NULL data_source
-- so they fall through to the catch-all 60 rank, which means a fresh
-- NSE_CORP_ANN row (rank 10) can win cleanly on the next ingest.
UPDATE corporate_actions
SET data_quality_rank = CASE COALESCE(data_source, '')
    WHEN 'NSE_CORP_ANN'   THEN 10
    WHEN 'NSE_ARCHIVE'    THEN 15
    WHEN 'BSE_CORP_FILE'  THEN 30
    WHEN 'finnhub'        THEN 40
    WHEN 'yfinance'       THEN 50
    ELSE 60
END
WHERE data_quality_rank = 50;

-- Real UPSERTs need a unique key. The writer scripts have always
-- treated (ticker, ex_date, action_type) as the natural key (see
-- fetch_corporate_actions.py docstring "Rows keyed on (ticker,
-- ex_date, action_type)") but the constraint was never enforced at
-- the schema level. Adding it now lets us replace the
-- DELETE-then-INSERT pattern with ON CONFLICT precedence guards.
--
-- Defensive de-dupe before the unique index: if any duplicates exist
-- for the natural key, keep the highest-priority (lowest rank) row
-- per group, falling back to the most recent id.
WITH ranked AS (
    SELECT id,
           ROW_NUMBER() OVER (
               PARTITION BY ticker, ex_date, action_type
               ORDER BY data_quality_rank ASC, id DESC
           ) AS rn
    FROM corporate_actions
    WHERE ticker IS NOT NULL
      AND ex_date IS NOT NULL
      AND action_type IS NOT NULL
)
DELETE FROM corporate_actions
WHERE id IN (SELECT id FROM ranked WHERE rn > 1);

CREATE UNIQUE INDEX IF NOT EXISTS uq_corporate_actions_natural_key
    ON corporate_actions(ticker, ex_date, action_type);

-- Read-path index for "latest action per ticker" projections that
-- want the highest-priority source first. Aggregation reads (e.g.
-- 5-year dividend history) ignore rank and don't use this index.
CREATE INDEX IF NOT EXISTS idx_corporate_actions_priority
    ON corporate_actions(ticker, ex_date DESC, data_quality_rank);

COMMENT ON COLUMN corporate_actions.data_quality_rank IS
    'Lower = higher priority. NSE_CORP_ANN=10, NSE_ARCHIVE=15, BSE_CORP_FILE=30, finnhub=40, yfinance=50, default=60. UPSERT precedence guard refuses to overwrite a lower-rank row with a higher-rank one. Mirrors financials precedence pattern (PR #208).';

COMMENT ON COLUMN corporate_actions.data_source IS
    'Provenance label for the row. Set by ingest scripts (fetch_corporate_actions.py, backfill_corporate_actions_yf.py). Drives data_quality_rank via the migration backfill and via _rank_for() in the writer scripts.';
