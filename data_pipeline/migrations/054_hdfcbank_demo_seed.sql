-- Day-103d (2026-05-22): demo seed for HDFCBANK.NS against the
-- CANONICAL tables. Replaces the seed rows that were inserted into
-- the now-dropped `concalls` (051a) and `annual_reports` (052a)
-- duplicate tables.
--
-- Idempotent: ON CONFLICT DO NOTHING on both natural keys.
--
-- Rationale: the concalls + AR panels render against the panel
-- endpoints regardless of whether real ingestion has populated the
-- canonical tables yet. Seeding a handful of HDFCBANK.NS rows lets
-- audit screens and the staging environment exercise the live UI.

-- ── concall_transcripts ───────────────────────────────────────
-- Schema: (ticker, filing_date, quarter_end, pdf_url, subject, category)
-- Natural key: UNIQUE (ticker, filing_date, subject).
-- The subject string carries the period semantics — the service
-- parses "Q3 FY26" / "Q3-FY26" patterns out at read time.

INSERT INTO concall_transcripts (ticker, filing_date, quarter_end, pdf_url, subject, category)
VALUES
    (
        'HDFCBANK.NS',
        DATE '2025-07-19',
        DATE '2025-06-30',
        'https://www.hdfcbank.com/personal/about-us/investor-relations/seed/q1-fy26-concall',
        'Q1 FY26 earnings call',
        'earnings_call'
    ),
    (
        'HDFCBANK.NS',
        DATE '2025-10-19',
        DATE '2025-09-30',
        'https://www.hdfcbank.com/personal/about-us/investor-relations/seed/q2-fy26-concall',
        'Q2 FY26 earnings call',
        'earnings_call'
    ),
    (
        'HDFCBANK.NS',
        DATE '2026-01-18',
        DATE '2025-12-31',
        'https://www.hdfcbank.com/personal/about-us/investor-relations/seed/q3-fy26-concall',
        'Q3 FY26 earnings call',
        'earnings_call'
    )
ON CONFLICT (ticker, filing_date, subject) DO NOTHING;

-- ── company_annual_reports ────────────────────────────────────
-- Schema: rich; we populate only the link-index columns here.
-- Natural key: UNIQUE (ticker, fiscal_year).

INSERT INTO company_annual_reports (ticker, fiscal_year, ar_url, source, published_at)
VALUES
    ('HDFCBANK.NS', 2022, 'https://www.bseindia.com/bseplus/AnnualReport/500180/79921500180.pdf', 'manual', DATE '2022-05-26'),
    ('HDFCBANK.NS', 2023, 'https://www.bseindia.com/bseplus/AnnualReport/500180/85910500180.pdf', 'manual', DATE '2023-05-17'),
    ('HDFCBANK.NS', 2024, 'https://www.bseindia.com/bseplus/AnnualReport/500180/91619500180.pdf', 'manual', DATE '2024-05-22'),
    ('HDFCBANK.NS', 2025, 'https://www.bseindia.com/bseplus/AnnualReport/500180/97520500180.pdf', 'manual', DATE '2025-05-21')
ON CONFLICT (ticker, fiscal_year) DO NOTHING;
