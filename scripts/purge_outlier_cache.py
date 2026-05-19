"""Day-1 cache purge for benchmark-reconciliation outliers.

Why this exists: PR #377 (DCF-collapse safety net) and PR #378 (verdict
gate) only run when each ticker is re-analysed. Stocks still carrying
pre-deploy cache rows keep showing up in the daily outlier report. The
cleanest one-shot fix is to delete those rows — the next user visit (or
the nightly canary refresh) rebuilds with the new code paths.

Usage:
    $env:DATABASE_URL = '...'
    $env:YQ_API_BASE  = 'https://api.yieldiq.in'
    $env:YQ_COOKIE    = 'yieldiq_token=...'

    # Dry run — list rows that would be deleted, write nothing:
    python scripts/purge_outlier_cache.py --limit 500 --dry-run

    # Real run — DELETE FROM analysis_cache WHERE ticker IN (...):
    python scripts/purge_outlier_cache.py --limit 500
"""
from __future__ import annotations

import argparse
import os
import sys
from typing import Iterable

import requests
import sqlalchemy as sa


def _auth_headers(cookie_or_token: str) -> dict[str, str]:
    raw = (cookie_or_token or "").strip()
    token = raw
    if "=" in raw and not raw.lower().startswith("bearer "):
        first_eq = raw.index("=")
        token = raw[first_eq + 1 :].split(";")[0].strip()
    if raw.lower().startswith("bearer "):
        token = raw[7:].strip()
    if "=" in raw and not raw.lower().startswith("bearer "):
        cookie_hdr = raw
    else:
        cookie_hdr = f"yieldiq_token={token}"
    return {"Cookie": cookie_hdr, "Authorization": f"Bearer {token}"}


def _fetch_outliers(base: str, cookie: str, limit: int) -> list[str]:
    url = f"{base}/api/v1/admin/benchmark-outliers"
    r = requests.get(
        url,
        params={"limit": limit, "threshold": 0.30, "min_analysts": 3},
        headers=_auth_headers(cookie),
        timeout=30,
    )
    if r.status_code == 401:
        raise SystemExit("401 Unauthorized — refresh yieldiq_token and retry.")
    r.raise_for_status()
    rows = r.json().get("rows", [])
    return [row["ticker"] for row in rows if row.get("ticker")]


def main(argv: Iterable[str] | None = None) -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--limit", type=int, default=500)
    p.add_argument("--tickers", default=None, help="comma-separated subset")
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args(list(argv) if argv is not None else None)

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        print("error: DATABASE_URL not set", file=sys.stderr)
        return 2
    base = os.environ.get("YQ_API_BASE", "https://api.yieldiq.in").rstrip("/")
    cookie = os.environ.get("YQ_COOKIE", "")

    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        if not cookie:
            print("error: YQ_COOKIE not set (need to fetch outliers list)", file=sys.stderr)
            return 2
        print(f"fetching outliers from {base} (limit={args.limit})...")
        tickers = _fetch_outliers(base, cookie, args.limit)

    if not tickers:
        print("no tickers to purge")
        return 0

    print(f"purge target: {len(tickers)} tickers")
    eng = sa.create_engine(db_url, pool_pre_ping=True)

    # Inspect: how many rows exist for these tickers?
    with eng.connect() as conn:
        n_rows = conn.execute(
            sa.text("SELECT COUNT(*) FROM analysis_cache WHERE ticker = ANY(:t)"),
            {"t": tickers},
        ).scalar() or 0
        print(f"analysis_cache rows matching: {n_rows}")

    if args.dry_run:
        print("DRY RUN — no rows deleted. Re-run without --dry-run to purge.")
        return 0

    with eng.begin() as conn:
        result = conn.execute(
            sa.text("DELETE FROM analysis_cache WHERE ticker = ANY(:t)"),
            {"t": tickers},
        )
        deleted = result.rowcount
    print(f"DELETED {deleted} rows from analysis_cache")
    print("Next user visit (or nightly canary) will rebuild with new code.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
