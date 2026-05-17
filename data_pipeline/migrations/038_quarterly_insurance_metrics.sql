-- 038_quarterly_insurance_metrics.sql
-- ─────────────────────────────────────────────────────────────────
-- Add insurance-native quarterly metrics to company_quarterly_results.
--
-- Why a single JSONB column instead of one column per metric:
--   Life and general insurers report fundamentally different metrics:
--     * Life:   solvency_ratio, persistency_13/25/37/49/61, NBP,
--               first-year/renewal/single premium splits,
--               benefits_paid_net, surplus_deficit, commission, etc.
--     * General: solvency_ratio, combined_ratio, underwriting_profit,
--               gross_premiums_written, net_premiums_written,
--               premium_earned, claims_paid, etc.
--   The intersection is small (basically only solvency_ratio). Modelling
--   both as a fixed wide schema either bloats columns or forces nullable
--   fields per sub-sector that downstream consumers must learn to skip.
--   A JSONB blob keyed by metric name (the canonical XBRL local-name
--   re-cased to snake_case) is the lowest-friction shape for the
--   downstream P/EV and combined-ratio scoring axes that will land in
--   follow-up PRs.
--
-- Shape:
--   { "solvency_ratio": 1.92,
--     "persistency_13": 87.0, "persistency_25": 79.0, ...,         -- life
--     "gross_premium_income_cr": 16893.4, "first_year_premium_cr": ...,
--     "benefits_paid_net_cr": ...,
--     "combined_ratio": 102.4, "underwriting_profit_cr": -212.0,   -- general
--     "gross_premiums_written_cr": ...,
--     ...                                                           }
--   Keys are populated as-discovered by the parser; consumers must
--   treat absence as None. NEVER deep-clone or merge — overwrite on
--   upsert (the XBRL is the source of truth for its period).
--
-- Idempotent: safe to re-run.
-- ─────────────────────────────────────────────────────────────────

ALTER TABLE company_quarterly_results
    ADD COLUMN IF NOT EXISTS insurance_metrics JSONB;

COMMENT ON COLUMN company_quarterly_results.insurance_metrics IS
    'Sector-specific quarterly metrics for insurance filings (schema_type=insurance). NULL for industrial/banking rows. Keys per parser data_pipeline.sources.nse_quarterly_xbrl.INSURANCE_QUARTERLY_TAGS / INSURANCE_QUARTERLY_RATIO_TAGS (snake_case of XBRL local-name).';

-- Partial GIN index — only insurance rows carry the blob, so a partial
-- index keeps the structure small. Used by future Insurance-cohort
-- screeners (e.g. "list life insurers with solvency_ratio > 1.8").
CREATE INDEX IF NOT EXISTS ix_company_quarterly_results_insurance_metrics
    ON company_quarterly_results
    USING GIN (insurance_metrics)
    WHERE schema_type = 'insurance';
