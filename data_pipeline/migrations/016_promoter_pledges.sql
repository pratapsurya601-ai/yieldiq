BEGIN;

-- Migration 016: promoter_pledges — track promoter share pledging.
--
-- Indian governance signal #1. Promoters pledging shares as collateral
-- for loans is a leading red flag (RCOM, Anil Ambani group, Zee, etc.).
-- BSE and NSE both publish pledge disclosures publicly:
--   * https://www.bseindia.com/corporates/sastpledge.aspx
--   * https://www.nseindia.com/companies-listing/corporate-filings-pledge
--
-- We snapshot one row per (ticker, as_of_date). `pledged_pct` is the
-- pledged fraction OF THE PROMOTER HOLDING (not of total shares
-- outstanding) — this is the convention used in the disclosures and
-- on screener.in. `promoter_group_pct` lets us reconstruct an
-- "% of total" view downstream if we want it.
--
-- See `docs/promoter_pledge_tracking_design.md` for refresh cadence,
-- alerting thresholds, and historical-backfill strategy.
--
-- Idempotent: CREATE TABLE / INDEX IF NOT EXISTS, plus a defensive
-- ON CONFLICT path baked into the unique constraint so the ingest
-- job can re-run a day without duplicating rows.

CREATE TABLE IF NOT EXISTS promoter_pledges (
    id BIGSERIAL PRIMARY KEY,
    ticker VARCHAR(20) NOT NULL REFERENCES stocks(ticker),
    as_of_date DATE NOT NULL,
    promoter_group_pct NUMERIC(6,3),       -- promoter total holding % of company
    pledged_pct NUMERIC(6,3),              -- of promoter holding, % pledged
    pledged_shares BIGINT,
    source_url VARCHAR(500),               -- BSE/NSE filing link
    fetched_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (ticker, as_of_date)
);

-- Hot query: "latest pledge for this ticker" and "pledge series for
-- this ticker over the last 90/365 days". Both want a (ticker, date DESC)
-- composite scan.
CREATE INDEX IF NOT EXISTS idx_pledges_ticker_date
    ON promoter_pledges (ticker, as_of_date DESC);

COMMIT;
