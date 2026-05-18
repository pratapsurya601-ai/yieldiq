-- 042_seed_structural_mergers.sql
-- 2026-05-18 — Phase-B seed rows for the structural-break CAGR overlay
-- introduced by 041_corporate_actions_structural.sql.
--
-- These rows are the operator-curated structural events that
-- backend/services/corporate_actions_service.compute_cagr_structural_aware
-- consumes to truncate the CAGR window past a merger / scheme of
-- arrangement. Without these rows, has_structural_break() returns
-- False for every ticker → callers fall through to plain CAGR (the
-- Phase-A no-op contract).
--
-- See:
--   * docs/design/hdfc-merger-growth-normalization.md  (this fix)
--   * docs/design/corporate-actions-overlay.md         (Phase-A overview)
--
-- Idempotent: ON CONFLICT DO NOTHING against the natural-key index
-- uq_corporate_actions_natural_key (ticker, ex_date, action_type)
-- introduced in 025_corporate_actions_quality_rank.sql.
--
-- Dual-path convention: mirrored at
-- db/migrations/013_seed_structural_mergers.sql.
--
-- Apply with:
--   python scripts/apply_migration.py \
--       data_pipeline/migrations/042_seed_structural_mergers.sql

INSERT INTO corporate_actions (
    ticker, ex_date, action_type, multiplier,
    source_url, source_doc, notes,
    data_source, data_quality_rank
) VALUES
    -- HDFCBANK — HDFC Ltd parent absorbed into HDFC Bank. Largest
    -- private-bank merger in Indian history; FY24 revenue ≈ 2×
    -- FY23 due to consolidation of the housing-finance book.
    ('HDFCBANK', DATE '2023-07-01', 'REVERSE_MERGER', 2.00,
     'https://www.sebi.gov.in/sebiweb/home/HomeAction.do',
     'RBI/SEBI joint approval — HDFC Ltd into HDFC Bank reverse merger',
     'HDFC Ltd parent absorbed into HDFC Bank; effective date 2023-07-01.',
     'curated', 10),

    -- AXISBANK — Citi India consumer-banking acquisition (cards,
    -- wealth, retail loans). Material but sub-structural in scale
    -- (~3% loan-book lift). Seeded so the truncation gate triggers
    -- but operators can re-classify if the per-action policy table
    -- (open question 8.3 in the design doc) decides MATERIAL_ACQUISITION
    -- should not truncate.
    ('AXISBANK', DATE '2023-03-01', 'MATERIAL_ACQUISITION', 1.03,
     'https://www.axisbank.com/investor-corner',
     'Press release — Citi India consumer-banking acquisition close',
     'Citi consumer-banking franchise acquired by Axis Bank; close 2023-03-01.',
     'curated', 10),

    -- INDUSINDBK — Bharat Financial Inclusion (microfinance) merger.
    -- Closed early FY18; outside the 3y CAGR window today but the
    -- 5y window may pick it up depending on fetch date.
    ('INDUSINDBK', DATE '2017-03-01', 'MERGER', 1.10,
     'https://www.sebi.gov.in/sebiweb/home/HomeAction.do',
     'SEBI filing — Bharat Financial Inclusion merger with IndusInd Bank',
     'BFIL microfinance arm merged into IndusInd; effective FY18.',
     'curated', 10),

    -- IDFCFIRSTB — Capital First reverse merger into IDFC Bank
    -- (creating IDFC First Bank). Outside the 3y window today but
    -- seeded for the historical record.
    ('IDFCFIRSTB', DATE '2018-12-01', 'REVERSE_MERGER', 1.40,
     'https://www.rbi.org.in/Scripts/AnnualPublications.aspx',
     'RBI approval — Capital First reverse merger into IDFC Bank',
     'Capital First reverse-merged into IDFC Bank → IDFC First Bank.',
     'curated', 10),

    -- KOTAKBANK — ING Vysya merger. Far outside the 3y CAGR window
    -- (10+ years); has_structural_break(window_years=3) will NOT
    -- pick this up. Seeded for completeness and future 10y CAGR
    -- analytics. Acts as a regression guard: this row must NOT
    -- affect the CAGR computation today.
    ('KOTAKBANK', DATE '2015-04-01', 'MERGER', 1.40,
     'https://www.rbi.org.in/Scripts/AnnualPublications.aspx',
     'RBI approval — ING Vysya merger with Kotak Mahindra Bank',
     'ING Vysya merged into Kotak Mahindra Bank; close 2015-04-01.',
     'curated', 10)
ON CONFLICT (ticker, ex_date, action_type) DO NOTHING;

COMMENT ON COLUMN corporate_actions.multiplier IS
    'Structural-event impact multiplier (e.g. ~2.0 for HDFC reverse merger). NULL for non-structural rows.';
