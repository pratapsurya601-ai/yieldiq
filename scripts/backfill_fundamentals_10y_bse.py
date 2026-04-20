"""Backfill 10 years of BSE Peercomp fundamentals for every listed ticker.

Uses the existing ``fetch_historical_financials`` helper in
``data_pipeline.sources.bse_xbrl`` which pulls 10Y annual + quarterly
P&L, balance sheet, and cash flow from BSE's Peercomp JSON API.

Not a true XBRL parser — BSE blocks raw XBRL downloads behind a WAF,
but their Peercomp endpoint returns the same financial facts as
parsed JSON, so we use that.

Features
--------
* Shards by ticker index (``--shard i --shards N``) so you can run
  ``N`` copies in parallel (e.g. GH Actions matrix) with zero overlap.
* Skips tickers that already have ``--skip-threshold`` annual
  periods (default 8) to make re-runs cheap.
* Rate-limit respectful: 0.3 s between BSE Peercomp calls. Four BSE
  endpoints per ticker × 0.3 s sleep + ~200 ms request latency ≈
  2 s per ticker. 5,500 tickers single-threaded → ~3 hrs. 4 shards →
  45 min.

Usage
-----
    python scripts/backfill_fundamentals_10y_bse.py --shards 4 --shard 0
    python scripts/backfill_fundamentals_10y_bse.py --top 500
    python scripts/backfill_fundamentals_10y_bse.py --limit 10  # smoke

Requires
--------
* stocks.bse_code populated (run scripts/backfill_bse_codes.py first)
* DATABASE_URL environment variable

Writes
------
Into ``financials`` table via UPSERT (db.merge). Idempotent — safe to
re-run; existing rows are updated, not duplicated.
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

from data_pipeline.sources.bse_xbrl import (  # type: ignore
    fetch_historical_financials,
    store_financials,
)


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("fund_10y_bse")
# Quiet the per-call info logs
logging.getLogger("data_pipeline.sources.bse_xbrl").setLevel(logging.WARNING)


def _engine():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url, pool_recycle=300, pool_pre_ping=True)


def _load_tickers(engine, top: int | None, shard: int, shards: int) -> list[tuple[str, str]]:
    """Return list of (ticker, bse_code) for active stocks with a bse_code.
    Shards by lexical ticker order so shard i gets ticker[i::N].
    """
    Session = sessionmaker(bind=engine)
    sess = Session()
    try:
        # Order by market_cap_cr desc if available (top-N = largest first)
        rows = sess.execute(sa_text("""
            SELECT s.ticker, s.bse_code
            FROM stocks s
            LEFT JOIN market_metrics m ON m.ticker = s.ticker
              AND m.trade_date = (
                SELECT MAX(trade_date) FROM market_metrics WHERE ticker = s.ticker
              )
            WHERE s.is_active = TRUE
              AND s.bse_code IS NOT NULL
              AND s.bse_code != ''
            ORDER BY COALESCE(m.market_cap_cr, 0) DESC, s.ticker
        """)).fetchall()
    finally:
        sess.close()

    tickers = [(r[0], str(r[1]).strip()) for r in rows if r[1]]
    if top is not None:
        tickers = tickers[:top]
    # Shard after top-filtering so each shard sees an equal slice of the top-N
    if shards > 1:
        tickers = tickers[shard::shards]
    return tickers


def _already_done(sess, ticker: str, threshold: int) -> bool:
    """Return True if ticker already has >= threshold annual periods."""
    row = sess.execute(sa_text("""
        SELECT COUNT(*) FROM financials
        WHERE ticker = :t AND period_type = 'annual' AND revenue IS NOT NULL
    """), {"t": ticker}).fetchone()
    return bool(row and row[0] >= threshold)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--top", type=int, default=None,
                    help="Only process top-N tickers by market cap")
    ap.add_argument("--limit", type=int, default=None,
                    help="Process at most N tickers (smoke test)")
    ap.add_argument("--skip-threshold", type=int, default=8,
                    help="Skip tickers with >= N annual periods already")
    ap.add_argument("--no-skip", action="store_true",
                    help="Don't skip — re-fetch everything")
    ap.add_argument("--sleep", type=float, default=0.0,
                    help="Extra sleep between tickers (seconds)")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL not set")
        return 2

    engine = _engine()
    Session = sessionmaker(bind=engine)

    tickers = _load_tickers(engine, args.top, args.shard, args.shards)
    logger.info(
        "shard %d/%d — %d tickers (top=%s, limit=%s)",
        args.shard, args.shards, len(tickers), args.top, args.limit,
    )
    if not tickers:
        logger.warning("no tickers — did you run backfill_bse_codes.py?")
        return 0

    stats = {"processed": 0, "skipped": 0, "ok": 0, "empty": 0, "error": 0, "periods": 0}
    t0 = time.time()

    for i, (ticker, scrip_code) in enumerate(tickers):
        if args.limit is not None and stats["processed"] >= args.limit:
            break

        sess = Session()
        try:
            if not args.no_skip and _already_done(sess, ticker, args.skip_threshold):
                stats["skipped"] += 1
                continue

            try:
                rows = fetch_historical_financials(scrip_code, ticker)
            except Exception as exc:
                logger.warning("fetch failed %s (%s): %s", ticker, scrip_code, exc)
                stats["error"] += 1
                continue

            if not rows:
                stats["empty"] += 1
                continue

            stored = 0
            for r in rows:
                try:
                    if store_financials(r, sess, r["period_end"], r.get("period_type", "annual")):
                        stored += 1
                except Exception as exc:
                    logger.warning("store failed %s %s: %s",
                                   ticker, r.get("period_end"), exc)

            stats["periods"] += stored
            stats["ok"] += 1 if stored else 0
            if stored == 0:
                stats["empty"] += 1

            if (stats["processed"] + 1) % 25 == 0:
                elapsed = time.time() - t0
                rate = (stats["processed"] + 1) / max(elapsed, 1.0)
                logger.info(
                    "  progress [%d/%d]: ok=%d skip=%d empty=%d err=%d periods=%d | %.2f tic/s",
                    stats["processed"] + 1, len(tickers),
                    stats["ok"], stats["skipped"], stats["empty"], stats["error"],
                    stats["periods"], rate,
                )
        finally:
            sess.close()
        stats["processed"] += 1
        if args.sleep > 0:
            time.sleep(args.sleep)

    elapsed = time.time() - t0
    logger.info("DONE in %.1f min", elapsed / 60)
    logger.info(
        "  processed=%d ok=%d skip=%d empty=%d error=%d periods_stored=%d",
        stats["processed"], stats["ok"], stats["skipped"],
        stats["empty"], stats["error"], stats["periods"],
    )
    return 0 if stats["error"] <= stats["processed"] * 0.10 else 1


if __name__ == "__main__":
    sys.exit(main())
