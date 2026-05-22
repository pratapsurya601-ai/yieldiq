-- Day-103b (2026-05-22): annual_reports — per-ticker AR filing index.
--
-- Lightweight, link-only table that powers the AnnualReportsPanel on
-- the stock analysis page (Screener.in parity — they ship FY12+ AR
-- links going back ~13 years, which Day-102 flagged as a top-3 gap).
--
-- Decoupled from `company_annual_reports` (migration 027), which is
-- the rich Claude-extracted structured-data table (segment_data,
-- capex commitments, auditor flags, etc.). That table is heavy and
-- Phase-2 backfill-only; this one is just a URL index we can ship
-- today and ingest from the BSE filings index in a follow-up.
--
-- One row per (ticker, fiscal_year). Latest 5 visible by default in
-- the UI, "Show all" expands.

CREATE TABLE IF NOT EXISTS annual_reports (
    id           SERIAL PRIMARY KEY,
    ticker       TEXT NOT NULL,
    fiscal_year  INT  NOT NULL,
    filed_date   DATE,
    source_url   TEXT NOT NULL,
    created_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT annual_reports_ticker_fy_uq UNIQUE (ticker, fiscal_year)
);

CREATE INDEX IF NOT EXISTS annual_reports_ticker_fy_idx
    ON annual_reports (ticker, fiscal_year DESC);
