-- 018_sebi_filings_queue.sql
--
-- Queue of SEBI quarterly-results / annual-report / press-release
-- filings detected on BSE or NSE corporate-filings feeds. The crawler
-- (backend/workers/sebi_filings_crawler.py) UPSERTs new rows; the
-- processor walks rows in `pending` and transitions them through
-- downloaded → parsed → ingested (or → failed / skipped).
--
-- Goal: end-to-end latency from filing on exchange to FV recompute
-- + user alert under 24h.
--
-- See docs/sebi_auto_ingest_design.md for the state-machine diagram.

CREATE TABLE IF NOT EXISTS sebi_filings_queue (
  id              BIGSERIAL PRIMARY KEY,
  ticker          VARCHAR(20)  NOT NULL,
  filing_type     VARCHAR(30)  NOT NULL,   -- 'quarterly_results' | 'annual_report' | 'investor_presentation' | 'press_release' | 'corporate_action' | 'other'
  fiscal_period   VARCHAR(20),             -- 'Q1FY25' | 'Q2FY25' | 'FY24' | etc
  filing_date     DATE         NOT NULL,
  source_exchange VARCHAR(10)  NOT NULL,   -- 'BSE' | 'NSE'
  source_url      VARCHAR(500) NOT NULL,
  pdf_url         VARCHAR(500),
  xbrl_url        VARCHAR(500),
  status          VARCHAR(20)  DEFAULT 'pending',  -- 'pending' | 'downloaded' | 'parsed' | 'ingested' | 'failed' | 'skipped'
  ingested_at     TIMESTAMPTZ,
  error_message   TEXT,
  retry_count     INT          DEFAULT 0,
  detected_at     TIMESTAMPTZ  DEFAULT NOW(),
  UNIQUE (ticker, filing_type, fiscal_period, source_exchange)
);

CREATE INDEX IF NOT EXISTS idx_sebi_q_status
  ON sebi_filings_queue (status, detected_at DESC);

CREATE INDEX IF NOT EXISTS idx_sebi_q_ticker_period
  ON sebi_filings_queue (ticker, fiscal_period DESC);
