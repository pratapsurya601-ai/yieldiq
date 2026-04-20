"""Backfill NSE bhavcopies 2004-01-01 → 2015-12-31 into Parquet ARCHIVE.

Rationale
---------
Extending PG `daily_prices` to 2004 would add ~500 MB and blow past the
Aiven Hobby 1 GB cap. The live API only queries 2016+ anyway. So we
write pre-2016 data to Parquet only, never to PG. Analytics that need
long history read PG ∪ Parquet via DuckDB.

Output layout (partitioned by year/month)::

    data/parquet/daily_prices_archive/
      year=2004/month=01/day=02.parquet
      year=2004/month=01/day=05.parquet
      ...

Each day is one parquet file. Idempotent — re-runs skip existing days
listed in `_manifest.jsonl`. Trading-holidays are detected as HTTP 404
and recorded with status=holiday (still counts as "done", won't retry).

Usage
-----
    python scripts/backfill_bhavcopy_parquet_archive.py
    python scripts/backfill_bhavcopy_parquet_archive.py --start 2004-01-01 --end 2015-12-31
    python scripts/backfill_bhavcopy_parquet_archive.py --sleep 0.5 --force
    python scripts/backfill_bhavcopy_parquet_archive.py --limit-days 50  # smoke test

Rate limits
-----------
archives.nseindia.com is a static CDN, no throttle observed at 0.5s
intervals across 5 sample dates per decade (verified 2026-04-20).

Estimated runtime at default 0.5s sleep: ~35-45 min for the full
2004-2015 range (~2,975 weekdays).

Volume estimate
---------------
Parquet-snappy, EQ series only: ~90-130 MB total for 12 years.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from datetime import date, timedelta
from pathlib import Path

try:
    import pandas as pd
    import pyarrow as pa
    import pyarrow.parquet as pq
except ImportError:
    print("pip install pandas pyarrow", file=sys.stderr)
    sys.exit(2)

# Add repo root to path so data_pipeline imports work
_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from data_pipeline.sources.nse_bhavcopy_legacy import (  # type: ignore
    _get_nse_session,
    download_bhavcopy_legacy_with_status,
)


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("bhav_parquet_archive")


DEFAULT_OUT = _REPO / "data" / "parquet" / "daily_prices_archive"
DEFAULT_START = date(2004, 1, 1)
DEFAULT_END = date(2015, 12, 31)
# Never try dates past this — the PG live table owns 2016+.
HARD_MAX = date(2015, 12, 31)


def _iter_weekdays(start: date, end: date):
    d = start
    one_day = timedelta(days=1)
    while d <= end:
        if d.weekday() < 5:  # 0=Mon .. 4=Fri
            yield d
        d += one_day


def _partition_path(out_root: Path, d: date) -> Path:
    return out_root / f"year={d.year}" / f"month={d.month:02d}" / f"day={d.day:02d}.parquet"


def _load_manifest(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with path.open("r", encoding="utf-8") as fp:
        for line in fp:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
                out[rec["date"]] = rec
            except Exception:
                pass
    return out


def _append_manifest(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fp:
        fp.write(json.dumps(rec, default=str) + "\n")


def _write_parquet(df: pd.DataFrame, out_file: Path) -> int:
    out_file.parent.mkdir(parents=True, exist_ok=True)
    t = pa.Table.from_pandas(df, preserve_index=False)
    pq.write_table(t, str(out_file), compression="snappy")
    return out_file.stat().st_size


def _fetch_one(trade_date: date, session, retries: int = 3):
    """Returns (df_or_none, status, http_code). status in {ok,holiday,throttle,error}."""
    last_exc = None
    last_code = 0
    for attempt in range(retries):
        try:
            df, code = download_bhavcopy_legacy_with_status(trade_date, session=session)
            last_code = code
            if code == 404:
                return None, "holiday", 404
            if code == 200 and df is not None and len(df) > 0:
                return df, "ok", 200
            if code == 200 and (df is None or len(df) == 0):
                return None, "holiday", 200
            # 403 / 5xx / 0 — transient, retry with backoff
            sleep = 5 * (attempt + 1)
            logger.warning("  %s HTTP %d — retry in %ds", trade_date, code, sleep)
            time.sleep(sleep)
        except Exception as exc:
            last_exc = exc
            sleep = 2 ** (attempt + 1)
            logger.warning("  %s attempt %d error: %s (sleep %ds)", trade_date, attempt + 1, exc, sleep)
            time.sleep(sleep)
    if last_code in (403, 429):
        return None, "throttle", last_code
    logger.error("  %s exhausted retries: code=%d exc=%s", trade_date, last_code, last_exc)
    return None, "error", last_code


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", default=DEFAULT_START.isoformat())
    ap.add_argument("--end", default=DEFAULT_END.isoformat())
    ap.add_argument("--out", default=str(DEFAULT_OUT))
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="Sleep between requests, seconds (default 0.5)")
    ap.add_argument("--force", action="store_true",
                    help="Re-fetch even if manifest says already done")
    ap.add_argument("--limit-days", type=int, default=None,
                    help="Max days to process (smoke test)")
    ap.add_argument("--session-recycle", type=int, default=500,
                    help="Recycle NSE session every N requests (default 500)")
    args = ap.parse_args()

    start = date.fromisoformat(args.start)
    end = min(date.fromisoformat(args.end), HARD_MAX)
    if start > end:
        logger.error("start %s > end %s", start, end)
        return 2

    out_root = Path(args.out)
    out_root.mkdir(parents=True, exist_ok=True)
    manifest_path = out_root / "_manifest.jsonl"
    manifest = _load_manifest(manifest_path)

    logger.info("range: %s → %s", start, end)
    logger.info("out:   %s", out_root)
    logger.info("sleep: %.2fs  recycle: %d  force: %s",
                args.sleep, args.session_recycle, args.force)
    logger.info("manifest has %d prior entries", len(manifest))

    session = _get_nse_session()

    stats = {"ok": 0, "holiday": 0, "throttle": 0, "error": 0, "skip": 0, "rows": 0, "bytes": 0}
    processed = 0
    t0 = time.time()

    for trade_date in _iter_weekdays(start, end):
        dstr = trade_date.isoformat()

        # Skip if already done
        if not args.force and dstr in manifest:
            prev = manifest[dstr]
            if prev.get("status") in ("ok", "holiday"):
                stats["skip"] += 1
                continue

        out_file = _partition_path(out_root, trade_date)
        if not args.force and out_file.exists():
            # File exists but no manifest entry — heal manifest and skip
            _append_manifest(manifest_path, {
                "date": dstr, "status": "ok", "healed": True,
            })
            stats["skip"] += 1
            continue

        df, status, code = _fetch_one(trade_date, session)

        rec = {
            "date": dstr,
            "status": status,
            "http_code": code,
            "ts": time.time(),
        }

        if status == "ok" and df is not None and len(df) > 0:
            size = _write_parquet(df, out_file)
            rec["rows"] = int(len(df))
            rec["bytes"] = int(size)
            rec["path"] = str(out_file.relative_to(_REPO))
            stats["ok"] += 1
            stats["rows"] += len(df)
            stats["bytes"] += size
            if stats["ok"] % 25 == 0:
                elapsed = time.time() - t0
                rate = stats["ok"] / max(elapsed, 1.0)
                logger.info(
                    "  progress: ok=%d holiday=%d err=%d skip=%d | %.2f/s | last=%s",
                    stats["ok"], stats["holiday"], stats["error"], stats["skip"],
                    rate, dstr,
                )
        elif status == "holiday":
            stats["holiday"] += 1
        elif status == "throttle":
            stats["throttle"] += 1
            # Throttle backoff: pause 60s, recycle session, don't write manifest (will retry next run)
            logger.warning("  throttled (HTTP %d) — pausing 60s and recycling session", code)
            time.sleep(60)
            session = _get_nse_session()
            continue
        else:
            stats["error"] += 1

        _append_manifest(manifest_path, rec)
        processed += 1

        # Session recycle to flush stale cookies
        if processed % args.session_recycle == 0:
            logger.info("  session recycle after %d requests", processed)
            session = _get_nse_session()

        if args.limit_days is not None and processed >= args.limit_days:
            logger.info("  limit-days %d reached — stopping", args.limit_days)
            break

        time.sleep(args.sleep)

    elapsed = time.time() - t0
    logger.info("DONE in %.1f min", elapsed / 60)
    logger.info(
        "  ok=%d holiday=%d throttle=%d error=%d skip=%d  rows=%d  parquet=%.1fMB",
        stats["ok"], stats["holiday"], stats["throttle"], stats["error"], stats["skip"],
        stats["rows"], stats["bytes"] / 1e6,
    )
    return 0 if stats["error"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
