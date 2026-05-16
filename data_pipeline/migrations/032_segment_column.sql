-- 032_segment_column.sql
-- ─────────────────────────────────────────────────────────────────
-- Adds `segment` + `report_period_type` to company_quarterly_results
-- so the NSE SME (EMERGE) cohort can land in the SAME table as main-
-- board (equities) without losing the ability to split analytics.
--
-- Why this is additive-only:
--   * SMEs use the same XBRL schema (`in-bse-fin:2020-03-31`) as
--     main-board industrials → existing parser handles them.
--   * SMEs split between Quarterly and Half-Yearly reporting cadence
--     → `report_period_type` lets the TTM compute know whether to
--     roll up 4 quarters or 2 half-years.
--
-- Defaults backfill cleanly:
--   * Every existing row is main-board → `segment='equities'`.
--   * Existing rows came from the Quarterly endpoint → set
--     `report_period_type='Quarterly'` for the back-cohort.
--
-- Idempotent: safe to re-run.
-- ─────────────────────────────────────────────────────────────────

ALTER TABLE company_quarterly_results
    ADD COLUMN IF NOT EXISTS segment            TEXT DEFAULT 'equities',
    ADD COLUMN IF NOT EXISTS report_period_type TEXT;  -- 'Quarterly' | 'Half-Yearly' | 'Annual'

-- Backfill any pre-existing rows that have a NULL report_period_type.
-- Every row landed pre-this-migration came from the Quarterly endpoint
-- (the only one the ingest ever called), so this label is correct.
UPDATE company_quarterly_results
SET    report_period_type = 'Quarterly'
WHERE  report_period_type IS NULL;

-- Defensive: make sure no existing row has NULL segment.
UPDATE company_quarterly_results
SET    segment = 'equities'
WHERE  segment IS NULL;

CREATE INDEX IF NOT EXISTS idx_cqr_segment
    ON company_quarterly_results (segment);

CREATE INDEX IF NOT EXISTS idx_cqr_segment_ticker_period_end
    ON company_quarterly_results (segment, ticker, period_end DESC);
