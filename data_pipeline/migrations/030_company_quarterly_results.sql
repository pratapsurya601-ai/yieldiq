-- 030_company_quarterly_results.sql
--
-- Phase 2 of the AR/quarterly data plan: structured quarterly P&L
-- ingested directly from NSE's SEBI-mandated XBRL filings
-- (in-bse-fin namespace, Ind-AS 2020 schema). Source URL pattern:
--   listing: GET /api/corporates-financial-results?index=equities
--                 &symbol=<SYM>&period=Quarterly
--   xbrl:    direct nsearchives.nseindia.com URL in the listing's `xbrl` field
--
-- Stores ONE row per (ticker, fiscal_quarter, is_consolidated). The same
-- filing typically publishes BOTH a standalone + a consolidated view; we
-- keep both because downstream analytics (segment depth, holdings ratios)
-- may want either.

CREATE TABLE IF NOT EXISTS company_quarterly_results (
    id BIGSERIAL PRIMARY KEY,
    ticker TEXT NOT NULL,
    fiscal_quarter TEXT NOT NULL,   -- e.g. 'Q3 FY25'
    period_start DATE NOT NULL,
    period_end DATE NOT NULL,
    is_consolidated BOOLEAN NOT NULL,
    is_audited BOOLEAN,
    is_single_segment BOOLEAN,

    -- P&L core (in ₹ Crores)
    revenue_cr NUMERIC,
    other_income_cr NUMERIC,
    total_expenses_cr NUMERIC,
    profit_before_tax_cr NUMERIC,
    tax_expense_cr NUMERIC,
    net_profit_cr NUMERIC,
    comprehensive_income_cr NUMERIC,

    -- P&L expense breakdown
    employee_benefit_cr NUMERIC,
    finance_costs_cr NUMERIC,
    depreciation_cr NUMERIC,
    other_expenses_cr NUMERIC,      -- top-line "Other Expenses" rollup

    -- Per-share
    basic_eps NUMERIC,
    diluted_eps NUMERIC,
    face_value NUMERIC,
    paid_up_capital_cr NUMERIC,

    -- Detail JSON
    other_expense_breakdown JSONB,  -- [{description, amount_cr}, ...]
    oci_items JSONB,                -- [{kind, description, amount_cr}, ...]

    -- Provenance
    xbrl_url TEXT,
    xbrl_sha256 TEXT,
    filed_at TIMESTAMPTZ,
    ingested_at TIMESTAMPTZ DEFAULT now(),

    UNIQUE (ticker, fiscal_quarter, is_consolidated)
);

CREATE INDEX IF NOT EXISTS idx_cqr_ticker ON company_quarterly_results(ticker);
CREATE INDEX IF NOT EXISTS idx_cqr_period_end ON company_quarterly_results(period_end DESC);
