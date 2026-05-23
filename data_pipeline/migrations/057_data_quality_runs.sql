-- 057_data_quality_runs.sql
-- 2026-05-23 — Phase A.1: data-quality validator framework
--
-- Why this exists:
--   Day-111 and Day-112 surfaced four silent data-quality regressions
--   that had been live in production for months (industry serializer
--   dropping the field, bank D/E using wrong denominator, adj_close
--   == close_price from three different populators, 32/97 tickers
--   missing compounded_growth.stock). All four passed unit tests
--   because the tests asserted shape, not plausibility.
--
--   This table stores the per-run output of the data-quality
--   validator framework introduced in PR for phase-a1. Each row is
--   one validator invocation against one (table, populator) pair.
--   `checks` is the structured list of CheckResult dicts; an admin
--   UI / cron alert reads `overall_status` and surfaces yellow/red
--   runs.
--
-- Idempotent: CREATE TABLE / INDEX IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS data_quality_runs (
    id             BIGSERIAL PRIMARY KEY,
    table_name     TEXT NOT NULL,
    populator      TEXT NOT NULL,
    run_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    overall_status TEXT NOT NULL CHECK (overall_status IN ('green', 'yellow', 'red')),
    checks         JSONB NOT NULL,
    notes          TEXT
);

CREATE INDEX IF NOT EXISTS idx_dqr_table_run
    ON data_quality_runs (table_name, run_at DESC);

-- Partial index optimises the "show me what's broken right now" query
-- that the A.2 admin endpoint will run on every page load.
CREATE INDEX IF NOT EXISTS idx_dqr_status_run
    ON data_quality_runs (overall_status, run_at DESC)
    WHERE overall_status != 'green';

COMMENT ON TABLE data_quality_runs IS
    'Phase A.1 (2026-05-23). One row per validator invocation. '
    'overall_status is derived from checks: any fail -> red, any warn -> yellow, '
    'all pass -> green. checks is a JSONB array of CheckResult dicts '
    '({name, status, details, threshold}). Validators live in '
    'backend/services/data_quality/validators/ and are run by '
    'scripts/run_data_quality_validators.py. A.2 will add the cron + admin UI.';
