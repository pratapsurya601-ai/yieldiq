"""Bulk refresh of live_quotes for every active ticker in `stocks`.

Manual one-shot job dispatched from GitHub Actions UI. Mirrors the
canonical refresher (backend/workers/market_data_refresher.py::
refresh_live_quotes) but runs serially with throttling so we can hit
~2,300 tickers from a single GH runner without tripping yfinance's
rate limiter or the Aiven Postgres connection ceiling.

For each active ticker in `stocks` (bare symbol, no .NS/.BO suffix):
  1. Try yfinance.Ticker(t + ".NS").fast_info.last_price
  2. Fallback to .BO if .NS returns no price
  3. UPSERT (ticker, price, change_pct, volume, as_of) into live_quotes
     using the ".NS"/".BO" suffix that succeeded — so the row matches
     the rest of the codebase's convention.
  4. Sleep 0.4s between tickers; exponential backoff on any 429/Too Many
     Requests style exception.

CLI flags:
  --max-tickers N  : process only the first N (smoke test).
  --offset N       : skip the first N (resume after partial run).

Writes a JSON summary to reports/bulk_refresh_live_quotes_summary.json.
Logs progress to stderr; never writes to stdout (so CI logs stay clean).

Discipline notes:
  * Never imports backend.* — this is a standalone data job.
  * Idempotent: ON CONFLICT (ticker) DO UPDATE.
  * No CACHE_VERSION bump, no scoring math, no test harness side effects.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import psycopg2
import psycopg2.extras
import yfinance as yf

REPO_ROOT = Path(__file__).resolve().parents[2]
REPORTS_DIR = REPO_ROOT / "reports"
REPORTS_DIR.mkdir(parents=True, exist_ok=True)
SUMMARY_PATH = REPORTS_DIR / "bulk_refresh_live_quotes_summary.json"

THROTTLE_SECONDS = 0.4
BACKOFF_BASE = 4.0       # 4s, 8s, 16s, 32s
BACKOFF_MAX_ATTEMPTS = 4

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(message)s",
    stream=sys.stderr,
)
log = logging.getLogger("bulk_refresh_live_quotes")


def _normalize_db_url(url: str) -> str:
    if url.startswith("postgres://"):
        return "postgresql://" + url[len("postgres://"):]
    return url


def fetch_active_tickers(conn) -> list[str]:
    """Pull bare tickers (no suffix) from stocks where is_active = TRUE."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT ticker FROM stocks WHERE is_active = TRUE ORDER BY ticker"
        )
        return [r[0] for r in cur.fetchall() if r[0]]


def _is_rate_limit(exc: Exception) -> bool:
    msg = str(exc).lower()
    return (
        "429" in msg
        or "too many requests" in msg
        or "rate limit" in msg
    )


def _quote_for(yf_symbol: str) -> tuple[float | None, float | None, int | None]:
    """Return (price, change_pct, volume) from yfinance fast_info or (None, ...)."""
    tk = yf.Ticker(yf_symbol)
    fi = tk.fast_info
    price = float(getattr(fi, "last_price", 0) or 0)
    prev = float(getattr(fi, "previous_close", 0) or 0)
    vol = getattr(fi, "last_volume", None)
    try:
        vol = int(vol) if vol is not None else None
    except (TypeError, ValueError):
        vol = None
    chg = ((price - prev) / prev * 100) if prev else None
    return (price if price else None, chg, vol)


def fetch_with_fallback(
    bare_ticker: str,
) -> tuple[str | None, float | None, float | None, int | None]:
    """Try .NS first, fall back to .BO. Returns (suffix_used, price, chg, vol).

    suffix_used is None if both attempts returned no price.
    """
    for suffix in (".NS", ".BO"):
        sym = bare_ticker + suffix
        for attempt in range(BACKOFF_MAX_ATTEMPTS):
            try:
                price, chg, vol = _quote_for(sym)
                if price is not None:
                    return (suffix, price, chg, vol)
                # No price but no exception — don't retry, try next suffix.
                break
            except Exception as exc:
                if _is_rate_limit(exc) and attempt < BACKOFF_MAX_ATTEMPTS - 1:
                    sleep_s = BACKOFF_BASE * (2 ** attempt)
                    log.warning(
                        "rate-limited on %s (attempt %d), sleeping %.1fs",
                        sym, attempt + 1, sleep_s,
                    )
                    time.sleep(sleep_s)
                    continue
                log.debug("yfinance %s failed: %s", sym, exc)
                break
    return (None, None, None, None)


UPSERT_SQL = """
    INSERT INTO live_quotes (ticker, price, change_pct, volume, as_of)
    VALUES (%(ticker)s, %(price)s, %(change_pct)s, %(volume)s, %(as_of)s)
    ON CONFLICT (ticker) DO UPDATE SET
        price      = EXCLUDED.price,
        change_pct = EXCLUDED.change_pct,
        volume     = EXCLUDED.volume,
        as_of      = EXCLUDED.as_of
"""


def upsert_quote(conn, ticker_with_suffix: str, price: float,
                 chg: float | None, vol: int | None,
                 as_of: datetime) -> None:
    with conn.cursor() as cur:
        cur.execute(UPSERT_SQL, {
            "ticker": ticker_with_suffix,
            "price": price,
            "change_pct": chg,
            "volume": vol,
            "as_of": as_of,
        })
    conn.commit()


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--max-tickers", type=int, default=None,
                    help="Process at most N tickers (smoke test).")
    ap.add_argument("--offset", type=int, default=0,
                    help="Skip the first N tickers (resume).")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        log.error("DATABASE_URL not set")
        return 2

    conn = psycopg2.connect(_normalize_db_url(db_url))
    try:
        all_tickers = fetch_active_tickers(conn)
        log.info("fetched %d active tickers from stocks", len(all_tickers))

        sliced = all_tickers[args.offset:]
        if args.max_tickers is not None:
            sliced = sliced[:args.max_tickers]
        log.info("processing %d tickers (offset=%d, max=%s)",
                 len(sliced), args.offset, args.max_tickers)

        ok_ns = ok_bo = no_price = errored = 0
        started = time.time()

        for i, bare in enumerate(sliced, 1):
            try:
                suffix, price, chg, vol = fetch_with_fallback(bare)
                if suffix is None or price is None:
                    no_price += 1
                else:
                    upsert_quote(
                        conn,
                        bare + suffix,
                        price, chg, vol,
                        datetime.now(timezone.utc),
                    )
                    if suffix == ".NS":
                        ok_ns += 1
                    else:
                        ok_bo += 1
            except Exception as exc:
                errored += 1
                log.warning("upsert failed for %s: %s", bare, exc)
                try:
                    conn.rollback()
                except Exception:
                    pass

            if i % 50 == 0 or i == len(sliced):
                elapsed = time.time() - started
                rate = i / elapsed if elapsed else 0
                log.info(
                    "progress %d/%d  ok_ns=%d ok_bo=%d no_price=%d err=%d  "
                    "%.2f tickers/s",
                    i, len(sliced), ok_ns, ok_bo, no_price, errored, rate,
                )

            time.sleep(THROTTLE_SECONDS)

        elapsed = time.time() - started
        summary = {
            "started_at": datetime.fromtimestamp(
                started, tz=timezone.utc).isoformat(),
            "finished_at": datetime.now(timezone.utc).isoformat(),
            "elapsed_seconds": round(elapsed, 1),
            "active_tickers_total": len(all_tickers),
            "processed": len(sliced),
            "offset": args.offset,
            "max_tickers": args.max_tickers,
            "ok_ns": ok_ns,
            "ok_bo": ok_bo,
            "no_price": no_price,
            "errored": errored,
        }
        SUMMARY_PATH.write_text(json.dumps(summary, indent=2))
        log.info("summary written to %s", SUMMARY_PATH)
        log.info("done: %s", json.dumps(summary))
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    sys.exit(main())
