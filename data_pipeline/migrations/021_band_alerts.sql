BEGIN;

-- Migration 021: band-shift alerts.
--
-- Mirror of db/migrations/007_band_alerts.sql so the data_pipeline migrate
-- runner picks the schema up alongside the existing alerts/notifications
-- tables. Keeping both files identical means `apply_migration.py` and
-- the data_pipeline migrate script converge on the same shape regardless
-- of which entry point ops uses.
--
-- Side-channel only — does NOT touch the analysis response wire format,
-- so no CACHE_VERSION bump is required.

CREATE TABLE IF NOT EXISTS valuation_band_history (
    id            BIGSERIAL PRIMARY KEY,
    ticker        VARCHAR(32) NOT NULL,
    band          VARCHAR(64) NOT NULL,
    percentile    INTEGER,
    cohort_size   INTEGER,
    sector_label  VARCHAR(64),
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_valuation_band_ticker_at UNIQUE (ticker, computed_at)
);

CREATE INDEX IF NOT EXISTS idx_valuation_band_ticker
    ON valuation_band_history (ticker, computed_at DESC);

CREATE TABLE IF NOT EXISTS band_alerts (
    id                BIGSERIAL PRIMARY KEY,
    user_id           TEXT NOT NULL,
    ticker            VARCHAR(32) NOT NULL,
    from_band         VARCHAR(64),
    to_band           VARCHAR(64),
    fired_at          TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    delivered_email   BOOLEAN NOT NULL DEFAULT FALSE,
    delivered_push    BOOLEAN NOT NULL DEFAULT FALSE,
    user_dismissed    BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE INDEX IF NOT EXISTS idx_band_alerts_user
    ON band_alerts (user_id, fired_at DESC);

CREATE INDEX IF NOT EXISTS idx_band_alerts_undelivered
    ON band_alerts (delivered_email, fired_at DESC)
    WHERE delivered_email = FALSE;

CREATE INDEX IF NOT EXISTS idx_band_alerts_user_ticker
    ON band_alerts (user_id, ticker, fired_at DESC);

COMMIT;
