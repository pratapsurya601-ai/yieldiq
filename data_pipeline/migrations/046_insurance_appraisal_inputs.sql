-- 046_insurance_appraisal_inputs.sql
-- 2026-05-18 — Insurance Appraisal-Value engine (PR 1: data plumbing).
--
-- Stores operator-curated quarterly / half-yearly Embedded Value (EV)
-- and Value of New Business (VNB) disclosures from insurer IR reports
-- (Indian Embedded Value Report PDF, investor presentations).
--
-- Why: per docs/design/insurance-dcf-fix.md §3 (Approach A — Appraisal
-- Value), Indian life insurers must be valued by `FV = (EV + N×VNB) /
-- shares` rather than P/BV. The EV / VNB inputs are NOT auto-fetchable
-- (no free API; layouts vary year-to-year for PDF scraping) so the
-- product owner committed to a ~30 min/quarter manual data-entry
-- workflow via the admin UI. This table is that workflow's persistent
-- store; the admin endpoint in backend/routers/admin.py and the page
-- in frontend/src/app/(app)/admin/insurance/ write to / read from it.
--
-- Engine activation gate: the Appraisal Value engine in
-- backend/services/insurance_appraisal_service.py only routes the
-- ticker when a row exists in this table. Empty table → engine is a
-- no-op, current P/BV path remains. **No CACHE_VERSION bump required**
-- because the production analysis output is byte-identical until the
-- operator loads the first row of data.
--
-- Dual-path convention (see 025_corporate_actions_quality_rank.sql):
-- this file is mirrored at db/migrations/016_insurance_appraisal_inputs.sql.
--
-- Idempotent: CREATE TABLE / INDEX use IF NOT EXISTS so re-application
-- is safe.
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/046_insurance_appraisal_inputs.sql

CREATE TABLE IF NOT EXISTS insurance_appraisal_inputs (
    ticker                TEXT          NOT NULL,
    period_end            DATE          NOT NULL,
    embedded_value_cr     NUMERIC(14,2) NOT NULL,
    value_new_business_cr NUMERIC(14,2),
    vnb_margin_pct        NUMERIC(6,2),
    ev_growth_yoy_pct     NUMERIC(6,2),
    source_url            TEXT,
    entered_by            TEXT,
    entered_at            TIMESTAMP     NOT NULL DEFAULT NOW(),
    notes                 TEXT,
    PRIMARY KEY (ticker, period_end)
);

-- Lookup pattern is always "latest row per ticker", served by the
-- composite primary key descending on period_end.
CREATE INDEX IF NOT EXISTS ix_insurance_appraisal_ticker_period
    ON insurance_appraisal_inputs (ticker, period_end DESC);

COMMENT ON TABLE insurance_appraisal_inputs IS
    'Operator-curated quarterly EV/VNB disclosures from insurer IR PDFs. Read by backend/services/insurance_appraisal_service.py. Update workflow: docs/design/insurance-dcf-fix.md §8.4.';
COMMENT ON COLUMN insurance_appraisal_inputs.embedded_value_cr IS
    'Embedded Value in INR Crores (Adjusted Net Worth + Value of In-Force). Disclosed half-yearly in the Indian Embedded Value Report.';
COMMENT ON COLUMN insurance_appraisal_inputs.value_new_business_cr IS
    'VNB in INR Crores. Trailing-4-quarter sum preferred for full-year run-rate. Disclosed quarterly in investor presentations.';
COMMENT ON COLUMN insurance_appraisal_inputs.vnb_margin_pct IS
    'VNB margin = VNB / APE, in percent. Validation signal (insurer-disclosed; typical 22-28% for top-tier private life insurers).';
COMMENT ON COLUMN insurance_appraisal_inputs.ev_growth_yoy_pct IS
    'EV growth year-over-year, in percent. Used as one input to the Gordon-style N multiplier derivation.';
COMMENT ON COLUMN insurance_appraisal_inputs.source_url IS
    'Direct URL to the IR PDF or investor presentation the figures were taken from. Recommended but optional.';
COMMENT ON COLUMN insurance_appraisal_inputs.entered_by IS
    'Email of the admin user who created/last-updated this row.';
