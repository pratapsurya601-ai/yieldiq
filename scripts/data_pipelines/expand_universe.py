"""Expand the YieldIQ stock universe from ~3,005 to 5,000+ tickers.

Pulls three rosters and inserts/activates rows in the ``stocks`` table:

  1. NSE main board     (EQUITY_L.csv,        ~2,360 rows)
  2. NSE SME (Emerge)   (NIFTY SME EMERGE,     ~514 rows)
  3. BSE main board     (BSE bhavcopy A/B/X, ~4,800 rows pre-dedup)

Dedup rules (in order):

  - existing rows by ticker:    leave them alone (UPDATE only if currently
                                inactive, to flip is_active back to TRUE)
  - existing rows by ISIN:      treat as duplicate; do NOT insert a second
                                ticker row (NSE symbol always wins over BSE)
  - ticker collision (BSE-only):append ``.BO`` suffix per yfinance
                                convention, matching the policy already in
                                scripts/ingest_bse_only_universe.py

Cache discipline (per the data-fix discipline doc):

  This is a pure data-layer expansion of the ``stocks`` table. No
  scoring, validators, services, routers, or DCF math is touched. New
  tickers will compute fresh on first analysis request via the existing
  v76 cache key — no CACHE_VERSION bump needed.

Usage
-----
    python scripts/data_pipelines/expand_universe.py
    python scripts/data_pipelines/expand_universe.py --dry-run
    python scripts/data_pipelines/expand_universe.py --skip-bse  # NSE only
    python scripts/data_pipelines/expand_universe.py --skip-sme

Requires DATABASE_URL.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from data_pipeline.sources import nse_total_market, bse_securities_master  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("expand_universe")


def _engine():
    from sqlalchemy import create_engine
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise RuntimeError("DATABASE_URL not set")
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url, pool_pre_ping=True)


def _load_existing(engine):
    from sqlalchemy import text
    with engine.connect() as c:
        ticker_rows = c.execute(text(
            "SELECT ticker, isin, is_active FROM stocks"
        )).fetchall()
    by_ticker = {r[0].upper(): {"isin": (r[1] or None), "is_active": bool(r[2])}
                 for r in ticker_rows if r[0]}
    by_isin = {r[1].upper(): r[0].upper() for r in ticker_rows if r[1]}
    return by_ticker, by_isin


def _insert_rows(engine, rows: list[dict], batch_size: int = 500) -> int:
    from sqlalchemy import text
    if not rows:
        return 0
    inserted = 0
    with engine.begin() as conn:
        for i in range(0, len(rows), batch_size):
            chunk = rows[i:i + batch_size]
            result = conn.execute(text("""
                INSERT INTO stocks (
                    ticker, ticker_ns, company_name, isin, series, bse_code,
                    listed_date, is_active
                ) VALUES (
                    :ticker, :ticker_ns, :company_name, :isin, :series, :bse_code,
                    :listed_date, TRUE
                )
                ON CONFLICT (ticker) DO NOTHING
            """), chunk)
            inserted += result.rowcount or 0
    return inserted


def _reactivate(engine, tickers: list[str]) -> int:
    from sqlalchemy import text
    if not tickers:
        return 0
    with engine.begin() as conn:
        r = conn.execute(text("""
            UPDATE stocks SET is_active = TRUE, updated_at = now()
             WHERE ticker = ANY(:tickers) AND is_active = FALSE
        """), {"tickers": tickers})
    return r.rowcount or 0


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--dry-run", action="store_true",
                    help="Report counts only; don't write to DB")
    ap.add_argument("--skip-sme", action="store_true",
                    help="Skip the NIFTY SME EMERGE roster")
    ap.add_argument("--skip-bse", action="store_true",
                    help="Skip the BSE securities master")
    ap.add_argument("--skip-nse", action="store_true",
                    help="Skip the NSE main-board roster")
    args = ap.parse_args()

    if not args.dry_run and not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL not set")
        return 2

    # ── Step 1: pull rosters ─────────────────────────────────────────
    nse_main: list[dict] = []
    nse_sme: list[dict] = []
    bse_main: list[dict] = []

    if not args.skip_nse or not args.skip_sme:
        sess = nse_total_market._session()
        if not args.skip_nse:
            nse_main = nse_total_market.fetch_main_board(sess)
        if not args.skip_sme:
            nse_sme = nse_total_market.fetch_sme_emerge(sess)

    if not args.skip_bse:
        bse_main = bse_securities_master.fetch_securities_master()

    logger.info(
        "rosters: NSE-main=%d  NSE-SME=%d  BSE-main=%d",
        len(nse_main), len(nse_sme), len(bse_main),
    )

    if args.dry_run and not os.environ.get("DATABASE_URL"):
        logger.info("--dry-run + no DATABASE_URL → reporting roster sizes only.")
        print(f"NSE main: {len(nse_main)}")
        print(f"NSE SME:  {len(nse_sme)}")
        print(f"BSE main: {len(bse_main)}")
        return 0

    engine = _engine()
    by_ticker, by_isin = _load_existing(engine)
    logger.info("DB has %d existing tickers (%d with ISIN)",
                len(by_ticker), len(by_isin))

    # ── Step 2: build candidate rows (NSE main first, SME, then BSE) ─
    new_rows: list[dict] = []
    seen_new: set[str] = set()
    reactivate: list[str] = []
    skipped_existing = 0
    skipped_isin_dup = 0
    bse_collisions = 0

    def _accept(row: dict, *, allow_bse_suffix: bool = False):
        nonlocal bse_collisions, skipped_existing, skipped_isin_dup
        ticker = row["ticker"].upper()
        isin = (row.get("isin") or "").upper() or None

        # 1. ticker already in DB
        if ticker in by_ticker:
            existing = by_ticker[ticker]
            if not existing["is_active"]:
                reactivate.append(ticker)
            skipped_existing += 1
            return

        # 2. ISIN already mapped to a different ticker
        if isin and isin in by_isin:
            skipped_isin_dup += 1
            return

        # 3. ticker collision against another roster row we just queued
        final_ticker = ticker
        if final_ticker in seen_new:
            if allow_bse_suffix and row.get("exchange") == "BSE":
                final_ticker = f"{ticker}.BO"
                bse_collisions += 1
                if final_ticker in by_ticker or final_ticker in seen_new:
                    final_ticker = f"{ticker}.{row.get('bse_code') or ''}"
            else:
                skipped_existing += 1
                return
        # Also collide against existing DB tickers for BSE .BO fallback.
        if allow_bse_suffix and row.get("exchange") == "BSE" and final_ticker == ticker and ticker in by_ticker:
            # Already handled above, but this branch covers the suffix case
            # where ticker is in by_ticker but we already skipped it.
            return

        seen_new.add(final_ticker)
        new_rows.append({
            "ticker":       final_ticker,
            "ticker_ns":    f"{ticker}.NS" if row.get("exchange") == "NSE" else f"{ticker}.BO",
            "company_name": (row.get("name") or None) and row["name"][:200],
            "isin":         isin,
            "series":       row.get("series"),
            "bse_code":     row.get("bse_code"),
            "listed_date":  row.get("listing_date"),
        })
        if isin:
            by_isin[isin] = final_ticker

    for r in nse_main:
        _accept(r)
    for r in nse_sme:
        _accept(r)
    for r in bse_main:
        _accept(r, allow_bse_suffix=True)

    logger.info(
        "candidates: %d new  |  %d already in DB  |  %d ISIN-dups skipped  |  "
        "%d BSE ticker collisions resolved with .BO suffix  |  "
        "%d existing rows to re-activate",
        len(new_rows), skipped_existing, skipped_isin_dup, bse_collisions,
        len(reactivate),
    )

    if args.dry_run:
        logger.info("--dry-run — no writes. Sample new rows:")
        for r in new_rows[:5]:
            logger.info("  %s", r)
        return 0

    # ── Step 3: write ────────────────────────────────────────────────
    inserted = _insert_rows(engine, new_rows)
    logger.info("INSERT complete: %d new rows", inserted)
    reactivated = _reactivate(engine, reactivate)
    logger.info("UPDATE complete: %d rows re-activated", reactivated)

    # ── Step 4: final counts ─────────────────────────────────────────
    from sqlalchemy import text
    with engine.connect() as c:
        active = c.execute(text("SELECT COUNT(*) FROM stocks WHERE is_active")).scalar()
        with_industry = c.execute(text(
            "SELECT COUNT(*) FROM stocks WHERE is_active AND industry IS NOT NULL"
        )).scalar()
        with_bse = c.execute(text(
            "SELECT COUNT(*) FROM stocks WHERE is_active AND bse_code IS NOT NULL"
        )).scalar()

    print()
    print("=" * 60)
    print(f"Universe expansion summary (run @ now):")
    print("=" * 60)
    print(f"  Total NSE main:              {len(nse_main)}")
    print(f"  Total NSE SME:               {len(nse_sme)}")
    print(f"  Total BSE-only candidates:   {len(bse_main)}")
    print(f"  Already in DB (skipped):     {skipped_existing}")
    print(f"  ISIN duplicates skipped:     {skipped_isin_dup}")
    print(f"  BSE ticker collisions (.BO): {bse_collisions}")
    print(f"  New rows added:              {inserted}")
    print(f"  Existing rows re-activated:  {reactivated}")
    print(f"  ----")
    print(f"  Active total now:            {active}")
    print(f"    of which have bse_code:    {with_bse}")
    print(f"    of which have industry:    {with_industry}")
    print("=" * 60)
    return 0


if __name__ == "__main__":
    sys.exit(main())
