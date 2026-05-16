-- 036_bse_source_column.sql
-- ─────────────────────────────────────────────────────────────────
-- Tag the source venue of each company_quarterly_results row so we
-- can tell apart rows ingested from NSE XBRL listings vs. rows
-- scraped from BSE corporate-filings pages (Playwright path, used
-- for the ~96 BSE-only Group A+B legit tickers).
--
-- Default 'nse' is correct for every row already in the table
-- (migration 030 onward populated exclusively from
-- scripts/backfill_nse_quarterly_xbrl.py).
--
-- Idempotent: safe to re-run.
-- ─────────────────────────────────────────────────────────────────

ALTER TABLE company_quarterly_results
  ADD COLUMN IF NOT EXISTS source TEXT DEFAULT 'nse';

CREATE INDEX IF NOT EXISTS idx_cqr_source
  ON company_quarterly_results(source);

COMMENT ON COLUMN company_quarterly_results.source IS
  'Ingest venue: ''nse'' (NSE corporates-financial-results API, default) '
  'or ''bse'' (BSE Comp_Resultsnew Playwright scrape, used for BSE-only '
  'tickers like SPICEJET/TANFAC/JYOTIRES). See data_pipeline.sources.'
  'bse_quarterly_xbrl for the BSE ingest path.';
