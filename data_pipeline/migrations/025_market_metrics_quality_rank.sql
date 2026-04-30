-- Migration 025: market_metrics source-precedence + quality rank
--
-- Purpose: prevent future "yfinance NULL overwrites prior good data" bugs on
-- the market_metrics table. Mirrors PR #208's data_quality_rank pattern that
-- shipped for the financials table.
--
-- Today's incident (2026-04-30): yfinance daily refresh wrote 2,380 rows for
-- 2026-04-29 with market_cap_cr=NULL while prior trade_dates had valid
-- values. The cohort builder picked the latest row → got NULL → Value axis
-- collapsed to "n/a" across all tickers. Manually deleted the bad rows.
-- This migration prevents recurrence.
--
-- Three structural protections:
--   1. data_source column lets us know who wrote which row.
--   2. data_quality_rank lets UPSERTs refuse to let lower-trust sources
--      overwrite higher-trust data.
--   3. Read paths order by (rank, trade_date) so cached cohorts pick the
--      best available source, not just the most recent.
--
-- Idempotent: ALTER ... IF NOT EXISTS, defaults safe for existing rows.

ALTER TABLE market_metrics
    ADD COLUMN IF NOT EXISTS data_source VARCHAR(32);

ALTER TABLE market_metrics
    ADD COLUMN IF NOT EXISTS data_quality_rank INTEGER DEFAULT 50;

-- Backfill data_source: existing rows came from yfinance via fetch_market_metrics.py
UPDATE market_metrics
SET data_source = 'yfinance'
WHERE data_source IS NULL;

-- Backfill data_quality_rank by source. Lower = higher trust.
-- NSE official quote API (10) > NSE bhavcopy (20) > BSE (30/35) > finnhub (40) > yfinance (50)
UPDATE market_metrics
SET data_quality_rank = CASE COALESCE(data_source, '')
    WHEN 'NSE_QUOTE_API'  THEN 10
    WHEN 'NSE_BHAVCOPY'   THEN 20
    WHEN 'BSE_QUOTE'      THEN 30
    WHEN 'BSE_BHAVCOPY'   THEN 35
    WHEN 'finnhub'        THEN 40
    WHEN 'yfinance'       THEN 50
    ELSE 60
END
WHERE data_quality_rank = 50 OR data_quality_rank IS NULL;

-- Index supports DISTINCT ON (ticker) ORDER BY data_quality_rank ASC, trade_date DESC
CREATE INDEX IF NOT EXISTS idx_market_metrics_priority
    ON market_metrics(ticker, trade_date DESC, data_quality_rank);

COMMENT ON COLUMN market_metrics.data_source IS
    'Origin of the row: yfinance | NSE_QUOTE_API | NSE_BHAVCOPY | BSE_QUOTE | BSE_BHAVCOPY | finnhub | derived. Used by data_quality_rank.';

COMMENT ON COLUMN market_metrics.data_quality_rank IS
    'Lower = higher priority. UPSERT refuses to overwrite lower-rank rows with higher-rank sources. Read paths order by (rank ASC, trade_date DESC) so the cohort builder picks the best available source per ticker. Mirrors financials precedence pattern (PR #208 / migration 021_data_quality_rank.sql).';
