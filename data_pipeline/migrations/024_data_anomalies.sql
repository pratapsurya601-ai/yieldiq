CREATE TABLE IF NOT EXISTS data_anomalies (
    id SERIAL PRIMARY KEY,
    detected_at TIMESTAMPTZ DEFAULT NOW(),
    table_name VARCHAR(64) NOT NULL,
    ticker VARCHAR(32),
    field VARCHAR(64),
    suspected_value TEXT,                -- TEXT not NUMERIC — sometimes the value is a string ('USD'), sometimes null
    plausible_range_or_reason TEXT,      -- e.g. "PE > 500", "currency='USD' on Indian-primary", "mcap dropped >70% w/w"
    auto_handled VARCHAR(16) NOT NULL,   -- 'rejected' | 'logged' | 'overwritten' | 'flagged'
    source VARCHAR(32),                  -- the data_source that produced the bad value (yfinance, NSE_XBRL, etc.)
    notes TEXT,
    raw_payload JSONB                     -- optional dump of the rejected row for forensics
);

CREATE INDEX IF NOT EXISTS idx_data_anomalies_detected_at
    ON data_anomalies(detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_data_anomalies_table_ticker
    ON data_anomalies(table_name, ticker, detected_at DESC);
CREATE INDEX IF NOT EXISTS idx_data_anomalies_handled
    ON data_anomalies(auto_handled, detected_at DESC);

COMMENT ON TABLE data_anomalies IS
    'Telemetry for data-layer guards: rejected/suspicious writes from ingest paths and read-time validators. Used to diagnose data-quality regressions and to feed weekly review.';
