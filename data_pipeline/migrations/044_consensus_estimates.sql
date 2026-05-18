-- 044_consensus_estimates.sql
-- 2026-05-18 — Benchmark Reconciliation Framework PR 1 (data plumbing only).
--
-- Adds the `consensus_estimates` table that stores daily snapshots of
-- analyst-consensus price targets from yfinance and Finnhub. The
-- reconciliation logic that joins these against our DCF FVs ships in PR 2.
--
-- This migration is **pure schema** — no application behaviour change,
-- no CACHE_VERSION bump required (consensus is read separately and does
-- NOT participate in the analysis_cache key).
--
-- Design: docs/design/benchmark-reconciliation-framework.md §3
--
-- Idempotent: CREATE TABLE / INDEX / VIEW use IF NOT EXISTS / OR REPLACE
-- so re-application is safe.
--
-- Dual-path convention (see 025_corporate_actions_quality_rank.sql):
-- this file is mirrored at db/migrations/015_consensus_estimates.sql.
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/044_consensus_estimates.sql

CREATE TABLE IF NOT EXISTS consensus_estimates (
    ticker          TEXT          NOT NULL,
    source          TEXT          NOT NULL,        -- 'yfinance' | 'finnhub'
    target_mean     NUMERIC(12,2),
    target_median   NUMERIC(12,2),
    target_high     NUMERIC(12,2),
    target_low      NUMERIC(12,2),
    analyst_count   INT,
    currency        TEXT          DEFAULT 'INR',
    fetched_at      TIMESTAMPTZ   NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, source, fetched_at)
);

CREATE INDEX IF NOT EXISTS ix_consensus_ticker
    ON consensus_estimates (ticker);

CREATE INDEX IF NOT EXISTS ix_consensus_fetched
    ON consensus_estimates (fetched_at DESC);

-- Combined index supporting the "latest row per ticker" view below.
CREATE INDEX IF NOT EXISTS ix_consensus_ticker_recent
    ON consensus_estimates (ticker, fetched_at DESC);

-- Convenience view: most recent row per ticker, preferring Finnhub > yfinance
-- and restricting to rows fetched within the last 14 days (anything older
-- is treated as stale by the reconciliation service in PR 2).
CREATE OR REPLACE VIEW latest_consensus_per_ticker AS
SELECT DISTINCT ON (ticker)
    ticker,
    source,
    target_mean,
    target_median,
    target_high,
    target_low,
    analyst_count,
    currency,
    fetched_at
FROM consensus_estimates
WHERE fetched_at > NOW() - INTERVAL '14 days'
ORDER BY
    ticker,
    CASE source WHEN 'finnhub' THEN 1 WHEN 'yfinance' THEN 2 ELSE 3 END,
    fetched_at DESC;

COMMENT ON TABLE consensus_estimates IS
    'Daily snapshots of external analyst-consensus price targets. Read-only sanity-check layer; never copied into our model FV. See docs/design/benchmark-reconciliation-framework.md.';
COMMENT ON COLUMN consensus_estimates.source IS
    'Provider key: ''yfinance'' or ''finnhub''. Finnhub preferred when both available (better small/mid-cap coverage).';
COMMENT ON COLUMN consensus_estimates.target_median IS
    'Median analyst price target. Preferred over target_mean for the reconciliation delta — more robust to outlier analysts.';
COMMENT ON COLUMN consensus_estimates.analyst_count IS
    'Number of contributing analysts. Reconciliation skips tickers with count < 3 (low signal).';
