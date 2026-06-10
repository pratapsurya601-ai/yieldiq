-- 202606101845_fair_value_history_yieldiq_score.sql
-- =================================================================
-- ROOT CAUSE #13 — Peer table SCORE column empty.
--
-- Root cause: peers_service._cached_score has a DB fallback for
-- fair_value/mos_pct/verdict from fair_value_history, but the
-- yieldiq_score field is "not persisted; cache-only for now". Result:
-- a peer that has not been analysed in the current in-process cache
-- window shows SCORE='—' on the Peers tab even when its FV/MoS render
-- correctly (because those come from the DB fallback).
--
-- Fix: add yieldiq_score + grade columns to fair_value_history so the
-- DB fallback can populate the score column too. Both nullable —
-- legacy rows written before this migration carry NULL and the
-- frontend already handles NULL gracefully (`—`).
--
-- The write-hook (data_pipeline/sources/fv_history.store_today_fair_value)
-- is extended in the same PR to write these columns on every persist;
-- the columns auto-fill as tickers are re-analysed.
--
-- Canary impact: nullable column adds only. NO UPDATE statements run
-- against existing columns; fair_value/mos_pct/verdict cannot change
-- by construction.
-- =================================================================

BEGIN;

ALTER TABLE fair_value_history
    ADD COLUMN IF NOT EXISTS yieldiq_score INTEGER NULL,
    ADD COLUMN IF NOT EXISTS grade         VARCHAR(4) NULL;

-- Score sanity check — formula clamps 0..100 (dashboard.utils.scoring).
-- NULL is allowed (rows written before this migration / write-hook
-- failure paths persist NULL deliberately).
ALTER TABLE fair_value_history
    DROP CONSTRAINT IF EXISTS chk_fv_history_yieldiq_score_range;
ALTER TABLE fair_value_history
    ADD CONSTRAINT chk_fv_history_yieldiq_score_range
    CHECK (
        yieldiq_score IS NULL
        OR (yieldiq_score >= 0 AND yieldiq_score <= 100)
    );

COMMIT;
