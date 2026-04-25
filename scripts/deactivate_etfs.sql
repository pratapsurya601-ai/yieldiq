-- scripts/deactivate_etfs.sql
--
-- One-shot migration: flag ETF / fund / index tickers as inactive in `stocks`.
-- These instruments have no fundamentals (FV=0 in analysis_cache for 282/453
-- rows traced to these) and pollute the analyzable universe.
--
-- Patterns matched (author-specified, see PART 2 spec 2026-04-25):
--   *BEES, *IETF, *ETF, NIFTY*, *ADD, CASHIETF, LIQUIDSHRI, MIDQ50*, TOP15*
--   sector IN ('ETF','Fund','Index')
--
-- Idempotent: re-running is a no-op once every matching row has is_active=false.
--
-- Run:
--   psql "$NEON_DATABASE_URL" -v ON_ERROR_STOP=1 -f scripts/deactivate_etfs.sql
--
BEGIN;

-- BEFORE counts
SELECT 'BEFORE_active_total' AS label, COUNT(*) AS n FROM stocks WHERE is_active = TRUE;
SELECT 'BEFORE_matching_active' AS label, COUNT(*) AS n
FROM stocks
WHERE is_active = TRUE
  AND (
       ticker ~ 'BEES$'
    OR ticker ~ 'IETF$'
    OR ticker ~ 'ETF'
    OR ticker ~ '^NIFTY'
    OR ticker ~ 'ADD$'
    OR ticker LIKE '%CASHIETF%'
    OR ticker LIKE '%LIQUIDSHRI%'
    OR ticker LIKE '%MIDQ50%'
    OR ticker LIKE '%TOP15%'
    OR sector IN ('ETF','Fund','Index')
  );

UPDATE stocks
SET is_active = FALSE,
    updated_at = NOW()
WHERE is_active = TRUE
  AND (
       ticker ~ 'BEES$'
    OR ticker ~ 'IETF$'
    OR ticker ~ 'ETF'
    OR ticker ~ '^NIFTY'
    OR ticker ~ 'ADD$'
    OR ticker LIKE '%CASHIETF%'
    OR ticker LIKE '%LIQUIDSHRI%'
    OR ticker LIKE '%MIDQ50%'
    OR ticker LIKE '%TOP15%'
    OR sector IN ('ETF','Fund','Index')
  );

-- AFTER counts
SELECT 'AFTER_active_total' AS label, COUNT(*) AS n FROM stocks WHERE is_active = TRUE;
SELECT 'AFTER_matching_active' AS label, COUNT(*) AS n
FROM stocks
WHERE is_active = TRUE
  AND (
       ticker ~ 'BEES$'
    OR ticker ~ 'IETF$'
    OR ticker ~ 'ETF'
    OR ticker ~ '^NIFTY'
    OR ticker ~ 'ADD$'
    OR ticker LIKE '%CASHIETF%'
    OR ticker LIKE '%LIQUIDSHRI%'
    OR ticker LIKE '%MIDQ50%'
    OR ticker LIKE '%TOP15%'
    OR sector IN ('ETF','Fund','Index')
  );

COMMIT;
