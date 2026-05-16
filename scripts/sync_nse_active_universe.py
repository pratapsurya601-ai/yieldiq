"""sync_nse_active_universe.py
================================

Weekly maintenance script that compares the YieldIQ ``stocks`` table against the
NSE EQUITY_L.csv master and reports tickers that are active in our DB but no
longer listed on NSE (delisted / suspended / renamed).

Why this exists
---------------
Without periodic reconciliation, stale tickers accumulate in the active universe
and cause:

* Backfill workers spending cycles on symbols that 404 on yfinance / NSE / BSE
* Validator floods in Sentry (one bad ticker can emit 10k+ events / day)
* 404s on the public ``/og-data`` endpoint when stale links are shared

Usage
-----

Report only (default, read-only)::

    python scripts/sync_nse_active_universe.py

Apply the deactivation (sets ``is_active = FALSE`` for stale rows)::

    python scripts/sync_nse_active_universe.py --apply

Write the stale list to a CSV report::

    python scripts/sync_nse_active_universe.py --report reports/stale_$(date +%F).csv

The script is safe to run from a GitHub Actions weekly cron. It exits non-zero
only on hard failures (DB / NSE fetch). In ``--apply`` mode the deactivation
runs inside a single transaction.
"""

from __future__ import annotations

import argparse
import csv
import io
import logging
import os
import sys
from typing import Iterable, Set

logger = logging.getLogger("sync_nse_active_universe")

NSE_EQUITY_L_URL = (
    "https://nsearchives.nseindia.com/content/equities/EQUITY_L.csv"
)
NSE_HOMEPAGE_URL = "https://www.nseindia.com/"


def fetch_nse_active_symbols() -> Set[str]:
    """Return the set of SYMBOL values from NSE's EQUITY_L.csv master.

    Prefers ``curl_cffi`` (handles Akamai TLS fingerprinting) and falls back to
    a ``requests`` session that warms up the homepage cookie first.
    """

    try:
        from curl_cffi import requests as creq  # type: ignore

        resp = creq.get(
            NSE_EQUITY_L_URL, impersonate="chrome120", timeout=30
        )
        if resp.status_code == 200 and "SYMBOL" in resp.text[:200]:
            return _parse_symbols(resp.text)
        logger.warning(
            "curl_cffi returned status=%s (len=%s); falling back to requests",
            resp.status_code,
            len(resp.text),
        )
    except Exception as exc:  # pragma: no cover - network path
        logger.warning("curl_cffi unavailable or failed: %s", exc)

    import requests

    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            "Accept": "*/*",
            "Accept-Language": "en-US,en;q=0.9",
            "Referer": NSE_HOMEPAGE_URL,
        }
    )
    # Warm cookies, NSE blocks bare archive hits otherwise.
    session.get(NSE_HOMEPAGE_URL, timeout=15)
    resp = session.get(NSE_EQUITY_L_URL, timeout=30)
    resp.raise_for_status()
    return _parse_symbols(resp.text)


def _parse_symbols(csv_text: str) -> Set[str]:
    """Extract the SYMBOL column from EQUITY_L.csv text."""
    reader = csv.DictReader(io.StringIO(csv_text))
    if "SYMBOL" not in (reader.fieldnames or []):
        raise ValueError(
            f"EQUITY_L.csv missing SYMBOL column; got fields={reader.fieldnames}"
        )
    return {row["SYMBOL"].strip() for row in reader if row.get("SYMBOL")}


def fetch_db_active_tickers(database_url: str) -> Set[str]:
    """Return the set of tickers where ``stocks.is_active = TRUE``."""
    import psycopg2

    conn = psycopg2.connect(database_url)
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT ticker FROM stocks WHERE is_active = TRUE")
            return {row[0] for row in cur.fetchall()}
    finally:
        conn.close()


def compute_stale(
    db_active: Set[str], nse_active: Set[str]
) -> Set[str]:
    """Tickers present in our DB but missing from the NSE active master."""
    return db_active - nse_active


def deactivate(database_url: str, tickers: Iterable[str]) -> int:
    """Set ``is_active = FALSE`` for the given tickers. Returns rows updated."""
    import psycopg2

    tickers_list = sorted(set(tickers))
    if not tickers_list:
        return 0

    conn = psycopg2.connect(database_url)
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    UPDATE stocks
                       SET is_active = FALSE
                     WHERE is_active = TRUE
                       AND ticker = ANY(%s)
                    """,
                    (tickers_list,),
                )
                return cur.rowcount
    finally:
        conn.close()


def write_report(path: str, stale: Iterable[str]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["ticker", "status"])
        for ticker in sorted(stale):
            writer.writerow([ticker, "stale_not_on_nse_master"])


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Set is_active=FALSE for stale tickers (default: report only).",
    )
    parser.add_argument(
        "--report",
        default=None,
        help="Write the stale ticker list to this CSV path.",
    )
    parser.add_argument(
        "--env-file",
        default=".env.local",
        help="dotenv file to load DATABASE_URL from (default: .env.local).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    args = parse_args(argv)

    if args.env_file and os.path.exists(args.env_file):
        from dotenv import load_dotenv

        load_dotenv(args.env_file, override=True)

    database_url = os.environ.get("DATABASE_URL")
    if not database_url:
        logger.error("DATABASE_URL not set (env-file=%s)", args.env_file)
        return 2

    logger.info("Fetching NSE EQUITY_L master...")
    nse_active = fetch_nse_active_symbols()
    logger.info("NSE active symbols: %d", len(nse_active))

    logger.info("Fetching DB active tickers...")
    db_active = fetch_db_active_tickers(database_url)
    logger.info("DB active tickers: %d", len(db_active))

    stale = compute_stale(db_active, nse_active)
    logger.info("Stale (in DB, not on NSE): %d", len(stale))
    for ticker in sorted(stale):
        logger.info("  stale: %s", ticker)

    if args.report:
        write_report(args.report, stale)
        logger.info("Wrote report: %s", args.report)

    if args.apply and stale:
        updated = deactivate(database_url, stale)
        logger.info("Deactivated %d rows", updated)
    elif args.apply:
        logger.info("Nothing to deactivate")
    else:
        logger.info("Dry run; pass --apply to deactivate")

    return 0


if __name__ == "__main__":
    sys.exit(main())
