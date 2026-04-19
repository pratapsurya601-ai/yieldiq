"""Enrich stocks.sector and stocks.industry from yfinance.

Current state: stocks.sector + stocks.industry are 100% NULL for all
2,970 active tickers, which makes peer_groups fall back to same-cap-
tier-only matching. yfinance's .info carries a clean sector/industry
classification for most NSE stocks.

Usage:
    DATABASE_URL=... python scripts/enrich_stocks_sector_yf.py --all
    DATABASE_URL=... python scripts/enrich_stocks_sector_yf.py --tickers RELIANCE,TCS
    DATABASE_URL=... python scripts/enrich_stocks_sector_yf.py --only-missing  # skip already-populated rows

Rate-limited. ~30-40 min for full 2,970-ticker universe.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("sector_enrich")


def _load_tickers(sess, args) -> list[str]:
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    if args.only_missing:
        sql = text("""
            SELECT ticker FROM stocks
            WHERE is_active = TRUE
              AND (sector IS NULL OR sector = '' OR industry IS NULL OR industry = '')
            ORDER BY ticker
        """)
    else:
        sql = text("SELECT ticker FROM stocks WHERE is_active = TRUE ORDER BY ticker")
    return [r[0] for r in sess.execute(sql).fetchall()]


UPDATE_SQL = text("""
    UPDATE stocks SET
        sector   = COALESCE(:sector, sector),
        industry = COALESCE(:industry, industry),
        updated_at = now()
    WHERE ticker = :ticker
""")


def fetch_one(ticker: str) -> dict:
    try:
        import yfinance as yf
    except ImportError:
        return {"sector": None, "industry": None, "error": "yfinance missing"}
    try:
        info = yf.Ticker(f"{ticker}.NS").info or {}
        return {
            "sector": (info.get("sector") or "").strip() or None,
            "industry": (info.get("industry") or "").strip() or None,
            "error": None,
        }
    except Exception as e:
        return {"sector": None, "industry": None, "error": str(e)[:80]}


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--tickers", default=None)
    g.add_argument("--only-missing", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.4)
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    engine = create_engine(url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    sess = Session()

    tickers = _load_tickers(sess, args)
    logger.info("enriching %d tickers", len(tickers))

    n_updated = n_skipped = n_failed = 0
    for i, t in enumerate(tickers, 1):
        r = fetch_one(t)
        if r["error"]:
            n_failed += 1
        elif not r["sector"] and not r["industry"]:
            n_skipped += 1
        else:
            try:
                sess.execute(UPDATE_SQL, {
                    "ticker": t,
                    "sector": r["sector"],
                    "industry": r["industry"],
                })
                sess.commit()
                n_updated += 1
            except Exception as e:
                logger.warning("%s: update failed: %s", t, e)
                sess.rollback()
                n_failed += 1

        if i % 100 == 0:
            logger.info(
                "[%d/%d] updated=%d skipped=%d failed=%d",
                i, len(tickers), n_updated, n_skipped, n_failed,
            )
        time.sleep(args.sleep)

    logger.info(
        "done. updated=%d skipped_no_info=%d failed=%d",
        n_updated, n_skipped, n_failed,
    )
    sess.close()
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
