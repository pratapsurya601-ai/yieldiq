-- SUPERSEDED 2026-05-22 by Day-103d schema-refactor.
-- This table was created in error — existing infrastructure already
-- covered this concern via concall_transcripts (010) / company_annual_reports (027).
-- DO NOT apply this migration to new Neon instances. The Day-103d service
-- refactor retargets the panel endpoints at the canonical tables.
-- See docs/design/day103d-schema-cleanup-2026-05-22.md

BEGIN;

-- Migration 051 (Day-103a): concalls — ticker-level earnings call library
-- with AI-generated structured summaries.
--
-- Context: Day-102 competitive audit flagged that Screener.in carries
-- 28+ concall transcripts per stock going back to 2018 and surfaces them
-- prominently. This is their biggest depth advantage. To close the gap
-- without taking on their entire pipeline, we add a slim public-facing
-- library that pairs each transcript URL with a cached AI-generated
-- structured summary so users get the gist on-page even before they
-- click through to the source PDF.
--
-- This is a NEW table, separate from `concall_transcripts` (migration
-- 009) which stores raw NSE corporate-announcement filings. That table
-- is keyed on (ticker, filing_date, subject) and is populated by the
-- weekly NSE crawler; it has no transcript text or summaries. The
-- `concalls` table here is the curated library surface where each row
-- represents one quarterly call with stable period semantics
-- ("FY26-Q4"), a single canonical source_url, and an AI summary that
-- is computed once and cached forever (until the model is upgraded).
--
-- Ingestion of real concall rows from the BSE filing index is a
-- follow-up task. Until that lands, the public endpoint returns an
-- empty list for everyone except the few seed rows in 051a.
--
-- Rollback:
--   DROP TABLE IF EXISTS concalls;

CREATE TABLE IF NOT EXISTS concalls (
    id                       SERIAL PRIMARY KEY,
    ticker                   TEXT NOT NULL,
    period                   TEXT NOT NULL,
    concall_date             DATE,
    source_url               TEXT NOT NULL,
    transcript_text          TEXT,
    ai_summary               TEXT,
    ai_summary_model         TEXT,
    ai_summary_generated_at  TIMESTAMPTZ,
    created_at               TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_concalls_ticker_period UNIQUE (ticker, period)
);

CREATE INDEX IF NOT EXISTS idx_concalls_ticker_date
    ON concalls (ticker, concall_date DESC);

COMMIT;
