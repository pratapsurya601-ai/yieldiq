-- Migration 012: financials.current_liabilities for proper ROCE
-- ═══════════════════════════════════════════════════════════════
-- Bug context: ROCE on the analysis page was rendering as 0.0% (or
-- "—" after the FV fix) for most top tickers because the `financials`
-- table exposes `total_assets` and `ebit` but NOT `current_liabilities`.
-- The textbook formula is:
--
--     ROCE = EBIT / (Total Assets − Current Liabilities)
--
-- Without CL we were either hitting the looser EBIT/TA fallback or
-- returning None outright. The fix is to teach the NSE XBRL parser to
-- extract Current Liabilities (the tag exists in every SEBI-mandated
-- Ind-AS 2016 filing we already download) and to provide the column
-- it lands in.
--
-- Idempotent — re-running is a no-op thanks to IF NOT EXISTS.

ALTER TABLE financials
  ADD COLUMN IF NOT EXISTS current_liabilities DOUBLE PRECISION;
