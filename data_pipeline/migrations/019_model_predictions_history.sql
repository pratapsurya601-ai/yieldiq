-- ═══════════════════════════════════════════════════════════════
-- Migration 019: model_predictions_history + prediction_outcomes
-- ───────────────────────────────────────────────────────────────
-- Backs the public Performance Retrospective (Task 12).
--
-- Two tables, both append-mostly:
--
--   model_predictions_history  — daily snapshot of the live model's
--                                opinion on every covered ticker.
--                                Written by retrospective_service.
--                                record_daily_predictions(date) once
--                                a day. UNIQUE(ticker, prediction_date)
--                                means re-runs are idempotent.
--
--   prediction_outcomes        — t+30/60/90/180/365 realised returns,
--                                computed once the outcome_date passes.
--                                One row per (prediction_id, window).
--
-- We deliberately store the cache_version so future audits can ask
-- "did this prediction come from the buggy v32 _normalize_pct cohort?"
-- and exclude / annotate as needed.
--
-- See docs/performance_retrospective_design.md for the methodology
-- discussion (counterfactual vs reconstructed historical model).
-- ═══════════════════════════════════════════════════════════════

CREATE TABLE IF NOT EXISTS model_predictions_history (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    prediction_date DATE NOT NULL,            -- date the model issued this view
    current_price NUMERIC(12,2) NOT NULL,     -- price on prediction_date
    fair_value NUMERIC(12,2),
    margin_of_safety_pct NUMERIC(6,2),        -- (fv - cmp) / cmp * 100
    yieldiq_score INT,                        -- 0-100
    grade VARCHAR(3),
    verdict VARCHAR(40),                      -- 'undervalued' | 'fair_value' | 'overvalued' | 'data_limited'
    cache_version_at_prediction INT NOT NULL,
    recorded_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (ticker, prediction_date)
);

CREATE INDEX IF NOT EXISTS idx_pred_date
    ON model_predictions_history (prediction_date DESC);

CREATE INDEX IF NOT EXISTS idx_pred_ticker_date
    ON model_predictions_history (ticker, prediction_date DESC);

-- Computed-on-read returns table. We write one row per (prediction, window).
-- A daily-refreshed materialized view was considered but the data volume is
-- modest (≤ 3000 tickers × 5 windows × N days) and direct rows make ad-hoc
-- analytics much easier to express in plain SQL.
CREATE TABLE IF NOT EXISTS prediction_outcomes (
    id BIGSERIAL PRIMARY KEY,
    prediction_id BIGINT NOT NULL
        REFERENCES model_predictions_history(id) ON DELETE CASCADE,
    outcome_date DATE NOT NULL,               -- t+30, t+60, t+90, t+180, t+365
    outcome_price NUMERIC(12,2),
    return_pct NUMERIC(8,2),                  -- (outcome - cmp) / cmp * 100
    computed_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE (prediction_id, outcome_date)
);

CREATE INDEX IF NOT EXISTS idx_outcome_pred_date
    ON prediction_outcomes (prediction_id, outcome_date);
