-- 076_v_financials_unified.sql
--
-- Reconciliation view that unifies the two annual-financials tables:
--   - company_financials (new, XBRL-driven, tall: one row per
--     statement_type per (ticker, FY); shallow ~3 FYs; precise but with
--     a documented FY2024-stub populator bug)
--   - financials         (old, yfinance/screener backfill, wide: one row
--     per (ticker, period_end, period_type); deep 8-10 FYs; clean but
--     stale, no nightly refresh)
--
-- Per-cell preference (per (ticker, fiscal_year)):
--   1. Prefer company_financials when present AND non-corrupt.
--      "Corrupt" is defined precisely as:
--        (a) Duplicate (ticker_nse, fiscal_year) rows for the SAME
--            statement_type (the 41-ticker FY2024-stub cohort identified
--            in redesign/followups/financials-table-reconciliation.md
--            §1.2-1.3), OR
--        (b) revenue is NULL, OR
--        (c) revenue YoY magnitude > 50% versus the prior FY in the same
--            table (the CRISIL +342%, ABB +292%, DIXON +121% markers
--            from §1.2). The 50% threshold is the explicit corruption
--            marker called out in the reconciliation diagnosis.
--   2. Otherwise fall back to financials.
--   3. Emit a `source` column ('company_financials' | 'financials' |
--      'none') so downstream consumers can audit which side each row
--      came from.
--
-- The view is NON-LOAD-BEARING on creation: no consumer has been
-- rewired to read from it. That rewiring is a deliberate, separate
-- decision per option (C) in the reconciliation diagnosis §4 and is
-- tracked as a follow-up. Shipping the view first lets us validate the
-- shape and reconciliation logic against the live DB without putting
-- DCF / CAGR / hex_history on it before we're ready.
--
-- Fiscal-year convention: Indian FY ending March. fiscal_year =
-- EXTRACT(YEAR FROM period_end_date). FY2024 = period_end_date in
-- March 2024 = FY ending Mar-2024.
--
-- Idempotent: CREATE OR REPLACE VIEW.
--
-- Run against: Aiven Postgres (yieldiq Financials DB).
-- Apply with: psql "$AIVEN_DSN" -f 076_v_financials_unified.sql

BEGIN;

-- ---------------------------------------------------------------
-- Step 1: collapse company_financials (tall, 3 rows per FY) into
-- one wide row per (ticker, fiscal_year), and flag corruption.
-- ---------------------------------------------------------------
CREATE OR REPLACE VIEW v_company_financials_wide AS
WITH per_stmt AS (
    SELECT
        ticker_nse                              AS ticker,
        EXTRACT(YEAR FROM period_end_date)::INT AS fiscal_year,
        MAX(period_end_date)                    AS period_end,
        statement_type,
        currency,
        -- Income statement
        MAX(revenue)        AS revenue,
        MAX(ebitda)         AS ebitda,
        MAX(ebit)           AS ebit,
        MAX(pretax_income)  AS pretax_income,
        MAX(net_income)     AS net_income,
        MAX(eps_basic)      AS eps_basic,
        MAX(eps_diluted)    AS eps_diluted,
        -- Balance sheet
        MAX(total_assets)        AS total_assets,
        MAX(total_equity)        AS total_equity,
        MAX(total_debt)          AS total_debt,
        MAX(current_liabilities) AS current_liabilities,
        MAX(cash)                AS cash,
        MAX(net_debt)            AS net_debt,
        -- Cash flow
        MAX(operating_cf)    AS operating_cf,
        MAX(investing_cf)    AS investing_cf,
        MAX(financing_cf)    AS financing_cf,
        MAX(capex)           AS capex,
        MAX(free_cash_flow)  AS free_cash_flow,
        -- Corruption signal (a): duplicate rows at the
        -- (ticker, FY, statement_type) grain. The 41-ticker
        -- FY2024 cohort is this exact pattern.
        COUNT(*)             AS row_count_per_stmt
    FROM company_financials
    WHERE period_type = 'annual'
      AND period_end_date IS NOT NULL
    GROUP BY ticker_nse,
             EXTRACT(YEAR FROM period_end_date)::INT,
             statement_type,
             currency
),
collapsed AS (
    SELECT
        ticker,
        fiscal_year,
        MAX(period_end) AS period_end,
        MAX(currency)   AS currency,
        -- Coalesce across statement_type rows. revenue typically
        -- lives on income; balance-sheet fields on balance_sheet;
        -- cf fields on cashflow.
        MAX(revenue)             AS revenue,
        MAX(ebitda)              AS ebitda,
        MAX(ebit)                AS ebit,
        MAX(pretax_income)       AS pretax_income,
        MAX(net_income)          AS net_income,
        MAX(eps_basic)           AS eps_basic,
        MAX(eps_diluted)         AS eps_diluted,
        MAX(total_assets)        AS total_assets,
        MAX(total_equity)        AS total_equity,
        MAX(total_debt)          AS total_debt,
        MAX(current_liabilities) AS current_liabilities,
        MAX(cash)                AS cash,
        MAX(net_debt)            AS net_debt,
        MAX(operating_cf)        AS operating_cf,
        MAX(investing_cf)        AS investing_cf,
        MAX(financing_cf)        AS financing_cf,
        MAX(capex)               AS capex,
        MAX(free_cash_flow)      AS free_cash_flow,
        -- has_duplicate_fy = TRUE iff any statement_type for this
        -- (ticker, FY) has more than one row. This is the §1.2
        -- corruption marker (a).
        BOOL_OR(row_count_per_stmt > 1) AS has_duplicate_fy
    FROM per_stmt
    GROUP BY ticker, fiscal_year
)
SELECT
    c.ticker,
    c.fiscal_year,
    c.period_end,
    c.currency,
    c.revenue,
    c.ebitda,
    c.ebit,
    c.pretax_income,
    c.net_income,
    c.eps_basic,
    c.eps_diluted,
    c.total_assets,
    c.total_equity,
    c.total_debt,
    c.current_liabilities,
    c.cash,
    c.net_debt,
    c.operating_cf,
    c.investing_cf,
    c.financing_cf,
    c.capex,
    c.free_cash_flow,
    c.has_duplicate_fy,
    -- Corruption signal (c): |revenue YoY| > 0.50 vs prior FY in
    -- the SAME table. Compared on absolute ratio: a >50% jump in
    -- either direction. NULL prev_revenue (first observed FY) is
    -- treated as "not corrupt" -- we have no baseline to compare.
    LAG(c.revenue) OVER (PARTITION BY c.ticker ORDER BY c.fiscal_year)
        AS prev_revenue,
    CASE
        WHEN c.revenue IS NULL THEN TRUE                       -- (b)
        WHEN c.has_duplicate_fy THEN TRUE                      -- (a)
        WHEN LAG(c.revenue) OVER (PARTITION BY c.ticker ORDER BY c.fiscal_year) IS NULL
            THEN FALSE
        WHEN LAG(c.revenue) OVER (PARTITION BY c.ticker ORDER BY c.fiscal_year) = 0
            THEN FALSE
        WHEN ABS(
              (c.revenue
               - LAG(c.revenue) OVER (PARTITION BY c.ticker ORDER BY c.fiscal_year))
              / NULLIF(LAG(c.revenue) OVER (PARTITION BY c.ticker ORDER BY c.fiscal_year), 0)
            ) > 0.50
            THEN TRUE                                          -- (c)
        ELSE FALSE
    END AS is_corrupt
FROM collapsed c;

-- ---------------------------------------------------------------
-- Step 2: aggregate financials (already wide) at (ticker, FY) so
-- both sides have the same grain.
-- ---------------------------------------------------------------
CREATE OR REPLACE VIEW v_financials_wide AS
SELECT
    -- Strip .NS/.BO suffix to match company_financials.ticker_nse
    -- (which is normalized bare on write per db_writer.py).
    UPPER(REPLACE(REPLACE(ticker, '.NS', ''), '.BO', '')) AS ticker,
    EXTRACT(YEAR FROM period_end)::INT                    AS fiscal_year,
    MAX(period_end)                                       AS period_end,
    MAX(currency)                                         AS currency,
    -- Income
    MAX(revenue)        AS revenue,
    MAX(ebitda)         AS ebitda,
    MAX(ebit)           AS ebit,
    MAX(pbt)            AS pretax_income,
    MAX(pat)            AS net_income,
    MAX(eps_basic)      AS eps_basic,
    MAX(eps_diluted)    AS eps_diluted,
    -- Balance sheet
    MAX(total_assets)         AS total_assets,
    MAX(total_equity)         AS total_equity,
    MAX(total_debt)           AS total_debt,
    MAX(current_liabilities)  AS current_liabilities,
    MAX(cash_and_equivalents) AS cash,
    MAX(net_debt)             AS net_debt,
    -- Cash flow
    MAX(cfo)             AS operating_cf,
    MAX(cfi)             AS investing_cf,
    MAX(cff)             AS financing_cf,
    MAX(capex)           AS capex,
    MAX(free_cash_flow)  AS free_cash_flow
FROM financials
WHERE period_type != 'ttm'
  AND period_end IS NOT NULL
GROUP BY
    UPPER(REPLACE(REPLACE(ticker, '.NS', ''), '.BO', '')),
    EXTRACT(YEAR FROM period_end)::INT;

-- ---------------------------------------------------------------
-- Step 3: the unified view.
--
-- Per (ticker, fiscal_year): prefer company_financials when it
-- exists and is non-corrupt; otherwise fall back to financials.
-- Emit `source` so consumers (and tests) can audit the choice.
--
-- The 'reconciled_avg' enum value is reserved in the source
-- column vocabulary for future use (e.g. averaging two near-
-- agreeing values) but is not produced by this version of the
-- view -- the current per-cell rule is strictly pick-one.
-- ---------------------------------------------------------------
CREATE OR REPLACE VIEW v_financials_unified AS
WITH all_keys AS (
    SELECT ticker, fiscal_year FROM v_company_financials_wide
    UNION
    SELECT ticker, fiscal_year FROM v_financials_wide
)
SELECT
    k.ticker,
    k.fiscal_year,
    COALESCE(
        CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL
             THEN cf.period_end
        END,
        f.period_end
    )                                                              AS period_end,
    COALESCE(
        CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL
             THEN cf.currency
        END,
        f.currency
    )                                                              AS currency,
    -- Income
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.revenue        END, f.revenue)        AS revenue,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.ebitda         END, f.ebitda)         AS ebitda,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.ebit           END, f.ebit)           AS ebit,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.pretax_income  END, f.pretax_income)  AS pretax_income,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.net_income     END, f.net_income)     AS net_income,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.eps_basic      END, f.eps_basic)      AS eps_basic,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.eps_diluted    END, f.eps_diluted)    AS eps_diluted,
    -- Balance sheet
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.total_assets        END, f.total_assets)        AS total_assets,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.total_equity        END, f.total_equity)        AS total_equity,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.total_debt          END, f.total_debt)          AS total_debt,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.current_liabilities END, f.current_liabilities) AS current_liabilities,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.cash               END, f.cash)               AS cash,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.net_debt           END, f.net_debt)           AS net_debt,
    -- Cash flow
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.operating_cf    END, f.operating_cf)    AS operating_cf,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.investing_cf    END, f.investing_cf)    AS investing_cf,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.financing_cf    END, f.financing_cf)    AS financing_cf,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.capex           END, f.capex)           AS capex,
    COALESCE(CASE WHEN cf.is_corrupt IS NOT TRUE AND cf.ticker IS NOT NULL THEN cf.free_cash_flow  END, f.free_cash_flow)  AS free_cash_flow,
    -- Audit columns
    CASE
        WHEN cf.ticker IS NOT NULL AND cf.is_corrupt IS NOT TRUE THEN 'company_financials'
        WHEN f.ticker IS NOT NULL                                THEN 'financials'
        WHEN cf.ticker IS NOT NULL                               THEN 'financials'  -- cf was corrupt but no fallback row exists
        ELSE 'none'
    END                                              AS source,
    cf.has_duplicate_fy                              AS cf_has_duplicate_fy,
    cf.is_corrupt                                    AS cf_is_corrupt
FROM all_keys k
LEFT JOIN v_company_financials_wide cf
       ON cf.ticker = k.ticker AND cf.fiscal_year = k.fiscal_year
LEFT JOIN v_financials_wide f
       ON f.ticker = k.ticker AND f.fiscal_year = k.fiscal_year;

COMMIT;

-- ---------------------------------------------------------------
-- NOT IN THIS MIGRATION (per reconciliation diagnosis §4 option C):
--   * Re-pointing CAGR / financials_service / hex_history_service /
--     analysis/db.py to read v_financials_unified.
--   * Fixing the FY2024-stub populator bug in
--     data_pipeline/xbrl/db_writer.py.
--   * Hand-curated DELETE fixes for the 41 dup-FY2024 tickers and
--     the ~13 low-revenue FY2024 cases (§5).
-- The view is the deliverable; switching consumers is a deliberate
-- separate decision.
-- ---------------------------------------------------------------
