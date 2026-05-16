"""Production NSE quarterly XBRL backfill CLI.

Two modes:
  --dry-run  : fetch + parse + print what would be inserted (NO DB writes)
  --apply    : fetch + parse + upsert to company_quarterly_results

Examples:
  # Smoke test on 3 representative tickers (no DB):
  python scripts/backfill_nse_quarterly_xbrl.py \
      --tickers INFY HDFCBANK BAJAJFINSV --dry-run

  # Apply for the nifty50 batch:
  python scripts/backfill_nse_quarterly_xbrl.py --batch nifty50 --apply

Manual post-merge steps (user runs after reviewing PR):
  1. psql $DATABASE_URL -f data_pipeline/migrations/031_quarterly_bank_fields.sql
  2. (optional) DELETE buggy rows for affected tickers
  3. python scripts/backfill_nse_quarterly_xbrl.py --batch nifty50 --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

try:
    from dotenv import load_dotenv
    load_dotenv(ROOT / ".env.local", override=True)
except ImportError:
    pass

from data_pipeline.sources.nse_quarterly_xbrl import (  # noqa: E402
    N_QUARTERS,
    fetch_and_parse,
)
from data_pipeline.sources.nse_xbrl_fundamentals import _get_session  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("backfill_xbrl")


# Pre-defined batches for convenience
BATCHES: dict[str, list[str]] = {
    "smoke3": ["INFY", "HDFCBANK", "BAJAJFINSV"],
    "nifty50_b1": [
        "RELIANCE", "HDFCBANK", "TCS", "BHARTIARTL", "ICICIBANK",
        "SBIN", "HINDUNILVR", "BAJFINANCE", "ITC", "LT",
    ],
    "nifty50_b2": [
        "INFY", "MARUTI", "M&M", "AXISBANK", "KOTAKBANK",
        "SUNPHARMA", "TITAN", "ULTRACEMCO", "ASIANPAINT", "BAJAJFINSV",
    ],
}


UPSERT_SQL = """
INSERT INTO company_quarterly_results (
    ticker, fiscal_quarter, period_start, period_end,
    is_consolidated, is_audited, is_single_segment,
    revenue_cr, other_income_cr, total_expenses_cr,
    profit_before_tax_cr, tax_expense_cr, net_profit_cr,
    comprehensive_income_cr,
    employee_benefit_cr, finance_costs_cr, depreciation_cr, other_expenses_cr,
    basic_eps, diluted_eps, face_value, paid_up_capital_cr,
    interest_earned_cr, interest_expended_cr,
    operating_profit_cr, provisions_cr,
    schema_type,
    xbrl_url, xbrl_sha256, filed_at
) VALUES (
    %(ticker)s, %(fiscal_quarter)s, %(period_start)s, %(period_end)s,
    %(is_consolidated)s, %(is_audited)s, %(is_single_segment)s,
    %(revenue_cr)s, %(other_income_cr)s, %(total_expenses_cr)s,
    %(profit_before_tax_cr)s, %(tax_expense_cr)s, %(net_profit_cr)s,
    %(comprehensive_income_cr)s,
    %(employee_benefit_cr)s, %(finance_costs_cr)s, %(depreciation_cr)s, %(other_expenses_cr)s,
    %(basic_eps)s, %(diluted_eps)s, %(face_value)s, %(paid_up_capital_cr)s,
    %(interest_earned_cr)s, %(interest_expended_cr)s,
    %(operating_profit_cr)s, %(provisions_cr)s,
    %(schema_type)s,
    %(xbrl_url)s, %(xbrl_sha256)s, %(filed_at)s
)
ON CONFLICT (ticker, fiscal_quarter, is_consolidated) DO UPDATE SET
    period_start = EXCLUDED.period_start,
    period_end = EXCLUDED.period_end,
    is_audited = EXCLUDED.is_audited,
    is_single_segment = EXCLUDED.is_single_segment,
    revenue_cr = EXCLUDED.revenue_cr,
    other_income_cr = EXCLUDED.other_income_cr,
    total_expenses_cr = EXCLUDED.total_expenses_cr,
    profit_before_tax_cr = EXCLUDED.profit_before_tax_cr,
    tax_expense_cr = EXCLUDED.tax_expense_cr,
    net_profit_cr = EXCLUDED.net_profit_cr,
    comprehensive_income_cr = EXCLUDED.comprehensive_income_cr,
    employee_benefit_cr = EXCLUDED.employee_benefit_cr,
    finance_costs_cr = EXCLUDED.finance_costs_cr,
    depreciation_cr = EXCLUDED.depreciation_cr,
    other_expenses_cr = EXCLUDED.other_expenses_cr,
    basic_eps = EXCLUDED.basic_eps,
    diluted_eps = EXCLUDED.diluted_eps,
    face_value = EXCLUDED.face_value,
    paid_up_capital_cr = EXCLUDED.paid_up_capital_cr,
    interest_earned_cr = EXCLUDED.interest_earned_cr,
    interest_expended_cr = EXCLUDED.interest_expended_cr,
    operating_profit_cr = EXCLUDED.operating_profit_cr,
    provisions_cr = EXCLUDED.provisions_cr,
    schema_type = EXCLUDED.schema_type,
    xbrl_url = EXCLUDED.xbrl_url,
    xbrl_sha256 = EXCLUDED.xbrl_sha256,
    filed_at = EXCLUDED.filed_at,
    ingested_at = now();
"""


def get_db_url() -> str | None:
    return os.environ.get("DATABASE_URL")


def _strip_internal(row: dict[str, Any]) -> dict[str, Any]:
    """Drop keys not present in the UPSERT SQL (internal markers like _resolved_symbol)."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def dry_run_summary(ticker: str, rows: list[dict[str, Any]]) -> None:
    log.info("---- DRY-RUN [%s] %d rows would be upserted ----", ticker, len(rows))
    log.info("%-10s %-6s %-7s %-12s %-12s %-10s %-8s",
             "fq", "consol", "schema", "revenue_cr", "net_profit_cr",
             "op_profit", "eps")
    for r in rows[:8]:
        log.info(
            "%-10s %-6s %-7s %-12s %-12s %-10s %-8s",
            r.get("fiscal_quarter"),
            "Y" if r.get("is_consolidated") else "N",
            r.get("schema_type", "?")[:7],
            r.get("revenue_cr"),
            r.get("net_profit_cr"),
            r.get("operating_profit_cr"),
            r.get("basic_eps"),
        )
    if len(rows) > 8:
        log.info("  ...(+%d more)", len(rows) - 8)


def upsert(conn, rows: list[dict[str, Any]]) -> int:
    n = 0
    for row in rows:
        payload = _strip_internal(row)
        # Ensure every key in UPSERT_SQL is present (None if missing)
        for key in (
            "is_single_segment", "comprehensive_income_cr",
            "interest_earned_cr", "interest_expended_cr",
            "operating_profit_cr", "provisions_cr",
            "finance_costs_cr", "depreciation_cr", "other_expenses_cr",
            "employee_benefit_cr", "total_expenses_cr",
        ):
            payload.setdefault(key, None)
        try:
            with conn.cursor() as cur:
                cur.execute(UPSERT_SQL, payload)
            conn.commit()
            n += 1
        except Exception as exc:
            conn.rollback()
            log.warning("upsert fail %s %s: %s",
                        row.get("ticker"), row.get("fiscal_quarter"), exc)
    return n


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--tickers", nargs="+",
        help="Explicit list of NSE tickers (overrides --batch)",
    )
    ap.add_argument(
        "--batch", choices=list(BATCHES.keys()),
        help="Named ticker batch",
    )
    ap.add_argument("--limit", type=int, default=N_QUARTERS,
                    help=f"Max quarterly filings per ticker (default {N_QUARTERS})")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                      help="Parse and print, NO DB writes")
    mode.add_argument("--apply", action="store_true",
                      help="Upsert to company_quarterly_results")
    ap.add_argument("--sleep", type=float, default=1.0,
                    help="Seconds between XBRL downloads")
    ap.add_argument("--json-out", type=Path,
                    help="(dry-run) write all parsed rows to this JSON file")
    args = ap.parse_args()

    if args.tickers:
        tickers = args.tickers
    elif args.batch:
        tickers = BATCHES[args.batch]
    else:
        log.error("must specify --tickers or --batch")
        return 2

    log.info("mode=%s  tickers=%s  limit=%d/ticker",
             "DRY-RUN" if args.dry_run else "APPLY",
             ",".join(tickers), args.limit)

    conn = None
    if args.apply:
        db_url = get_db_url()
        if not db_url:
            log.error("--apply requires DATABASE_URL")
            return 2
        import psycopg2
        conn = psycopg2.connect(db_url)
        conn.autocommit = False

    session = _get_session()
    t0 = time.time()
    grand_total = 0
    all_rows: dict[str, list[dict[str, Any]]] = {}

    for tk in tickers:
        log.info("=== %s ===", tk)
        try:
            rows = fetch_and_parse(
                tk, limit=args.limit, session=session, sleep_between=args.sleep,
            )
        except Exception as exc:
            log.error("%s failed: %s", tk, exc)
            continue
        all_rows[tk] = rows
        grand_total += len(rows)
        if args.dry_run:
            dry_run_summary(tk, rows)
        elif conn is not None:
            n = upsert(conn, rows)
            log.info("[%s] upserted %d/%d rows", tk, n, len(rows))

    elapsed = time.time() - t0
    log.info("=" * 60)
    log.info("DONE  tickers=%d  rows=%d  wall=%.1fs",
             len(tickers), grand_total, elapsed)

    if args.json_out and args.dry_run:
        # Serialize dates as ISO strings
        def _enc(o):
            if hasattr(o, "isoformat"):
                return o.isoformat()
            raise TypeError(f"unserializable {type(o)}")
        args.json_out.write_text(
            json.dumps(
                {tk: [_strip_internal(r) for r in rows]
                 for tk, rows in all_rows.items()},
                indent=2, default=_enc,
            ),
            encoding="utf-8",
        )
        log.info("wrote %s", args.json_out)

    if conn is not None:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
