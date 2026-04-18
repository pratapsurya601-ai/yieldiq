-- 002_add_analysis_cache.sql
--
-- Adds a persistent `analysis_cache` table so the hot path at
-- /api/v1/analysis/{ticker} can skip the full DCF recompute when a
-- fresh blob is already available. This is tier-2 behind the in-memory
-- `cache_service` (which is the tier-1 hit path). Tier order:
--   in-memory cache_service  -> DB analysis_cache  -> compute
--
-- Invalidation: the `cache_version` column stores the backend
-- CACHE_VERSION at write time. Reads require cache_version = current
-- backend value, so bumping CACHE_VERSION in code implicitly treats
-- every existing row as a miss (no manual TRUNCATE required).
--
-- Idempotent: IF NOT EXISTS guards allow safe re-run.
--
-- Run against: Aiven Postgres (yieldiq Financials DB).
-- Apply with: `psql "$AIVEN_DSN" -f 002_add_analysis_cache.sql`

BEGIN;

CREATE TABLE IF NOT EXISTS analysis_cache (
    ticker        TEXT PRIMARY KEY,
    payload       JSONB NOT NULL,
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
    cache_version TEXT NOT NULL,
    compute_ms    INTEGER
);

CREATE INDEX IF NOT EXISTS idx_analysis_cache_computed_at
    ON analysis_cache(computed_at);

COMMIT;
