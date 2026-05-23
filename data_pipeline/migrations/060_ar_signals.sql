-- Migration 060: ar_signals -- Phase H-schema (Block II).
--
-- Structured-signal extraction surface for annual reports. Mirrors
-- the migration-059 concall_signals shape one level up: a versioned
-- per-extraction row keyed off company_annual_reports (migration 027).
--
-- WHY a SEPARATE TABLE from company_annual_reports?
--   * 027 doubles as the AR INDEX (ticker, fiscal_year, ar_url,
--     ar_pdf_sha256, source, published_at). Its JSONB columns
--     (segment_data, capex_commitments, ...) are Phase-0 stubs
--     that were never populated.
--   * Phase H extracts via Anthropic Sonnet 4.5 and needs:
--     - re-extraction without losing history (model_version /
--       prompt_version + the UNIQUE on the triple);
--     - SEBI quality_flag so the public endpoint can withhold
--       free-text fields when the sanitizer fires;
--     - per-row cost tracking (input/output tokens + $cost) for
--       the operator cost meter.
--   ar_signals carries all of that. company_annual_reports stays
--   the canonical AR-link table; the Phase-0 JSONB columns there
--   are now informational / legacy.
--
-- Schema rationale:
--   * annual_report_id -> company_annual_reports.id with ON DELETE
--     CASCADE so dropping an AR cleans up its signal rows.
--   * Six JSONB extraction columns mirror the spec.
--   * management_outlook is a short TEXT narrative (<= 2000 chars
--     enforced in the service, not the DB) -- this is the only
--     free-text column.
--   * quality_flag enum-by-CHECK so a typo at write-time fails fast.
--   * model_version + prompt_version make the unique key
--     (annual_report_id, model_version, prompt_version) so the
--     operator can re-extract with a new prompt and keep both rows.
--   * cost_usd NUMERIC(8,4) -- four decimals lets us track
--     sub-cent variance; 9999.9999 USD max is well above any
--     plausible single-AR spend.
--
-- Idempotent: CREATE TABLE / CREATE INDEX IF NOT EXISTS.
--
-- Rollback:
--   DROP TABLE IF EXISTS ar_signals;
--
-- No CACHE_VERSION bump needed -- ar_signals is read-side only;
-- the cache-invalidation manifest entry for this surface goes in
-- the H-frontend PR (`v_phase_h_ar_signals_2026_05_26`).

CREATE TABLE IF NOT EXISTS ar_signals (
    id                          BIGSERIAL PRIMARY KEY,
    annual_report_id            BIGINT NOT NULL
        REFERENCES company_annual_reports(id) ON DELETE CASCADE,

    -- Six extracted JSONB sections (shapes documented in
    -- backend/services/ar_intel_service.py).
    segment_data                JSONB,
    capex_commitments           JSONB,
    related_party_transactions  JSONB,
    auditor_flags               JSONB,
    contingent_liabilities      JSONB,

    -- Short narrative -- the only free-text column. Service caps
    -- length and runs it through the SEBI sanitizer.
    management_outlook          TEXT,

    -- SEBI-discipline column. 'ok' on a clean walk;
    -- 'sebi_withheld' when the JSON sanitizer flagged a banned
    -- word; 'extraction_failed' when the LLM call or schema
    -- validation failed and the row is a placeholder for cost
    -- accounting only.
    quality_flag                TEXT NOT NULL DEFAULT 'ok'
        CHECK (quality_flag IN ('ok', 'sebi_withheld', 'extraction_failed')),

    -- Versioning + cost tracking.
    model_version               TEXT NOT NULL,
    prompt_version              INTEGER NOT NULL,
    input_tokens                INTEGER,
    output_tokens               INTEGER,
    cost_usd                    NUMERIC(8,4),

    extracted_at                TIMESTAMPTZ NOT NULL DEFAULT now(),

    UNIQUE (annual_report_id, model_version, prompt_version)
);

CREATE INDEX IF NOT EXISTS idx_ar_signals_ar
    ON ar_signals (annual_report_id);

CREATE INDEX IF NOT EXISTS idx_ar_signals_extracted_at
    ON ar_signals (extracted_at DESC);

COMMENT ON TABLE ar_signals IS
    'Phase H: structured Anthropic-extracted signals from annual reports. '
    'See backend/services/ar_intel_service.py for the JSONB shapes and '
    'the SEBI sanitizer that decides quality_flag.';
