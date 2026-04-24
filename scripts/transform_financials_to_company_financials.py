"""One-shot transform: `financials` (wide) → `company_financials` (tall).

Context
-------
The 3,000-ticker XBRL backfill landed rows in `financials` (wide: one row
per ticker / period_end / period_type), but the HEX history, /financials
endpoint, and analysis/db.py defensive reads all query
`company_financials` (tall: one row per statement_type). This script
closes the gap: every source row becomes up to 3 target rows
(income / balance_sheet / cashflow).

Usage
-----
    DATABASE_URL="..." python scripts/transform_financials_to_company_financials.py --dry-run
    DATABASE_URL="..." python scripts/transform_financials_to_company_financials.py
    # Single ticker for testing:
    DATABASE_URL="..." python scripts/transform_financials_to_company_financials.py --ticker BPCL

Safety
------
- Idempotent: all writes go through `upsert_records()` (ON CONFLICT DO UPDATE).
- No DELETE / TRUNCATE / destructive statements.
- Batch upsert failures are logged, not raised — one bad row won't kill
  a 67k-row job.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from sqlalchemy import text as sa_text

from data_pipeline.db import Session
from data_pipeline.xbrl.db_writer import upsert_records

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("transform_fin")


# ─── column map ──────────────────────────────────────────────────────────
# financials (source) → company_financials (target), grouped by statement_type.
# Keys are target columns; values are source columns. A statement_type is
# SKIPPED entirely if every source column in its group is None.

_INCOME_MAP = {
    "revenue":      "revenue",
    "ebitda":       "ebitda",
    "ebit":         "ebit",
    "pretax_income": "pbt",
    "net_income":   "pat",
    "eps_basic":    "eps_basic",
    "eps_diluted":  "eps_diluted",
}
_BS_MAP = {
    "total_assets":        "total_assets",
    "total_equity":        "total_equity",
    "total_debt":          "total_debt",
    "current_liabilities": "current_liabilities",
    "cash":                "cash_and_equivalents",
    "net_debt":            "net_debt",
}
_CF_MAP = {
    "operating_cf":    "cfo",
    "investing_cf":    "cfi",
    "financing_cf":    "cff",
    "capex":           "capex",
    "free_cash_flow":  "free_cash_flow",
}

_STATEMENT_GROUPS = [
    ("income",        _INCOME_MAP),
    ("balance_sheet", _BS_MAP),
    ("cashflow",      _CF_MAP),
]

# Columns we SELECT from `financials`. Keep this explicit so a schema
# drift surfaces loudly instead of silently writing NULLs.
_SOURCE_COLUMNS = [
    "ticker", "period_end", "period_type", "filing_date",
    "revenue", "revenue_from_ops", "ebitda", "ebit", "pbt", "pat",
    "eps_basic", "eps_diluted",
    "cfo", "cfi", "cff", "capex", "free_cash_flow",
    "total_assets", "total_equity", "total_debt", "current_liabilities",
    "cash_and_equivalents", "net_debt", "shares_outstanding",
    "data_source", "currency",
]


def _normalize_ticker(raw: str) -> str:
    """Normalize bare/suffixed tickers to the .NS form used by company_financials.

    Convention copied from `backend/services/analysis/db.py` (strip-then-suffix):
    - "BPCL"     → "BPCL.NS"
    - "BPCL.NS"  → "BPCL.NS"
    - "BPCL.BO"  → "BPCL.NS"   (BSE suffix rewritten to NSE form)
    """
    if not raw:
        return raw
    bare = raw.strip().upper().replace(".NS", "").replace(".BO", "")
    return bare + ".NS"


def _build_records(row: dict) -> list[dict]:
    """One source row → up to 3 target records (one per statement_type).

    Skips any statement_type whose source columns are ALL None.
    """
    ticker_nse = _normalize_ticker(row["ticker"])
    period_end = row["period_end"]
    period_type = row["period_type"]
    source = row.get("data_source") or "XBRL_BACKFILL"
    currency = row.get("currency") or "INR"

    base = {
        "ticker_nse": ticker_nse,
        "period_type": period_type,
        "period_end_date": period_end,
        "source": source,
        "currency": currency,
    }

    records = []
    for stmt_type, col_map in _STATEMENT_GROUPS:
        values = {tgt: row.get(src) for tgt, src in col_map.items()}
        if all(v is None for v in values.values()):
            continue  # skip empty statement_type
        rec = dict(base)
        rec["statement_type"] = stmt_type
        rec.update(values)
        records.append(rec)
    return records


def _count_source_rows(db, ticker: str | None, period_type: str) -> int:
    sql = "SELECT COUNT(*) FROM financials WHERE period_type != 'ttm'"
    params: dict = {}
    if ticker:
        sql += " AND (ticker = :t OR ticker = :t_ns OR ticker = :t_bo)"
        params["t"] = ticker
        params["t_ns"] = ticker + ".NS"
        params["t_bo"] = ticker + ".BO"
    if period_type != "all":
        sql += " AND period_type = :pt"
        params["pt"] = period_type
    return db.execute(sa_text(sql), params).scalar() or 0


def _iter_source_rows(db, ticker: str | None, period_type: str, batch_size: int):
    """Stream source rows paginated by (ticker, period_end) keyset."""
    base_sql = f"SELECT {', '.join(_SOURCE_COLUMNS)} FROM financials WHERE period_type != 'ttm'"
    params: dict = {}
    if ticker:
        base_sql += " AND (ticker = :t OR ticker = :t_ns OR ticker = :t_bo)"
        params["t"] = ticker
        params["t_ns"] = ticker + ".NS"
        params["t_bo"] = ticker + ".BO"
    if period_type != "all":
        base_sql += " AND period_type = :pt"
        params["pt"] = period_type
    base_sql += " ORDER BY ticker ASC, period_end DESC"

    # Simple OFFSET pagination — the table is ~67k rows, well within
    # what a single cursor-backed scan handles without keyset complexity.
    offset = 0
    while True:
        page_sql = base_sql + f" LIMIT {batch_size} OFFSET {offset}"
        rows = db.execute(sa_text(page_sql), params).mappings().all()
        if not rows:
            break
        for r in rows:
            yield dict(r)
        if len(rows) < batch_size:
            break
        offset += batch_size


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="SELECT count + log what would be written; no writes")
    ap.add_argument("--ticker", type=str, default=None,
                    help="Restrict to one ticker (bare form, e.g. BPCL)")
    ap.add_argument("--batch-size", type=int, default=500,
                    help="Source rows per upsert batch (default 500)")
    ap.add_argument("--period-type", choices=["annual", "quarterly", "all"],
                    default="all")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL not set")
        return 2
    if Session is None:
        logger.error("data_pipeline.db.Session is None — engine init failed")
        return 2

    db = Session()
    t0 = time.time()
    counters = {
        "scanned": 0,
        "skipped_empty_income": 0,
        "skipped_empty_bs": 0,
        "skipped_empty_cf": 0,
        "skipped_ttm": 0,
        "unusual_tickers": 0,
        "written": 0,
        "errors": 0,
    }

    try:
        total = _count_source_rows(db, args.ticker, args.period_type)
        logger.info(
            "source: %d rows in `financials` (ticker=%s period_type=%s)",
            total, args.ticker or "ALL", args.period_type,
        )

        if args.dry_run:
            # Sample 5 rows, show what we'd write
            sample = list(_iter_source_rows(db, args.ticker, args.period_type, 5))
            for row in sample[:5]:
                recs = _build_records(row)
                logger.info(
                    "DRY: %s %s %s → %d target rows (%s)",
                    row["ticker"], row["period_end"], row["period_type"],
                    len(recs), [r["statement_type"] for r in recs],
                )
            logger.info("DRY-RUN complete. Would process %d source rows.", total)
            return 0

        batch: list[dict] = []
        flush_at = args.batch_size * 3  # up to 3 target rows per source row

        for row in _iter_source_rows(db, args.ticker, args.period_type, args.batch_size):
            counters["scanned"] += 1

            # Track unusual ticker formats (not bare / .NS / .BO)
            raw_t = (row.get("ticker") or "").upper()
            if raw_t and not (raw_t.endswith(".NS") or raw_t.endswith(".BO")
                              or "." not in raw_t):
                counters["unusual_tickers"] += 1
                if counters["unusual_tickers"] <= 5:
                    logger.warning("unusual ticker format: %r", raw_t)

            recs = _build_records(row)
            present = {r["statement_type"] for r in recs}
            if "income" not in present:
                counters["skipped_empty_income"] += 1
            if "balance_sheet" not in present:
                counters["skipped_empty_bs"] += 1
            if "cashflow" not in present:
                counters["skipped_empty_cf"] += 1
            batch.extend(recs)

            if len(batch) >= flush_at:
                ins, errs = upsert_records(batch)
                counters["written"] += ins
                counters["errors"] += errs
                batch.clear()

            if counters["scanned"] % 100 == 0:
                elapsed = time.time() - t0
                rate = counters["scanned"] / max(elapsed, 1.0)
                eta_min = (total - counters["scanned"]) / max(rate, 0.001) / 60
                logger.info(
                    "[%d/%d] written=%d errors=%d skip(i/bs/cf)=%d/%d/%d "
                    "rate=%.1f/s ETA=%.1f min",
                    counters["scanned"], total,
                    counters["written"], counters["errors"],
                    counters["skipped_empty_income"],
                    counters["skipped_empty_bs"],
                    counters["skipped_empty_cf"],
                    rate, eta_min,
                )

        # Flush tail
        if batch:
            ins, errs = upsert_records(batch)
            counters["written"] += ins
            counters["errors"] += errs

    except KeyboardInterrupt:
        logger.warning("interrupted — running counters below")
    finally:
        try:
            db.close()
        except Exception:
            pass

    elapsed = time.time() - t0
    logger.info("DONE in %.1f min", elapsed / 60)
    for k, v in counters.items():
        logger.info("  %s = %d", k, v)
    return 0


if __name__ == "__main__":
    sys.exit(main())
