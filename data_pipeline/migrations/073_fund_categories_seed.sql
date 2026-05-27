-- 073_fund_categories_seed.sql
-- 2026-05-27 — Mutual Funds Phase 1: SEBI 36-category seed +
-- canonical TRI benchmark mapping.
--
-- The SEBI categorization circular (SEBI/HO/IMD/DF3/CIR/P/2017/114,
-- updated through 2021) defines 36 mutual fund categories across
-- equity, debt, hybrid, solution-oriented, and other buckets. This
-- seed provides the canonical label list + the default TRI benchmark
-- per category — used by fund pages, the screener category filter,
-- and the per-scheme benchmark resolver.
--
-- Per-scheme category mapping (which scheme is in which category) is
-- NOT seeded here — that comes from the AMC factsheet ingest (Phase 4)
-- or hand-curated for the top-500 in Phase 1. This file only declares
-- the universe of valid labels.
--
-- Numbering jumps 069 -> 073 intentionally: 070 (holdings),
-- 071 (managers), and 072 (returns cache) are reserved for later
-- phases per the scoping doc and intentionally not created here.
--
-- Idempotent — uses CREATE TABLE IF NOT EXISTS + ON CONFLICT DO NOTHING.
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/073_fund_categories_seed.sql

CREATE TABLE IF NOT EXISTS fund_categories (
    category              TEXT         PRIMARY KEY,
    bucket                TEXT         NOT NULL CHECK (bucket IN (
        'Equity',
        'Debt',
        'Hybrid',
        'Solution',
        'Other'
    )),
    default_benchmark     TEXT,
    description           TEXT,
    created_at            TIMESTAMPTZ  NOT NULL DEFAULT now()
);

COMMENT ON TABLE fund_categories IS
    'Seed table for the SEBI 36-category framework. Provides the canonical category label + default TRI benchmark per category. Per-scheme assignment is recorded on funds.category, not here.';

-- Equity (11 categories) -----------------------------------------------
INSERT INTO fund_categories (category, bucket, default_benchmark, description) VALUES
    ('Large Cap',                  'Equity', 'NIFTY_100_TRI',         'Top 100 by full market cap; min 80% in large caps.'),
    ('Large & Mid Cap',            'Equity', 'NIFTY_LARGEMIDCAP_250_TRI', 'Min 35% large cap + 35% mid cap.'),
    ('Mid Cap',                    'Equity', 'NIFTY_MIDCAP_150_TRI',  'Companies ranked 101-250 by market cap; min 65% in mid caps.'),
    ('Small Cap',                  'Equity', 'NIFTY_SMALLCAP_250_TRI', 'Companies ranked beyond 250; min 65% in small caps.'),
    ('Flexi Cap',                  'Equity', 'NIFTY_500_TRI',         'Dynamic allocation across market caps; min 65% equity.'),
    ('Multi Cap',                  'Equity', 'NIFTY_500_MULTICAP_5025_TRI', 'Min 25% each in large, mid, and small caps.'),
    ('ELSS',                       'Equity', 'NIFTY_500_TRI',         'Equity Linked Savings Scheme; 3y lock-in; 80C tax benefit.'),
    ('Value',                      'Equity', 'NIFTY_500_VALUE_50_TRI', 'Value investment strategy; min 65% equity.'),
    ('Contra',                     'Equity', 'NIFTY_500_TRI',         'Contrarian strategy; min 65% equity.'),
    ('Focused',                    'Equity', 'NIFTY_500_TRI',         'Max 30 stocks; min 65% equity.'),
    ('Dividend Yield',             'Equity', 'NIFTY_DIVIDEND_OPPS_50_TRI', 'Min 65% in dividend-yielding stocks.')
ON CONFLICT (category) DO NOTHING;

-- Sectoral / Thematic (1 category, many themes) -----------------------
INSERT INTO fund_categories (category, bucket, default_benchmark, description) VALUES
    ('Sectoral/Thematic',          'Equity', 'NIFTY_500_TRI',         'Min 80% in a single sector or theme; benchmark varies by theme.')
ON CONFLICT (category) DO NOTHING;

-- Debt (16 categories) -------------------------------------------------
INSERT INTO fund_categories (category, bucket, default_benchmark, description) VALUES
    ('Overnight',                  'Debt',   'CRISIL_OVERNIGHT_TRI',         'Overnight securities only (1 day maturity).'),
    ('Liquid',                     'Debt',   'CRISIL_LIQUID_DEBT_TRI',       'Debt and money market with maturity up to 91 days.'),
    ('Ultra Short Duration',       'Debt',   'CRISIL_ULTRA_SHORT_DEBT_TRI',  'Macaulay duration 3-6 months.'),
    ('Low Duration',               'Debt',   'CRISIL_LOW_DURATION_DEBT_TRI', 'Macaulay duration 6-12 months.'),
    ('Money Market',               'Debt',   'CRISIL_MONEY_MARKET_TRI',      'Money market instruments up to 1 year.'),
    ('Short Duration',             'Debt',   'CRISIL_SHORT_DURATION_DEBT_TRI', 'Macaulay duration 1-3 years.'),
    ('Medium Duration',            'Debt',   'CRISIL_MEDIUM_DURATION_DEBT_TRI', 'Macaulay duration 3-4 years.'),
    ('Medium to Long Duration',    'Debt',   'CRISIL_MEDIUM_LONG_DEBT_TRI',  'Macaulay duration 4-7 years.'),
    ('Long Duration',              'Debt',   'CRISIL_LONG_DURATION_DEBT_TRI', 'Macaulay duration greater than 7 years.'),
    ('Dynamic Bond',               'Debt',   'CRISIL_DYNAMIC_BOND_TRI',      'Dynamic across all durations.'),
    ('Corporate Bond',             'Debt',   'CRISIL_CORPORATE_BOND_TRI',    'Min 80% in AA+ and above corporate bonds.'),
    ('Credit Risk',                'Debt',   'CRISIL_CREDIT_RISK_TRI',       'Min 65% in AA and below corporate bonds.'),
    ('Banking and PSU',            'Debt',   'CRISIL_BANKING_PSU_DEBT_TRI',  'Min 80% in banks, PSUs, PFIs.'),
    ('Gilt',                       'Debt',   'CRISIL_GILT_TRI',              'Min 80% in government securities.'),
    ('Gilt with 10 year constant duration', 'Debt', 'CRISIL_10Y_GILT_TRI',  'Gilt with constant 10-year duration.'),
    ('Floater',                    'Debt',   'CRISIL_FLOATER_TRI',           'Min 65% in floating-rate instruments.')
ON CONFLICT (category) DO NOTHING;

-- Hybrid (7 categories) ------------------------------------------------
INSERT INTO fund_categories (category, bucket, default_benchmark, description) VALUES
    ('Conservative Hybrid',        'Hybrid', 'CRISIL_HYBRID_85_15_TRI',     '10-25% equity + 75-90% debt.'),
    ('Balanced Hybrid',            'Hybrid', 'CRISIL_HYBRID_50_50_TRI',     '40-60% equity + 40-60% debt.'),
    ('Aggressive Hybrid',          'Hybrid', 'CRISIL_HYBRID_35_65_TRI',     '65-80% equity + 20-35% debt.'),
    ('Dynamic Asset Allocation',   'Hybrid', 'CRISIL_HYBRID_50_50_TRI',     'Dynamic equity-debt mix; aka Balanced Advantage.'),
    ('Multi Asset Allocation',     'Hybrid', 'CRISIL_HYBRID_50_50_TRI',     'Min 10% each in at least 3 asset classes.'),
    ('Arbitrage',                  'Hybrid', 'NIFTY_50_ARBITRAGE_TRI',      'Min 65% in arbitrage opportunities.'),
    ('Equity Savings',             'Hybrid', 'NIFTY_EQUITY_SAVINGS_TRI',    'Equity + arbitrage + debt; tax-efficient.')
ON CONFLICT (category) DO NOTHING;

-- Solution-Oriented (2 categories) ------------------------------------
INSERT INTO fund_categories (category, bucket, default_benchmark, description) VALUES
    ('Retirement',                 'Solution', 'CRISIL_HYBRID_50_50_TRI',   'Retirement-targeted; 5y lock-in or till retirement age.'),
    ('Childrens',                  'Solution', 'CRISIL_HYBRID_50_50_TRI',   'Child-goal-targeted; 5y lock-in or till majority.')
ON CONFLICT (category) DO NOTHING;

-- Other (2 categories) ------------------------------------------------
INSERT INTO fund_categories (category, bucket, default_benchmark, description) VALUES
    ('Index Funds',                'Other',  'NIFTY_50_TRI',                 'Passive replication; benchmark is the index itself (TRI).'),
    ('Fund of Funds',              'Other',  NULL,                           'Invests in other mutual funds (domestic or international).')
ON CONFLICT (category) DO NOTHING;
