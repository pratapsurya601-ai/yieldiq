BEGIN;

-- Migration 022: NSE index daily history (close + valuation ratios).
--
-- Source: https://archives.nseindia.com/content/indices/ind_close_all_<DDMMYYYY>.csv
--
-- One CSV per trading day, ~110 rows (one per Nifty index — broad
-- market: 50, Next 50, 100, 200, 500; sectoral: Bank, IT, Auto,
-- Pharma, FMCG, Metal, Energy, Realty, PSU Bank, Pvt Bank, Fin
-- Services, Media; thematic: Commodities, Consumption, MNC, etc.).
--
-- Columns from CSV: Index Name, Index Date, Open, High, Low, Close,
-- Pts Chg, Chg%, Volume, Turnover, P/E, P/B, Div Yield.
--
-- Why we want this: sector-level P/E / P/B / Div-Yield daily series
-- powers sector valuation context (mean-reversion bands, sector
-- percentiles for ratio history) and historical sector returns. The
-- CSV is the cleanest, most authoritative free source — much better
-- than scraping per-index pages or paying for vendor feeds.
--
-- Idempotent: CREATE TABLE / INDEX IF NOT EXISTS, UNIQUE constraint
-- on (index_name, trade_date) lets the ingestor safely UPSERT.

CREATE TABLE IF NOT EXISTS nse_index_history (
    id SERIAL PRIMARY KEY,
    index_name VARCHAR(64) NOT NULL,
    trade_date DATE NOT NULL,
    open NUMERIC(14,4),
    high NUMERIC(14,4),
    low NUMERIC(14,4),
    close NUMERIC(14,4),
    pts_chg NUMERIC(14,4),
    chg_pct NUMERIC(10,4),
    volume BIGINT,
    turnover_cr NUMERIC(14,2),
    pe_ratio NUMERIC(10,2),
    pb_ratio NUMERIC(10,2),
    div_yield NUMERIC(8,4),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (index_name, trade_date)
);

CREATE INDEX IF NOT EXISTS idx_nse_index_history_date
    ON nse_index_history(trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_nse_index_history_name_date
    ON nse_index_history(index_name, trade_date DESC);

COMMIT;
