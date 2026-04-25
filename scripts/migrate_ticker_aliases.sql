-- =====================================================================
-- migrate_ticker_aliases.sql
-- ---------------------------------------------------------------------
-- Retroactively apply the corporate-actions alias registry
-- (config/ticker_aliases.yaml) to historical rows in Postgres.
--
-- Currently handled:
--   * MINDTREE -> LTIM  (rename, effective 2022-11-14)
--
-- Idempotent: each UPDATE is guarded by a NOT EXISTS / conflict check
-- so re-running is safe. The entire script runs in a single
-- transaction; if any step fails, nothing is committed.
--
-- Usage:
--   # Dry-run (prints what WOULD change, makes no writes):
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -v dryrun=1 \
--        -f scripts/migrate_ticker_aliases.sql
--
--   # Apply:
--   psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -v dryrun=0 \
--        -f scripts/migrate_ticker_aliases.sql
-- =====================================================================

\set ON_ERROR_STOP on
\set dryrun 1

BEGIN;

-- ---------------------------------------------------------------------
-- Dry-run preview: show what each rename would touch.
-- ---------------------------------------------------------------------
\echo '=== company_financials rows currently tagged ticker_nse=MINDTREE ==='
SELECT ticker_nse, period_type, COUNT(*) AS row_count,
       MIN(period_end_date) AS earliest,
       MAX(period_end_date) AS latest
  FROM company_financials
 WHERE ticker_nse = 'MINDTREE'
 GROUP BY ticker_nse, period_type;

\echo '=== financials rows currently tagged ticker=MINDTREE ==='
SELECT ticker, COUNT(*) AS row_count,
       MIN(period_end) AS earliest,
       MAX(period_end) AS latest
  FROM financials
 WHERE ticker = 'MINDTREE'
 GROUP BY ticker;

-- ---------------------------------------------------------------------
-- Apply: MINDTREE -> LTIM (legal entity identical post-merger).
-- Only rewrite MINDTREE rows whose (period_end_date, period_type)
-- does NOT already have a corresponding LTIM row — prevents unique
-- constraint violations and makes the migration idempotent.
-- ---------------------------------------------------------------------
\if :dryrun
  \echo '[DRY-RUN] skipping UPDATEs. Re-run with -v dryrun=0 to apply.'
\else
  UPDATE company_financials cf
     SET ticker_nse = 'LTIM'
   WHERE cf.ticker_nse = 'MINDTREE'
     AND NOT EXISTS (
       SELECT 1
         FROM company_financials cf2
        WHERE cf2.ticker_nse = 'LTIM'
          AND cf2.period_type = cf.period_type
          AND cf2.period_end_date = cf.period_end_date
     );

  -- Delete any residual MINDTREE rows that collided with an existing
  -- LTIM row for the same (period_type, period_end_date). Safe because
  -- LTIM is the canonical post-merger record.
  DELETE FROM company_financials
   WHERE ticker_nse = 'MINDTREE';

  UPDATE financials f
     SET ticker = 'LTIM'
   WHERE f.ticker = 'MINDTREE'
     AND NOT EXISTS (
       SELECT 1
         FROM financials f2
        WHERE f2.ticker = 'LTIM'
          AND f2.period_end = f.period_end
          AND f2.period_type = f.period_type
     );

  DELETE FROM financials
   WHERE ticker = 'MINDTREE';
\endif

-- ---------------------------------------------------------------------
-- Post-migration verification
-- ---------------------------------------------------------------------
\echo '=== Post-migration: MINDTREE rows should be zero ==='
SELECT 'company_financials' AS tbl, COUNT(*) AS leftover_mindtree
  FROM company_financials WHERE ticker_nse = 'MINDTREE'
UNION ALL
SELECT 'financials', COUNT(*) FROM financials WHERE ticker = 'MINDTREE';

\echo '=== Post-migration: LTIM row counts ==='
SELECT 'company_financials' AS tbl, COUNT(*) AS ltim_rows
  FROM company_financials WHERE ticker_nse = 'LTIM'
UNION ALL
SELECT 'financials', COUNT(*) FROM financials WHERE ticker = 'LTIM';

COMMIT;
