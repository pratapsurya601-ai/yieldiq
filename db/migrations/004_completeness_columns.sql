-- 004_completeness_columns.sql
-- 2026-04-29 — additive migration for the unified completeness pipeline.
--
-- Adds columns + indexes that the pipeline expects to UPSERT into. All
-- changes are idempotent (IF NOT EXISTS) and additive — no DROP, no
-- column rename, no value backfill. Safe to run repeatedly on Neon.
--
-- Why this migration exists:
--   * `market_metrics` predates this pipeline and may not have the
--     unique constraint on (ticker, trade_date) that ON CONFLICT
--     requires.
--   * `financials` may not have the (ticker, period_end, period_type)
--     uniqueness that the ANNUAL UPSERT relies on.
--   * `stocks.nifty_sector_index` is the column reserved for the
--     PR #191 foundation classifier fallback (NSE indices). Adding
--     the column here means the pipeline can write to it once that
--     fallback ships, with no second migration.
--
-- Apply with `python scripts/apply_migration.py db/migrations/004_completeness_columns.sql`.

-- Stocks: ensure industry/sector columns exist + reserved fallback col.
ALTER TABLE stocks
    ADD COLUMN IF NOT EXISTS sector             TEXT,
    ADD COLUMN IF NOT EXISTS industry           TEXT,
    ADD COLUMN IF NOT EXISTS nifty_sector_index TEXT;

CREATE INDEX IF NOT EXISTS idx_stocks_sector   ON stocks (sector);
CREATE INDEX IF NOT EXISTS idx_stocks_industry ON stocks (industry);

-- market_metrics: unique key required by ON CONFLICT (ticker, trade_date).
-- Use a UNIQUE INDEX (rather than CONSTRAINT) so it's idempotent.
CREATE UNIQUE INDEX IF NOT EXISTS uq_market_metrics_ticker_date
    ON market_metrics (ticker, trade_date);

-- Optional metric columns the pipeline may upsert.
ALTER TABLE market_metrics
    ADD COLUMN IF NOT EXISTS debt_equity NUMERIC,
    ADD COLUMN IF NOT EXISTS roe         NUMERIC;

-- financials: unique key required by ON CONFLICT (ticker, period_end, period_type).
CREATE UNIQUE INDEX IF NOT EXISTS uq_financials_ticker_pe_pt
    ON financials (ticker, period_end, period_type);
