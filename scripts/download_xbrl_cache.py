"""Download raw NSE XBRL filings to local disk for offline parser iteration.

The canonical offline cache for the YieldIQ fundamentals pipeline.

Why this exists
---------------
PR #46 extended the NSE XBRL parser's tag coverage, but every parser
tweak previously required re-hitting NSE (~8s per ticker × 3000 tickers
= 6.5 hours). That killed iteration speed and triggered NSE rate-limit
responses under load.

This script decouples download from parse:

1. Download each ticker's entire filing history ONCE → gzipped XML on
   local disk at ``data_pipeline/xbrl/raw_cache/<TICKER>/``.
2. Parser iterates freely against the cache — no network, no rate limits.
3. When a parse pass produces good output, a separate backfill script
   reads from the cache and writes structured rows to Neon.

Storage
-------
Each XBRL file: ~50-300 KB raw, ~15-40 KB gzipped. Typical ticker has
~80 filings (10y × 4Q + 10 annual) → ~2 MB gzipped per ticker. Top
500 universe ≈ 1 GB. Full 3000 universe ≈ 6 GB.

Resume semantics
----------------
Skips any XBRL file already present on disk (checked by path existence).
Safe to Ctrl+C and restart at any point. A ``--force-refresh`` flag is
provided for the rare case where NSE revises a filing (rare — XBRL is
SEBI-mandated archival).

Rate-limiting
-------------
Default inter-request sleep 0.4s with ±50% jitter = ~0.2-0.6s between
HTTP calls. NSE hasn't rate-limited under this budget in test runs.
Exponential backoff on HTTP 403 / 429 (tripling sleep, max 3 retries).

Usage
-----
    # Defaults: top 500 tickers, 10-year history, resumable
    python scripts/download_xbrl_cache.py

    # Targeted: specific tickers
    python scripts/download_xbrl_cache.py --tickers BPCL,ONGC,IOC

    # Wider scope: top 1000
    python scripts/download_xbrl_cache.py --top 1000

    # Full history (20y) for top 100
    python scripts/download_xbrl_cache.py --top 100 --start-year 2004

Output layout
-------------
    data_pipeline/xbrl/raw_cache/
        TCS/
            _filings_manifest.json       # metadata for every filing
            2024-03-31_annual_cons.xml.gz
            2024-03-31_annual_std.xml.gz
            2024-12-31_quarterly.xml.gz
            ...
        RELIANCE/
            ...

Each ticker dir also has ``_filings_manifest.json`` which records the
NSE-provided metadata (xbrl URL, broadcast date, consolidation flag,
financial year). The parser reads from this to avoid re-fetching the
filings-list.
"""
from __future__ import annotations

import argparse
import gzip
import json
import logging
import os
import random
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.orm import sessionmaker

from data_pipeline.sources.nse_xbrl_fundamentals import (
    _get_session,
    fetch_filings_list,
    _CONSOLIDATED_KEYS,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("xbrl_cache")

# Cache root — matches the .gitignore entry data_pipeline/xbrl/raw_cache/
CACHE_ROOT = _REPO / "data_pipeline" / "xbrl" / "raw_cache"


def _engine():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url, pool_recycle=300, pool_pre_ping=True)


def _load_universe(engine, top: int | None) -> list[str]:
    """Top-N NSE tickers by market cap. Bare symbols (no .NS/.BO)."""
    Session = sessionmaker(bind=engine)
    sess = Session()
    try:
        rows = sess.execute(sa_text("""
            SELECT s.ticker
            FROM stocks s
            LEFT JOIN market_metrics m ON m.ticker = s.ticker
              AND m.trade_date = (
                SELECT MAX(trade_date) FROM market_metrics
                WHERE ticker = s.ticker
              )
            WHERE s.is_active = TRUE
              AND s.ticker NOT LIKE '%.BO'
            ORDER BY COALESCE(m.market_cap_cr, 0) DESC, s.ticker
        """)).fetchall()
    finally:
        sess.close()
    universe = [r[0] for r in rows if r and r[0]]
    if top is not None:
        universe = universe[:top]
    return universe


def _sleep_jitter(base: float) -> None:
    """Sleep base seconds ± 50% jitter."""
    time.sleep(base * random.uniform(0.5, 1.5))


def _filename_for(filing: dict, period: str) -> str:
    """Deterministic filename from filing metadata.

    Layout: <period_end>_<period>[_<consolidation>].xml.gz

    Examples:
        2024-03-31_annual_cons.xml.gz
        2024-03-31_annual_std.xml.gz
        2024-12-31_quarterly.xml.gz

    Consolidation tag included when detectable. Unclassified filings
    (no consolidation marker) omit the suffix — they get the bare
    `_annual.xml.gz` / `_quarterly.xml.gz` form so the parser knows
    to probe both interpretations.
    """
    period_end = (
        filing.get("toDate")
        or filing.get("to_date")
        or filing.get("period_end")
        or "unknown"
    )
    # Detect consolidation from known flag fields.
    cons_tag = ""
    for k in _CONSOLIDATED_KEYS:
        v = filing.get(k)
        if v is None:
            continue
        s = str(v).strip().lower()
        if "consolidated" in s or s in ("true", "yes", "y", "1", "cons"):
            cons_tag = "_cons"
            break
        if "standalone" in s or s in ("false", "no", "n", "0", "std"):
            cons_tag = "_std"
            break
    period_lc = period.lower()
    return f"{period_end}_{period_lc}{cons_tag}.xml.gz"


def _fetch_with_backoff(
    session,
    url: str,
    *,
    max_retries: int = 3,
    base_sleep: float = 1.0,
) -> bytes | None:
    """Download URL with exponential backoff on 403/429."""
    sleep = base_sleep
    for attempt in range(max_retries):
        try:
            r = session.get(url, timeout=30)
        except Exception as exc:
            logger.info("  fetch exception (try %d): %s", attempt + 1, exc)
            time.sleep(sleep)
            sleep *= 3
            continue
        if r.status_code == 200:
            if len(r.content) < 500:
                logger.info("  short response (%d bytes), treating as empty", len(r.content))
                return None
            return r.content
        if r.status_code in (403, 429):
            logger.info(
                "  rate-limited HTTP %d on try %d — sleeping %.1fs",
                r.status_code, attempt + 1, sleep,
            )
            time.sleep(sleep)
            sleep *= 3
            continue
        logger.info("  HTTP %d for %s", r.status_code, url)
        return None
    return None


def _download_ticker(
    session,
    ticker: str,
    cache_dir: Path,
    start_year: int,
    force_refresh: bool,
    sleep_between_files: float,
    max_filings_per_period: int,
) -> dict[str, int]:
    """Download a single ticker's filing history. Returns stats dict."""
    stats = {"list_ok": 0, "list_err": 0, "downloaded": 0, "skipped": 0, "errored": 0}
    ticker_dir = cache_dir / ticker
    ticker_dir.mkdir(parents=True, exist_ok=True)

    manifest: list[dict[str, Any]] = []
    for period in ("Annual", "Quarterly"):
        try:
            filings = fetch_filings_list(ticker, period=period, session=session)
        except Exception as exc:
            logger.info("  filings_list error %s %s: %s", ticker, period, exc)
            stats["list_err"] += 1
            continue
        if not filings:
            stats["list_err"] += 1
            continue
        stats["list_ok"] += 1
        # Trim to recent N filings per period (default 200 — effectively no cap
        # for a typical 20y window). Still a guard against runaway responses.
        filings = filings[:max_filings_per_period]

        for filing in filings:
            period_end = (
                filing.get("toDate")
                or filing.get("to_date")
                or filing.get("period_end")
            )
            if not period_end:
                continue
            # Year filter
            try:
                year = int(str(period_end)[:4])
                if year < start_year:
                    continue
            except Exception:
                pass
            xbrl_url = filing.get("xbrl")
            if not xbrl_url or not str(xbrl_url).startswith("http"):
                continue
            # NSE uses a bare "-" (or URL ending in "/-") as a sentinel
            # for "filing exists in the index but has no XBRL attachment" —
            # common for pre-2015 filings before XBRL was SEBI-mandated.
            # Skip these silently; downloading them returns 404 and
            # inflates the error count by 5x (observed on BPCL smoke
            # test: 86 of 148 filings were "-" sentinels).
            _url_str = str(xbrl_url).rstrip()
            if _url_str.endswith("/-") or _url_str.endswith("/-.xml") or _url_str == "-":
                stats["skipped"] += 1
                continue

            fname = _filename_for(filing, period)
            fpath = ticker_dir / fname
            rel = f"{ticker}/{fname}"

            # Add manifest entry regardless of whether we download
            manifest.append({
                "period": period,
                "period_end": period_end,
                "xbrl_url": xbrl_url,
                "filename": fname,
                "broadcast_date": filing.get("broadcastDate") or filing.get("bcastDate"),
                "fy": filing.get("financial_year") or filing.get("fy"),
                "consolidation_raw": {
                    k: filing.get(k) for k in _CONSOLIDATED_KEYS if filing.get(k)
                },
            })

            if fpath.exists() and not force_refresh:
                stats["skipped"] += 1
                continue

            content = _fetch_with_backoff(session, xbrl_url)
            if content is None:
                stats["errored"] += 1
                _sleep_jitter(sleep_between_files)
                continue
            tmp = fpath.with_suffix(fpath.suffix + ".tmp")
            try:
                with gzip.open(tmp, "wb", compresslevel=6) as gz:
                    gz.write(content)
                tmp.replace(fpath)
                stats["downloaded"] += 1
                logger.debug("  saved %s (%d bytes raw → %d bytes gzipped)",
                             rel, len(content), fpath.stat().st_size)
            except Exception as exc:
                logger.info("  write failed for %s: %s", rel, exc)
                stats["errored"] += 1
                try:
                    tmp.unlink(missing_ok=True)
                except Exception:
                    pass
            _sleep_jitter(sleep_between_files)

    # Write manifest (full, not append) — the NSE API list is source of truth
    mpath = ticker_dir / "_filings_manifest.json"
    try:
        with mpath.open("w", encoding="utf-8") as f:
            json.dump({"ticker": ticker, "filings": manifest}, f, indent=2)
    except Exception as exc:
        logger.info("  manifest write failed for %s: %s", ticker, exc)
    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--top", type=int, default=500,
                    help="Top-N NSE tickers by market cap (default 500)")
    ap.add_argument("--tickers", type=str, default=None,
                    help="Comma-separated allowlist (overrides --top)")
    ap.add_argument("--start-year", type=int, default=date.today().year - 10,
                    help="Include filings with period_end year >= this (default: 10 years ago)")
    ap.add_argument("--force-refresh", action="store_true",
                    help="Re-download files that already exist on disk")
    ap.add_argument("--sleep", type=float, default=0.4,
                    help="Base sleep between XBRL downloads, jittered ±50%% (default 0.4s)")
    ap.add_argument("--inter-ticker-sleep", type=float, default=1.5,
                    help="Sleep between tickers, jittered ±50%% (default 1.5s)")
    ap.add_argument("--max-filings-per-period", type=int, default=200,
                    help="Hard cap on annual filings + quarterly filings per ticker (default 200)")
    ap.add_argument("--progress-every", type=int, default=10,
                    help="Log aggregate progress every N tickers (default 10)")
    ap.add_argument("--workers", type=int, default=4,
                    help=(
                        "Number of parallel ticker workers. Each worker has "
                        "its own curl_cffi session. NSE tolerates up to ~6 "
                        "concurrent sessions from a single IP without "
                        "rate-limiting — default 4 gives us headroom. Set "
                        "to 1 for serial (debugging)."
                    ))
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL not set — needed to load ticker universe")
        return 2

    CACHE_ROOT.mkdir(parents=True, exist_ok=True)
    logger.info("cache root: %s", CACHE_ROOT)

    # Resolve universe
    if args.tickers:
        universe = [
            t.strip().upper().replace(".NS", "").replace(".BO", "")
            for t in args.tickers.split(",") if t.strip()
        ]
        logger.info("universe: %d tickers from --tickers allowlist", len(universe))
    else:
        engine = _engine()
        universe = _load_universe(engine, args.top)
        logger.info("universe: top %d NSE tickers by market cap (%d loaded)",
                    args.top, len(universe))

    if not universe:
        logger.error("empty universe")
        return 1

    logger.info("config: start_year=%d sleep=%.1fs±50%% force_refresh=%s",
                args.start_year, args.sleep, args.force_refresh)

    # ── Parallel downloader ─────────────────────────────────────────
    # Each worker gets its own curl_cffi session — important because NSE
    # warms per-session cookies and we don't want workers stepping on each
    # other's session state. Threading (not multiprocessing) is the right
    # model: every worker spends 95% of its time in socket.recv() waiting
    # on NSE, so GIL is not a bottleneck.
    import threading
    from concurrent.futures import ThreadPoolExecutor, as_completed

    totals = {"list_ok": 0, "list_err": 0, "downloaded": 0, "skipped": 0, "errored": 0}
    totals_lock = threading.Lock()
    t0 = time.time()
    completed = {"n": 0}
    completed_lock = threading.Lock()

    # Pre-build one session per worker slot. Reused across tickers
    # assigned to that slot (sessions are not thread-safe to SHARE, but
    # each thread gets its own).
    worker_sessions: dict[int, Any] = {}
    worker_sessions_lock = threading.Lock()

    def _get_worker_session() -> Any:
        tid = threading.get_ident()
        with worker_sessions_lock:
            if tid not in worker_sessions:
                worker_sessions[tid] = _get_session()
            return worker_sessions[tid]

    def _work(ticker: str) -> tuple[str, dict[str, int] | None, Exception | None]:
        try:
            sess = _get_worker_session()
            s = _download_ticker(
                sess, ticker, CACHE_ROOT,
                start_year=args.start_year,
                force_refresh=args.force_refresh,
                sleep_between_files=args.sleep,
                max_filings_per_period=args.max_filings_per_period,
            )
            return ticker, s, None
        except Exception as exc:
            return ticker, None, exc
        finally:
            # Inter-ticker sleep is per-worker, not global — keeps this
            # worker's request rate reasonable without serialising the pool.
            _sleep_jitter(args.inter_ticker_sleep)

    workers = max(1, args.workers)
    logger.info("dispatching %d tickers across %d parallel worker(s)",
                len(universe), workers)

    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = {pool.submit(_work, t): t for t in universe}
        for fut in as_completed(futures):
            ticker, s, exc = fut.result()
            with completed_lock:
                completed["n"] += 1
                n_done = completed["n"]

            if exc is not None:
                logger.info("ticker %s crashed: %s", ticker, exc)
                with totals_lock:
                    totals["errored"] += 1
            else:
                with totals_lock:
                    for k, v in s.items():
                        totals[k] += v
                logger.info(
                    "[%d/%d] %s: dl=%d skip=%d err=%d",
                    n_done, len(universe), ticker,
                    s["downloaded"], s["skipped"], s["errored"],
                )

            if n_done % args.progress_every == 0:
                elapsed = time.time() - t0
                rate = n_done / max(elapsed, 1.0)
                eta_min = (len(universe) - n_done) / max(rate, 0.001) / 60
                with totals_lock:
                    logger.info(
                        "  --- progress: %d/%d tickers | %.1f/min | ETA %.1f min | "
                        "total: dl=%d skip=%d err=%d",
                        n_done, len(universe), rate * 60, eta_min,
                        totals["downloaded"], totals["skipped"], totals["errored"],
                    )

    elapsed = time.time() - t0
    logger.info("DONE in %.1f min", elapsed / 60)
    logger.info(
        "  downloaded=%d skipped=%d errored=%d | filings_list ok=%d err=%d",
        totals["downloaded"], totals["skipped"], totals["errored"],
        totals["list_ok"], totals["list_err"],
    )
    # Disk usage summary
    try:
        total_size = sum(
            f.stat().st_size
            for f in CACHE_ROOT.rglob("*.xml.gz")
        )
        total_files = sum(1 for _ in CACHE_ROOT.rglob("*.xml.gz"))
        logger.info(
            "  cache: %d files, %.1f MB on disk (%s)",
            total_files, total_size / (1024 * 1024), CACHE_ROOT,
        )
    except Exception:
        pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
