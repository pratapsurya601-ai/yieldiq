BEGIN;

-- Migration 017: related_party_transactions — RPT analyzer (scaffolding).
--
-- Indian governance bread-and-butter. Related-party transactions (RPTs)
-- are disclosed in:
--   * AOC-2 schedule (Section 188 of the Companies Act 2013) — material
--     contracts/arrangements with related parties, with arms-length flag.
--   * MGT-9 (extract of annual return) — related-party listing.
--   * Notes to the financial statements — actual transaction values.
--
-- Western data platforms ignore this almost entirely. SEBI Listing
-- Obligations Reg 23 + Companies Act Sec 188 force these disclosures,
-- but they live in PDF annual reports — not XBRL — and need extraction.
--
-- Schema deliberately stores ONE row per (party, txn_type, amount)
-- so we can summarise by txn_type and run red-flag rules without
-- re-parsing JSON blobs. See docs/related_party_analyzer_design.md.
--
-- Idempotent: CREATE TABLE / INDEX IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS related_party_transactions (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL,
    fiscal_year SMALLINT NOT NULL,
    -- Source filing the row was extracted from. Helps audit + replay.
    --   AOC-2        -- Companies Act Sec 188 material-contracts schedule
    --   MGT-9        -- annual-return extract (named related parties)
    --   AnnualReport -- generic AR section (not labelled MGT/AOC)
    --   NoteN        -- numbered note in financial statements (P&L / BS)
    source_filing VARCHAR(20) NOT NULL,
    related_party_name VARCHAR(300) NOT NULL,
    -- Categorisation per AS-18 / Ind-AS-24 / SEBI LODR Reg 23.
    --   subsidiary | associate | kmp | promoter_entity |
    --   director_entity | relative_kmp | other
    related_party_type VARCHAR(50),
    -- Type of transaction:
    --   loan_given | loan_taken | sale_goods | purchase_goods |
    --   rendering_service | receiving_service | royalty | rent |
    --   guarantee | asset_sale | asset_purchase | investment | other
    txn_type VARCHAR(50) NOT NULL,
    amount_inr NUMERIC(15,2),
    -- Declared in AOC-2: whether the txn is on arms-length terms.
    -- NULL = not declared / not applicable / unknown.
    is_arms_length BOOLEAN,
    description TEXT,
    source_pdf_url VARCHAR(500),
    source_page INT,
    llm_extracted BOOLEAN DEFAULT TRUE,
    -- 0.00–1.00 confidence from the extracting LLM. Rows below the
    -- auto-publish threshold (default 0.85) should be queued for
    -- human review before exposure on the analysis page.
    llm_confidence NUMERIC(3,2),
    human_reviewed BOOLEAN DEFAULT FALSE,
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    -- Dedup key: same party + same txn_type + same amount in the same
    -- year is almost certainly a re-extraction, not a new disclosure.
    -- amount_inr deliberately part of the key so $0 / NULL rows do not
    -- collide with real disclosures (Postgres treats NULLs as distinct
    -- in unique constraints).
    UNIQUE (ticker, fiscal_year, related_party_name, txn_type, amount_inr)
);

-- Hottest query: "give me all RPTs for ticker X for the last N years"
-- (analysis page sidebar + governance red-flag chip).
CREATE INDEX IF NOT EXISTS idx_rpt_ticker_year
    ON related_party_transactions (ticker, fiscal_year DESC);

-- Used by the cross-ticker red-flag scan ("show every promoter-entity
-- loan across the universe") and by frontend filters.
CREATE INDEX IF NOT EXISTS idx_rpt_party_type
    ON related_party_transactions (related_party_type);

COMMIT;
