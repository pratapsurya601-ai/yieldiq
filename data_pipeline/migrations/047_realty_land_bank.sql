-- 047_realty_land_bank.sql
-- 2026-05-18 — Realty developer land-bank multiplier (Approach C engine).
--
-- Per docs/design/realty-developers-dcf-fix.md §5.4, the realty-developer
-- engine routes through a curated table:
--
--   FV_per_share = (BVPS × sector_peer_PB) + uplift_per_share
--
-- The uplift is derived from the annual-report land-bank schedule:
--
--   uplift_per_share = (land_bank_market_value_cr - land_bank_book_value_cr)
--                      * 1e7 / shares_outstanding
--
-- A 2-hour annual operator pass populates this table from each company's
-- most recent annual report (acres × city-blended ₹/acre × realisation
-- haircut). The engine ONLY routes through Approach C when a curation
-- row exists; otherwise the ticker falls through to the existing Tier 2
-- generic path. This is why no CACHE_VERSION bump is required — the
-- table being empty is the no-op default.
--
-- Idempotent: CREATE TABLE / INDEX use IF NOT EXISTS so re-application
-- is safe.
--
-- Dual-path convention (mirror at db/migrations/017_realty_land_bank.sql).
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/047_realty_land_bank.sql

CREATE TABLE IF NOT EXISTS realty_land_bank_inputs (
    ticker                       TEXT          PRIMARY KEY,
    reporting_fy                 TEXT          NOT NULL,         -- "FY25", "FY26", ...
    land_bank_acres              NUMERIC(14,2),
    land_bank_market_value_cr    NUMERIC(14,2) NOT NULL,         -- ₹ Cr
    land_bank_book_value_cr      NUMERIC(14,2),                  -- ₹ Cr
    unsold_inventory_cr          NUMERIC(14,2),
    pre_sales_pipeline_cr        NUMERIC(14,2),
    uplift_per_share             NUMERIC(14,2) NOT NULL,         -- ₹/share
    source_url                   TEXT,
    entered_by                   TEXT,
    entered_at                   TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_realty_land_bank_entered_at
    ON realty_land_bank_inputs (entered_at DESC);

COMMENT ON TABLE realty_land_bank_inputs IS
    'Curated land-bank uplift table for the Realty developer Approach-C engine. '
    'Refreshed annually (~2h operator pass) from each company''s annual-report '
    'land-bank schedule. Engine routes through this table when a row exists.';
COMMENT ON COLUMN realty_land_bank_inputs.uplift_per_share IS
    '(land_bank_market_value_cr - land_bank_book_value_cr) × 1e7 / shares_outstanding. '
    'Added on top of (BVPS × sector_peer_PB) in the realty FV formula.';
COMMENT ON COLUMN realty_land_bank_inputs.reporting_fy IS
    'Source-annual-report FY label, e.g. "FY25". Used to compute the '
    '"next annual review due" date (entered_at + 1 year) shown in the admin UI.';
