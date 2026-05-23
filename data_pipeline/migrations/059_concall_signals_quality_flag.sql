-- 059_concall_signals_quality_flag.sql
-- 2026-05-23 — Phase G-intel-phase1: SEBI sanitizer flag + cost tracking
--
-- Why this exists:
--   Phase G-intel-phase1 promotes the Phase-0 concall_intel_service
--   scaffold to live Anthropic-driven structured signal extraction.
--   The LLM output is JSON-schema-validated, but banned vocabulary
--   ('buy', 'sell', 'strong', 'recommend', ...) can still appear in
--   string leaf values (key_quotes, management_tone). When the
--   JSON-walker sanitizer flags any banned word, we persist the row
--   with quality_flag='sebi_withheld' instead of dropping it on the
--   floor — operator can review later and re-extract with a tighter
--   prompt if the false-positive rate is high.
--
--   We also persist Anthropic spend per row so the operator can budget
--   the wider rollout. Anthropic Sonnet pricing ($3/$15 per Mtoken) is
--   ~10x Groq, so cost discipline matters more here than on the
--   summary path.
--
-- Schema additions (all nullable, additive — no risk to existing rows):
--   quality_flag      TEXT — 'ok' | 'sebi_withheld' | NULL (legacy rows)
--   transcript_id     INT  — FK-style link to concall_transcripts.id
--                            so we can trace which transcript produced
--                            this row. Not enforced as a real FK to
--                            keep this migration drop-safe.
--   ai_input_tokens   INT
--   ai_output_tokens  INT
--   ai_cost_usd       NUMERIC(8,4)
--
-- Index on (quality_flag) for the admin "review withheld signals" view.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS, CREATE INDEX IF NOT EXISTS.

ALTER TABLE concall_signals
    ADD COLUMN IF NOT EXISTS quality_flag      TEXT,
    ADD COLUMN IF NOT EXISTS transcript_id     INTEGER,
    ADD COLUMN IF NOT EXISTS ai_input_tokens   INTEGER,
    ADD COLUMN IF NOT EXISTS ai_output_tokens  INTEGER,
    ADD COLUMN IF NOT EXISTS ai_cost_usd       NUMERIC(8, 4);

CREATE INDEX IF NOT EXISTS idx_concall_signals_quality_flag
    ON concall_signals (quality_flag)
    WHERE quality_flag IS NOT NULL;

CREATE INDEX IF NOT EXISTS idx_concall_signals_transcript_id
    ON concall_signals (transcript_id)
    WHERE transcript_id IS NOT NULL;
