-- 056_price_adjustment_log.sql
-- 2026-05-23 — Day-112 robust price data infrastructure.
--
-- Why this exists:
--   Until today, every populator that wrote to daily_prices set
--   `adj_close = close_price`. The pipeline carried no record of the
--   corporate-action math that should have produced an adjusted close.
--   Symptoms: RELIANCE 5y stock-CAGR rendered as -7.8% in production
--   because the engine compared a raw post-bonus close to a raw
--   pre-bonus close.
--
--   `scripts/rebuild_adj_close.py` (added in this PR) overwrites
--   daily_prices.adj_close with the correctly-adjusted series sourced
--   from yfinance auto_adjust=False (Adj Close) cross-validated against
--   the splits/bonuses we already store in `corporate_actions`. Every
--   write goes through this log so an operator can later answer:
--     "Why did RELIANCE's 2020-08-12 adj_close change from X to Y?
--      What corp action caused it?"
--
-- Idempotent: CREATE TABLE / INDEX IF NOT EXISTS.

CREATE TABLE IF NOT EXISTS price_adjustment_log (
    id                  BIGSERIAL PRIMARY KEY,
    ticker              TEXT      NOT NULL,
    trade_date          DATE      NOT NULL,
    close_price         NUMERIC,
    adj_close_before    NUMERIC,
    adj_close_after     NUMERIC,
    adjustment_factor   NUMERIC,
    source              TEXT      NOT NULL,
    corp_actions        JSONB,
    rebuilt_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT uq_padjlog_natural
        UNIQUE (ticker, trade_date, rebuilt_at)
);

CREATE INDEX IF NOT EXISTS idx_padjlog_ticker_date
    ON price_adjustment_log (ticker, trade_date DESC);

CREATE INDEX IF NOT EXISTS idx_padjlog_rebuilt_at
    ON price_adjustment_log (rebuilt_at DESC);

CREATE INDEX IF NOT EXISTS idx_padjlog_source
    ON price_adjustment_log (source);

COMMENT ON TABLE price_adjustment_log IS
    'Day-112 audit trail. Every write to daily_prices.adj_close performed by '
    'scripts/rebuild_adj_close.py is logged here with before/after values, '
    'the adjustment factor applied, the source (yfinance / nse_corp_actions / '
    'reconciled), and the corporate-action JSON that produced it.';

COMMENT ON COLUMN price_adjustment_log.source IS
    'One of: yfinance, nse_corp_actions, reconciled, manual.';

COMMENT ON COLUMN price_adjustment_log.corp_actions IS
    'JSON of corporate actions in effect at/after this trade_date that produced '
    'the adjustment_factor, e.g. {"splits":[{"ex_date":"2020-08-12","ratio":"1:2"}],'
    '"bonuses":[],"dividends":[]}.';

COMMENT ON COLUMN price_adjustment_log.adjustment_factor IS
    'Multiplicative factor applied to close_price to produce adj_close_after, '
    'i.e. adj_close_after = close_price * adjustment_factor (split-only model). '
    'A 1:2 split on a future date gives adjustment_factor = 0.5 for dates before '
    'the ex-date; 1.0 after.';
