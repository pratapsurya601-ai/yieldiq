-- Migration 007: Sector percentile rankings on ratio_history
--
-- Adds four percentile columns (1–100, higher = better) so the frontend
-- can render "Top 12% in IT Services for ROE" badges without recomputing.
--
--   • roe_sector_pct   — higher ROE  → higher percentile
--   • roce_sector_pct  — higher ROCE → higher percentile
--   • pe_sector_pct    — LOWER PE    → higher percentile (REVERSED)
--   • de_sector_pct    — LOWER D/E   → higher percentile (REVERSED)
--
-- Computed by scripts/build_analytics_extensions.py "Step 2 — sector
-- percentiles" pass. Cohort = (period_end, period_type, sector) joined
-- on stocks.sector; tickers without a sector fall back to a synthetic
-- cohort keyed off stocks.market_cap_category so every row gets ranked.
--
-- Idempotent: ADD COLUMN IF NOT EXISTS — safe to apply twice.

ALTER TABLE ratio_history
    ADD COLUMN IF NOT EXISTS roe_sector_pct   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS roce_sector_pct  DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS pe_sector_pct    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS de_sector_pct    DOUBLE PRECISION;
