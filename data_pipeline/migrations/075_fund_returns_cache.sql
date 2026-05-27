-- 075_fund_returns_cache.sql
-- 2026-05-27 — Mutual Funds Phase 2: returns + risk + score compute cache.
--
-- One row per scheme_code with all computed trailing returns, CAGR
-- windows, rolling-window stats, risk metrics (stdev, beta, Sharpe,
-- Sortino, alpha, info ratio, up/down capture), max drawdown, category
-- percentiles, TER, and the YieldIQ Fund Score (rule-based composite).
--
-- Mirrors the stock-side CACHE_VERSION discipline: cache_version is
-- carried on every row, the recompute orchestrator stamps the active
-- version from backend/services/cache_invalidation_manifest.py, and the
-- canary diff harness gates merges that touch this surface.
--
-- Schema diverges slightly from the original 072 scoping sketch:
--   * Numbered 075 (not 072) — 070/071/072 reserved by the scoping doc
--     for holdings/managers/older-returns-shape but unused in Phase 1;
--     we leave them free for the holdings phase to claim.
--   * ter_direct / ter_regular live here for now (lookup parity with the
--     other compute fields); the factsheet ingest in Phase 4 will write
--     them, the compute service treats them as read-only inputs.
--   * yieldiq_fund_score stored as int 0..100; component sub-scores are
--     stored as separate numeric columns so the breakdown card in
--     Phase 3 can render the rationale without re-computing.
--
-- Idempotent: CREATE TABLE / INDEX use IF NOT EXISTS.
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/075_fund_returns_cache.sql

CREATE TABLE IF NOT EXISTS fund_returns_cache (
    scheme_code              TEXT         PRIMARY KEY REFERENCES funds(scheme_code) ON DELETE CASCADE,
    computed_at              TIMESTAMPTZ  NOT NULL DEFAULT now(),
    cache_version            TEXT,
    nav_as_of                DATE,
    history_days             INT,

    -- Trailing returns (simple price-return, decimal fractions, e.g. 0.123 = 12.3%)
    ret_1y                   NUMERIC(12, 6),
    ret_3y                   NUMERIC(12, 6),
    ret_5y                   NUMERIC(12, 6),
    ret_10y                  NUMERIC(12, 6),
    ret_si                   NUMERIC(12, 6),

    -- CAGR (annualized, decimal fractions)
    cagr_3y                  NUMERIC(12, 6),
    cagr_5y                  NUMERIC(12, 6),
    cagr_10y                 NUMERIC(12, 6),

    -- Rolling-window stats (monthly-anchored, 3y trailing window)
    rolling_3y_mean          NUMERIC(12, 6),
    rolling_3y_median        NUMERIC(12, 6),
    rolling_3y_min           NUMERIC(12, 6),
    rolling_3y_max           NUMERIC(12, 6),
    rolling_3y_window_count  INT,

    -- Risk: scheme-only
    stdev_3y                 NUMERIC(12, 6),
    sharpe_3y                NUMERIC(12, 6),
    sortino_3y               NUMERIC(12, 6),
    max_dd_3y                NUMERIC(12, 6),
    max_dd_5y                NUMERIC(12, 6),

    -- Risk: scheme-vs-benchmark
    beta_3y                  NUMERIC(12, 6),
    alpha_3y                 NUMERIC(12, 6),
    info_ratio_3y            NUMERIC(12, 6),
    tracking_error_3y        NUMERIC(12, 6),
    upside_capture_3y        NUMERIC(12, 6),
    downside_capture_3y      NUMERIC(12, 6),
    benchmark_excess_3y      NUMERIC(12, 6),

    -- Category percentile (1.0 = top, 0.0 = bottom; null if category < 5 peers)
    category_percentile_3y   NUMERIC(6, 4),

    -- Cost (read-only inputs maintained by the factsheet ingest)
    ter_direct               NUMERIC(6, 4),
    ter_regular              NUMERIC(6, 4),

    -- Composite score (rule-based, 0..100). Components persisted for the
    -- breakdown card; weights live in compute_score.py.
    yieldiq_fund_score       INT          CHECK (yieldiq_fund_score IS NULL OR (yieldiq_fund_score BETWEEN 0 AND 100)),
    score_component_rolling  INT,
    score_component_sharpe   INT,
    score_component_drawdown INT,
    score_component_ter      INT,
    score_component_tenure   INT,

    -- Diagnostic: why a row may have NULLs (e.g. "inception < 3y").
    notes                    TEXT
);

CREATE INDEX IF NOT EXISTS idx_fund_returns_cache_score
    ON fund_returns_cache(yieldiq_fund_score) WHERE yieldiq_fund_score IS NOT NULL;
CREATE INDEX IF NOT EXISTS idx_fund_returns_cache_computed_at
    ON fund_returns_cache(computed_at);
CREATE INDEX IF NOT EXISTS idx_fund_returns_cache_cache_version
    ON fund_returns_cache(cache_version);

COMMENT ON TABLE fund_returns_cache IS
    'Per-scheme cache of computed returns / risk / score metrics. Populated by backend/services/funds/recompute.py (daily cron after NAV ingest). Mirrors the stock-side CACHE_VERSION discipline — cache_version carried per row, canary-diff gates merges that touch this surface. Decimal columns store fractions (0.12 = 12 percent) per the equity-side convention.';
COMMENT ON COLUMN fund_returns_cache.cache_version IS
    'Active manifest version_id at the time of compute (e.g. v_phase2_mf_returns_compute_2026_05_27).';
COMMENT ON COLUMN fund_returns_cache.history_days IS
    'Distinct trading days of NAV available for this scheme; gates which windows are computed (e.g. <750 trading days disables the 3y window).';
COMMENT ON COLUMN fund_returns_cache.rolling_3y_mean IS
    'Mean of monthly-anchored 3y rolling CAGRs across the full available history. The rolling_3y_window_count column reports how many windows contributed.';
COMMENT ON COLUMN fund_returns_cache.beta_3y IS
    'cov(scheme, benchmark) / var(benchmark) computed on daily log returns over the trailing 3y window. NULL when the scheme has no benchmark mapping or the benchmark series is incomplete.';
COMMENT ON COLUMN fund_returns_cache.alpha_3y IS
    'Jensen alpha (regression intercept, annualized) from r_scheme - rf = a + b * (r_bench - rf). NULL when beta is NULL.';
COMMENT ON COLUMN fund_returns_cache.upside_capture_3y IS
    'Avg monthly scheme return in months where the benchmark is positive, divided by avg benchmark return in those months. Decimal (1.0 = market-matching).';
COMMENT ON COLUMN fund_returns_cache.category_percentile_3y IS
    'Percentile rank of cagr_3y within funds.category. 1.0 = top of category, 0.0 = bottom. NULL when fewer than 5 peers have a valid cagr_3y.';
COMMENT ON COLUMN fund_returns_cache.yieldiq_fund_score IS
    'Composite 0..100 score from compute_score.py — rule-based, NOT LLM. Weighted blend of rolling-return percentile, Sharpe percentile, max-DD percentile, TER percentile, and a manager-tenure floor. Component sub-scores are persisted alongside for the breakdown card.';
COMMENT ON COLUMN fund_returns_cache.notes IS
    'Free-form diagnostic note explaining NULLs (e.g. "history<3y", "no benchmark mapping", "category too small for percentile"). Read by the analysis page to render a one-line explainer instead of a blank.';
