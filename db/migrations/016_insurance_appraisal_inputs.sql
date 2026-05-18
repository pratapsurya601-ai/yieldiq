-- 016_insurance_appraisal_inputs.sql
-- Mirror of data_pipeline/migrations/046_insurance_appraisal_inputs.sql.
-- See that file for the authoritative comments and rationale.
--
-- Dual-path convention (see 010_corporate_actions_quality_rank.sql):
-- the db/migrations/ tree mirrors data_pipeline/migrations/ for the
-- supabase-managed CI path. Schema kept identical.

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

CREATE INDEX IF NOT EXISTS ix_insurance_appraisal_ticker_period
    ON insurance_appraisal_inputs (ticker, period_end DESC);
