-- Migration 009: concall_transcripts table
--
-- Stores metadata about earnings-call / analyst-meet filings fetched from
-- the NSE corporate-announcements API. The PDF itself is NOT downloaded
-- or parsed here -- we only persist the attachment URL plus filing meta
-- so the existing /concall page can surface links. A follow-up task will
-- fetch + OCR/parse the PDFs (expensive; not done inline).
--
-- Schema rationale:
--   - (ticker, filing_date, subject) is a natural dedupe key; NSE can
--     occasionally re-publish the same announcement with a new id so we
--     dedupe on content triple rather than on NSE's own id.
--   - quarter_end is best-effort -- parsed from free-text subject lines
--     like "Q3 FY25 earnings call" or "Quarter ended 30 June 2024".
--     Nullable because some meet-type filings don't reference a quarter.
--
-- Idempotent: CREATE TABLE IF NOT EXISTS + CREATE INDEX IF NOT EXISTS.
--
-- Rollback:
--   DROP TABLE IF EXISTS concall_transcripts;

CREATE TABLE IF NOT EXISTS concall_transcripts (
    id           SERIAL PRIMARY KEY,
    ticker       TEXT NOT NULL,
    filing_date  DATE NOT NULL,
    quarter_end  DATE,
    pdf_url      TEXT,
    subject      TEXT NOT NULL,
    category     TEXT,
    created_at   TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_concall_ticker_date_subject
        UNIQUE (ticker, filing_date, subject)
);

CREATE INDEX IF NOT EXISTS idx_concall_ticker_date
    ON concall_transcripts (ticker, filing_date DESC);

CREATE INDEX IF NOT EXISTS idx_concall_filing_date
    ON concall_transcripts (filing_date DESC);
