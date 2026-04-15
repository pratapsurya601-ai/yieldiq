import os
import sys
from sqlalchemy import create_engine, text

migration = os.environ.get("MIGRATION", "")
url = os.environ.get("DATABASE_URL", "")

if not url:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

# SQLAlchemy 2.x dropped the `postgres://` scheme — Aiven and others
# still hand out URLs that start with it. Normalise to `postgresql://`.
if url.startswith("postgres://"):
    url = "postgresql://" + url[len("postgres://"):]

engine = create_engine(url)

MIGRATIONS = {
    "create_fair_value_history": {
        "ddl": """
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
""",
        "verify_table": "fair_value_history",
    },
    "create_yfinance_info_cache": {
        "ddl": """
CREATE TABLE IF NOT EXISTS yfinance_info_cache (
    ticker     VARCHAR(30) PRIMARY KEY,
    info_json  TEXT NOT NULL,
    updated_at TIMESTAMP NOT NULL DEFAULT NOW()
);
CREATE INDEX IF NOT EXISTS ix_yf_info_updated_at
    ON yfinance_info_cache (updated_at);
""",
        "verify_table": "yfinance_info_cache",
    },
}

if migration in MIGRATIONS:
    spec = MIGRATIONS[migration]
    with engine.connect() as conn:
        conn.execute(text(spec["ddl"]))
        conn.commit()
        count = conn.execute(
            text(f"SELECT COUNT(*) FROM {spec['verify_table']}")
        ).scalar()
        print("Migration complete.")
        print(f"{spec['verify_table']} rows: {count}")
else:
    print(f"Unknown migration: {migration}")
    print(f"Available: {', '.join(MIGRATIONS.keys())}")
    sys.exit(1)
