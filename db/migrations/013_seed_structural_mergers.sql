-- 013_seed_structural_mergers.sql
-- 2026-05-18 — db/ mirror of
-- data_pipeline/migrations/042_seed_structural_mergers.sql.
--
-- See that file for the canonical comments; this file exists solely
-- to keep the dual migration trees in lockstep per the convention
-- established by 010/012/025/041.

INSERT INTO corporate_actions (
    ticker, ex_date, action_type, multiplier,
    source_url, source_doc, notes,
    data_source, data_quality_rank
) VALUES
    ('HDFCBANK', DATE '2023-07-01', 'REVERSE_MERGER', 2.00,
     'https://www.sebi.gov.in/sebiweb/home/HomeAction.do',
     'RBI/SEBI joint approval — HDFC Ltd into HDFC Bank reverse merger',
     'HDFC Ltd parent absorbed into HDFC Bank; effective date 2023-07-01.',
     'curated', 10),

    ('AXISBANK', DATE '2023-03-01', 'MATERIAL_ACQUISITION', 1.03,
     'https://www.axisbank.com/investor-corner',
     'Press release — Citi India consumer-banking acquisition close',
     'Citi consumer-banking franchise acquired by Axis Bank; close 2023-03-01.',
     'curated', 10),

    ('INDUSINDBK', DATE '2017-03-01', 'MERGER', 1.10,
     'https://www.sebi.gov.in/sebiweb/home/HomeAction.do',
     'SEBI filing — Bharat Financial Inclusion merger with IndusInd Bank',
     'BFIL microfinance arm merged into IndusInd; effective FY18.',
     'curated', 10),

    ('IDFCFIRSTB', DATE '2018-12-01', 'REVERSE_MERGER', 1.40,
     'https://www.rbi.org.in/Scripts/AnnualPublications.aspx',
     'RBI approval — Capital First reverse merger into IDFC Bank',
     'Capital First reverse-merged into IDFC Bank → IDFC First Bank.',
     'curated', 10),

    ('KOTAKBANK', DATE '2015-04-01', 'MERGER', 1.40,
     'https://www.rbi.org.in/Scripts/AnnualPublications.aspx',
     'RBI approval — ING Vysya merger with Kotak Mahindra Bank',
     'ING Vysya merged into Kotak Mahindra Bank; close 2015-04-01.',
     'curated', 10)
ON CONFLICT (ticker, ex_date, action_type) DO NOTHING;
