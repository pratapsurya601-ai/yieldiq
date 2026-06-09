-- 202606091210_eli15_thesis_cache.sql
-- =================================================================
-- ELI15 thesis cache — persists the 3-bullet AI explainer per
-- (ticker, model_version, prompt_version, generated_date).
--
-- Read by GET /api/v1/analysis/{ticker}/eli15-thesis on the hot
-- path; duplicate same-day requests hit this table instead of
-- re-calling Claude. Day-granularity TTL — the underlying analysis
-- moves on the order of hours/days and Anthropic cost matters at
-- scale.
--
-- Schema:
--   * ticker             text                  — canonicalized symbol
--   * model_version      text                  — eli15-thesis-vN-anthropic-YYYY-MM-DD
--   * prompt_version     int                   — bump when system prompt changes
--   * generated_date     date                  — day key (IST)
--   * bullets            jsonb (list of text)  — exactly 3, SEBI-filtered
--   * verdict            text                  — wire-format enum
--   * verdict_display    text                  — neutral display label
--   * source             text                  — llm_first | llm_retry | template | template_no_llm
--   * sanitizer_hits     jsonb (list of text)  — audit trail for SEBI trips
--   * generated_at       timestamptz           — exact write time (UTC)
--
-- Primary key composite enforces the cache key contract; the
-- (ticker, generated_date) lookup index optimises the warm-cache
-- read path which doesn't constrain on model/prompt version when
-- the caller wants "any thesis from today, any version".
-- =================================================================

BEGIN;

CREATE TABLE IF NOT EXISTS eli15_thesis_cache (
    ticker          TEXT        NOT NULL,
    model_version   TEXT        NOT NULL,
    prompt_version  INTEGER     NOT NULL,
    generated_date  DATE        NOT NULL,
    bullets         JSONB       NOT NULL,
    verdict         TEXT        NOT NULL DEFAULT '',
    verdict_display TEXT        NOT NULL DEFAULT '',
    source          TEXT        NOT NULL DEFAULT '',
    sanitizer_hits  JSONB       NOT NULL DEFAULT '[]'::jsonb,
    generated_at    TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (ticker, model_version, prompt_version, generated_date)
);

-- Lookup-by-ticker hot path: callers ask for today's thesis under
-- the current model/prompt; a btree on (ticker, generated_date)
-- collapses the PK scan to a single row.
CREATE INDEX IF NOT EXISTS ix_eli15_thesis_cache_ticker_date
    ON eli15_thesis_cache (ticker, generated_date DESC);

COMMIT;
