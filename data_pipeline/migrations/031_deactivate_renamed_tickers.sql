-- 031_deactivate_renamed_tickers.sql
--
-- Deactivate ADANITRANS (Adani Transmission Ltd), which was renamed to
-- ADANIENSOL (Adani Energy Solutions Ltd) in 2024. The legacy symbol still
-- sits in our active universe with is_active=TRUE; audits show it returning
-- empty/timeout payloads because yfinance no longer serves the retired
-- symbol. The 2026-04-30 deactivation sweep (reports/deactivated_tickers_2026-04-30.csv)
-- flagged it but the corresponding UPDATE was never executed against prod.
--
-- Idempotent: safe to re-run. The INSERT … ON CONFLICT clause covers the
-- case where ADANIENSOL was added by a prior backfill run.
--
-- Run by ops post-merge:
--   psql "$DATABASE_URL" -f data_pipeline/migrations/031_deactivate_renamed_tickers.sql

BEGIN;

-- Deactivate the retired symbol. The router-level TICKER_ALIASES rewrite
-- (see backend/routers/analysis.py) silently redirects any leftover requests
-- for ADANITRANS / ADANITRANS.NS to ADANIENSOL.NS so existing bookmarks and
-- shared OG links continue to resolve.
UPDATE stocks
   SET is_active = FALSE
 WHERE ticker IN ('ADANITRANS', 'ADANITRANS.NS')
   AND is_active = TRUE;

-- Ensure the canonical post-rename symbol exists and is active. We insert a
-- minimal row; the next nightly metadata refresh will fill in market_cap,
-- industry, and other fields from yfinance / NSE.
INSERT INTO stocks (ticker, name, sector, is_active)
VALUES ('ADANIENSOL', 'Adani Energy Solutions Limited', 'Utilities', TRUE)
ON CONFLICT (ticker) DO UPDATE SET is_active = TRUE;

COMMIT;
