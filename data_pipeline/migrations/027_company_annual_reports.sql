-- Migration 027: company_annual_reports table
--
-- Stores Annual Report (AR) metadata + STRUCTURED data extracted from the
-- PDF via an LLM (Claude Sonnet in the planned Phase 2 activation).
--
-- Design intent: ARs are an AUGMENTATION LAYER on top of existing data,
-- NOT a replacement for it. ARs are uniquely valuable for:
--   * Segment data (fixes conglomerate DCF -- RELIANCE, ITC, etc.)
--   * Capex commitments from MD&A (forward modeling)
--   * Auditor's going-concern flags (early warning)
--   * Contingent liabilities (risk pillar input)
--   * Related-party transactions (governance signal)
--
-- ARs CANNOT replace:
--   * Daily prices (need NSE bhavcopy)
--   * Quarterly results (need separate quarterly filings)
--   * Live corporate actions
--
-- Phase 1 (this migration): schema only. Extractor service is a stub --
-- no live LLM call, no anthropic SDK in requirements.txt yet.
--
-- Phase 2 (next PR): wire Claude Sonnet extractor, add anthropic SDK,
-- implement discover/download for the BSE filings index.
--
-- Phase 3: backfill top 200 tickers, integrate AR data into the analysis
-- service so segment data flows into conglomerate DCFs.
--
-- Schema rationale:
--   * (ticker, fiscal_year) is the natural dedupe key -- one AR per FY.
--     Re-extraction overwrites via UPSERT (handled in service).
--   * JSONB columns let us evolve the extraction schema without a
--     migration each iteration (extractor_version captures the shape).
--   * source CHECK keeps provenance machine-queryable.
--   * ar_pdf_sha256 lets us detect when an AR PDF is re-published with
--     fixes (audit corrections, errata) and trigger re-extraction.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.
--
-- Rollback:
--   DROP TABLE IF EXISTS company_annual_reports;

CREATE TABLE IF NOT EXISTS company_annual_reports (
  id BIGSERIAL PRIMARY KEY,
  ticker TEXT NOT NULL,
  fiscal_year INT NOT NULL,
  ar_url TEXT,
  ar_pdf_sha256 TEXT,
  source TEXT CHECK (source IN ('bse', 'nse', 'company_website', 'manual')),
  published_at DATE,
  ingested_at TIMESTAMPTZ DEFAULT now(),
  -- Extracted structured data (populated by extractor in Phase 2)
  segment_data JSONB,
  capex_commitments JSONB,
  auditor_flags JSONB,
  contingent_liabilities JSONB,
  related_party_transactions JSONB,
  mda_summary TEXT,
  extractor_version TEXT,
  UNIQUE (ticker, fiscal_year)
);

CREATE INDEX IF NOT EXISTS idx_company_ars_ticker
  ON company_annual_reports(ticker);

CREATE INDEX IF NOT EXISTS idx_company_ars_published
  ON company_annual_reports(published_at DESC);
