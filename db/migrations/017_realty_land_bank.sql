-- 017_realty_land_bank.sql  (mirror of data_pipeline/migrations/047_realty_land_bank.sql)
-- See the canonical file for full design rationale.

CREATE TABLE IF NOT EXISTS realty_land_bank_inputs (
    ticker                       TEXT          PRIMARY KEY,
    reporting_fy                 TEXT          NOT NULL,
    land_bank_acres              NUMERIC(14,2),
    land_bank_market_value_cr    NUMERIC(14,2) NOT NULL,
    land_bank_book_value_cr      NUMERIC(14,2),
    unsold_inventory_cr          NUMERIC(14,2),
    pre_sales_pipeline_cr        NUMERIC(14,2),
    uplift_per_share             NUMERIC(14,2) NOT NULL,
    source_url                   TEXT,
    entered_by                   TEXT,
    entered_at                   TIMESTAMPTZ   NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS ix_realty_land_bank_entered_at
    ON realty_land_bank_inputs (entered_at DESC);
