"""
ingest_insider_txns.py — STUB scraper for SEBI Reg 7 / PIT insider filings.

Status: scaffolding only. `# TODO: actual fetch` everywhere. Real ingest
should reuse the proven cookie-prime pattern in
`backend/services/sebi_sast_service.py::_fetch_pit`, but persist rows
into `insider_transactions` (created in
backend/migrations/016_create_insider_activity.sql) instead of
aggregating in-memory for the pulse.

Sources documented here:

NSE PIT (Prohibition of Insider Trading) feed — preferred
    https://www.nseindia.com/api/corporates-pit?index=equities
        &from_date=DD-MM-YYYY&to_date=DD-MM-YYYY
    UI:
    https://www.nseindia.com/companies-listing/corporate-filings-insider-trading
    Why preferred: returns every disclosure for the date window in one
    call, JSON, with structured fields (symbol, personCategory,
    secAcq, secSold, secVal). Cookie-prime required (see
    sebi_sast_service.py).
    Refresh: T+2 — companies must report within 2 trading days of the
    transaction per SEBI PIT Regulation 7(2).

SEBI portal (fallback / authoritative)
    https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doInsiderTrading=yes
    Returns paginated HTML. Use only as a cross-check; the NSE feed
    surfaces the same Reg 7 disclosures with a much cleaner JSON shape.

BSE
    https://www.bseindia.com/corporates/Insider_Trading_new.aspx
    Some BSE-only listings file with BSE only. Out of scope for the
    initial scaffolding — open question #3 in
    docs/insider_activity_design.md.

Field mapping (NSE PIT row -> insider_transactions column):
    symbol               -> ticker
    date / acqDate       -> filing_date
    acqfromDt            -> trade_date (start of trade window)
    acqName              -> insider_name
    personCategory       -> insider_role  (normalize to
                            'promoter' | 'director' | 'kmp')
    NOOFSECACQ vs NOOFSECSOLD -> buy_sell ('B' / 'S')
    secVal               -> value_inr
    afterAcqSharesPer    -> post_holding_pct
    NSE filing detail page -> source_url

Run:
    python scripts/ingest_insider_txns.py [--days 30] [--dry-run]

Idempotency:
    UPSERT keyed on the natural-key UNIQUE INDEX uq_insider_filing
    (see migration 016). Re-running over the same window is safe.
"""

from __future__ import annotations

import argparse
import logging
import sys
from typing import Any, Dict, List

logger = logging.getLogger("yieldiq.ingest.insider")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


NSE_PIT_URL = (
    "https://www.nseindia.com/api/corporates-pit"
    "?index=equities&from_date={from_d}&to_date={to_d}"
)
SEBI_PORTAL_URL = (
    "https://www.sebi.gov.in/sebiweb/other/OtherAction.do?doInsiderTrading=yes"
)


_ROLE_MAP = {
    "promoter": "promoter",
    "promoters": "promoter",
    "promoter group": "promoter",
    "director": "director",
    "directors": "director",
    "kmp": "kmp",
    "key managerial personnel": "kmp",
    "designated person": "kmp",
    "designated persons": "kmp",
}


def normalize_role(raw: str | None) -> str | None:
    if not raw:
        return None
    key = raw.strip().lower()
    if key in _ROLE_MAP:
        return _ROLE_MAP[key]
    for k, v in _ROLE_MAP.items():
        if k in key:
            return v
    return None


# ---------------------------------------------------------------------------
# Fetch stub
# ---------------------------------------------------------------------------


def fetch_nse_pit(days: int) -> List[Dict[str, Any]]:
    """Returns rows shaped like insider_transactions columns.

    Real implementation should reuse `sebi_sast_service._fetch_pit`
    (which already handles cookie priming + retry) and just change the
    aggregation step to per-filing rows instead of per-ticker totals.
    """
    # TODO: actual fetch.
    logger.info("STUB fetch_nse_pit(days=%s) → returning []", days)
    return []


def fetch_sebi_portal(days: int) -> List[Dict[str, Any]]:
    # TODO: actual fetch — only as a cross-check to NSE PIT.
    logger.info("STUB fetch_sebi_portal(days=%s) → returning []", days)
    return []


# ---------------------------------------------------------------------------
# Idempotent UPSERT
# ---------------------------------------------------------------------------


UPSERT_SQL = """
INSERT INTO insider_transactions
    (ticker, filing_date, trade_date, insider_name, insider_role,
     buy_sell, quantity, value_inr, post_holding_pct, source_url)
VALUES
    (:ticker, :filing_date, :trade_date, :insider_name, :insider_role,
     :buy_sell, :quantity, :value_inr, :post_holding_pct, :source_url)
ON CONFLICT ON CONSTRAINT uq_insider_filing DO UPDATE SET
    value_inr = EXCLUDED.value_inr,
    post_holding_pct = EXCLUDED.post_holding_pct,
    fetched_at = NOW();
"""


def upsert_rows(rows: List[Dict[str, Any]], *, dry_run: bool = False) -> int:
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
        "--days", type=int, default=30,
        help="Look-back window in days (NSE PIT default: 30).",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="Don't write to DB; just log fetched row counts.",
    )
    args = p.parse_args(argv)

    rows: List[Dict[str, Any]] = []
    try:
        rows.extend(fetch_nse_pit(args.days))
    except Exception as exc:  # noqa: BLE001
        logger.error("fetch_nse_pit failed: %s", exc)

    upsert_rows(rows, dry_run=args.dry_run)
    logger.info("done: %d insider rows for last %d days", len(rows), args.days)
    return 0


if __name__ == "__main__":
    sys.exit(main())
