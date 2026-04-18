-- Migration: create hex_history table
-- Owned by Agent Psi1 (Time Machine) — feeds the 12-quarter Prism scrubber.
--
-- Stores precomputed hex snapshots per (ticker, quarter_end). Populated by
-- backend/scripts/backfill_hex_history.py (one-off backfill) and the weekly
-- GitHub Actions workflow .github/workflows/hex_history_weekly.yml.
--
-- Idempotent: safe to re-run. UPSERT by (ticker, quarter_end).

CREATE TABLE IF NOT EXISTS hex_history (
  ticker            TEXT NOT NULL,
  quarter_end       DATE NOT NULL,    -- e.g. 2024-03-31, 2024-06-30
  -- Snapshot of the 6 axes at that quarter (0..10 each, or NULL if uncomputable)
  value_score       NUMERIC,
  quality_score     NUMERIC,
  growth_score      NUMERIC,
  moat_score        NUMERIC,
  safety_score      NUMERIC,
  pulse_score       NUMERIC,
  overall           NUMERIC,
  refraction_index  NUMERIC,
  verdict_band      TEXT,
  -- Metadata
  computed_at       TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (ticker, quarter_end)
);

CREATE INDEX IF NOT EXISTS idx_hex_history_ticker
  ON hex_history(ticker);
CREATE INDEX IF NOT EXISTS idx_hex_history_quarter
  ON hex_history(quarter_end DESC);
