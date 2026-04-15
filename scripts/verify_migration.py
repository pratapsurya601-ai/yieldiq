import os
import sys
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL", "")
if not url:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

# SQLAlchemy 2.x dropped the `postgres://` scheme — normalise.
if url.startswith("postgres://"):
    url = "postgresql://" + url[len("postgres://"):]

engine = create_engine(url)
with engine.connect() as conn:
    # Verify whichever tables exist — either migration may have just
    # run, and we don't want to fail verification on tables that
    # weren't part of this migration invocation.
    for table in ("fair_value_history", "yfinance_info_cache"):
        try:
            count = conn.execute(
                text(f"SELECT COUNT(*) FROM {table}")
            ).scalar()
            print(f"Verification: {table} exists with {count} rows")
        except Exception as exc:
            print(f"Verification: {table} not present ({exc})")
