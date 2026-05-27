-- 074_fund_nav_history_partition_default.sql
-- 2026-05-27 — Phase 1 hotfix: extend partition coverage on fund_nav_history.
--
-- Background
-- ==========
-- Migration 068 created yearly partitions for 2015..2027 on
-- fund_nav_history. The mfapi.in history endpoint returns NAV rows
-- going back to 2014-12-31 for some schemes that launched in late
-- 2014, which causes the operator backfill to fail with:
--
--   psycopg2.errors.CheckViolation: no partition of relation
--   "fund_nav_history" found for row
--   DETAIL: (nav_date) = (2014-12-31)
--
-- This migration:
--   1. Adds a 2014 yearly partition matching the 068 pattern.
--   2. Adds a DEFAULT partition as a safety net so a date that falls
--      outside the configured yearly range (e.g. an upstream feed
--      glitch publishing a 2013 row) never crashes the daily cron.
--
-- The DEFAULT partition is intentionally a long-term safety net only;
-- the future rolling-partition cron is still responsible for extending
-- the explicit yearly coverage forward each year. Rows that land in
-- the DEFAULT can be moved into a proper yearly partition later via
-- ATTACH/DETACH if any ever land.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS on both new partitions.
--
-- Note
-- ====
-- This migration was applied manually to prod Neon on 2026-05-27 to
-- unblock the first operator backfill run. This file lands it in code
-- so dev / staging environments stay in sync.
--
-- Apply with:
--   python scripts/apply_migration.py \
--       data_pipeline/migrations/074_fund_nav_history_partition_default.sql

CREATE TABLE IF NOT EXISTS fund_nav_history_2014
    PARTITION OF fund_nav_history
    FOR VALUES FROM ('2014-01-01') TO ('2015-01-01');

CREATE TABLE IF NOT EXISTS fund_nav_history_default
    PARTITION OF fund_nav_history DEFAULT;

COMMENT ON TABLE fund_nav_history_default IS
    'Safety-net DEFAULT partition for fund_nav_history. Captures rows whose nav_date falls outside the explicit yearly partitions defined in migration 068 (2015..2027) and 074 (2014). Operationally expected to be empty; any rows that land here indicate an upstream date that needs an explicit yearly partition created.';
