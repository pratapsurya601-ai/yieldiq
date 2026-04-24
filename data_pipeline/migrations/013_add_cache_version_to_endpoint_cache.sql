-- 013_add_cache_version_to_endpoint_cache.sql
--
-- Adds a `cache_version` column to `endpoint_cache` so persistent
-- rows are implicitly invalidated on a backend CACHE_VERSION bump,
-- matching the pattern already used by `analysis_cache` (see
-- 002_add_analysis_cache.sql). Without this, endpoints backed by
-- endpoint_cache_service (/financials, /fv-history, ...) keep
-- serving the previous version's payloads for up to 24h after a
-- CACHE_VERSION bump.
--
-- The DEFAULT '0' means every existing row is treated as version 0
-- and will never match the current CACHE_VERSION on read, i.e. all
-- pre-migration rows are auto-invalidated on first deploy. Fresh
-- writes stamp the current CACHE_VERSION via save path.
--
-- Idempotent: IF NOT EXISTS guard allows safe re-run.
--
-- Run against: Aiven Postgres (yieldiq Financials DB).
-- Apply with: `psql "$AIVEN_DSN" -f 013_add_cache_version_to_endpoint_cache.sql`

BEGIN;

ALTER TABLE endpoint_cache
    ADD COLUMN IF NOT EXISTS cache_version TEXT NOT NULL DEFAULT '0';

COMMIT;
