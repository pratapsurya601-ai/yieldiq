#!/usr/bin/env python3
"""Fetch fundamentals for all stocks — BSE Peercomp primary, yfinance fallback."""
import os, sys, time, logging

sys.path.insert(0, str(__import__("pathlib").Path(__file__).resolve().parent.parent))
logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fundamentals")

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from data_pipeline.sources.bse_xbrl import (
    get_bse_scrip_code,
    fetch_historical_financials,
    store_financials,
    store_ttm,
)
from data_pipeline.sources.yfinance_supplement import fetch_and_store_yfinance

# SQLAlchemy 2.x dropped 'postgres://' — normalise to 'postgresql://'
_db_url = os.environ["DATABASE_URL"]
if _db_url.startswith("postgres://"):
    _db_url = "postgresql://" + _db_url[len("postgres://"):]
engine = create_engine(_db_url, pool_recycle=300, pool_pre_ping=True)
Session = sessionmaker(bind=engine)
db = Session()

# Load all active stocks with ISIN
with engine.connect() as c:
    rows = c.execute(
        text("SELECT ticker, isin FROM stocks WHERE is_active = true ORDER BY ticker")
    ).fetchall()
    already_done_bse = set(
        r[0] for r in c.execute(
            text("SELECT DISTINCT ticker FROM financials WHERE data_source = 'BSE_PEERCOMP'")
        )
    )

all_stocks = [(r[0], r[1]) for r in rows]
todo = [(t, isin) for t, isin in all_stocks if t not in already_done_bse]
logger.info(
    f"Total: {len(all_stocks)}, already done (BSE): {len(already_done_bse)}, todo: {len(todo)}"
)

success = 0
failed = 0
bse_ok = 0
yf_ok = 0

for i, (ticker, isin) in enumerate(todo):
    stored_from_bse = 0
    try:
        # --- BSE Peercomp as primary source ---
        scrip_code = get_bse_scrip_code(isin) if isin else None
        if scrip_code:
            periods = fetch_historical_financials(scrip_code, ticker)
            for period in periods:
                ok = store_financials(
                    period, db,
                    period_end=period["period_end"],
                    period_type=period["period_type"],
                )
                if ok:
                    stored_from_bse += 1
            if stored_from_bse > 0:
                store_ttm(ticker, db)
                bse_ok += 1
                success += 1

        # --- yfinance fallback if BSE returned nothing ---
        if stored_from_bse == 0:
            yf_result = fetch_and_store_yfinance(f"{ticker}.NS", ticker, db)
            if yf_result:
                yf_ok += 1
                success += 1
            else:
                failed += 1

    except Exception as e:
        failed += 1
        try:
            db.rollback()
        except Exception:
            pass

        # Handle 429 rate limits
        if "429" in str(e) or "Too Many" in str(e):
            logger.warning(f"Rate limited — sleeping 60s")
            time.sleep(60)

        # Handle DB connection loss
        if "closed" in str(e).lower() or "connection" in str(e).lower():
            logger.warning(f"DB connection issue — reconnecting")
            try:
                db.close()
            except Exception:
                pass
            db = Session()

    time.sleep(1.0)
    if (i + 1) % 50 == 0:
        logger.info(
            f"Progress: {i+1}/{len(todo)} "
            f"(success={success}, failed={failed}, bse={bse_ok}, yf={yf_ok})"
        )

db.close()
logger.info(
    f"DONE: {success} ok, {failed} failed out of {len(todo)} "
    f"(BSE: {bse_ok}, yfinance: {yf_ok})"
)
