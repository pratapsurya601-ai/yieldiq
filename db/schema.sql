-- ═══════════════════════════════════════════════════════════════
-- YieldIQ — Supabase PostgreSQL Schema
-- Run this in Supabase SQL Editor (Dashboard → SQL Editor → New Query)
-- ═══════════════════════════════════════════════════════════════

-- 1. Users metadata (extends Supabase auth.users)
CREATE TABLE IF NOT EXISTS users_meta (
    id              UUID PRIMARY KEY REFERENCES auth.users(id) ON DELETE CASCADE,
    email           TEXT UNIQUE NOT NULL,
    tier            TEXT NOT NULL DEFAULT 'free',
    is_active       BOOLEAN NOT NULL DEFAULT true,
    -- NULL = treated as not opted out (default mailing-allowed). See
    -- newsletter_service.get_weekly_pick_recipients for the OR clause.
    email_opted_out BOOLEAN DEFAULT false,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at      TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 2. Subscriptions (Razorpay)
CREATE TABLE IF NOT EXISTS subscriptions (
    id                  BIGSERIAL PRIMARY KEY,
    user_email          TEXT NOT NULL,
    razorpay_sub_id     TEXT UNIQUE,
    razorpay_payment_id TEXT,
    razorpay_plan_id    TEXT NOT NULL,
    tier                TEXT NOT NULL,
    status              TEXT NOT NULL DEFAULT 'created',
    amount_paise        INTEGER,
    currency            TEXT DEFAULT 'INR',
    current_end         TEXT,
    created_at          TIMESTAMPTZ DEFAULT now(),
    updated_at          TIMESTAMPTZ DEFAULT now()
);
CREATE INDEX IF NOT EXISTS idx_sub_email ON subscriptions(user_email);

-- 3. Portfolio
CREATE TABLE IF NOT EXISTS portfolio (
    id           BIGSERIAL PRIMARY KEY,
    user_email   TEXT NOT NULL DEFAULT '',
    ticker       TEXT NOT NULL,
    company_name TEXT,
    entry_price  REAL,
    iv           REAL,
    mos_pct      REAL,
    signal       TEXT,
    wacc         REAL,
    sym          TEXT DEFAULT '$',
    to_code      TEXT DEFAULT 'USD',
    notes        TEXT DEFAULT '',
    saved_at     TEXT,
    sector       TEXT DEFAULT '',
    UNIQUE(user_email, ticker)
);

-- 4. Watchlist
CREATE TABLE IF NOT EXISTS watchlist (
    id             BIGSERIAL PRIMARY KEY,
    user_email     TEXT NOT NULL,
    ticker         TEXT NOT NULL,
    company_name   TEXT DEFAULT '',
    added_price    REAL DEFAULT 0,
    target_price   REAL DEFAULT 0,
    mos_threshold  REAL DEFAULT 20,
    note           TEXT DEFAULT '',
    added_at       TEXT DEFAULT '',
    UNIQUE(user_email, ticker)
);

-- 5. Price alerts
CREATE TABLE IF NOT EXISTS price_alerts (
    id            BIGSERIAL PRIMARY KEY,
    user_email    TEXT NOT NULL,
    ticker        TEXT NOT NULL,
    alert_type    TEXT NOT NULL DEFAULT 'below',
    target_price  REAL NOT NULL,
    is_active     BOOLEAN NOT NULL DEFAULT true,
    created_at    TIMESTAMPTZ DEFAULT now(),
    triggered_at  TIMESTAMPTZ
);
CREATE INDEX IF NOT EXISTS idx_alerts_email ON price_alerts(user_email);

-- 6. Analysis events (analytics)
CREATE TABLE IF NOT EXISTS analysis_events (
    id          BIGSERIAL PRIMARY KEY,
    user_email  TEXT,
    tier        TEXT,
    ticker      TEXT,
    signal      TEXT,
    mos_pct     REAL,
    wacc        REAL,
    market      TEXT DEFAULT 'US',
    ts          TIMESTAMPTZ DEFAULT now(),
    duration_ms INTEGER
);

-- 7. Event log (product analytics)
CREATE TABLE IF NOT EXISTS event_log (
    id         BIGSERIAL PRIMARY KEY,
    user_email TEXT,
    tier       TEXT,
    event_type TEXT,
    meta       JSONB DEFAULT '{}',
    ts         TIMESTAMPTZ DEFAULT now()
);

-- 8. Nudge log (upgrade prompt tracking)
CREATE TABLE IF NOT EXISTS nudge_log (
    id         BIGSERIAL PRIMARY KEY,
    user_email TEXT,
    tier       TEXT,
    nudge_type TEXT,
    action     TEXT DEFAULT 'shown',
    ts         TIMESTAMPTZ DEFAULT now()
);

-- 9. User onboarding
CREATE TABLE IF NOT EXISTS user_onboarding (
    id                   BIGSERIAL PRIMARY KEY,
    user_email           TEXT UNIQUE NOT NULL,
    onboarding_completed BOOLEAN DEFAULT false,
    last_step            INTEGER DEFAULT 1,
    completed_at         TIMESTAMPTZ,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
);

-- 10. Institutional ownership history
CREATE TABLE IF NOT EXISTS institutional_ownership_history (
    id            BIGSERIAL PRIMARY KEY,
    ticker        TEXT NOT NULL,
    filing_date   TEXT,
    total_shares  BIGINT,
    total_value   BIGINT,
    num_holders   INTEGER,
    top_10_pct    REAL,
    updated_at    TIMESTAMPTZ DEFAULT now()
);

-- 11. User sheets settings
CREATE TABLE IF NOT EXISTS user_sheets_settings (
    id              BIGSERIAL PRIMARY KEY,
    user_email      TEXT UNIQUE NOT NULL,
    spreadsheet_id  TEXT,
    range           TEXT,
    last_synced     TIMESTAMPTZ,
    created_at      TIMESTAMPTZ DEFAULT now()
);

-- 12. Price snapshots (backtesting)
CREATE TABLE IF NOT EXISTS price_snapshots (
    id          BIGSERIAL PRIMARY KEY,
    ticker      TEXT NOT NULL,
    saved_at    TEXT NOT NULL,
    entry_price REAL,
    iv          REAL,
    signal      TEXT,
    horizon     TEXT,
    snap_date   TEXT,
    snap_price  REAL,
    hit         BOOLEAN,
    return_pct  REAL,
    vs_iv_pct   REAL,
    UNIQUE(ticker, saved_at, horizon)
);

-- 13a. PAYG (pay-as-you-go) analysis unlocks
-- One row per successful ₹99 single-analysis purchase. The "unlock"
-- lasts 24h from unlocked_at — enforce the TTL in application code
-- since Postgres has no native row-expiry.
CREATE TABLE IF NOT EXISTS payg_unlocks (
    id                  BIGSERIAL PRIMARY KEY,
    user_email          TEXT NOT NULL,
    ticker              TEXT NOT NULL,
    razorpay_payment_id TEXT,
    razorpay_order_id   TEXT,
    amount_paise        INTEGER,
    unlocked_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    -- Idempotency: one Razorpay payment_id maps to exactly one unlock
    -- (so a retried /verify call doesn't create duplicate rows).
    UNIQUE(razorpay_payment_id)
);
CREATE INDEX IF NOT EXISTS idx_payg_user_ticker
    ON payg_unlocks(user_email, ticker, unlocked_at DESC);

-- 13. Sector DCF cache
CREATE TABLE IF NOT EXISTS sector_dcf_cache (
    sector      TEXT PRIMARY KEY,
    avg_mos     REAL,
    pct_under   REAL,
    pct_over    REAL,
    avg_wacc    REAL,
    top_pick    TEXT,
    stocks_json JSONB,
    updated_at  TIMESTAMPTZ DEFAULT now()
);

-- ═══════════════════════════════════════════════════════════════
-- Trigger: auto-update updated_at on users_meta changes
-- ═══════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION update_updated_at()
RETURNS TRIGGER AS $$
BEGIN
    NEW.updated_at = now();
    RETURN NEW;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER users_meta_updated_at
    BEFORE UPDATE ON users_meta
    FOR EACH ROW EXECUTE FUNCTION update_updated_at();

-- ═══════════════════════════════════════════════════════════════
-- Trigger: auto-create users_meta row when auth.users signup
-- ═══════════════════════════════════════════════════════════════
CREATE OR REPLACE FUNCTION handle_new_user()
RETURNS TRIGGER AS $$
BEGIN
    INSERT INTO public.users_meta (id, email, tier)
    VALUES (NEW.id, NEW.email, 'free')
    ON CONFLICT (id) DO NOTHING;
    RETURN NEW;
END;
$$ LANGUAGE plpgsql SECURITY DEFINER;

CREATE TRIGGER on_auth_user_created
    AFTER INSERT ON auth.users
    FOR EACH ROW EXECUTE FUNCTION handle_new_user();
