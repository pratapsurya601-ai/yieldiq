-- Migration 006: Analytics extensions on ratio_history
--
-- Adds columns for the Tier-1 analytic derivatives that our peers don't
-- compute historically:
--
--   • piotroski_f_score  (0–9)  — balance-sheet strength checklist
--   • altman_z_score     (float) — distress predictor
--   • dupont_margin      (%)    — net_income / revenue
--   • dupont_asset_turn  (ratio) — revenue / total_assets
--   • dupont_leverage    (ratio) — total_assets / total_equity
--   • revenue_cagr_7y    (DECIMAL)
--   • revenue_cagr_10y   (DECIMAL)
--   • pat_cagr_3y / 5y / 7y / 10y  (DECIMAL)
--
-- All computed by scripts/build_analytics_extensions.py.  Rolling back
-- is safe — none of these feed the live API yet.

ALTER TABLE ratio_history
    ADD COLUMN IF NOT EXISTS piotroski_f_score   INTEGER,
    ADD COLUMN IF NOT EXISTS altman_z_score      DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS dupont_margin       DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS dupont_asset_turn   DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS dupont_leverage     DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS revenue_cagr_7y     DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS revenue_cagr_10y    DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS pat_cagr_3y         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS pat_cagr_5y         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS pat_cagr_7y         DOUBLE PRECISION,
    ADD COLUMN IF NOT EXISTS pat_cagr_10y        DOUBLE PRECISION;
