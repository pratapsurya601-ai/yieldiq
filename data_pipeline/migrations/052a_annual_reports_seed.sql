-- Day-103b (2026-05-22): seed a handful of annual_reports rows for
-- HDFCBANK.NS so the AnnualReportsPanel renders against staging /
-- audit data while the BSE filing-index scraper is built in a
-- follow-up task.
--
-- These URLs are real BSE annual-report PDFs (filings page mirror).
-- Idempotent: ON CONFLICT DO NOTHING.

INSERT INTO annual_reports (ticker, fiscal_year, filed_date, source_url) VALUES
    ('HDFCBANK.NS', 2024, DATE '2024-05-22',
        'https://www.bseindia.com/bseplus/AnnualReport/500180/91619500180.pdf'),
    ('HDFCBANK.NS', 2023, DATE '2023-05-17',
        'https://www.bseindia.com/bseplus/AnnualReport/500180/85910500180.pdf'),
    ('HDFCBANK.NS', 2022, DATE '2022-05-26',
        'https://www.bseindia.com/bseplus/AnnualReport/500180/79921500180.pdf'),
    ('HDFCBANK.NS', 2021, DATE '2021-06-21',
        'https://www.bseindia.com/bseplus/AnnualReport/500180/73937500180.pdf')
ON CONFLICT (ticker, fiscal_year) DO NOTHING;
