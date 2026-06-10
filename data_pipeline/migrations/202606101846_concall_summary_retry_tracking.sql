-- 202606101846_concall_summary_retry_tracking.sql
-- =================================================================
-- ROOT CAUSE #10 — Concall AI summary cache missing for HDFCBANK
-- Q1-FY26 (and likely other tickers in the Phase G/H/I backfill
-- in-progress sweep).
--
-- Today: populate_concall_summary persists '(summary unavailable)'
-- as the ai_summary value on any failure (PDF fetch dies, extracted
-- text < 200 chars, Groq returns empty). The next list_concalls call
-- sees a non-null ai_summary and short-circuits — the row is now
-- silently permanent-failed with no operator visibility.
--
-- Fix:
--   1. Add `ai_summary_attempts` counter so the retry workflow can
--      distinguish "never tried" from "tried 3x, gave up".
--   2. Add `ai_summary_last_attempt_at` for staleness audits.
--   3. Add `concall_ai_summaries_failed` dead-letter table so each
--      permanent-failure carries a structured reason the operator
--      can act on (network 503, oversize PDF, SEBI vocab withheld).
--
-- The frontend ConcallPanel will read the new failure surface and
-- render "Summary generation failed — see transcript" instead of
-- the bare "(summary unavailable)" placeholder.
--
-- Canary impact: schema-only adds. NO writes to existing data;
-- legacy rows that already carry the placeholder will continue to
-- render the old text until the next retry sweep overwrites them.
-- =================================================================

BEGIN;

-- 1. Per-row retry tracking on concall_transcripts.
ALTER TABLE concall_transcripts
    ADD COLUMN IF NOT EXISTS ai_summary_attempts INTEGER NOT NULL DEFAULT 0,
    ADD COLUMN IF NOT EXISTS ai_summary_last_attempt_at TIMESTAMPTZ NULL;

-- 2. Dead-letter table for permanent failures. One row per failed
-- (concall_transcripts.id, reason) pair. The retry workflow inserts
-- here when ai_summary_attempts crosses the threshold (default 3).
CREATE TABLE IF NOT EXISTS concall_ai_summaries_failed (
    id BIGSERIAL PRIMARY KEY,
    concall_id INTEGER NOT NULL,
    ticker VARCHAR(20) NOT NULL,
    period VARCHAR(20) NULL,
    filing_date DATE NULL,
    reason VARCHAR(64) NOT NULL,
    detail TEXT NULL,
    attempts INTEGER NOT NULL DEFAULT 1,
    first_failed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_failed_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT chk_concall_failure_reason
        CHECK (reason IN (
            'pdf_fetch_failed',
            'pdf_oversize',
            'pdf_extract_empty',
            'transcript_too_short',
            'groq_unavailable',
            'groq_empty_output',
            'sebi_withheld',
            'unknown'
        ))
);

CREATE UNIQUE INDEX IF NOT EXISTS ux_concall_failed_id_reason
    ON concall_ai_summaries_failed (concall_id, reason);

CREATE INDEX IF NOT EXISTS ix_concall_failed_ticker
    ON concall_ai_summaries_failed (ticker, last_failed_at DESC);

COMMIT;
