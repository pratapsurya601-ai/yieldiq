-- Migration: 016 — insider activity + bulk/block deals scaffolding
--
-- Foundation for Task 8 (governance / insider activity feature). These
-- tables hold raw, public regulatory data:
--
--   bulk_block_deals     — NSE/BSE bulk + block trade reports (T+0)
--   insider_transactions — SEBI Reg 7 / PIT insider filings (T+2)
--
-- Notes on existing state:
--   - SQLAlchemy already defines `bulk_deals` (data_pipeline/models.py
--     class BulkDeal) populated by data_pipeline/sources/nse_bulk_deals.py.
--     That table uses different column names (trade_date, deal_category)
--     and is the live one — DO NOT drop it. The new
--     `bulk_block_deals` table here is the canonical schema described in
--     the v3 roadmap (governance pillar). Backfill / migration of the
--     existing `bulk_deals` rows into `bulk_block_deals` is tracked in
--     docs/insider_activity_design.md (open question #1).
--   - `hex_pulse_inputs.insider_net_30d` is currently aggregated on the
--     fly inside backend/services/sebi_sast_service.py — once
--     `insider_transactions` is populated, the pulse pipeline should
--     read from the table instead of hitting NSE every run.
--
-- Idempotent. Safe to run multiple times.

CREATE TABLE IF NOT EXISTS bulk_block_deals (
  id BIGSERIAL PRIMARY KEY,
  ticker VARCHAR(20) NOT NULL,
  deal_date DATE NOT NULL,
  deal_type VARCHAR(20) NOT NULL,        -- 'bulk' | 'block'
  client_name VARCHAR(200),
  buy_sell CHAR(1) NOT NULL,             -- 'B' | 'S'
  quantity BIGINT NOT NULL,
  price NUMERIC(12,2),
  exchange VARCHAR(10) NOT NULL,         -- 'NSE' | 'BSE'
  fetched_at TIMESTAMPTZ DEFAULT NOW(),
  CONSTRAINT uq_bulk_block_deal UNIQUE
    (ticker, deal_date, exchange, client_name, buy_sell, quantity)
);

CREATE INDEX IF NOT EXISTS idx_bbd_ticker_date
  ON bulk_block_deals(ticker, deal_date DESC);

CREATE INDEX IF NOT EXISTS idx_bbd_deal_date
  ON bulk_block_deals(deal_date DESC);


CREATE TABLE IF NOT EXISTS insider_transactions (
  id BIGSERIAL PRIMARY KEY,
  ticker VARCHAR(20) NOT NULL,
  filing_date DATE NOT NULL,
  trade_date DATE,
  insider_name VARCHAR(200),
  insider_role VARCHAR(50),              -- 'promoter', 'director', 'kmp'
  buy_sell CHAR(1),                      -- 'B' | 'S'
  quantity BIGINT,
  value_inr NUMERIC(15,2),
  post_holding_pct NUMERIC(6,3),
  source_url VARCHAR(500),
  fetched_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_insider_ticker_date
  ON insider_transactions(ticker, filing_date DESC);

CREATE INDEX IF NOT EXISTS idx_insider_filing_date
  ON insider_transactions(filing_date DESC);

-- A natural-key constraint to make ingest idempotent. SEBI / NSE PIT
-- feeds don't expose a stable filing UUID, so we compose one from the
-- fields a single filing uniquely combines. NULLs are allowed because
-- the upstream rows occasionally omit `trade_date` or `quantity` until
-- a correction filing arrives — the scraper passes ON CONFLICT DO
-- NOTHING and re-tries on the next refresh.
CREATE UNIQUE INDEX IF NOT EXISTS uq_insider_filing
  ON insider_transactions
     (ticker, filing_date,
      COALESCE(trade_date, filing_date),
      COALESCE(insider_name, ''),
      COALESCE(buy_sell, 'X'),
      COALESCE(quantity, 0));
