"""Backfill 5Y of quarterly shareholding history into shareholding_pattern.

Today the table holds ~654 rows — basically only the latest quarter per
ticker, written by data_pipeline.sources.nse_shareholding.run_daily.
Phase 2.3 of DATA_STRATEGY.md calls for 5Y of quarterly history so the
analysis page can light up "promoter pledge rising" and "FII outflow"
signals.

Strategy (in order of preference):
  1. NSE per-symbol shareholding API
       /api/corporate-share-holdings-master?index=equities&symbol=XYZ
     This returns ALL historical quarters NSE has on file for the symbol
     (typically 8-20 quarters back). Already wrapped by
     data_pipeline.sources.nse_shareholding.download_symbol_shareholding,
     and idempotent against the (ticker, quarter_end) unique index.
  2. BSE shareholding-pattern JSON API (fallback for tickers NSE returns
     <4 quarters for):
       https://api.bseindia.com/BseIndiaAPI/api/ShareholdingPattern/w
         ?scripcode=<bse_code>&qtrid=<YYYYMMDD>
     BSE retains 5Y+ but indexed by scrip_code which we don't carry on
     the Stock model — for now we punt the BSE fallback and log the gap
     so a follow-up task can wire in scripts/enrich_stocks_bse_codes.py.

Per-ticker rate limit: 1.5 sec between requests (NSE blocks faster).

Usage:
    DATABASE_URL=... python scripts/backfill_shareholding_history.py --top 500
    DATABASE_URL=... python scripts/backfill_shareholding_history.py --tickers RELIANCE,TCS
    DATABASE_URL=... python scripts/backfill_shareholding_history.py --all

Runtime estimate:
    top-500 tickers × ~20 quarters each × 1.5 sec/request ≈ 15-25 min
    full universe (~2,500 tickers)                          ≈ 1-2 hours

Resumable: writes are merge-style (update existing (ticker, quarter)
rows, insert new ones) so re-runs are safe and fast.

Apply migration 008 first (adds the (ticker, quarter_end DESC) index):
    DATABASE_URL=... python scripts/apply_migration.py \
        data_pipeline/migrations/008_shareholding_quarterly_index.sql
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("sh_backfill")

DEFAULT_SLEEP = 1.5


def _resolve_universe(args, engine) -> list[str]:
    from sqlalchemy import text

    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    with engine.connect() as conn:
        if args.all:
            rows = conn.execute(text(
                "SELECT s.ticker FROM stocks s "
                "WHERE s.is_active = TRUE "
                "ORDER BY s.ticker"
            )).fetchall()
        else:
            n = args.top or 500
            rows = conn.execute(text(
                "SELECT s.ticker FROM stocks s "
                "LEFT JOIN market_metrics mm ON mm.ticker = s.ticker "
                "WHERE s.is_active = TRUE "
                "ORDER BY COALESCE(mm.market_cap_cr, 0) DESC "
                "LIMIT :n"
            ), {"n": n}).fetchall()
    return [r[0] for r in rows if r and r[0]]


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--top", type=int, help="Top-N by market cap (default 500)")
    g.add_argument("--tickers", help="Comma-separated ticker list")
    g.add_argument("--all", action="store_true", help="All active tickers")

    ap.add_argument("--sleep", type=float, default=DEFAULT_SLEEP,
                    help="Sleep between per-ticker NSE requests")
    ap.add_argument("--skip-existing", action="store_true",
                    help="Skip tickers that already have >= --skip-threshold quarters")
    ap.add_argument("--skip-threshold", type=int, default=18,
                    help="Quarters considered 'enough' (default 18 ≈ 4.5Y)")
    ap.add_argument("--limit", type=int, default=None,
                    help="Cap tickers processed (smoke testing)")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    from data_pipeline.sources.nse_shareholding import (
        download_symbol_shareholding,
    )

    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    engine = create_engine(url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)

    universe = _resolve_universe(args, engine)
    logger.info("universe size: %d tickers", len(universe))

    if args.skip_existing:
        with engine.connect() as conn:
            rows = conn.execute(text(
                "SELECT ticker, COUNT(*) AS n FROM shareholding_pattern "
                "WHERE ticker = ANY(:tks) GROUP BY ticker"
            ), {"tks": universe}).fetchall()
        counts = {r[0]: int(r[1] or 0) for r in rows}
        kept = [t for t in universe if counts.get(t, 0) < args.skip_threshold]
        logger.info(
            "skip-existing: dropped %d / %d tickers with >= %d quarters",
            len(universe) - len(kept), len(universe), args.skip_threshold,
        )
        universe = kept

    if args.limit:
        universe = universe[: args.limit]

    if not universe:
        logger.info("nothing to do")
        return 0

    total_records = 0
    total_failed = 0
    bse_punted = 0  # tickers that returned <4 quarters from NSE — flagged for BSE fallback

    for i, ticker in enumerate(universe, 1):
        sess = Session()
        before = 0
        try:
            before = sess.execute(text(
                "SELECT COUNT(*) FROM shareholding_pattern WHERE ticker = :t"
            ), {"t": ticker}).scalar() or 0
        except Exception:
            sess.rollback()

        try:
            stored = download_symbol_shareholding(ticker, sess)
        except Exception as exc:
            logger.warning("[%d/%d] %s failed: %s", i, len(universe), ticker, exc)
            total_failed += 1
            stored = 0
        finally:
            try:
                after = sess.execute(text(
                    "SELECT COUNT(*) FROM shareholding_pattern WHERE ticker = :t"
                ), {"t": ticker}).scalar() or 0
            except Exception:
                after = before
            sess.close()

        total_records += stored
        delta = after - before
        if after < 4:
            bse_punted += 1

        if i % 10 == 0 or i == len(universe):
            logger.info(
                "[%d/%d] %s: +%d (now %d quarters) | running: records=%d failed=%d "
                "bse_followup=%d",
                i, len(universe), ticker, delta, after,
                total_records, total_failed, bse_punted,
            )

        time.sleep(args.sleep)

    logger.info("")
    logger.info("DONE shareholding history backfill")
    logger.info("  tickers processed       : %d", len(universe))
    logger.info("  records written         : %d", total_records)
    logger.info("  ticker failures         : %d", total_failed)
    logger.info("  BSE fallback candidates : %d (NSE returned < 4 quarters)", bse_punted)
    if bse_punted:
        logger.info(
            "  -> follow-up: enrich Stock.bse_code and add a BSE per-quarter "
            "fetch loop here for the deep historical tail (>3Y back)."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
