"""Playwright-driven 10Y fundamentals backfill.

Drop-in replacement for scripts/backfill_fundamentals_10y_bse.py after
BSE's JSON API started returning 302 redirects to plain HTTP clients.
This version runs a real Chromium instance, solves Akamai's JS
challenge, and reuses the authenticated context to hit the same
Peercomp endpoints.

Usage
-----
    DATABASE_URL=... python scripts/backfill_fundamentals_10y_browser.py \\
        --shards 4 --shard 0 --top 500 --sleep 0.3

    # Smoke test on 5 tickers
    python scripts/backfill_fundamentals_10y_browser.py --limit 5

Requires
--------
    pip install playwright playwright-stealth
    playwright install chromium --with-deps

Timing
------
~3-4s per ticker in headless mode. 2,500 tickers single-threaded
≈ 2.5 hours. With --shards 4 on GH Actions matrix: ~45 min.
"""
from __future__ import annotations

import argparse
import asyncio
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

from data_pipeline.sources.bse_peercomp_browser import BSEBrowserClient
from data_pipeline.sources.bse_xbrl import store_financials  # type: ignore


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("fund_10y_browser")


def _engine():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url, pool_recycle=300, pool_pre_ping=True)


def _load_tickers(engine, top: int | None, shard: int, shards: int) -> list[tuple[str, str]]:
    Session = sessionmaker(bind=engine)
    sess = Session()
    try:
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
    if shards > 1:
        tickers = tickers[shard::shards]
    return tickers


def _already_done(sess, ticker: str, threshold: int) -> bool:
    row = sess.execute(sa_text("""
        SELECT COUNT(*) FROM financials
        WHERE ticker=:t AND period_type='annual' AND revenue IS NOT NULL
    """), {"t": ticker}).fetchone()
    return bool(row and row[0] >= threshold)


async def _run(args) -> int:
    if not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL not set"); return 2

    engine = _engine()
    Session = sessionmaker(bind=engine)

    tickers = _load_tickers(engine, args.top, args.shard, args.shards)
    logger.info("shard %d/%d — %d tickers", args.shard, args.shards, len(tickers))
    if not tickers:
        logger.warning("no tickers to process"); return 0

    client = BSEBrowserClient(headless=not args.headed)
    await client.init()

    stats = {"processed": 0, "ok": 0, "skip": 0, "empty": 0, "error": 0, "periods": 0}
    t0 = time.time()

    try:
        for i, (ticker, scrip) in enumerate(tickers):
            if args.limit is not None and stats["processed"] >= args.limit:
                break
            sess = Session()
            try:
                if not args.no_skip and _already_done(sess, ticker, args.skip_threshold):
                    stats["skip"] += 1
                    continue
                try:
                    rows = await client.fetch(scrip, ticker)
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
                        if store_financials(r, sess, r["period_end"], r.get("period_type", "annual")):
                            stored += 1
                    except Exception as exc:
                        logger.warning("store failed %s %s: %s", ticker, r.get("period_end"), exc)
                if stored > 0:
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
                sess.close()
            stats["processed"] += 1
            await asyncio.sleep(args.sleep)
    finally:
        await client.close()

    elapsed = time.time() - t0
    logger.info("DONE in %.1f min", elapsed / 60)
    logger.info(
        "  processed=%d ok=%d skip=%d empty=%d error=%d periods=%d",
        stats["processed"], stats["ok"], stats["skip"],
        stats["empty"], stats["error"], stats["periods"],
    )
    return 0 if stats["error"] <= stats["processed"] * 0.10 else 1


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--shard", type=int, default=0)
    ap.add_argument("--shards", type=int, default=1)
    ap.add_argument("--top", type=int, default=None)
    ap.add_argument("--limit", type=int, default=None)
    ap.add_argument("--skip-threshold", type=int, default=8)
    ap.add_argument("--no-skip", action="store_true")
    ap.add_argument("--sleep", type=float, default=0.3)
    ap.add_argument("--headed", action="store_true", help="Show Chromium window (debug)")
    args = ap.parse_args()
    return asyncio.run(_run(args))


if __name__ == "__main__":
    sys.exit(main())
