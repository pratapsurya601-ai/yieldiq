-- Migration 061: bank_operational_kpis -- Phase I-schema (Block II).
--
-- Per-bank operational metrics surface for the ~38-ticker commercial
-- bank universe defined by _PURE_BANK_TICKERS_FOR_DE in
-- backend/services/analysis/sector_overrides.py.
--
-- WHY a SEPARATE TABLE from company_financials / ratio_history?
--   * company_financials carries cross-sector XBRL fields. The
--     bank-specific operational KPIs (GNPA, NNPA, PCR, CASA,
--     branches, ATMs, customer base, cost-to-income, credit-deposit)
--     have no natural home in either generic surface -- they map to
--     RBI / NSE / BSE XBRL Schedules V / VII / XI / XVIII that are
--     not extracted today, plus AR-PDF "performance highlights"
--     sections for branches / ATMs / customers.
--   * Phase I ingest fills this table from TWO independent sources
--     (BSE quarterly XBRL for the financial KPIs, Anthropic-extracted
--     AR PDFs for the operational KPIs). The (ticker, period_end,
--     period_type, source) UNIQUE key lets both paths coexist
--     without one clobbering the other.
--   * The frontend BankKpiPanel surfaces the most recent annual row
--     plus a last-4-quarter trend per metric -- read straight off
--     this table.
--
-- See docs/diagnostics/phase-i-bank-kpi-coverage-2026-05-26.md for
-- the gap analysis that gates this migration. Verdict: RESCOPE
-- (proceed with narrowed initial scope) -- 90% of these KPIs have
-- no source today; this migration creates the destination, and the
-- two I-ingest PRs populate it incrementally over time via the
-- operator workflow.
--
-- Idempotent: CREATE TABLE / CREATE INDEX IF NOT EXISTS.
--
-- Rollback:
--   DROP TABLE IF EXISTS bank_operational_kpis;
--
-- No CACHE_VERSION bump needed -- this surface is read-side only
-- and additive. The cache-invalidation manifest entry for the
-- frontend exposure (`v_phase_i_bank_kpis_2026_05_26`) goes in
-- the I-frontend PR.

CREATE TABLE IF NOT EXISTS bank_operational_kpis (
    id                  BIGSERIAL PRIMARY KEY,
    ticker              TEXT NOT NULL,
    period_end          DATE NOT NULL,
    period_type         TEXT NOT NULL
        CHECK (period_type IN ('quarterly', 'annual')),

    -- Operational KPIs (AR-sourced; nullable until I-ingest-b lands)
    branches_total      INTEGER,
    branches_tier1      INTEGER,
    branches_tier2      INTEGER,
    branches_tier3      INTEGER,
    atms_total          INTEGER,
    customers_millions  NUMERIC(8,2),

    -- Asset-quality + balance-sheet ratios (XBRL-sourced; nullable
    -- until I-ingest-a lands).
    --
    -- All "_pct" columns are PERCENTAGES (0.00 - 100.000) for direct
    -- frontend rendering -- NOT decimals. The cohort helpers in
    -- sector_overrides.py auto-detect decimal vs. percent via the
    -- >1 heuristic, so callers reading from this table do not need
    -- to renormalise. NUMERIC(6,3) accommodates e.g. 100.000 with
    -- three decimals of precision (sufficient for GNPA / PCR which
    -- typically run 0.5 - 12.0 with two decimals of precision in
    -- disclosure).
    gnpa_pct            NUMERIC(6,3),
    nnpa_pct            NUMERIC(6,3),
    pcr_pct             NUMERIC(6,3),
    casa_pct            NUMERIC(6,3),
    cost_to_income_pct  NUMERIC(6,3),
    credit_deposit_pct  NUMERIC(6,3),

    -- Source provenance. 'source' is a short identifier
    -- ('bse_xbrl_sch_xviii', 'bse_xbrl_sch_v', 'ar_anthropic',
    -- 'manual') chosen by the ingest script; 'source_url' is the
    -- specific XBRL filing URL or AR PDF URL the row was extracted
    -- from. Both are kept for audit-trail + operator debugging when
    -- a row looks wrong.
    source              TEXT NOT NULL,
    source_url          TEXT,
    extracted_at        TIMESTAMPTZ NOT NULL DEFAULT now(),

    -- One row per (ticker, period_end, period_type, source). Two
    -- sources for the same ticker/period coexist (e.g. quarterly
    -- BSE XBRL row for the financial KPIs AND the annual AR row
    -- for the operational KPIs both land independently). The
    -- frontend prefers the source with the most non-null fields
    -- when both are present for the same period.
    UNIQUE (ticker, period_end, period_type, source)
);

CREATE INDEX IF NOT EXISTS idx_bank_kpis_ticker_period
    ON bank_operational_kpis (ticker, period_end DESC);

COMMENT ON TABLE bank_operational_kpis IS
    'Phase I: per-bank operational + asset-quality KPIs for the '
    '_PURE_BANK_TICKERS_FOR_DE universe. Filled by scripts/'
    'ingest_bank_kpis_from_xbrl.py (financial KPIs) and scripts/'
    'extract_bank_kpis_from_ar.py (operational KPIs). See '
    'docs/diagnostics/phase-i-bank-kpi-coverage-2026-05-26.md.';
