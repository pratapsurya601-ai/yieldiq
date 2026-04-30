BEGIN;

-- Migration 023: insider_trading — SEBI PIT Reg 7 disclosures.
--
-- NSE publishes 9-10 years of insider buy/sell records per ticker at
--   /api/corporates-pit?index=equities&symbol=<SYM>
-- and full-universe-per-year at
--   /api/corporates-pit?from=01-01-2024&to=31-12-2024
--
-- Source schema (acqNameList[] entries):
--   acqName, buyValue, sellValue, before/after holding %, anex (annexure
--   type — Form C / Form D / etc), xbrl (filing PDF URL).
--
-- This is purely additive data; no analysis math depends on it. The
-- analysis page reads the most-recent rows for governance signal.
--
-- Idempotent: CREATE TABLE / INDEX IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS insider_trading (
    id SERIAL PRIMARY KEY,
    ticker VARCHAR(32) NOT NULL,
    isin VARCHAR(32),
    filing_date DATE,
    acquirer_name VARCHAR(256),
    acquirer_category VARCHAR(64),
    transaction_type VARCHAR(32),  -- Market/Off-Market/Tender Offer
    buy_qty BIGINT,
    sell_qty BIGINT,
    transaction_value_cr NUMERIC(14,2),
    holding_before_pct NUMERIC(8,4),
    holding_after_pct NUMERIC(8,4),
    annex_type VARCHAR(16),
    pdf_url TEXT,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ticker, filing_date, acquirer_name, buy_qty, sell_qty)
);

CREATE INDEX IF NOT EXISTS idx_insider_ticker_date
    ON insider_trading(ticker, filing_date DESC);

COMMIT;
