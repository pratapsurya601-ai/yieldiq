-- 037_document_upside_pct_semantics.sql
-- ─────────────────────────────────────────────────────────────────
-- Semantic clarification for the column historically named
-- `margin_of_safety_pct` on `model_predictions_history` (migration 019).
--
-- Despite the name, this column has ALWAYS stored UPSIDE % computed
-- as (fv - cmp) / cmp * 100 -- i.e. the upside fraction relative to
-- current price, NOT Buffett's true margin of safety which would be
-- (fv - cmp) / fv (the discount relative to intrinsic value).
--
-- We intentionally do NOT rename the column: doing so would break
-- historical joins, dashboards, and the public canary contract.
-- This migration only attaches a COMMENT so future readers (and
-- `\d+` / information_schema queries) see the true semantics.
--
-- Step B of the MoS-formula fix will introduce a separate, correctly
-- computed Buffett-MoS column. Until then, the wire format stays as
-- it is and only the SEMANTIC labelling is corrected.
-- ─────────────────────────────────────────────────────────────────

COMMENT ON COLUMN model_predictions_history.margin_of_safety_pct IS
    'Upside %% = (fair_value - current_price) / current_price * 100. '
    'Despite the legacy column name, this is upside relative to '
    'current price, NOT Buffett margin of safety. See migration 037 '
    'for the rename rationale; a true Buffett-MoS column will be '
    'added in a follow-up.';

COMMENT ON COLUMN prediction_outcomes.return_pct IS
    'Realised return %% = (outcome_price - prediction current_price) '
    '/ current_price * 100. Sign convention matches '
    'model_predictions_history.margin_of_safety_pct (which is also '
    'upside %% despite the legacy name).';
