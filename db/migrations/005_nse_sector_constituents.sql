-- 005_nse_sector_constituents.sql
-- 2026-04-29 — additive migration for the NSE-archive-first pipeline.
--
-- Stores NSE sectoral-index constituents (Nifty IT, Nifty Bank, …). This
-- is the canonical source for stocks.sector / stocks.industry — yfinance
-- is only consulted when a ticker is not in any NSE sectoral index
-- (typically micro-caps / SME boards).
--
-- Endpoint: https://nsearchives.nseindia.com/content/indices/ind_<index>list.csv
-- Refreshed monthly (NSE re-balances quarterly but publishes monthly).
--
-- Apply with `python scripts/apply_migration.py db/migrations/005_nse_sector_constituents.sql`.

CREATE TABLE IF NOT EXISTS nse_sector_constituents (
    ticker           TEXT NOT NULL,
    nifty_index      TEXT NOT NULL,
    canonical_sector TEXT NOT NULL,
    fetched_at       TIMESTAMPTZ DEFAULT now(),
    PRIMARY KEY (ticker, nifty_index)
);

CREATE INDEX IF NOT EXISTS idx_nse_sector_canonical
    ON nse_sector_constituents (canonical_sector);

CREATE INDEX IF NOT EXISTS idx_nse_sector_ticker
    ON nse_sector_constituents (ticker);
