-- 024_shareholding_yfcache_quality_rank.sql
-- Mirror of db/migrations/009_shareholding_yfcache_quality_rank.sql.
-- Kept in lock-step so the data_pipeline migration runner picks up the
-- same change. See the canonical file for full rationale.

ALTER TABLE shareholding_pattern
    ADD COLUMN IF NOT EXISTS data_source TEXT;

ALTER TABLE shareholding_pattern
    ADD COLUMN IF NOT EXISTS data_quality_rank INTEGER DEFAULT 50;

UPDATE shareholding_pattern
SET data_source = 'NSE_SHAREHOLDING'
WHERE data_source IS NULL;

UPDATE shareholding_pattern
SET data_quality_rank = CASE COALESCE(data_source, '')
    WHEN 'NSE_SHAREHOLDING' THEN 10
    WHEN 'AMFI'             THEN 25
    WHEN 'BSE_SHAREHOLDING' THEN 30
    WHEN 'finnhub'          THEN 40
    WHEN 'yfinance'         THEN 50
    ELSE 60
END
WHERE data_quality_rank = 50;

CREATE INDEX IF NOT EXISTS idx_shareholding_priority
    ON shareholding_pattern(ticker, quarter_end DESC, data_quality_rank);

COMMENT ON COLUMN shareholding_pattern.data_quality_rank IS
    'Lower = higher priority. Mirrors PR #208 pattern.';
COMMENT ON COLUMN shareholding_pattern.data_source IS
    'Source identifier. Existing rows backfilled to NSE_SHAREHOLDING.';

ALTER TABLE yfinance_info_cache
    ADD COLUMN IF NOT EXISTS data_quality_rank INTEGER DEFAULT 50;

COMMENT ON COLUMN yfinance_info_cache.data_quality_rank IS
    'Defaults to 50; cache layer for yfinance.info responses.';
