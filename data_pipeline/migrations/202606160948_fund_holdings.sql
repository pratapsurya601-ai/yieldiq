-- 202606160948_fund_holdings.sql
-- 2026-06-16 — Mutual Funds Phase 3 expansion: holdings SCAFFOLD (no ingester).
--
-- One row per (scheme_code, as_of_month, isin). Empty by design until the
-- holdings ingester (a later phase) populates it from AMC monthly portfolio
-- disclosures. The detail API's `portfolio` block is forward-compatible:
-- with zero rows it returns the explicit empty / "updating" state; once
-- rows land it surfaces top holdings + asset / sector / mcap roll-ups.
--
-- Conventions:
--   * as_of_month is the first-of-month DATE the disclosure pertains to
--     (e.g. 2026-05-01 for the May portfolio).
--   * weight_pct is a PERCENT (e.g. 4.2 = 4.2 percent of the portfolio) —
--     NOT a decimal fraction. (Holdings disclosures are published as
--     percentages; we store them verbatim to avoid a lossy round-trip.)
--   * change_3m_pct is the change in weight over the trailing 3 months,
--     in percentage POINTS (signed). NULL when no 3-months-prior snapshot.
--
-- Idempotent: CREATE TABLE / INDEX use IF NOT EXISTS.
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/202606160948_fund_holdings.sql

CREATE TABLE IF NOT EXISTS fund_holdings (
    scheme_code     TEXT  NOT NULL REFERENCES funds(scheme_code) ON DELETE CASCADE,
    as_of_month     DATE  NOT NULL,
    isin            TEXT  NOT NULL,
    instrument      TEXT,
    weight_pct      NUMERIC(8, 4),   -- PERCENT (4.2 = 4.2 percent), not a fraction
    asset_class     TEXT,            -- e.g. 'Equity', 'Debt', 'Cash'
    sector          TEXT,            -- AMC-disclosed sector label
    mcap_bucket     TEXT,            -- e.g. 'Large Cap', 'Mid Cap', 'Small Cap'
    change_3m_pct   NUMERIC(8, 4),   -- signed change in weight (pct points) over 3m
    PRIMARY KEY (scheme_code, as_of_month, isin)
);

CREATE INDEX IF NOT EXISTS idx_fund_holdings_scheme_month
    ON fund_holdings(scheme_code, as_of_month);

COMMENT ON TABLE fund_holdings IS
    'Per-(scheme_code, as_of_month, isin) holdings from AMC monthly portfolio disclosures. SCAFFOLD — empty until the holdings ingester lands. Surfaced by the detail API portfolio block (forward-compatible). weight_pct / change_3m_pct are PERCENTS, not decimal fractions.';
COMMENT ON COLUMN fund_holdings.weight_pct IS
    'Holding weight as a PERCENT of the portfolio (4.2 = 4.2 percent). Stored verbatim from the disclosure; NOT a decimal fraction.';
COMMENT ON COLUMN fund_holdings.change_3m_pct IS
    'Signed change in weight over the trailing 3 months, in percentage POINTS. NULL when no 3-months-prior snapshot exists.';
