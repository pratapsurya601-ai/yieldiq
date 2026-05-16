-- 034_quarterly_cashflow_fields.sql
-- ─────────────────────────────────────────────────────────────────
-- Add half-yearly cash-flow columns to company_quarterly_results.
--
-- Why "half-yearly", not "quarterly":
--   Under SEBI LODR Reg 33, listed entities publish a cash-flow
--   statement only HALF-YEARLY (alongside Q2 / Sep and Q4 / Mar
--   results). Q1 / Q3 quarterly XBRL filings carry
--   `WhetherCashFlowStatementIsApplicableOnCompany = false` and
--   no cash-flow facts. So these columns are populated only on
--   ~50% of rows (the H1 + H2 prints).
--
-- Unit semantics:
--   `cfo_cr`, `cfi_cr`, `cff_cr`, `capex_cr` are values in ₹ Crores.
--   The amount represents the YTD cumulative cash flow from the
--   start of the FY through `period_end` (NOT a per-quarter flow):
--     * period_end = Sep 30 (Q2) → 6-month YTD (Apr-Sep) = H1 FY
--     * period_end = Mar 31 (Q4) → 12-month YTD (Apr-Mar) = FULL FY
--   The cumulative period length is recorded in
--   `cashflow_period_months` so the TTM aggregator knows how to
--   stitch H1 + previous-FY-H2 into a true trailing twelve months.
--   This matches the FourD-context convention documented in
--   data_pipeline/sources/nse_xbrl_fundamentals.py
--   (_detect_period_type_from_contexts).
--
-- `fcf_cr` is a STORED generated column. NULL-tolerant: PostgreSQL
-- arithmetic with NULL yields NULL, which is the right behaviour
-- (we'd rather show "missing" than silently treat capex as 0).
--
-- Companion flag `has_cashflow_statement` records whether the
-- filing's `WhetherCashFlowStatementIsApplicableOnCompany` was
-- 'true' regardless of whether the individual line items
-- populated — useful for diagnosing parser misses vs. genuinely
-- absent statements (e.g. small NBFC holdcos that file
-- `false` even on the half-year filings).
--
-- Idempotent: safe to re-run.
-- ─────────────────────────────────────────────────────────────────

ALTER TABLE company_quarterly_results
    ADD COLUMN IF NOT EXISTS cfo_cr                   NUMERIC,
    ADD COLUMN IF NOT EXISTS cfi_cr                   NUMERIC,
    ADD COLUMN IF NOT EXISTS cff_cr                   NUMERIC,
    ADD COLUMN IF NOT EXISTS capex_cr                 NUMERIC,
    ADD COLUMN IF NOT EXISTS cashflow_period_months   SMALLINT,
    ADD COLUMN IF NOT EXISTS has_cashflow_statement   BOOLEAN;

-- fcf_cr = cfo_cr - capex_cr. Generated column so callers can't
-- get it wrong (and so downstream SUM(fcf_cr) just works without
-- needing to know the derivation rule).
DO $$
BEGIN
    IF NOT EXISTS (
        SELECT 1
        FROM information_schema.columns
        WHERE table_name = 'company_quarterly_results'
          AND column_name = 'fcf_cr'
    ) THEN
        ALTER TABLE company_quarterly_results
            ADD COLUMN fcf_cr NUMERIC
            GENERATED ALWAYS AS (cfo_cr - capex_cr) STORED;
    END IF;
END $$;

-- Partial index: only the rows that actually carry cash-flow data
-- (~50% of all rows). Used by the TTM aggregator in
-- backend/services/quarterly_results_service.py::compute_ttm_from_xbrl
-- to pick the latest 2 half-year prints quickly.
CREATE INDEX IF NOT EXISTS ix_company_quarterly_results_cashflow_period_end
    ON company_quarterly_results (ticker, is_consolidated, period_end DESC)
    WHERE cfo_cr IS NOT NULL;

COMMENT ON COLUMN company_quarterly_results.cfo_cr IS
    'Cash flow from operating activities, H1 or H2 YTD in Cr. NULL on Q1/Q3 filings.';
COMMENT ON COLUMN company_quarterly_results.cfi_cr IS
    'Cash flow from investing activities, H1 or H2 YTD in Cr. NULL on Q1/Q3 filings.';
COMMENT ON COLUMN company_quarterly_results.cff_cr IS
    'Cash flow from financing activities, H1 or H2 YTD in Cr. NULL on Q1/Q3 filings.';
COMMENT ON COLUMN company_quarterly_results.capex_cr IS
    'Purchase of PP&E (capex), H1 or H2 YTD in Cr. NULL on Q1/Q3 filings.';
COMMENT ON COLUMN company_quarterly_results.fcf_cr IS
    'Generated: cfo_cr - capex_cr. Same YTD cumulative period as the input columns.';
COMMENT ON COLUMN company_quarterly_results.cashflow_period_months IS
    'Months of YTD cumulation in the cash-flow columns. 6 = H1 (Q2 print), 12 = full FY (Q4 print). NULL when cash flow absent.';
COMMENT ON COLUMN company_quarterly_results.has_cashflow_statement IS
    'Mirrors WhetherCashFlowStatementIsApplicableOnCompany from the XBRL. True for H1/H2 filings of companies that file under Reg 33.';
