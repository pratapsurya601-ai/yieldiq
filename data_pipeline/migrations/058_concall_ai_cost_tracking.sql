-- 058_concall_ai_cost_tracking.sql
-- 2026-05-23 — Phase G-cost: per-row LLM token + USD spend tracking
--
-- Why this exists:
--   Day-104b added a lazy AI-summary cache to concall_transcripts via
--   Groq Llama 3.3 70B. We have no visibility into per-row spend, no
--   running batch total, and no way for the backfill operator to cap
--   cost at a budget. Phase G-cost adds three additive columns and
--   wires the Groq response's `usage` block into them.
--
--   Phase G-intel-phase1 will add a separate (more expensive)
--   Anthropic-driven structured signal extraction on top of the same
--   transcript_text. That phase records its own spend on the
--   concall_signals row (out of scope for this migration).
--
-- Schema rationale:
--   - All three columns are NULL-by-default and apply only to NEW or
--     re-summarised rows. We do NOT backfill costs for historic rows
--     (those summaries were already paid for; the cost is sunk).
--   - ai_cost_usd is NUMERIC(8,4) — supports up to $9999.9999 per row,
--     four decimal places. Realistic per-row cost on Llama 3.3 70B is
--     ~$0.0008-$0.005 so four decimals is the right precision.
--   - Token counts are nullable INTEGER (BIGINT not needed; Groq
--     responses never exceed ~64k tokens per call).
--
-- Idempotent: ADD COLUMN IF NOT EXISTS.
--
-- Rollback (only if absolutely needed — additive columns are cheap):
--   ALTER TABLE concall_transcripts
--       DROP COLUMN IF EXISTS ai_input_tokens,
--       DROP COLUMN IF EXISTS ai_output_tokens,
--       DROP COLUMN IF EXISTS ai_cost_usd;

ALTER TABLE concall_transcripts
    ADD COLUMN IF NOT EXISTS ai_input_tokens  INTEGER,
    ADD COLUMN IF NOT EXISTS ai_output_tokens INTEGER,
    ADD COLUMN IF NOT EXISTS ai_cost_usd      NUMERIC(8, 4);
