-- Migration 026: concall_signals table
--
-- Stores STRUCTURED SIGNALS extracted from earnings call transcripts via
-- an LLM (Claude API in the planned Phase 1 activation). Distinct from
-- migration 010 (concall_transcripts) which only stores the link/metadata
-- of a transcript filing -- this table stores the analyst-grade extracted
-- signals (guidance, capex, margins, tone, key quotes) per fiscal period.
--
-- Phase 0 (this migration): schema only. The extractor service is a stub
-- and there is NO live LLM call wired up. A follow-up phase will add the
-- anthropic SDK dependency, the extraction pipeline, and the router.
--
-- Schema rationale:
--   - (ticker, fiscal_period) is the natural dedupe key -- one extraction
--     per call. Re-extraction overwrites via UPSERT (handled in service).
--   - JSONB columns let us evolve the extraction schema without a
--     migration each iteration (extractor_version captures the shape).
--   - management_tone is a CHECK-constrained enum to keep dashboards sane.
--   - extractor_version lets us re-run extractions with newer prompts and
--     diff against older signals.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.
--
-- Rollback:
--   DROP TABLE IF EXISTS concall_signals;

CREATE TABLE IF NOT EXISTS concall_signals (
  id SERIAL PRIMARY KEY,
  ticker TEXT NOT NULL,
  fiscal_period TEXT NOT NULL,  -- e.g. "Q1FY26"
  concall_date DATE NOT NULL,
  transcript_source TEXT,
  guidance_changes JSONB,
  capex_commitments JSONB,
  margin_commentary JSONB,
  management_tone TEXT CHECK (management_tone IN ('bullish','neutral','cautious','defensive')),
  key_quotes JSONB,
  extracted_at TIMESTAMPTZ DEFAULT now(),
  extractor_version TEXT,
  UNIQUE (ticker, fiscal_period)
);

CREATE INDEX IF NOT EXISTS idx_concall_signals_ticker
  ON concall_signals(ticker);

CREATE INDEX IF NOT EXISTS idx_concall_signals_date
  ON concall_signals(concall_date DESC);
