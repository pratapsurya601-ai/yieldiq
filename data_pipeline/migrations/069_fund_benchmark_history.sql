-- 069_fund_benchmark_history.sql
-- 2026-05-27 — Mutual Funds Phase 1: TRI benchmark time series.
--
-- Daily TRI (Total Return Index) values per benchmark code. TRI — NOT
-- PRI — is the correct benchmark for fund-vs-benchmark alpha math
-- because PRI excludes dividend reinvestment and produces inflated
-- alpha for dividend-paying equity benchmarks.
--
-- Separate from nse_index_history (which stores PRI close + valuation
-- ratios) because:
--   1. TRI series sometimes have different start dates than PRI for
--      the same index (older TRI back-fills land via different feeds).
--   2. The set of indices we ingest as "fund benchmarks" is the subset
--      mapped in 073_fund_categories_seed.sql — narrower than
--      nse_index_history's ~110 index universe.
--   3. Avoiding a wide column on nse_index_history that is NULL for the
--      bulk of indices.
--
-- Populated by the TRI extension to nse_indices_history.py (same daily
-- cron — see cron-mf-benchmark-tri-daily.yml or the extended indices
-- workflow).
--
-- Idempotent.
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/069_fund_benchmark_history.sql

CREATE TABLE IF NOT EXISTS fund_benchmark_history (
    benchmark_index_code TEXT           NOT NULL,
    nav_date             DATE           NOT NULL,
    tri_value            NUMERIC(18, 4) NOT NULL,
    PRIMARY KEY (benchmark_index_code, nav_date)
);

CREATE INDEX IF NOT EXISTS idx_fund_benchmark_history_date
    ON fund_benchmark_history(nav_date);

COMMENT ON TABLE fund_benchmark_history IS
    'Daily TRI (Total Return Index) values per benchmark code, keyed on (benchmark_index_code, nav_date). TRI specifically — PRI is insufficient because it excludes reinvested dividends and produces inflated alpha. Populated by the TRI pass in data_pipeline/sources/nse_indices_history.py (extended in Phase 1).';
COMMENT ON COLUMN fund_benchmark_history.benchmark_index_code IS
    'Canonical TRI benchmark code (e.g. NIFTY_50_TRI, NIFTY_500_TRI, NIFTY_MIDCAP_150_TRI, CRISIL_COMP_BOND_TRI). Maps to funds.benchmark_index_code.';
COMMENT ON COLUMN fund_benchmark_history.tri_value IS
    'Total Return Index level (dividend-reinvested). Numeric(18,4) is sized for the long-running indices where the TRI has compounded over decades — Nifty 50 TRI crossed 40,000 in 2024 and the 18-digit width gives multi-decade headroom.';
