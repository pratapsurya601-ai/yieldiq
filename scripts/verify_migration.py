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
    count = conn.execute(
        text("SELECT COUNT(*) FROM fair_value_history")
    ).scalar()
    print(
        f"Verification: fair_value_history exists with {count} rows"
    )
