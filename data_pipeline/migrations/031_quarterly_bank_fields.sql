-- 031_quarterly_bank_fields.sql
--
-- Add banking-specific columns to company_quarterly_results (created in
-- migration 030). Additive only — no DROP, no DELETE. Safe to apply on
-- a live DB that already contains industrial rows.
--
-- These columns are populated by data_pipeline/sources/nse_quarterly_xbrl.py
-- when the source XBRL is in the `in-bse-fin-bnk` schema. For industrial
-- filings they stay NULL.

ALTER TABLE company_quarterly_results
    ADD COLUMN IF NOT EXISTS interest_earned_cr   NUMERIC,
    ADD COLUMN IF NOT EXISTS interest_expended_cr NUMERIC,
    ADD COLUMN IF NOT EXISTS operating_profit_cr  NUMERIC,
    ADD COLUMN IF NOT EXISTS provisions_cr        NUMERIC,
    ADD COLUMN IF NOT EXISTS schema_type          TEXT;  -- 'industrial' | 'banking' | 'insurance'

CREATE INDEX IF NOT EXISTS idx_cqr_schema_type
    ON company_quarterly_results(schema_type);

COMMENT ON COLUMN company_quarterly_results.schema_type IS
    'XBRL schema used to parse this row. industrial = in-bse-fin, banking = in-bse-fin-bnk, insurance = in-bse-fin-ins (not yet supported).';
