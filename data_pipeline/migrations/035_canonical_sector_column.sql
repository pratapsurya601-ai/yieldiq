-- 035_canonical_sector_column.sql
--
-- Add canonical_sector / canonical_industry columns to stocks.
--
-- Background (2026-05-16 audit)
-- -----------------------------
-- `stocks.sector` carries 30 distinct labels across active rows, but
-- the canonical taxonomy in backend/services/sector_taxonomy.py only
-- defines 13 buckets. The raw column also mixes provider granularities:
--   * yfinance broad labels ("Basic Materials", "Industrials",
--     "Consumer Cyclical", "Communication Services", "Financial Services")
--   * NSE Nifty bucket strings ("Nifty Auto", "Nifty Bank", "Nifty IT")
--   * Hand-curated short labels ("Bank", "Pharma", "FMCG")
--
-- Cohort SQL that joins on `sector` therefore fragments single logical
-- sectors across multiple buckets — the sector aggregator (PR #227)
-- silently misses constituents because of this.
--
-- This migration is ADDITIVE: it does NOT touch the raw `sector` column.
-- A follow-up script (scripts/migrate_canonical_sectors.py) populates
-- the new columns from a deterministic mapping that uses both
-- (raw sector, raw industry) and a per-ticker override list for the
-- 2026-05-16 mis-tag fixes (POLICYBZR, RELIGARE, HDFCLIFE, ICICIGI,
-- SBILIFE, GOCOLORS, MEDPLUS, SBICARD).
--
-- Roll-forward order
-- ------------------
-- 1. Apply this migration (adds columns + index, instant on Neon).
-- 2. Run `python scripts/migrate_canonical_sectors.py --dry-run` and
--    eyeball the per-source mapping counts.
-- 3. Run `python scripts/migrate_canonical_sectors.py --apply`.
-- 4. Backend can now SELECT canonical_sector instead of sector for
--    cohort queries (sector_aggregator already prefers canonical when
--    not None — see backend/services/sector_aggregator.py).
--
-- Rollback
-- --------
-- DROP INDEX IF EXISTS idx_stocks_canonical_sector;
-- ALTER TABLE stocks
--   DROP COLUMN IF EXISTS canonical_sector,
--   DROP COLUMN IF EXISTS canonical_industry;

ALTER TABLE stocks
    ADD COLUMN IF NOT EXISTS canonical_sector TEXT,
    ADD COLUMN IF NOT EXISTS canonical_industry TEXT;

CREATE INDEX IF NOT EXISTS idx_stocks_canonical_sector
    ON stocks(canonical_sector);

COMMENT ON COLUMN stocks.canonical_sector IS
    'Mapped from raw (sector, industry) via SECTOR_CANONICAL_MAP in '
    'backend/services/sector_taxonomy.py — use this for cohort queries. '
    'One of the 13 values in CANONICAL_SECTORS, or "Unknown" if the '
    'raw label could not be resolved. Populated by '
    'scripts/migrate_canonical_sectors.py; raw sector preserved.';

COMMENT ON COLUMN stocks.canonical_industry IS
    'Sub-bucket within canonical_sector. Free-form for now (no enum); '
    'set by scripts/migrate_canonical_sectors.py and used by the '
    'sector deep-dive page for sub-cohort medians (e.g. "Insurance" '
    'inside "Financial Services").';
