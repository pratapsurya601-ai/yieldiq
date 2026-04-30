-- 021_data_quality_rank.sql
-- 2026-04-30 — mirror of db/migrations/006_data_quality_rank.sql.
--
-- The repo historically maintains migrations in two places:
--   * data_pipeline/migrations/ (older, legacy)
--   * db/migrations/            (newer, used by NSE-first pipeline)
-- Both directories are kept in sync. Idempotent guards make
-- re-application safe.
--
-- See db/migrations/006_data_quality_rank.sql for the canonical
-- intent / rank table.

ALTER TABLE financials
    ADD COLUMN IF NOT EXISTS data_quality_rank INTEGER DEFAULT 50;

UPDATE financials
SET data_quality_rank = CASE COALESCE(data_source, '')
    WHEN 'NSE_XBRL'             THEN 10
    WHEN 'NSE_XBRL_STANDALONE'  THEN 15
    WHEN 'NSE_XBRL_SYNTH'       THEN 20
    WHEN 'BSE_PEERCOMP'         THEN 30
    WHEN 'BSE_API'              THEN 40
    WHEN 'finnhub'              THEN 50
    WHEN 'yfinance'             THEN 60
    ELSE 70
END
WHERE data_quality_rank = 50;

CREATE INDEX IF NOT EXISTS idx_financials_priority
    ON financials(ticker, period_type, period_end, data_quality_rank);

COMMENT ON COLUMN financials.data_quality_rank IS
    'Lower = higher priority. NSE_XBRL=10, NSE_XBRL_STANDALONE=15, NSE_XBRL_SYNTH=20, BSE_PEERCOMP=30, BSE_API=40, finnhub=50, yfinance=60, default=70. Used by UPSERT precedence guard.';
