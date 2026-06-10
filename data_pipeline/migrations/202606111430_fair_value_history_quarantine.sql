-- ═════════════════════════════════════════════════════════════════
-- Migration: fair_value_history_quarantine table
-- ROOT CAUSE #12 — 2026-06-11
-- ═════════════════════════════════════════════════════════════════
--
-- Sibling table to ``fair_value_history``. Receives rows that the
-- WRITE-time sanity gate (backend/services/fair_value_history_writer.py)
-- rejected for failing the daily |Δ| > 25 % corroboration test.
-- Rejected writes are EVIDENCE — they are preserved here so an
-- operator can review the cluster and adjust the canonical row
-- after deciding whether the move was real (and merely needed a
-- contemporaneous manifest entry) or a genuine engine anomaly.
--
-- Idempotent (CREATE TABLE IF NOT EXISTS + ALTER TABLE ... IF NOT
-- EXISTS where supported). Safe to re-run.

CREATE TABLE IF NOT EXISTS fair_value_history_quarantine (
    ticker        TEXT          NOT NULL,
    date          DATE          NOT NULL,
    fair_value    NUMERIC(18,4) NOT NULL,
    prev_fv       NUMERIC(18,4),
    delta_pct     NUMERIC(10,4),
    reason        TEXT          NOT NULL,
    price         NUMERIC(18,4),
    mos_pct       NUMERIC(10,4),
    verdict       TEXT,
    created_at    TIMESTAMPTZ   NOT NULL DEFAULT now(),
    PRIMARY KEY (ticker, date)
);

CREATE INDEX IF NOT EXISTS idx_fv_history_quarantine_created
    ON fair_value_history_quarantine (created_at DESC);

CREATE INDEX IF NOT EXISTS idx_fv_history_quarantine_ticker
    ON fair_value_history_quarantine (ticker);

COMMENT ON TABLE fair_value_history_quarantine IS 'FV-history rows rejected by the write-time sanity gate (ROOT CAUSE 12). Daily delta > 25 percent without a corroborating manifest entry / corporate action / concall summary lands here instead of the canonical fair_value_history table. Read by an operator review surface and never reflected in user-facing charts.';
