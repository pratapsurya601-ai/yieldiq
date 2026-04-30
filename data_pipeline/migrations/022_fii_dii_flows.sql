-- Migration: 022 — FII/DII daily flow archive
--
-- NSE exposes FII/DII buy/sell/net only as a current-day snapshot at
-- https://www.nseindia.com/api/fiidiiTradeReact — there is no historical
-- archive endpoint. We self-archive going forward via the daily cron
-- defined in .github/workflows/nse_flows_daily.yml.
--
-- Companion to migration 016 (bulk_block_deals) which holds the deal
-- archive. Together they form the "market flows" pillar surfaced on
-- /discover and inside the analysis Insider Activity panel.
--
-- Idempotent. Safe to run multiple times.

CREATE TABLE IF NOT EXISTS fii_dii_flows (
    id SERIAL PRIMARY KEY,
    trade_date DATE NOT NULL,
    category VARCHAR(16) NOT NULL CHECK (category IN ('FII', 'DII')),
    buy_value_cr NUMERIC(14,2),
    sell_value_cr NUMERIC(14,2),
    net_value_cr NUMERIC(14,2),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    CONSTRAINT uq_fii_dii_day UNIQUE (trade_date, category)
);

CREATE INDEX IF NOT EXISTS idx_fii_dii_date
    ON fii_dii_flows(trade_date DESC);
