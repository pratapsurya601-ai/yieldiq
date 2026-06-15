"""AMFI daily NAV ingest.

Source: https://www.amfiindia.com/spages/NAVAll.txt

The NAVAll.txt feed is pipe-delimited text grouped by AMC. Each AMC
section opens with a header line (the AMC name), then a column-name
line, then one row per scheme, separated by blank lines. The layout
is essentially:

    ;        Open Ended Schemes ( Equity Scheme - Large Cap Fund )

    Aditya Birla Sun Life Mutual Fund

    Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
    100033;INF209K01157;INF209K01165;Aditya Birla Sun Life Frontline Equity Fund - Growth - Regular Plan;485.7234;27-May-2026
    ...

This module:

    fetch_navall_text(session=None) -> str
        Download the raw text. Handles non-UTF8 encoding gracefully.

    parse_navall(text) -> Iterator[dict]
        Yield one dict per scheme row. Skips header/category lines,
        blank-NAV rows (holiday-published schemes), and malformed
        rows. Each dict has: scheme_code, isin_div, isin_growth,
        scheme_name, nav, nav_date.

    upsert_nav_rows(rows, conn) -> int
        Bulk UPSERT into fund_nav_history keyed on (scheme_code,
        nav_date). Idempotent.

    main()
        CLI entry point — fetches today's snapshot and upserts.
        Invoked by cron-mf-nav-daily.yml.

Discipline notes:
    * No CACHE_VERSION bump — this is pure ingest, no derived data.
    * Backfill (10y history) is a separate operator-run script
      (scripts/backfill_mf_nav.py); this module is for the daily
      delta only.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, datetime
from typing import Iterable, Iterator

logger = logging.getLogger(__name__)

NAVALL_URL = "https://www.amfiindia.com/spages/NAVAll.txt"

# Row format AMFI has published since at least 2010.
_EXPECTED_COL_COUNT = 6


# ── HTTP fetch ───────────────────────────────────────────────────────


def fetch_navall_text(url: str = NAVALL_URL, timeout: int = 60) -> str:
    """Download NAVAll.txt and return its text body.

    AMFI occasionally serves the file with a non-UTF8 byte (legacy
    Windows-1252 encoded scheme names with curly quotes). We decode
    with errors='replace' so a single bad byte does not abort the
    entire ingest — the affected scheme_name lands with a replacement
    character but the numeric NAV is unaffected.
    """
    import requests
    r = requests.get(url, timeout=timeout)
    r.raise_for_status()
    # Try UTF-8 first; fall back to cp1252 (AMFI's legacy encoding) on
    # decode failure. The third try is utf-8 with replacement so we
    # never raise on a single bad byte.
    raw = r.content
    for enc in ("utf-8", "cp1252"):
        try:
            return raw.decode(enc)
        except UnicodeDecodeError:
            continue
    return raw.decode("utf-8", errors="replace")


# ── Parsing ─────────────────────────────────────────────────────────


def _parse_amfi_date(s: str) -> date | None:
    """Parse AMFI's '27-May-2026' format. Returns None on malformed input."""
    s = (s or "").strip()
    if not s:
        return None
    for fmt in ("%d-%b-%Y", "%d-%B-%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    return None


def _safe_float(s: str) -> float | None:
    """Parse a NAV value. Returns None for blanks, 'N.A.', or non-numeric."""
    s = (s or "").strip()
    if not s or s.upper() in ("N.A.", "N/A", "NA", "-"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    # AMFI never publishes negative or zero NAV legitimately; treat
    # both as missing (holiday placeholder).
    if v <= 0:
        return None
    return v


def parse_navall(text: str) -> Iterator[dict]:
    """Yield one scheme dict per data row of an AMFI NAVAll text body.

    Skips:
      * Empty lines (section separators).
      * Lines that don't have the expected 6 pipe-delimited fields
        (AMC headers, category headers, the column-name line itself).
      * Rows where NAV is blank / non-numeric / <= 0 — these are
        holiday placeholders for schemes that did not publish a NAV
        for that day, common for some debt schemes with T+1 NAV.
      * Rows where the date does not parse.

    The caller decides what to do with each yielded dict — typically
    pass them straight to upsert_nav_rows.
    """
    for raw in text.splitlines():
        line = raw.strip()
        if not line:
            continue
        if "|" not in line and ";" not in line:
            continue
        # AMFI uses ';' as the field separator. The header section
        # opener also contains ';' but starts with a leading ';' which
        # means the first field is blank — filter those out by
        # requiring a numeric scheme code.
        parts = line.split(";")
        if len(parts) != _EXPECTED_COL_COUNT:
            continue
        scheme_code = parts[0].strip()
        if not scheme_code.isdigit():
            # Header row ('Scheme Code;ISIN Div Payout/...') or AMC
            # banner — silently skip.
            continue
        # AMFI column order is:
        #   parts[1] = "ISIN Div Payout/ ISIN Growth" — the primary ISIN,
        #              which carries the Growth ISIN for Growth schemes.
        #   parts[2] = "ISIN Div Reinvestment" — a literal "-" for
        #              Growth-only schemes.
        isin_growth = parts[1].strip() or None
        isin_div    = parts[2].strip() or None
        scheme_name = parts[3].strip()
        nav         = _safe_float(parts[4])
        nav_date    = _parse_amfi_date(parts[5])
        if nav is None or nav_date is None:
            continue
        yield {
            "scheme_code": scheme_code,
            "isin_div":    isin_div,
            "isin_growth": isin_growth,
            "scheme_name": scheme_name,
            "nav":         nav,
            "nav_date":    nav_date,
        }


# ── Persistence ─────────────────────────────────────────────────────

# Batched via psycopg2.extras.execute_values (VALUES %s). The daily file
# is ~14k rows and a single backfilled scheme carries years of daily NAV
# (~2.5k rows), so the old row-by-row executemany blew the workflow
# timeout — the daily ingest cron was being cancelled mid-run, leaving
# fund_nav_history empty. The whole batch now lands in a few multi-row
# INSERTs instead of thousands of single-row round-trips.
UPSERT_SQL = """
INSERT INTO fund_nav_history (scheme_code, nav_date, nav)
VALUES %s
ON CONFLICT (scheme_code, nav_date) DO UPDATE SET
    nav = EXCLUDED.nav
"""

UPSERT_TEMPLATE = "(%(scheme_code)s, %(nav_date)s, %(nav)s)"


def upsert_nav_rows(rows: Iterable[dict], conn) -> int:
    """Bulk UPSERT NAV rows using a raw psycopg2 connection.

    Returns the count of rows written. Idempotent on (scheme_code,
    nav_date) — re-running the same day's ingest is a no-op aside from
    refreshing the NAV value if AMFI corrected it. Rows are deduped on
    (scheme_code, nav_date) keeping the last value, so a single multi-row
    VALUES batch can't trip "ON CONFLICT ... cannot affect row a second
    time" on a duplicate date in the feed.
    """
    by_key: dict[tuple, dict] = {}
    for r in rows:
        by_key[(r["scheme_code"], r["nav_date"])] = r
    deduped = list(by_key.values())
    if not deduped:
        return 0
    # Lazy import so parse-only callers / tests don't require psycopg2.
    from psycopg2.extras import execute_values

    with conn.cursor() as cur:
        execute_values(
            cur, UPSERT_SQL, deduped,
            template=UPSERT_TEMPLATE, page_size=1000,
        )
    conn.commit()
    return len(deduped)


# ── CLI ─────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--url", default=NAVALL_URL,
                   help="Override the AMFI NAVAll endpoint (test fixture).")
    p.add_argument("--dry-run", action="store_true",
                   help="Parse only; do not write to DB.")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    text = fetch_navall_text(args.url)
    rows = list(parse_navall(text))
    logger.info("amfi_nav: parsed %d rows from %s", len(rows), args.url)

    if args.dry_run:
        return 0

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        return 2
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]

    import psycopg2
    conn = psycopg2.connect(db_url)
    try:
        n = upsert_nav_rows(rows, conn)
        logger.info("amfi_nav: upserted %d rows", n)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
