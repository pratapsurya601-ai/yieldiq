"""
ingest_bulk_block_deals.py — STUB scraper for NSE + BSE bulk/block deals.

Status: scaffolding only. The actual fetch is left as `# TODO: actual
fetch` because NSE has anti-bot measures (curl_cffi + cookie priming
required) that deserve a careful, isolated session and rate-limiting
review. See docs/insider_activity_design.md for the plan.

Existing live ingest:
    data_pipeline/sources/nse_bulk_deals.py — already pulls NSE bulk +
    block deals into the LEGACY `bulk_deals` ORM table. The shape
    differs from the canonical `bulk_block_deals` schema in
    backend/migrations/016_create_insider_activity.sql; the migration
    plan documents how to fold the legacy rows in.

Sources documented here:

NSE bulk deals
    https://www.nseindia.com/api/historical/bulk-deals
    Live current-day list (used by data_pipeline/sources/nse_bulk_deals):
        https://www.nseindia.com/api/bulk-deals?type=bulk
    Refresh: daily after 18:30 IST (post-market close).
    Auth: requires NSE session cookies. Use curl_cffi with
    impersonate="chrome" — see _get_nse_session() in nse_bulk_deals.py.
    Anti-bot: hard rate-limits. Warm session by GETting nseindia.com
    homepage first, then the corporate-filings page.

NSE block deals
    https://www.nseindia.com/api/historical/block-deals
    Same auth/anti-bot regime as bulk deals.

BSE bulk + block deals
    https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx
    https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx
    Returns HTML pages — parse with bs4 or fall back to the JSON
    endpoint at /BseIndiaAPI/api/BulkDealsList/w (undocumented; subject
    to change).
    Refresh: daily after 18:00 IST.
    Auth: less strict than NSE; standard Mozilla UA usually works.

Run:
    python scripts/ingest_bulk_block_deals.py [--dry-run]

Idempotency:
    UPSERT keyed on UNIQUE (ticker, deal_date, exchange, client_name,
    buy_sell, quantity). Re-running the same day is safe.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from typing import Any, Dict, List

logger = logging.getLogger("yieldiq.ingest.bulk_block")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


NSE_BULK_URL = "https://www.nseindia.com/api/historical/bulk-deals"
NSE_BLOCK_URL = "https://www.nseindia.com/api/historical/block-deals"
BSE_BULK_URL = "https://www.bseindia.com/markets/equity/EQReports/bulk_deals.aspx"
BSE_BLOCK_URL = "https://www.bseindia.com/markets/equity/EQReports/block_deals.aspx"


# ---------------------------------------------------------------------------
# Fetch stubs
# ---------------------------------------------------------------------------


def fetch_nse_bulk(target: date) -> List[Dict[str, Any]]:
    """Returns rows shaped like bulk_block_deals columns."""
    # TODO: actual fetch — see data_pipeline/sources/nse_bulk_deals.py
    # for the working curl_cffi pattern. Migrate it here, normalize to
    # the canonical schema (deal_date, deal_type='bulk', exchange='NSE',
    # buy_sell in {'B','S'}).
    logger.info("STUB fetch_nse_bulk(target=%s) → returning []", target)
    return []


def fetch_nse_block(target: date) -> List[Dict[str, Any]]:
    # TODO: actual fetch.
    logger.info("STUB fetch_nse_block(target=%s) → returning []", target)
    return []


def fetch_bse_bulk(target: date) -> List[Dict[str, Any]]:
    # TODO: actual fetch — BSE returns HTML; use bs4 to parse the
    # bulk_deals.aspx table. Schema mapping documented in the module
    # docstring.
    logger.info("STUB fetch_bse_bulk(target=%s) → returning []", target)
    return []


def fetch_bse_block(target: date) -> List[Dict[str, Any]]:
    # TODO: actual fetch.
    logger.info("STUB fetch_bse_block(target=%s) → returning []", target)
    return []


# ---------------------------------------------------------------------------
# Idempotent UPSERT
# ---------------------------------------------------------------------------


UPSERT_SQL = """
INSERT INTO bulk_block_deals
    (ticker, deal_date, deal_type, client_name, buy_sell,
     quantity, price, exchange)
VALUES
    (:ticker, :deal_date, :deal_type, :client_name, :buy_sell,
     :quantity, :price, :exchange)
ON CONFLICT ON CONSTRAINT uq_bulk_block_deal DO UPDATE SET
    price = EXCLUDED.price,
    fetched_at = NOW();
"""


def upsert_rows(rows: List[Dict[str, Any]], *, dry_run: bool = False) -> int:
    """Upsert into bulk_block_deals. Returns count attempted.

    The DB connection is not wired into this stub — see
    backend/services/local_data_service.py for the existing
    SQLAlchemy session helper to re-use.
    """
    if not rows:
        return 0
    if dry_run:
        logger.info("[dry-run] would upsert %d rows", len(rows))
        return len(rows)
    # TODO: get a SQLAlchemy session and execute UPSERT_SQL.
    logger.warning(
        "upsert_rows: DB write path not wired. %d rows discarded.", len(rows)
    )
    return 0


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------


def main(argv: List[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    p.add_argument(
        "--dry-run", action="store_true",
        help="Don't write to DB; just log fetched row counts.",
    )
    p.add_argument(
        "--target-date", default=None,
        help="ISO date (YYYY-MM-DD); defaults to today.",
    )
    args = p.parse_args(argv)

    target = (
        date.fromisoformat(args.target_date) if args.target_date else date.today()
    )

    all_rows: List[Dict[str, Any]] = []
    for fn in (fetch_nse_bulk, fetch_nse_block, fetch_bse_bulk, fetch_bse_block):
        try:
            all_rows.extend(fn(target))
        except Exception as exc:  # noqa: BLE001
            logger.error("%s failed: %s", fn.__name__, exc)

    upsert_rows(all_rows, dry_run=args.dry_run)
    logger.info("done: %d rows for %s", len(all_rows), target)
    return 0


if __name__ == "__main__":
    sys.exit(main())
