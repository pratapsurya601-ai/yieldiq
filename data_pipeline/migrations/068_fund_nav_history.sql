-- 068_fund_nav_history.sql
-- 2026-05-27 — Mutual Funds Phase 1: daily NAV time series.
--
-- Partitioned by year on nav_date. Sizing: ~6,000 active scheme variants
-- (Direct+Regular × Growth+IDCW) × ~252 trading days × 10y ≈ 15M rows.
-- Yearly partitions keep individual partition size manageable for index
-- maintenance and queries that almost always scope to a single year or
-- rolling 3y/5y window.
--
-- AUM is monthly and frequently NULL on daily rows — populated only on
-- the month-end row by the (future) factsheet ingest (Phase 4).
--
-- Foreign key to funds.scheme_code is intentionally NOT declared on the
-- partition parent — Postgres requires the FK to live on each partition
-- and the partition-add helper handles that. Logical integrity is
-- enforced by the upsert path in amfi_nav.py which only writes
-- scheme_codes that exist in funds.
--
-- Idempotent: CREATE TABLE / partition statements all use IF NOT EXISTS.
--
-- Apply with:
--   python scripts/apply_migration.py data_pipeline/migrations/068_fund_nav_history.sql

CREATE TABLE IF NOT EXISTS fund_nav_history (
    scheme_code  TEXT           NOT NULL,
    nav_date     DATE           NOT NULL,
    nav          NUMERIC(14, 4) NOT NULL,
    aum_cr       NUMERIC(14, 2),
    PRIMARY KEY (scheme_code, nav_date)
) PARTITION BY RANGE (nav_date);

-- Per-year partitions covering 2015-01-01 .. 2027-12-31.
-- A future rolling-partition cron extends this forward each year.
DO $$
DECLARE
    yr INT;
    part_name TEXT;
    start_d  TEXT;
    end_d    TEXT;
BEGIN
    FOR yr IN 2015..2027 LOOP
        part_name := format('fund_nav_history_%s', yr);
        start_d   := format('%s-01-01', yr);
        end_d     := format('%s-01-01', yr + 1);
        EXECUTE format(
            'CREATE TABLE IF NOT EXISTS %I PARTITION OF fund_nav_history '
            'FOR VALUES FROM (%L) TO (%L)',
            part_name, start_d, end_d
        );
    END LOOP;
END
$$;

-- Index on nav_date alone (within each partition) supports cross-scheme
-- queries on a single date (e.g. "all NAVs on 2026-05-27"). The
-- composite PK already serves the much more common per-scheme range
-- scan path.
CREATE INDEX IF NOT EXISTS idx_fund_nav_history_date
    ON fund_nav_history(nav_date);

COMMENT ON TABLE fund_nav_history IS
    'Daily NAV per AMFI scheme. Range-partitioned by year on nav_date. Populated by data_pipeline/sources/amfi_nav.py (daily cron) for incremental rows; bulk-backfilled by scripts/backfill_mf_nav.py (operator-run, local only). AUM is sparse — only month-end rows carry it (Phase 4 factsheet ingest).';
COMMENT ON COLUMN fund_nav_history.nav IS
    'Net Asset Value in INR per unit. Numeric(14,4) — AMFI publishes to 4 decimal places; the 14 total digits cover any value up to 99,999,999.9999 which is well above the highest-NAV scheme on record.';
COMMENT ON COLUMN fund_nav_history.aum_cr IS
    'Assets Under Management in INR crore. NULL on daily rows; populated only on month-end disclosures.';
