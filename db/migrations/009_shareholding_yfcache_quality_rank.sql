-- 009_shareholding_yfcache_quality_rank.sql
-- 2026-04-30 — additive migration: per-row source-precedence rank on
-- `shareholding_pattern` and `yfinance_info_cache`. Mirrors PR #208's
-- pattern (006_data_quality_rank.sql for `financials`).
--
-- shareholding_pattern today has no `data_source` column at all; this
-- migration adds both `data_source` (TEXT) and `data_quality_rank`
-- (INTEGER). Existing rows are NSE-only (written by
-- data_pipeline.sources.nse_shareholding) so we backfill data_source
-- to 'NSE_SHAREHOLDING' and rank to 10 for any row still on default.
--
-- yfinance_info_cache is single-source (yfinance) by definition; we
-- add the column for schema consistency at the standard rank=50.
--
-- Convention (mirrors PR #208): lower rank = higher priority.
--   NSE_SHAREHOLDING => 10
--   AMFI             => 25  (mutual-fund disclosures)
--   BSE_SHAREHOLDING => 30
--   finnhub          => 40
--   yfinance         => 50
--   anything else    => 60
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, UPDATE only touches rows on
-- the default rank to avoid clobbering any explicit value.
--
-- Apply with:
--   python scripts/apply_migration.py db/migrations/009_shareholding_yfcache_quality_rank.sql

-- ── shareholding_pattern ─────────────────────────────────────────────
ALTER TABLE shareholding_pattern
    ADD COLUMN IF NOT EXISTS data_source TEXT;

ALTER TABLE shareholding_pattern
    ADD COLUMN IF NOT EXISTS data_quality_rank INTEGER DEFAULT 50;

-- All existing rows came from data_pipeline.sources.nse_shareholding
-- (the only writer that touches this table today). Stamp them.
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

-- Read-path index for "best-row-per-quarter" dedupe.
CREATE INDEX IF NOT EXISTS idx_shareholding_priority
    ON shareholding_pattern(ticker, quarter_end DESC, data_quality_rank);

COMMENT ON COLUMN shareholding_pattern.data_quality_rank IS
    'Lower = higher priority. NSE_SHAREHOLDING=10, AMFI=25, BSE_SHAREHOLDING=30, finnhub=40, yfinance=50, default=60. Mirrors PR #208 pattern.';
COMMENT ON COLUMN shareholding_pattern.data_source IS
    'Source identifier for the row. Existing rows backfilled to NSE_SHAREHOLDING (the only writer at time of migration).';

-- ── yfinance_info_cache ──────────────────────────────────────────────
ALTER TABLE yfinance_info_cache
    ADD COLUMN IF NOT EXISTS data_quality_rank INTEGER DEFAULT 50;

-- Single-source table; rank=50 (yfinance) is correct for every row.
-- No backfill UPDATE needed since the default already matches.

COMMENT ON COLUMN yfinance_info_cache.data_quality_rank IS
    'Defaults to 50; this is a cache layer for yfinance.info responses (single source). Column exists for schema consistency with the wider source-precedence pattern (PR #208, #this-PR).';
