-- 006_data_quality_rank.sql
-- 2026-04-30 — additive migration: per-row source-precedence rank on `financials`.
--
-- Purpose
-- ───────
-- Make NSE_XBRL row always win over yfinance for the same
-- (ticker, period_end, period_type). Prevents the v74-class incident
-- where the 2026-04-29 NSE-archive backfill (PR #194) silently
-- overwrote good NSE_XBRL FY24 anchors with bad yfinance FY25 capex
-- on 16 cement+metals tickers (band-aided in PR #207 by NULLing the
-- corrupted rows; this migration is the structural fix).
--
-- Convention: lower rank = higher quality / wins on conflict.
--   NSE_XBRL              =>  10
--   NSE_XBRL_STANDALONE   =>  15  (consolidated-preferred but standalone-only filers exist)
--   NSE_XBRL_SYNTH        =>  20
--   BSE_PEERCOMP          =>  30
--   BSE_API               =>  40
--   finnhub               =>  50
--   yfinance              =>  60
--   anything else / NULL  =>  70
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, default safe for existing
-- rows, UPDATE only touches rows still on the default.
--
-- Apply with:
--   python scripts/apply_migration.py db/migrations/006_data_quality_rank.sql

ALTER TABLE financials
    ADD COLUMN IF NOT EXISTS data_quality_rank INTEGER DEFAULT 50;

-- Backfill rank for existing rows based on data_source. Only touch
-- rows still sitting on the default to avoid clobbering any explicit
-- rank a future patch may have set.
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

-- Read-path index: dedupe-by-period uses (ticker, period_type,
-- period_end, data_quality_rank) ordering inside a window function.
CREATE INDEX IF NOT EXISTS idx_financials_priority
    ON financials(ticker, period_type, period_end, data_quality_rank);

COMMENT ON COLUMN financials.data_quality_rank IS
    'Lower = higher priority. NSE_XBRL=10, NSE_XBRL_STANDALONE=15, NSE_XBRL_SYNTH=20, BSE_PEERCOMP=30, BSE_API=40, finnhub=50, yfinance=60, default=70. Used by UPSERT precedence guard (fetch_annual_financials.py, bse_xbrl.store_financials) and by the read-path window-function dedupe in pipeline.get_stock_data_from_db.';
