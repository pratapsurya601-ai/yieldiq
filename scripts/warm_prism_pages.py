"""Warm Prism SEO pages + OG images for every active ticker.

Hits two URLs per ticker:
  1. https://yieldiq.in/prism/{ticker}               — triggers Next.js ISR
  2. https://yieldiq.in/api/og/prism/{ticker}        — pre-generates OG PNG

Purpose
-------
After Phase A adds ~2,500 BSE-only stocks, none of their Prism pages
have been visited, so Next.js won't have ISR-rendered them and Google
won't index them fast. Hitting each URL forces static regeneration so
crawlers get HTML in <500ms instead of triggering a cold SSR.

Run this AFTER Phase A lands and the sitemap reflects new tickers.

Usage
-----
    python scripts/warm_prism_pages.py
    python scripts/warm_prism_pages.py --limit 100
    python scripts/warm_prism_pages.py --workers 20

The warmer uses a thread pool (default 10 workers) because the bottleneck
is remote HTTP latency, not CPU. Each hit is a fire-and-forget GET; we
don't care about the response body, only that the edge cached the page.

Rate limit: polite 20 req/s max. Vercel doesn't throttle GETs.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

try:
    import requests
except ImportError:
    print("pip install requests", file=sys.stderr)
    sys.exit(2)

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("warm_prism")


DEFAULT_BASE = "https://yieldiq.in"
PRISM_PATH = "/prism/{ticker}"
OG_PATH = "/api/og/prism/{ticker}"


def _load_tickers(database_url: str, limit: int | None) -> list[str]:
    import psycopg2

    conn = psycopg2.connect(database_url)
    cur = conn.cursor()
    try:
        cur.execute("""
            SELECT ticker FROM stocks
            WHERE is_active = TRUE
            ORDER BY ticker
        """)
        rows = cur.fetchall()
    finally:
        conn.close()
    tickers = [r[0] for r in rows if r and r[0]]
    # Strip .NS / .BO to match Prism route convention
    tickers = [t.replace(".NS", "").replace(".BO", "") for t in tickers]
    if limit:
        tickers = tickers[:limit]
    return tickers


def _hit(base: str, url_path: str, ticker: str, timeout: float = 30) -> tuple[str, int, float]:
    """Returns (ticker, status_code, elapsed_seconds)."""
    from urllib.parse import quote
    url = base + url_path.format(ticker=quote(ticker, safe=""))
    t0 = time.time()
    try:
        r = requests.get(
            url,
            timeout=timeout,
            headers={
                "User-Agent": "YieldIQ-Warmer/1.0",
                "Cache-Control": "no-cache",
            },
        )
        return ticker, r.status_code, time.time() - t0
    except Exception as exc:
        logger.debug("  %s: %s", ticker, exc)
        return ticker, -1, time.time() - t0


def _warm_surface(
    base: str,
    url_path: str,
    label: str,
    tickers: list[str],
    workers: int,
) -> dict[str, int]:
    stats = {"200": 0, "304": 0, "4xx": 0, "5xx": 0, "timeout": 0, "other": 0}
    total = len(tickers)
    t0 = time.time()

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_hit, base, url_path, t): t for t in tickers}
        done = 0
        for fut in as_completed(futures):
            ticker, code, elapsed = fut.result()
            done += 1
            if code == 200:
                stats["200"] += 1
            elif code == 304:
                stats["304"] += 1
            elif 400 <= code < 500:
                stats["4xx"] += 1
            elif 500 <= code < 600:
                stats["5xx"] += 1
            elif code == -1:
                stats["timeout"] += 1
            else:
                stats["other"] += 1

            if done % 100 == 0 or done == total:
                elapsed_t = time.time() - t0
                rate = done / max(elapsed_t, 0.1)
                logger.info(
                    "[%s] %d/%d (%.1f/s) | 200=%d 304=%d 4xx=%d 5xx=%d timeout=%d",
                    label, done, total, rate,
                    stats["200"], stats["304"], stats["4xx"], stats["5xx"], stats["timeout"],
                )

    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default=os.environ.get("WARMUP_BASE", DEFAULT_BASE))
    ap.add_argument("--limit", type=int, default=None, help="Only warm first N tickers")
    ap.add_argument("--workers", type=int, default=10)
    ap.add_argument("--skip-og", action="store_true", help="Skip OG image warming")
    ap.add_argument("--skip-page", action="store_true", help="Skip page warming")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    tickers = _load_tickers(os.environ["DATABASE_URL"], args.limit)
    logger.info("loaded %d active tickers", len(tickers))
    if not tickers:
        return 0

    logger.info("base URL: %s", args.base)
    logger.info("workers: %d", args.workers)

    overall = {}
    if not args.skip_page:
        logger.info("=== warming /prism/{ticker} pages ===")
        overall["page"] = _warm_surface(args.base, PRISM_PATH, "prism-page", tickers, args.workers)

    if not args.skip_og:
        logger.info("=== warming /api/og/prism/{ticker} images ===")
        overall["og"] = _warm_surface(args.base, OG_PATH, "prism-og", tickers, args.workers)

    logger.info("")
    logger.info("SUMMARY")
    for surface, stats in overall.items():
        logger.info("  %s: %s", surface, stats)

    # Soft-fail: if >10% 5xx on either surface, exit 1
    for surface, stats in overall.items():
        five_pct = (stats["5xx"] + stats["timeout"]) / max(len(tickers), 1)
        if five_pct > 0.10:
            logger.error("  %s failure rate %.1f%% > 10%% — alerting", surface, five_pct * 100)
            return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
