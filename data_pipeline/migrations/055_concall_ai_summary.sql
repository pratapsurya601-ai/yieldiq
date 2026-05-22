-- Day-104b: add AI summary cache columns to concall_transcripts.
-- ai_summary populated lazily on first list_concalls request that
-- finds a row with pdf_url but no summary. Groq cost is ~$0.001 per
-- summary so we cache aggressively.
--
-- transcript_text caches the parsed PDF text so we don't re-fetch +
-- re-parse if Groq errors after a successful PDF extraction.
--
-- Idempotent.
ALTER TABLE concall_transcripts
    ADD COLUMN IF NOT EXISTS ai_summary TEXT,
    ADD COLUMN IF NOT EXISTS ai_summary_model TEXT,
    ADD COLUMN IF NOT EXISTS ai_summary_generated_at TIMESTAMPTZ,
    ADD COLUMN IF NOT EXISTS transcript_text TEXT;
