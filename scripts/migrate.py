import os
import sys
from sqlalchemy import create_engine, text

migration = os.environ.get("MIGRATION", "")
url = os.environ.get("DATABASE_URL", "")

if not url:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

engine = create_engine(url)

if migration == "create_fair_value_history":
    ddl = """
CREATE TABLE IF NOT EXISTS fair_value_history (
    id         SERIAL PRIMARY KEY,
    ticker     VARCHAR(20) NOT NULL,
    date       DATE NOT NULL,
    fair_value FLOAT NOT NULL,
    price      FLOAT NOT NULL,
    mos_pct    FLOAT NOT NULL,
    verdict    VARCHAR(20),
    wacc       FLOAT,
    confidence INTEGER,
    updated_at TIMESTAMP DEFAULT NOW(),
    CONSTRAINT uq_fv_ticker_date
        UNIQUE (ticker, date)
);
CREATE INDEX IF NOT EXISTS ix_fv_history_ticker
    ON fair_value_history (ticker);
CREATE INDEX IF NOT EXISTS ix_fv_history_date
    ON fair_value_history (date);
"""
    with engine.connect() as conn:
        conn.execute(text(ddl))
        conn.commit()
        count = conn.execute(
            text("SELECT COUNT(*) FROM fair_value_history")
        ).scalar()
        print("Migration complete.")
        print(f"fair_value_history rows: {count}")
else:
    print(f"Unknown migration: {migration}")
    sys.exit(1)
