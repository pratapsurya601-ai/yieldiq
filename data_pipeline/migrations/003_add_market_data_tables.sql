-- 003_add_market_data_tables.sql
--
-- Adds three tables that replace request-time yfinance calls for
-- market indices, FX, and portfolio live quotes. A background
-- APScheduler job (backend/workers/market_data_refresher.py) UPSERTs
-- fresh rows into these tables; read paths query them and only fall
-- through to yfinance when a row is missing.
--
-- Idempotent: uses IF NOT EXISTS so re-runs are safe.
--
-- Run against: Aiven Postgres (yieldiq Financials DB).
-- Apply with: `psql "$AIVEN_DSN" -f 003_add_market_data_tables.sql`

BEGIN;

-- 1. Live quotes for portfolio holdings + screener top picks.
--    Refreshed every 5 min during market hours.
CREATE TABLE IF NOT EXISTS live_quotes (
    ticker     TEXT PRIMARY KEY,
    price      DOUBLE PRECISION NOT NULL,
    change_pct DOUBLE PRECISION,
    volume     BIGINT,
    as_of      TIMESTAMPTZ NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS ix_live_quotes_as_of
    ON live_quotes (as_of);

-- 2. FX pairs (USDINR primarily). Refreshed every 15 min.
CREATE TABLE IF NOT EXISTS fx_rates (
    pair  TEXT PRIMARY KEY,            -- "USDINR", "EURINR"
    rate  DOUBLE PRECISION NOT NULL,
    as_of TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 3. Index + commodity snapshots (NIFTY, SENSEX, VIX, gold, silver).
--    Refreshed every 15 min.
CREATE TABLE IF NOT EXISTS index_snapshots (
    symbol     TEXT PRIMARY KEY,       -- "^NSEI", "^BSESN", "^NSEBANK",
                                       -- "^INDIAVIX", "GC=F", "SI=F",
                                       -- "^NSEMDCP50"
    name       TEXT,
    price      DOUBLE PRECISION NOT NULL,
    change_pct DOUBLE PRECISION,
    as_of      TIMESTAMPTZ NOT NULL DEFAULT now()
);

COMMIT;
