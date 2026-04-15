import os
import sys
from sqlalchemy import create_engine, text

url = os.environ.get("DATABASE_URL", "")
if not url:
    print("ERROR: DATABASE_URL not set")
    sys.exit(1)

engine = create_engine(url)
with engine.connect() as conn:
    count = conn.execute(
        text("SELECT COUNT(*) FROM fair_value_history")
    ).scalar()
    print(
        f"Verification: fair_value_history exists with {count} rows"
    )
