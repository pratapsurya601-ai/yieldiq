"""Backfill 10-20Y fundamentals from NSE's XBRL filing feed.

Replaces the dead BSE Peercomp path. NSE serves the same SEBI-mandated
XBRL openly at ``nsearchives.nseindia.com`` with no bot wall.

Usage
-----
    DATABASE_URL=... python scripts/backfill_fundamentals_nse_xbrl.py \\
        --shards 5 --shard 0 --top 500

    # Smoke test
    python scripts/backfill_fundamentals_nse_xbrl.py --limit 3

Time
----
~8s per ticker (1 master call + ~10-20 XBRL downloads at 0.3s sleep).
3,000 tickers single-threaded ≈ 6.5 hours. 5 parallel shards on GH
Actions ≈ ~80 min.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.orm import sessionmaker

from data_pipeline.sources.nse_xbrl_fundamentals import (
    fetch_ticker_financials,
    _get_session,
)
from data_pipeline.sources.bse_xbrl import store_financials  # reuse writer


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fund_nse_xbrl")


def _engine():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url, pool_recycle=300, pool_pre_ping=True)


def _load_tickers(engine, top: int | None, shard: int, shards: int) -> list[str]:
    """Return NSE-listed tickers only (NSE XBRL feed only covers them)."""
    Session = sessionmaker(bind=engine)
    sess = Session()
    try:
        rows = sess.execute(sa_text("""
            SELECT s.ticker
            FROM stocks s
            LEFT JOIN market_metrics m ON m.ticker = s.ticker
              AND m.trade_date = (
                SELECT MAX(trade_date) FROM market_metrics WHERE ticker = s.ticker
              )
            WHERE s.is_active = TRUE
              AND s.ticker NOT LIKE '%.BO'
              AND (s.ticker !~ '[^A-Z0-9-]' OR s.ticker ~ '[A-Z]')
            ORDER BY COALESCE(m.market_cap_cr, 0) DESC, s.ticker
        """)).fetchall()
    finally:
        sess.close()
    tickers = [r[0] for r in rows if r and r[0]]
    if top is not None:
        tickers = tickers[:top]
    if shards > 1:
        tickers = tickers[shard::shards]
    return tickers


def _already_done(sess, ticker: str, threshold: int) -> bool:
    row = sess.execute(sa_text("""
        SELECT COUNT(*) FROM financials
        WHERE ticker = :t
          AND period_type = 'annual'
          AND revenue IS NOT NULL
          AND data_source IN ('NSE_XBRL')
    """), {"t": ticker}).fetchone()
    return bool(row and row[0] >= threshold)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--skip-threshold", type=int, default=10,
                    help="Skip if ticker already has N annual rows from NSE_XBRL")
    ap.add_argument("--no-skip", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--max-annual", type=int, default=15)
    ap.add_argument("--max-quarterly", type=int, default=40)
    ap.add_argument("--inter-ticker-sleep", type=float, default=0.5)
    ap.add_argument(
        "--tickers",
        type=str,
        default=None,
        help=(
            "Comma-separated explicit ticker allowlist (bare symbols, e.g. "
            "'BPCL,ONGC,IOC'). Overrides --top / --shard / --shards / "
            "--limit entirely — useful for targeted re-parses after a "
            "parser-coverage fix without re-ingesting the full universe."
        ),
    )
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL not set"); return 2

    engine = _engine()
    Session = sessionmaker(bind=engine)

    # --tickers short-circuits the DB-driven universe load. Any symbol
    # with '.NS' / '.BO' suffix gets stripped so either form works.
    if args.tickers:
        tickers = [
            t.strip().upper().replace(".NS", "").replace(".BO", "")
            for t in args.tickers.split(",")
            if t.strip()
        ]
        logger.info("using --tickers allowlist: %s", tickers)
    else:
        tickers = _load_tickers(engine, args.top, args.shard, args.shards)
    logger.info("shard %d/%d: %d tickers (top=%s, limit=%s)",
                args.shard, args.shards, len(tickers), args.top, args.limit)
    if not tickers:
        return 0

    nse_sess = _get_session()

    stats = {"processed": 0, "ok": 0, "skip": 0, "empty": 0, "error": 0, "periods": 0}
    t0 = time.time()

    for i, ticker in enumerate(tickers):
        if args.limit is not None and stats["processed"] >= args.limit:
            break
        db = Session()
        try:
            if not args.no_skip and _already_done(db, ticker, args.skip_threshold):
                stats["skip"] += 1
                continue

            try:
                rows = fetch_ticker_financials(
                    ticker, session=nse_sess,
                    max_annual=args.max_annual, max_quarterly=args.max_quarterly,
                    sleep=args.sleep,
                )
            except Exception as exc:
                logger.warning("fetch failed %s: %s", ticker, exc)
                stats["error"] += 1
                continue

            if not rows:
                stats["empty"] += 1
                continue

            stored = 0
            for r in rows:
                try:
                    if store_financials(r, db, r["period_end"], r.get("period_type", "annual")):
                        stored += 1
                except Exception as exc:
                    logger.debug("store failed %s %s: %s", ticker, r.get("period_end"), exc)
            if stored:
                stats["ok"] += 1
                stats["periods"] += stored
            else:
                stats["empty"] += 1

            if (stats["processed"] + 1) % 25 == 0:
                elapsed = time.time() - t0
                rate = (stats["processed"] + 1) / max(elapsed, 1.0)
                logger.info(
                    "  [%d/%d] ok=%d skip=%d empty=%d err=%d periods=%d | %.2f tic/s",
                    stats["processed"] + 1, len(tickers),
                    stats["ok"], stats["skip"], stats["empty"], stats["error"],
                    stats["periods"], rate,
                )
        finally:
            db.close()
        stats["processed"] += 1
        time.sleep(args.inter_ticker_sleep)

    elapsed = time.time() - t0
    logger.info("DONE in %.1f min", elapsed / 60)
    logger.info(
        "  processed=%d ok=%d skip=%d empty=%d error=%d periods_stored=%d",
        stats["processed"], stats["ok"], stats["skip"],
        stats["empty"], stats["error"], stats["periods"],
    )
    return 0 if stats["error"] <= stats["processed"] * 0.15 else 1


if __name__ == "__main__":
    sys.exit(main())
