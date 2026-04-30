-- 025_corporate_actions_quality_rank.sql
-- 2026-04-30 — mirror of db/migrations/010_corporate_actions_quality_rank.sql.
--
-- The repo historically maintains migrations in two places:
--   * data_pipeline/migrations/ (older, legacy)
--   * db/migrations/            (newer, used by NSE-first pipeline)
-- Both directories are kept in sync. Idempotent guards make
-- re-application safe.
--
-- See db/migrations/010_corporate_actions_quality_rank.sql for the
-- canonical intent / rank table.

ALTER TABLE corporate_actions
    ADD COLUMN IF NOT EXISTS data_source VARCHAR(50);

ALTER TABLE corporate_actions
    ADD COLUMN IF NOT EXISTS data_quality_rank INTEGER DEFAULT 50;

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

CREATE INDEX IF NOT EXISTS idx_corporate_actions_priority
    ON corporate_actions(ticker, ex_date DESC, data_quality_rank);

COMMENT ON COLUMN corporate_actions.data_quality_rank IS
    'Lower = higher priority. NSE_CORP_ANN=10, NSE_ARCHIVE=15, BSE_CORP_FILE=30, finnhub=40, yfinance=50, default=60. UPSERT precedence guard refuses to overwrite a lower-rank row with a higher-rank one. Mirrors financials precedence pattern (PR #208).';

COMMENT ON COLUMN corporate_actions.data_source IS
    'Provenance label for the row. Set by ingest scripts (fetch_corporate_actions.py, backfill_corporate_actions_yf.py).';
