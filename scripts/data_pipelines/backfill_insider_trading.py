"""Backfill 10y of NSE insider-trading (SEBI PIT Reg 7) disclosures.

Strategy: iterate calendar years 2015..present. Each year is one big
NSE call (~13 MB JSON for a busy year, ~100K-300K total rows expected
across the decade). We bulk-UPSERT into ``insider_trading`` keyed on
(ticker, filing_date, acquirer_name, buy_qty, sell_qty) — same as
the migration's UNIQUE constraint, so re-running is idempotent.

No analysis math touched — purely additive data ingest.
"""
from __future__ import annotations

import argparse
import logging
import sys
import time
from datetime import datetime

from data_pipeline.sources.nse_insider_trading import (
    fetch_insider_trading_for_year,
    _get_session,
)
from scripts.data_pipelines._common import (
    get_database_url,
    setup_logging,
)

logger = logging.getLogger("backfill_insider_trading")


UPSERT_SQL = """
INSERT INTO insider_trading (
    ticker, isin, filing_date, acquirer_name, acquirer_category,
    transaction_type, buy_qty, sell_qty, transaction_value_cr,
    holding_before_pct, holding_after_pct, annex_type, pdf_url
) VALUES (
    %(ticker)s, %(isin)s, %(filing_date)s, %(acquirer_name)s, %(acquirer_category)s,
    %(transaction_type)s, %(buy_qty)s, %(sell_qty)s, %(transaction_value_cr)s,
    %(holding_before_pct)s, %(holding_after_pct)s, %(annex_type)s, %(pdf_url)s
)
ON CONFLICT (ticker, filing_date, acquirer_name, buy_qty, sell_qty)
DO UPDATE SET
    isin = COALESCE(EXCLUDED.isin, insider_trading.isin),
    acquirer_category = COALESCE(EXCLUDED.acquirer_category, insider_trading.acquirer_category),
    transaction_type = COALESCE(EXCLUDED.transaction_type, insider_trading.transaction_type),
    transaction_value_cr = COALESCE(EXCLUDED.transaction_value_cr, insider_trading.transaction_value_cr),
    holding_before_pct = COALESCE(EXCLUDED.holding_before_pct, insider_trading.holding_before_pct),
    holding_after_pct = COALESCE(EXCLUDED.holding_after_pct, insider_trading.holding_after_pct),
    annex_type = COALESCE(EXCLUDED.annex_type, insider_trading.annex_type),
    pdf_url = COALESCE(EXCLUDED.pdf_url, insider_trading.pdf_url)
"""


def _upsert_rows(conn, rows: list[dict]) -> int:
    if not rows:
        return 0
    written = 0
    with conn.cursor() as cur:
        # psycopg2.extras.execute_batch would be faster, but execute() in
        # a loop is fine for ~10-30K rows/year and avoids a new import.
        for row in rows:
            try:
                cur.execute(UPSERT_SQL, row)
                written += 1
            except Exception as exc:
                logger.debug("skip row %s/%s: %s", row.get("ticker"), row.get("filing_date"), exc)
                conn.rollback()
                continue
    conn.commit()
    return written


def run(start_year: int, end_year: int, dry_run: bool = False) -> int:
    setup_logging()
    import psycopg2

    session = _get_session()
    total = 0
    if dry_run:
        for y in range(start_year, end_year + 1):
            rows = fetch_insider_trading_for_year(y, session=session)
            logger.info("[dry-run] %d -> %d rows (sample %s)", y, len(rows), rows[:1])
            total += len(rows)
            time.sleep(2.0)
        return total

    conn = psycopg2.connect(get_database_url())
    try:
        for y in range(start_year, end_year + 1):
            rows = fetch_insider_trading_for_year(y, session=session)
            written = _upsert_rows(conn, rows)
            logger.info("year=%d fetched=%d upserted=%d", y, len(rows), written)
            total += written
            # Be polite to NSE between massive year-pulls.
            time.sleep(2.0)
    finally:
        conn.close()
    return total


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-year", type=int, default=2015)
    parser.add_argument("--end-year", type=int, default=datetime.utcnow().year)
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args(argv)
    n = run(args.start_year, args.end_year, dry_run=args.dry_run)
    logger.info("insider-trading backfill complete: %d rows", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
