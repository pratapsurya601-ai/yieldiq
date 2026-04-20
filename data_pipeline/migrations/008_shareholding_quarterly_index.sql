-- Migration 008: shareholding_pattern (ticker, quarter_end DESC) index
--
-- Context: Today shareholding_pattern carries one row per ticker (the latest
-- quarter from the NSE master API). Phase 2.3 of the data strategy backfills
-- 5Y of quarterly history from BSE — ~10K rows for the top-500 tickers and
-- eventually ~120K for the full universe. The frontend "promoter pledge
-- rising" / "FII outflow" signals scan history per ticker ordered by
-- quarter_end DESC, so we want a covering index that matches that exact
-- access pattern.
--
-- The existing UniqueConstraint(ticker, quarter_end) gives uniqueness but
-- not the DESC ordering — Postgres can use it for equality lookups but a
-- dedicated DESC btree is cheaper for top-N-by-quarter scans.
--
-- Idempotent: CREATE INDEX IF NOT EXISTS.
--
-- Rollback:
--   DROP INDEX IF EXISTS idx_sh_ticker_quarter_desc;

CREATE INDEX IF NOT EXISTS idx_sh_ticker_quarter_desc
    ON shareholding_pattern (ticker, quarter_end DESC);

-- Optional secondary index for cross-ticker scans like
-- "all promoters with pledge > 50% as of latest quarter".
CREATE INDEX IF NOT EXISTS idx_sh_quarter_desc
    ON shareholding_pattern (quarter_end DESC);
