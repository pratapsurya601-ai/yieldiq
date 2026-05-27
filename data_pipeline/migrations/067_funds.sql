-- 067_funds.sql
-- 2026-05-27 — Mutual Funds Phase 1 foundation.
--
-- Core master table for Indian mutual fund schemes. One row per AMFI
-- scheme code (the 6-digit primary key AMFI assigns); Direct and Regular
-- plan variants are separate rows because they have distinct codes,
-- distinct NAVs, and distinct TER. Mirrors the scoping doc Section 3.
--
-- This is a foundation migration (Phase 1 — data plumbing only). NAV
-- history (068) and benchmark TRI history (069) reference this table.
-- Holdings (070), managers (071), and returns cache (072) are later
-- phases and intentionally NOT included here.
--
-- Idempotent: CREATE TABLE / INDEX use IF NOT EXISTS. No CACHE_VERSION
-- bump needed — no engine code touches funds yet.
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/067_funds.sql

CREATE TABLE IF NOT EXISTS funds (
    scheme_code            TEXT         PRIMARY KEY,
    isin_growth            TEXT,
    isin_div               TEXT,
    scheme_name            TEXT         NOT NULL,
    amc                    TEXT         NOT NULL,
    plan                   TEXT         CHECK (plan IN ('Direct', 'Regular')),
    option                 TEXT         CHECK (option IN ('Growth', 'IDCW', 'IDCW-Reinvest')),
    category               TEXT,
    sub_category           TEXT,
    benchmark_index_code   TEXT,
    inception_date         DATE,
    riskometer_level       TEXT         CHECK (
        riskometer_level IS NULL OR riskometer_level IN (
            'Low',
            'LowToModerate',
            'Moderate',
            'ModeratelyHigh',
            'High',
            'VeryHigh'
        )
    ),
    is_active              BOOLEAN      NOT NULL DEFAULT TRUE,
    created_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT now()
);

CREATE INDEX IF NOT EXISTS idx_funds_amc          ON funds(amc);
CREATE INDEX IF NOT EXISTS idx_funds_category     ON funds(category);
CREATE INDEX IF NOT EXISTS idx_funds_isin_growth  ON funds(isin_growth) WHERE isin_growth IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_funds_active       ON funds(is_active) WHERE is_active = TRUE;

COMMENT ON TABLE funds IS
    'Master table for Indian mutual fund schemes (AMFI universe). One row per AMFI 6-digit scheme code. Direct and Regular plan variants are distinct rows. Populated by data_pipeline/sources/amfi_scheme_master.py (weekly cron). Riskometer level is read verbatim from the AMC disclosure per SEBI mandate — never recomputed.';
COMMENT ON COLUMN funds.scheme_code IS
    'AMFI 6-digit scheme code. Primary key and join key for fund_nav_history.';
COMMENT ON COLUMN funds.isin_growth IS
    'ISIN for the Growth option (preferred secondary join key — cleaner than scheme_name).';
COMMENT ON COLUMN funds.plan IS
    'Direct or Regular. Parsed out of the AMFI scheme name by amfi_scheme_master.parse_plan_option.';
COMMENT ON COLUMN funds.option IS
    'Growth | IDCW | IDCW-Reinvest. Income Distribution cum Capital Withdrawal is the SEBI-mandated rename of Dividend (2021).';
COMMENT ON COLUMN funds.category IS
    'SEBI 36-category label (Large Cap, Mid Cap, Flexi Cap, ELSS, Liquid, Gilt, etc). Seeded from 073_fund_categories_seed.sql; per-scheme mapping is operator-curated for Phase 1 top-500.';
COMMENT ON COLUMN funds.riskometer_level IS
    'Official SEBI Riskometer level (Low / LowToModerate / Moderate / ModeratelyHigh / High / VeryHigh). MUST be read from AMC disclosure verbatim — never compute our own.';
COMMENT ON COLUMN funds.is_active IS
    'Soft-deactivation flag. Set to FALSE when a scheme disappears from the AMFI master (merger / wind-up). Historical NAV rows are preserved either way.';
