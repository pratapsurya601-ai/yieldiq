-- Migration: add bse_code column to stocks table.
-- Owned by Agent E (Pulse axis — BSE shareholding + SEBI SAST wiring).
--
-- bse_code is the numeric BSE scrip code (e.g. 500325 for RELIANCE) used
-- by the BSE ShareholdingPattern JSON endpoint. We join on ISIN where
-- possible (stocks.isin) and fall back to normalised company-name match.
--
-- Idempotent: safe to run multiple times. Also applied programmatically
-- on startup by backend/scripts/backfill_bse_codes.py as a safety net.

ALTER TABLE stocks ADD COLUMN IF NOT EXISTS bse_code TEXT;

CREATE INDEX IF NOT EXISTS idx_stocks_bse_code
  ON stocks (bse_code)
  WHERE bse_code IS NOT NULL;
