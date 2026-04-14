#!/usr/bin/env python3
"""Fetch fundamentals for all stocks not yet covered."""
import os, sys, time, logging

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fundamentals")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from data_pipeline.sources.yfinance_supplement import fetch_and_store_yfinance

engine = create_engine(os.environ["DATABASE_URL"], pool_recycle=300, pool_pre_ping=True)
Session = sessionmaker(bind=engine)
db = Session()

with engine.connect() as c:
    all_tickers = [r[0] for r in c.execute(text("SELECT ticker FROM stocks WHERE is_active = true ORDER BY ticker"))]
    already_done = set(r[0] for r in c.execute(text("SELECT DISTINCT ticker FROM financials")))

todo = [t for t in all_tickers if t not in already_done]
logger.info(f"Total: {len(all_tickers)}, done: {len(already_done)}, todo: {len(todo)}")

success = 0
failed = 0
for i, ticker in enumerate(todo):
    try:
        ok = fetch_and_store_yfinance(f"{ticker}.NS", ticker, db)
        if ok:
            success += 1
        else:
            failed += 1
    except Exception as e:
        failed += 1
        try:
            db.rollback()
        except Exception:
            pass
        if "429" in str(e) or "Too Many" in str(e):
            time.sleep(60)
        if "closed" in str(e).lower() or "connection" in str(e).lower():
            try:
                db.close()
            except Exception:
                pass
            db = Session()
    time.sleep(2)
    if (i + 1) % 50 == 0:
        logger.info(f"Progress: {i+1}/{len(todo)} ({success} ok, {failed} failed)")

db.close()
logger.info(f"DONE: {success} ok, {failed} failed out of {len(todo)}")
