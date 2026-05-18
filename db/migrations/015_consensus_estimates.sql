-- 015_consensus_estimates.sql
-- Mirror of data_pipeline/migrations/044_consensus_estimates.sql.
-- See that file for full rationale and design pointer.

CREATE TABLE IF NOT EXISTS consensus_estimates (
    ticker          TEXT          NOT NULL,
    source          TEXT          NOT NULL,
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

CREATE INDEX IF NOT EXISTS ix_consensus_ticker_recent
    ON consensus_estimates (ticker, fetched_at DESC);

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
