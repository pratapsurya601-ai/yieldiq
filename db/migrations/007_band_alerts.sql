-- 007_band_alerts.sql
-- 2026-04-29 — additive migration for the watchlist band-shift alerts feature.
--
-- Adds two tables that power the sector-percentile-band shift alert pipeline:
--
--   1. valuation_band_history — append-only audit log of each ticker's
--      computed sector-percentile band at the moment hex_service ran.
--      We compare the latest two rows to detect a shift.
--
--   2. band_alerts — append-only fan-out table. One row per (user, ticker,
--      shift) tuple. The `delivered_*` flags drive the daily-digest email
--      worker; `user_dismissed` is set by the frontend when the user
--      clicks "dismiss" in the notifications drawer.
--
-- Both tables are side-channel — they do NOT participate in the analysis
-- response wire format, so cache invalidation is unaffected and no
-- CACHE_VERSION bump is required.
--
-- Apply with `python scripts/apply_migration.py db/migrations/007_band_alerts.sql`.
-- Idempotent: CREATE TABLE / INDEX IF NOT EXISTS.

BEGIN;

-- ── 1. Per-ticker band history ─────────────────────────────────
CREATE TABLE IF NOT EXISTS valuation_band_history (
    id            BIGSERIAL PRIMARY KEY,
    ticker        VARCHAR(32) NOT NULL,
    band          VARCHAR(64) NOT NULL,        -- e.g. 'in_range', 'strong_discount'
    percentile    INTEGER,
    cohort_size   INTEGER,
    sector_label  VARCHAR(64),
    computed_at   TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    CONSTRAINT uq_valuation_band_ticker_at UNIQUE (ticker, computed_at)
);

CREATE INDEX IF NOT EXISTS idx_valuation_band_ticker
    ON valuation_band_history (ticker, computed_at DESC);

-- ── 2. Per-user fired alerts ───────────────────────────────────
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

-- Daily-digest worker scans WHERE delivered_email=FALSE AND fired_at>NOW()-'24h'.
CREATE INDEX IF NOT EXISTS idx_band_alerts_undelivered
    ON band_alerts (delivered_email, fired_at DESC)
    WHERE delivered_email = FALSE;

-- Frontend "any unread band alert for this ticker?" lookup on the
-- watchlist page.
CREATE INDEX IF NOT EXISTS idx_band_alerts_user_ticker
    ON band_alerts (user_id, ticker, fired_at DESC);

COMMIT;
