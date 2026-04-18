-- Migration: create hex_pulse_inputs table
-- Owned by Agent D (Pulse data pipeline) — feeds the 6th axis of the YieldIQ Hex.
--
-- Idempotent: safe to run multiple times. Also auto-created by
-- pulse_data_service.ensure_table() on import as a backup.

CREATE TABLE IF NOT EXISTS hex_pulse_inputs (
  ticker TEXT PRIMARY KEY,
  -- Promoter holding change QoQ (percentage points). Positive = promoter increased stake.
  promoter_delta_qoq NUMERIC,
  -- Net insider trading last 30 days in INR Cr. Positive = net buying.
  insider_net_30d NUMERIC,
  -- Analyst estimate revisions last 30 days: (# up - # down) / total, range -1..+1
  estimate_revision_30d NUMERIC,
  -- Pledged shares % change QoQ. Positive = MORE shares pledged (bad signal).
  pledged_pct_delta NUMERIC,
  -- Bulk/block deals net value last 30 days, INR Cr. Positive = institutional buying.
  institutional_flow_30d NUMERIC,
  -- Raw computed pulse score -10..+10 (before hex_service normalizes to 0..10)
  pulse_raw NUMERIC,
  computed_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  sources_used JSONB  -- which sources worked this run
);

CREATE INDEX IF NOT EXISTS idx_hex_pulse_inputs_computed
  ON hex_pulse_inputs (computed_at);
