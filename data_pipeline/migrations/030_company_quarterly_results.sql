-- 030_company_quarterly_results.sql
-- ─────────────────────────────────────────────────────────────────
-- Per-quarter P&L parsed from NSE XBRL (Ind AS).
--
-- One row per (ticker, period_end, is_consolidated). Sole reader
-- today is backend/services/quarterly_results_service.py, which
-- prefers consolidated rows (financial reality of a group) and
-- falls back to standalone when no consolidated filing exists.
--
-- NOTE on `fiscal_quarter`: the labels currently in the table are
-- off-by-one-year for Apr-Dec quarters (e.g. 2024-09-30 is tagged
-- "Q2 FY24" but should be "Q2 FY25"). Always sort and filter by
-- `period_end` — never derive the FY from the label string. The
-- ingestion job will be patched in a follow-up; this is documented
-- in the field comment below so no one re-introduces the bug from
-- the read side.
--
-- Idempotent: safe to re-run on environments where the table was
-- created out-of-band before this migration landed.
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS company_quarterly_results (
    id                      BIGSERIAL PRIMARY KEY,
    ticker                  TEXT        NOT NULL,
    fiscal_quarter          TEXT,        -- DO NOT TRUST for FY math; see header.
    period_start            DATE,
    period_end              DATE        NOT NULL,
    is_consolidated         BOOLEAN     NOT NULL,
    is_audited              BOOLEAN,
    is_single_segment       BOOLEAN,
    revenue_cr              NUMERIC,
    other_income_cr         NUMERIC,
    total_expenses_cr       NUMERIC,
    profit_before_tax_cr    NUMERIC,
    tax_expense_cr          NUMERIC,
    net_profit_cr           NUMERIC,
    comprehensive_income_cr NUMERIC,
    employee_benefit_cr     NUMERIC,
    finance_costs_cr        NUMERIC,
    depreciation_cr         NUMERIC,
    other_expenses_cr       NUMERIC,
    basic_eps               NUMERIC,
    diluted_eps             NUMERIC,
    face_value              NUMERIC,
    paid_up_capital_cr      NUMERIC,
    other_expense_breakdown JSONB,
    oci_items               JSONB,
    xbrl_url                TEXT,
    xbrl_sha256             TEXT,
    filed_at                TIMESTAMPTZ,
    ingested_at             TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, period_end, is_consolidated)
);

CREATE INDEX IF NOT EXISTS ix_company_quarterly_results_ticker_period_end
    ON company_quarterly_results (ticker, period_end DESC);

CREATE INDEX IF NOT EXISTS ix_company_quarterly_results_ticker_consolidated_period_end
    ON company_quarterly_results (ticker, is_consolidated, period_end DESC);
