# data_pipeline/setup.py
# Run once to set up database and backfill historical data.
# Usage: python -m data_pipeline.setup
from __future__ import annotations

import logging
import sys
from pathlib import Path

# Ensure project root is on path
_ROOT = str(Path(__file__).resolve().parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

if __name__ == "__main__":
    from data_pipeline.db import Session, engine
    from data_pipeline.models import Base, BulkDeal  # noqa
    from data_pipeline.isin_loader import build_isin_map, populate_stocks_table
    from data_pipeline.pipeline import ISIN_MAP, run_initial_setup

    if engine is None:
        print("ERROR: DATABASE_URL not set. Set it in .env or environment.")
        sys.exit(1)

    print("Creating database tables...")
    Base.metadata.create_all(engine)
    print("Tables created.")

    db = Session()
    try:
        # Step 0: Populate stocks master table + ISIN map
        print("Populating stocks master table from NSE equity list...")
        count = populate_stocks_table(db)
        print(f"Loaded {count} stocks into master table.")

        isin_map = build_isin_map()
        ISIN_MAP.update(isin_map)
        print(f"Built ISIN map: {len(isin_map)} entries.")

        # Steps 1-5: Full backfill
        print("Starting initial data backfill (this takes 2-4 hours)...")
        run_initial_setup(db)
        print("Initial setup complete.")
    finally:
        db.close()
