-- 202606160947_fund_category_stats.sql
-- 2026-06-16 — Mutual Funds Phase 3 expansion: per-sub_category aggregate stats.
--
-- One row per funds.sub_category. Holds the median / average of the
-- already-computed per-scheme metrics (from fund_returns_cache, derived in
-- backend/services/funds/recompute.py pass-3) so the fund detail page can
-- render STRICTLY COMPARATIVE category context (median/avg CAGR, avg
-- Sharpe / stdev / max-drawdown) without re-aggregating on every request.
--
-- CACHE_VERSION discipline mirrors fund_returns_cache: cache_version is
-- carried per row and stamped with ACTIVE_CACHE_VERSION by the recompute
-- orchestrator.
--
-- Conventions:
--   * CAGR columns are DECIMAL FRACTIONS (0.12 = 12 percent), matching
--     fund_returns_cache and the equity side.
--   * avg_ter is INTENTIONALLY nullable and left NULL by pass-3 — TER is
--     not present in the compute objects, so we do NOT fabricate it. The
--     factsheet ingest (Phase 4) will populate it later.
--   * n_funds = count of schemes in the sub_category that contributed at
--     least one non-null metric to the aggregate.
--
-- Idempotent: CREATE TABLE / INDEX use IF NOT EXISTS.
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/202606160947_fund_category_stats.sql

CREATE TABLE IF NOT EXISTS fund_category_stats (
    sub_category            TEXT         PRIMARY KEY,
    updated_at             TIMESTAMPTZ  NOT NULL DEFAULT now(),
    cache_version          TEXT,

    -- Per-sub_category aggregates of the per-scheme metrics.
    -- CAGR fields are DECIMAL FRACTIONS (0.12 = 12 percent).
    median_cagr_1y         NUMERIC(12, 6),
    median_cagr_3y         NUMERIC(12, 6),
    median_cagr_5y         NUMERIC(12, 6),
    avg_cagr_1y            NUMERIC(12, 6),
    avg_cagr_3y           NUMERIC(12, 6),
    avg_cagr_5y           NUMERIC(12, 6),

    -- Cost: NULL until factsheet TER ingest lands. recompute pass-3 does
    -- NOT populate this (TER is not in the compute objects).
    avg_ter               NUMERIC(8, 5),

    -- Risk aggregates (dimensionless Sharpe; stdev / max-dd decimal).
    avg_sharpe_3y         NUMERIC(12, 6),
    avg_stdev_3y          NUMERIC(12, 6),
    avg_max_drawdown_3y   NUMERIC(12, 6),

    n_funds               INT
);

CREATE INDEX IF NOT EXISTS idx_fund_category_stats_cache_version
    ON fund_category_stats(cache_version);

COMMENT ON TABLE fund_category_stats IS
    'Per-sub_category aggregate stats (median/avg of fund_returns_cache metrics). Populated by backend/services/funds/recompute.py pass-3 on the daily cron. STRICTLY COMPARATIVE category context — no recommendation. CAGR columns are decimal fractions (0.12 = 12 percent).';
COMMENT ON COLUMN fund_category_stats.avg_ter IS
    'Average expense ratio across the sub_category. Left NULL by pass-3 — TER is not present in the compute objects; populated later by the factsheet ingest. Never fabricated.';
COMMENT ON COLUMN fund_category_stats.n_funds IS
    'Count of schemes in this sub_category that contributed at least one non-null metric to the aggregates.';
COMMENT ON COLUMN fund_category_stats.median_cagr_3y IS
    'Median of fund_returns_cache.cagr_3y across the sub_category cohort (decimal fraction). median_cagr_1y uses fund_returns_cache.ret_1y, which equals the 1y CAGR by definition.';
