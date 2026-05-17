-- 040_earnings_calendar.sql
-- ─────────────────────────────────────────────────────────────────
-- Earnings calendar unification (feat/earnings-calendar-unification).
--
-- We already have `upcoming_earnings` (added in an earlier unnumbered
-- migration via SQLAlchemy create_all) populated by the NSE event
-- calendar cron. This migration is additive: it extends that table
-- with provenance / confidence / fiscal-period columns so that EVERY
-- surface (analysis Summary card, Discover Earnings This Week strip,
-- home EarningsWeekStrip, future watchlist alerts) can read the same
-- row and render consistent badges.
--
-- New columns
--   source         text       — 'nse_event_calendar' | 'yfinance' |
--                               'finnhub' | 'manual_backfill'
--   confirmed      boolean    — true when the company has filed the
--                               intimation with NSE (purpose contains
--                               'financial result'); false for
--                               yfinance/finnhub *expected* dates
--   fiscal_period  text       — 'Q1FY27' / 'Q4FY26' etc; derived from
--                               event_date by service layer
--   fetched_at     timestamptz — when this row was last refreshed
--
-- All four columns are nullable so existing rows keep working without
-- a backfill (the service layer treats NULL source as 'nse_event_
-- calendar' for back-compat with rows the cron wrote before this PR).
--
-- Idempotent: every ALTER uses IF NOT EXISTS.
-- ─────────────────────────────────────────────────────────────────

ALTER TABLE upcoming_earnings
    ADD COLUMN IF NOT EXISTS source        TEXT,
    ADD COLUMN IF NOT EXISTS confirmed     BOOLEAN DEFAULT TRUE,
    ADD COLUMN IF NOT EXISTS fiscal_period TEXT,
    ADD COLUMN IF NOT EXISTS fetched_at    TIMESTAMPTZ DEFAULT NOW();

COMMENT ON COLUMN upcoming_earnings.source IS
    'Provenance: nse_event_calendar (preferred), yfinance, finnhub, manual_backfill. NULL treated as nse_event_calendar for legacy rows.';
COMMENT ON COLUMN upcoming_earnings.confirmed IS
    'TRUE when the company has filed an NSE intimation (purpose contains "financial result"); FALSE for yfinance/finnhub expected dates.';
COMMENT ON COLUMN upcoming_earnings.fiscal_period IS
    'Indian fiscal period label, e.g. Q1FY27. Derived from event_date.';
COMMENT ON COLUMN upcoming_earnings.fetched_at IS
    'When this row was last fetched/refreshed. Used by the daily cron to skip recently-fetched tickers.';

-- Helpful covering index for the hot "next earnings for ticker" lookup.
CREATE INDEX IF NOT EXISTS ix_upcoming_earnings_ticker_date
    ON upcoming_earnings (ticker, event_date);
