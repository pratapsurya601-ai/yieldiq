-- 033_deactivate_stale_nse_delisted.sql
--
-- Auto-generated from NSE EQUITY_L.csv comparison on 2026-05-16.
-- These 65 tickers exist in stocks.is_active=TRUE but are not present on the
-- NSE active master (https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv).
-- They are delisted/suspended and need to be deactivated to stop:
--   * universe backfill cycles wasting resources on them
--   * Sentry validator floods (CLCIND alone = 16,777 events / 24h)
--   * 404s on prod /og-data
--
-- Source counts (2026-05-16):
--   NSE EQUITY_L active symbols:  2,365
--   YieldIQ stocks.is_active=TRUE: 2,429
--   Delta to deactivate:               65
--
-- Going forward, scripts/sync_nse_active_universe.py runs weekly to catch
-- new delistings before they accumulate.
--
-- Idempotent: the WHERE clause filters on is_active=TRUE so re-runs are no-ops.
--
-- Run by ops post-merge:
--   psql "$DATABASE_URL" -f data_pipeline/migrations/033_deactivate_stale_nse_delisted.sql

BEGIN;

UPDATE stocks
   SET is_active = FALSE
 WHERE is_active = TRUE
   AND ticker IN (
     'ABAN',
     'AGSTRA',
     'AJRINFRA',
     'ALPSINDUS',
     'ANDREWYU',
     'ARSSINFRA',
     'BGLOBAL',
     'BILVYAPAR',
     'BIRLATYRE',
     'BRFL',
     'BURNPUR',
     'CIGNITITEC',
     'CLCIND',
     'CMICABLES',
     'DHARAN',
     'DHARSUGAR',
     'DIL',
     'EDUCOMP',
     'EROSMEDIA',
     'EXCEL',
     'FCONSUMER',
     'FRETAIL',
     'GBGLOBAL',
     'GENSOL',
     'GFSTEELS',
     'GSPL',
     'GSTL',
     'HERCULES',
     'HINDMOTORS',
     'INDLMETER',
     'JBFIND',
     'JPASSOCIAT',
     'JPINFRATEC',
     'JSWISPL',
     'LGBFORGE',
     'LTIM',
     'MARSHALL',
     'MBECL',
     'MCDHOLDING',
     'MERCATOR',
     'NEUEON',
     'OMKARCHEM',
     'PDPL',
     'PODDARHOUS',
     'QUINTEGRA',
     'RAJVIR',
     'RELCAPITAL',
     'RELINFRA',
     'SABEVENTS',
     'SANGHIIND',
     'SECURCRED',
     'SEL',
     'SETUINFRA',
     'SIMBHALS',
     'SKIL',
     'SPTL',
     'SRPL',
     'SUULD',
     'TATAMETALI',
     'TECHIN',
     'TINPLATE',
     'UNIVAFOODS',
     'VISESHINFO',
     'VISHAL',
     'WATERBASE'
   );

COMMIT;
