"""
Backfill pe_ratio + pb_ratio in market_metrics for all active tickers.

Usage:
    DATABASE_URL=<neon> python scripts/data_patches/backfill_pe_pb_all_2026-04-29.py [--workers 5]

    Optional env:
        FINNHUB_API_KEY  - second-source fallback
        FMP_API_KEY      - third-source fallback

Resumable: tracks progress in scripts/data_patches/_backfill_pe_pb_progress.json
so you can Ctrl-C and re-run without redoing completed tickers.

Source cascade (first non-null per metric wins):
    1. yfinance .info  (trailingPE, priceToBook)
    2. Finnhub /stock/metric  (peTTM, pbAnnual)
    3. FMP /key-metrics-ttm   (peRatioTTM, pbRatioTTM)

Strategy:
    - Active universe pulled from https://api.yieldiq.in/api/v1/public/all-tickers
    - For each ticker: look at the most-recent market_metrics row. If pe_ratio
      OR pb_ratio is NULL there (or no row exists at all), fetch from cascade.
    - Write into a row keyed by (ticker, trade_date=today) using
      ON CONFLICT (ticker, trade_date) DO UPDATE so reruns are idempotent
      and preserve already-set columns we don't touch.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import date
from pathlib import Path
from typing import Optional

try:
    import psycopg2
    import psycopg2.extras
except ImportError:
    print("ERROR: pip install psycopg2-binary", file=sys.stderr)
    sys.exit(2)

try:
    import yfinance as yf
except ImportError:
    print("ERROR: pip install yfinance", file=sys.stderr)
    sys.exit(2)

try:
    import requests_cache  # type: ignore
    _SESSION = requests_cache.CachedSession(
        ".cache/yfinance_cache",
        expire_after=24 * 3600,
    )
except ImportError:
    _SESSION = None


HERE = Path(__file__).resolve().parent
PROGRESS_PATH = HERE / "_backfill_pe_pb_progress.json"
UNTOUCHABLE_PATH = HERE / "_backfill_pe_pb_untouchable.json"
TICKERS_URL = "https://api.yieldiq.in/api/v1/public/all-tickers"

FINNHUB_KEY = os.environ.get("FINNHUB_API_KEY", "").strip()
FMP_KEY = os.environ.get("FMP_API_KEY", "").strip()

_yf_lock = threading.Lock()
_yf_last_call = [0.0]
_progress_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# Fetchers
# --------------------------------------------------------------------------- #
def fetch_yf(ticker_full: str) -> tuple[Optional[float], Optional[float]]:
    """Return (pe, pb) from yfinance .info, with global 1/sec throttle."""
    with _yf_lock:
        elapsed = time.monotonic() - _yf_last_call[0]
        if elapsed < 1.0:
            time.sleep(1.0 - elapsed)
        _yf_last_call[0] = time.monotonic()
    try:
        if _SESSION is not None:
            tk = yf.Ticker(ticker_full, session=_SESSION)
        else:
            tk = yf.Ticker(ticker_full)
        info = tk.info or {}
        pe = info.get("trailingPE")
        pb = info.get("priceToBook")
        pe_f = float(pe) if pe not in (None, 0) and isinstance(pe, (int, float)) else None
        pb_f = float(pb) if pb not in (None, 0) and isinstance(pb, (int, float)) else None
        # Sanity bounds: PE/PB outside (-1000, 10000) is junk
        if pe_f is not None and not (-1000 < pe_f < 10000):
            pe_f = None
        if pb_f is not None and not (-1000 < pb_f < 10000):
            pb_f = None
        return pe_f, pb_f
    except Exception:
        return None, None


def fetch_finnhub(ticker_full: str) -> tuple[Optional[float], Optional[float]]:
    if not FINNHUB_KEY:
        return None, None
    try:
        url = (
            f"https://finnhub.io/api/v1/stock/metric"
            f"?symbol={ticker_full}&metric=all&token={FINNHUB_KEY}"
        )
        req = urllib.request.Request(url, headers={"User-Agent": "yieldiq-backfill"})
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode("utf-8"))
        m = (data or {}).get("metric") or {}
        pe = m.get("peTTM")
        pb = m.get("pbAnnual") or m.get("pbQuarterly")
        pe_f = float(pe) if isinstance(pe, (int, float)) and pe not in (0,) else None
        pb_f = float(pb) if isinstance(pb, (int, float)) and pb not in (0,) else None
        return pe_f, pb_f
    except Exception:
        return None, None


def fetch_fmp(ticker_full: str) -> tuple[Optional[float], Optional[float]]:
    if not FMP_KEY:
        return None, None
    try:
        # FMP uses bare ticker without .NS suffix sometimes; try as-is then bare
        for symbol in (ticker_full, ticker_full.replace(".NS", "")):
            url = (
                f"https://financialmodelingprep.com/api/v3/key-metrics-ttm/"
                f"{symbol}?apikey={FMP_KEY}"
            )
            req = urllib.request.Request(url, headers={"User-Agent": "yieldiq-backfill"})
            with urllib.request.urlopen(req, timeout=15) as resp:
                data = json.loads(resp.read().decode("utf-8"))
            if data and isinstance(data, list) and len(data) > 0:
                row = data[0]
                pe = row.get("peRatioTTM")
                pb = row.get("pbRatioTTM")
                pe_f = float(pe) if isinstance(pe, (int, float)) and pe != 0 else None
                pb_f = float(pb) if isinstance(pb, (int, float)) and pb != 0 else None
                if pe_f is not None or pb_f is not None:
                    return pe_f, pb_f
        return None, None
    except Exception:
        return None, None


def fetch_with_retry(ticker_full: str) -> tuple[Optional[float], Optional[float], str]:
    """Cascade through sources. Returns (pe, pb, source_label)."""
    backoffs = [5, 15, 60]
    for attempt in range(len(backoffs) + 1):
        try:
            pe, pb = fetch_yf(ticker_full)
            if pe is not None or pb is not None:
                src = "yf"
                # If still missing one, try fallbacks for the missing one
                if pe is None or pb is None:
                    pe2, pb2 = fetch_finnhub(ticker_full)
                    if pe is None and pe2 is not None:
                        pe = pe2
                        src = "yf+finnhub"
                    if pb is None and pb2 is not None:
                        pb = pb2
                        src = "yf+finnhub"
                if pe is None or pb is None:
                    pe3, pb3 = fetch_fmp(ticker_full)
                    if pe is None and pe3 is not None:
                        pe = pe3
                        src = src + "+fmp"
                    if pb is None and pb3 is not None:
                        pb = pb3
                        src = src + "+fmp"
                return pe, pb, src
            # yf was empty: try finnhub
            pe2, pb2 = fetch_finnhub(ticker_full)
            if pe2 is not None or pb2 is not None:
                # Try to top up missing from fmp
                if pe2 is None or pb2 is None:
                    pe3, pb3 = fetch_fmp(ticker_full)
                    if pe2 is None:
                        pe2 = pe3
                    if pb2 is None:
                        pb2 = pb3
                return pe2, pb2, "finnhub"
            pe3, pb3 = fetch_fmp(ticker_full)
            if pe3 is not None or pb3 is not None:
                return pe3, pb3, "fmp"
            return None, None, "untouchable"
        except urllib.error.HTTPError as e:
            if e.code == 429 and attempt < len(backoffs):
                time.sleep(backoffs[attempt])
                continue
            return None, None, "error"
        except Exception:
            if attempt < len(backoffs):
                time.sleep(backoffs[attempt])
                continue
            return None, None, "error"
    return None, None, "untouchable"


# --------------------------------------------------------------------------- #
# DB helpers
# --------------------------------------------------------------------------- #
UPSERT_SQL = """
INSERT INTO market_metrics (ticker, trade_date, pe_ratio, pb_ratio)
VALUES (%s, %s, %s, %s)
ON CONFLICT (ticker, trade_date) DO UPDATE SET
    pe_ratio = COALESCE(EXCLUDED.pe_ratio, market_metrics.pe_ratio),
    pb_ratio = COALESCE(EXCLUDED.pb_ratio, market_metrics.pb_ratio)
"""

NEEDS_BACKFILL_SQL = """
WITH latest AS (
    SELECT DISTINCT ON (ticker) ticker, pe_ratio, pb_ratio
    FROM market_metrics
    ORDER BY ticker, trade_date DESC
)
SELECT s.ticker AS ticker
FROM (SELECT unnest(%s::text[]) AS ticker) s
LEFT JOIN latest l ON l.ticker = s.ticker
WHERE l.ticker IS NULL OR l.pe_ratio IS NULL OR l.pb_ratio IS NULL
"""


def get_tickers_needing_backfill(db_url: str, all_tickers: list[str]) -> list[str]:
    bare = [t.replace(".NS", "") for t in all_tickers]
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute(NEEDS_BACKFILL_SQL, (bare,))
        needing = [r[0] for r in cur.fetchall()]
        cur.close()
    finally:
        conn.close()
    return needing


def upsert(db_url: str, ticker_bare: str, pe: Optional[float], pb: Optional[float]) -> None:
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute(UPSERT_SQL, (ticker_bare, date.today(), pe, pb))
        conn.commit()
        cur.close()
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Progress
# --------------------------------------------------------------------------- #
def load_progress() -> dict:
    if PROGRESS_PATH.exists():
        try:
            return json.loads(PROGRESS_PATH.read_text())
        except Exception:
            return {}
    return {}


def save_progress(progress: dict) -> None:
    tmp = PROGRESS_PATH.with_suffix(".json.tmp")
    tmp.write_text(json.dumps(progress, indent=2, sort_keys=True))
    tmp.replace(PROGRESS_PATH)


# --------------------------------------------------------------------------- #
# Counts (for pre/post stats)
# --------------------------------------------------------------------------- #
def count_filled(db_url: str) -> tuple[int, int, int]:
    """Return (distinct_tickers_with_pe, distinct_tickers_with_pb, distinct_tickers_total)
    looking only at the latest row per ticker."""
    conn = psycopg2.connect(db_url)
    try:
        cur = conn.cursor()
        cur.execute("""
            WITH latest AS (
                SELECT DISTINCT ON (ticker) ticker, pe_ratio, pb_ratio
                FROM market_metrics
                ORDER BY ticker, trade_date DESC
            )
            SELECT
                COUNT(*) FILTER (WHERE pe_ratio IS NOT NULL) AS with_pe,
                COUNT(*) FILTER (WHERE pb_ratio IS NOT NULL) AS with_pb,
                COUNT(*) AS total
            FROM latest
        """)
        row = cur.fetchone()
        cur.close()
        return tuple(row)  # type: ignore
    finally:
        conn.close()


# --------------------------------------------------------------------------- #
# Main
# --------------------------------------------------------------------------- #
def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--workers", type=int, default=5)
    ap.add_argument("--limit", type=int, default=0, help="Cap number of tickers (debug)")
    ap.add_argument("--stats-only", action="store_true",
                    help="Just print pre-fill counts and exit.")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL", "").strip()
    if not db_url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        return 2

    print(f"[{time.strftime('%H:%M:%S')}] Fetching active universe from {TICKERS_URL}")
    with urllib.request.urlopen(TICKERS_URL, timeout=30) as resp:
        data = json.loads(resp.read().decode("utf-8"))
    all_tickers = [d["full_ticker"] for d in data]
    print(f"  -> {len(all_tickers)} active tickers")

    pe_pre, pb_pre, total_pre = count_filled(db_url)
    print(f"\nPRE-FILL latest-row coverage:")
    print(f"  distinct tickers in market_metrics : {total_pre}")
    print(f"  with pe_ratio (latest row)         : {pe_pre}")
    print(f"  with pb_ratio (latest row)         : {pb_pre}")

    if args.stats_only:
        return 0

    needing_bare = get_tickers_needing_backfill(db_url, all_tickers)
    needing_set = set(needing_bare)
    universe = [t for t in all_tickers if t.replace(".NS", "") in needing_set]
    if args.limit > 0:
        universe = universe[:args.limit]
    print(f"\n  -> {len(universe)} tickers need backfill")

    progress = load_progress()
    done = set(progress.get("done", []))
    untouchable: dict = progress.get("untouchable", {})
    src_counts: dict = progress.get("src_counts", {})

    todo = [t for t in universe if t not in done]
    print(f"  -> {len(todo)} remaining after resume (already done: {len(done)})")

    started = time.monotonic()
    processed = 0

    def worker(ticker_full: str) -> tuple[str, Optional[float], Optional[float], str]:
        pe, pb, src = fetch_with_retry(ticker_full)
        bare = ticker_full.replace(".NS", "")
        if pe is not None or pb is not None:
            try:
                upsert(db_url, bare, pe, pb)
            except Exception as exc:
                return ticker_full, None, None, f"db_error:{exc}"
        return ticker_full, pe, pb, src

    try:
        with ThreadPoolExecutor(max_workers=args.workers) as ex:
            futures = {ex.submit(worker, t): t for t in todo}
            for fut in as_completed(futures):
                ticker_full, pe, pb, src = fut.result()
                processed += 1
                with _progress_lock:
                    done.add(ticker_full)
                    src_counts[src] = src_counts.get(src, 0) + 1
                    if src in ("untouchable", "error"):
                        untouchable[ticker_full] = src
                    if processed % 50 == 0:
                        progress = {
                            "done": sorted(done),
                            "untouchable": untouchable,
                            "src_counts": src_counts,
                        }
                        save_progress(progress)
                        rate = processed / max(1.0, time.monotonic() - started)
                        eta_s = (len(todo) - processed) / max(rate, 1e-6)
                        print(
                            f"[{time.strftime('%H:%M:%S')}] {processed}/{len(todo)} "
                            f"({100*processed/len(todo):.1f}%)  "
                            f"rate={rate:.2f}/s  ETA={eta_s/60:.1f}min  "
                            f"src_counts={src_counts}"
                        )
    finally:
        progress = {
            "done": sorted(done),
            "untouchable": untouchable,
            "src_counts": src_counts,
        }
        save_progress(progress)
        UNTOUCHABLE_PATH.write_text(json.dumps(untouchable, indent=2, sort_keys=True))

    elapsed = time.monotonic() - started
    pe_post, pb_post, total_post = count_filled(db_url)

    print("\n" + "=" * 60)
    print("BACKFILL COMPLETE")
    print("=" * 60)
    print(f"  wall clock                : {elapsed/60:.1f} min")
    print(f"  tickers attempted         : {len(todo)}")
    print(f"  source counts             : {src_counts}")
    print(f"  untouchable               : {len(untouchable)}")
    print()
    print(f"  PRE  pe={pe_pre}  pb={pb_pre}  total={total_pre}")
    print(f"  POST pe={pe_post}  pb={pb_post}  total={total_post}")
    print(f"  delta pe = +{pe_post - pe_pre}")
    print(f"  delta pb = +{pb_post - pb_pre}")
    print()
    print(f"  Top 20 untouchable tickers:")
    for t in sorted(untouchable.keys())[:20]:
        print(f"    {t}  ({untouchable[t]})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
