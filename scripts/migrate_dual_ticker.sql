-- scripts/migrate_dual_ticker.sql
--
-- One-shot migration: collapse dual-ticker (.NS / bare) duplicates in
-- company_financials and analysis_cache to a single BARE-form row per
-- logical key. Service-layer readers query bare form; the .NS rows
-- were shadow data nobody consumed.
--
-- Companion code changes (2026-04-25 data-hygiene pass):
--   - scripts/transform_financials_to_company_financials.py _normalize_ticker
--   - scripts/backfill_from_cache.py _normalize_ticker
--   - data_pipeline/xbrl/db_writer.py _prepare (defense-in-depth on write)
--
-- Run:
--   psql "$NEON_DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/migrate_dual_ticker.sql
--
BEGIN;

-- Pre-counts
SELECT 'BEFORE_cf_ns'  AS label, COUNT(*) AS n FROM company_financials WHERE ticker_nse LIKE '%.NS';
SELECT 'BEFORE_ac_ns'  AS label, COUNT(*) AS n FROM analysis_cache     WHERE ticker     LIKE '%.NS';

-- ===== company_financials =====
-- Delete .NS duplicates where a PLAIN row already exists at the same PK.
DELETE FROM company_financials cf_ns
USING company_financials cf_plain
WHERE cf_ns.ticker_nse LIKE '%.NS'
  AND cf_plain.ticker_nse = REGEXP_REPLACE(cf_ns.ticker_nse, '\.NS$', '')
  AND cf_ns.period_type = cf_plain.period_type
  AND cf_ns.period_end_date IS NOT DISTINCT FROM cf_plain.period_end_date
  AND cf_ns.statement_type = cf_plain.statement_type
  AND cf_ns.source = cf_plain.source;

-- Strip suffix from remaining .NS rows.
UPDATE company_financials
   SET ticker_nse = REGEXP_REPLACE(ticker_nse, '\.NS$', '')
 WHERE ticker_nse LIKE '%.NS';

-- ===== analysis_cache =====
-- PK is (ticker), so any stripped .NS row that collides with an existing
-- bare row would fail the UPDATE. Resolve collisions first by keeping the
-- newer row (higher cache_version, tie-broken by computed_at) and deleting
-- the older one. This is symmetric — sometimes the .NS row is newer,
-- sometimes the bare row is.
--
-- Step 1: delete the OLDER row in any dual-ticker pair.
WITH pairs AS (
  SELECT
    ac_ns.ticker    AS ns_ticker,
    ac_plain.ticker AS plain_ticker,
    CASE
      WHEN ac_plain.cache_version >  ac_ns.cache_version THEN 'ns'
      WHEN ac_plain.cache_version <  ac_ns.cache_version THEN 'plain'
      WHEN ac_plain.computed_at  >= ac_ns.computed_at    THEN 'ns'
      ELSE 'plain'
    END AS loser
  FROM analysis_cache ac_ns
  JOIN analysis_cache ac_plain
    ON ac_plain.ticker = REGEXP_REPLACE(ac_ns.ticker, '\.NS$', '')
  WHERE ac_ns.ticker LIKE '%.NS'
)
DELETE FROM analysis_cache ac
USING pairs p
WHERE (p.loser = 'ns'    AND ac.ticker = p.ns_ticker)
   OR (p.loser = 'plain' AND ac.ticker = p.plain_ticker);

-- Step 2: strip suffix from all remaining .NS rows (no collision possible now).
UPDATE analysis_cache
   SET ticker = REGEXP_REPLACE(ticker, '\.NS$', '')
 WHERE ticker LIKE '%.NS';

-- Post-counts (expect 0 / 0)
SELECT 'AFTER_cf_ns'   AS label, COUNT(*) AS n FROM company_financials WHERE ticker_nse LIKE '%.NS';
SELECT 'AFTER_ac_ns'   AS label, COUNT(*) AS n FROM analysis_cache     WHERE ticker     LIKE '%.NS';

COMMIT;
