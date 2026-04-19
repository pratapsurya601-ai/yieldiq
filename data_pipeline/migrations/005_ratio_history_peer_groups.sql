-- Migration 005: RatioHistory + PeerGroup tables
--
-- Context: YieldIQ's analysis page renders current-snapshot ratios (ROE, ROCE,
-- D/E, EV/EBITDA, etc.) but nothing historical. Peers like Screener.in serve
-- 10-year ratio charts as a baseline. This migration adds the two tables
-- needed to close that gap:
--
-- 1. ratio_history  — one row per (ticker, period_end, period_type).
--    Populated by scripts/build_ratio_history.py from the financials table.
--    Indexed for fast (ticker, period_end DESC) queries.
--
-- 2. peer_groups    — one row per (ticker, peer_ticker, rank).
--    Populated by scripts/build_peer_groups.py from the stocks table.
--    Peers: same sub_sector (or sector) AND same market_cap_category,
--    top-6 by market-cap proximity. Rebuilt weekly.
--
-- Both tables are safe to drop + rebuild (no user data).
--
-- Rollback:
--   DROP TABLE IF EXISTS ratio_history;
--   DROP TABLE IF EXISTS peer_groups;

CREATE TABLE IF NOT EXISTS ratio_history (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(20)  NOT NULL,
    period_end      DATE         NOT NULL,
    period_type     VARCHAR(10)  NOT NULL,  -- 'annual' | 'quarterly' | 'ttm'

    -- Profitability
    roe             DOUBLE PRECISION,       -- Net income / shareholders equity, PERCENT
    roce            DOUBLE PRECISION,       -- EBIT / (Total Assets - Current Liab), PERCENT
    roa             DOUBLE PRECISION,       -- Net income / Total assets, PERCENT

    -- Leverage
    de_ratio        DOUBLE PRECISION,       -- Total debt / Total equity, DECIMAL (0.5 = 50%)
    debt_ebitda     DOUBLE PRECISION,       -- Total debt / EBITDA, ratio
    interest_cov    DOUBLE PRECISION,       -- EBIT / Interest expense, ratio

    -- Margins (all PERCENT)
    gross_margin    DOUBLE PRECISION,
    operating_margin DOUBLE PRECISION,
    net_margin      DOUBLE PRECISION,
    fcf_margin      DOUBLE PRECISION,

    -- Growth (YoY vs same period prior year, DECIMAL — 0.12 = 12%)
    revenue_yoy     DOUBLE PRECISION,
    ebitda_yoy      DOUBLE PRECISION,
    pat_yoy         DOUBLE PRECISION,
    fcf_yoy         DOUBLE PRECISION,

    -- Valuation (point-in-time at period_end)
    pe_ratio        DOUBLE PRECISION,
    pb_ratio        DOUBLE PRECISION,
    ev_ebitda       DOUBLE PRECISION,
    dividend_yield  DOUBLE PRECISION,        -- PERCENT
    market_cap_cr   DOUBLE PRECISION,        -- Market cap in crores at period_end

    -- Liquidity / efficiency
    current_ratio   DOUBLE PRECISION,
    asset_turnover  DOUBLE PRECISION,

    -- Provenance
    computed_at     TIMESTAMP    NOT NULL DEFAULT now(),
    source_version  VARCHAR(10),             -- matches backend CACHE_VERSION when computed

    CONSTRAINT ratio_history_unique
        UNIQUE (ticker, period_end, period_type)
);

CREATE INDEX IF NOT EXISTS idx_ratio_history_ticker_period
    ON ratio_history (ticker, period_end DESC);

CREATE INDEX IF NOT EXISTS idx_ratio_history_period_type
    ON ratio_history (ticker, period_type, period_end DESC);


CREATE TABLE IF NOT EXISTS peer_groups (
    id              BIGSERIAL PRIMARY KEY,
    ticker          VARCHAR(20)  NOT NULL,
    peer_ticker     VARCHAR(20)  NOT NULL,
    rank            INTEGER      NOT NULL,  -- 1 = closest peer, 6 = 6th
    reason          VARCHAR(100),            -- e.g. "same_sub_sector_mcap_proximity"
    mcap_ratio      DOUBLE PRECISION,        -- peer_mcap / ticker_mcap (for proximity)
    sector          VARCHAR(100),            -- Snapshot of sector at build time
    sub_sector      VARCHAR(100),
    computed_at     TIMESTAMP    NOT NULL DEFAULT now(),

    CONSTRAINT peer_groups_unique
        UNIQUE (ticker, peer_ticker),
    CONSTRAINT peer_groups_rank_check
        CHECK (rank BETWEEN 1 AND 10)
);

CREATE INDEX IF NOT EXISTS idx_peer_groups_ticker
    ON peer_groups (ticker, rank);


-- Seed empty — populated by scripts.

-- ---------------------------------------------------------------------
-- Forward-compat: record the migration so alembic/version tracking can
-- recognise it. If you use manual runs, this is a no-op comment.
-- ---------------------------------------------------------------------
