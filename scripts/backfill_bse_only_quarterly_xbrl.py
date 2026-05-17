"""BSE-only quarterly XBRL backfill CLI.

Mirrors scripts/backfill_nse_quarterly_xbrl.py but pulls XBRL via the
Playwright path in data_pipeline.sources.bse_quarterly_xbrl. Reads the
ticker list from data_pipeline/data/bse_only_tickers.json.

Two modes:
  --dry-run  : fetch + parse + print, NO DB writes
  --apply    : fetch + parse + upsert to company_quarterly_results
               with source='bse'

Examples:
  # Smoke test on 3 representative tickers (NO DB):
  python scripts/backfill_bse_only_quarterly_xbrl.py \
      --tickers SPICEJET TANFAC JYOTIRES --dry-run

  # Single-ticker dry-run from JSON-file index:
  python scripts/backfill_bse_only_quarterly_xbrl.py \
      --ticker SPICEJET --dry-run

  # Apply for the full BSE-only batch (one Playwright session, ~20-25 min):
  python scripts/backfill_bse_only_quarterly_xbrl.py --all --apply

Pre-requisites (one-time):
  pip install playwright playwright-stealth
  playwright install chromium        # bundled fallback
  # AND: real Google Chrome installed on host (channel='chrome')

Manual post-merge steps (user runs after reviewing PR):
  1. psql $DATABASE_URL -f data_pipeline/migrations/036_bse_source_column.sql
  2. python scripts/backfill_bse_only_quarterly_xbrl.py --all --apply
"""
from __future__ import annotations

import argparse
import asyncio
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

from data_pipeline.sources.bse_quarterly_xbrl import (  # noqa: E402
    BSEXBRLBrowserClient,
    fetch_and_parse_async,
)

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
log = logging.getLogger("backfill_bse_xbrl")


TICKERS_JSON = ROOT / "data_pipeline" / "data" / "bse_only_tickers.json"


# UPSERT mirrors backfill_nse_quarterly_xbrl.UPSERT_SQL but adds the
# `source` column from migration 036. Kept inline (not imported) so a
# change to the NSE upsert shape doesn't silently affect BSE ingest.
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
    segment, report_period_type,
    insurance_metrics,
    xbrl_url, xbrl_sha256, filed_at, source
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
    %(segment)s, %(report_period_type)s,
    %(insurance_metrics)s,
    %(xbrl_url)s, %(xbrl_sha256)s, %(filed_at)s, %(source)s
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
    segment = EXCLUDED.segment,
    report_period_type = EXCLUDED.report_period_type,
    xbrl_url = EXCLUDED.xbrl_url,
    xbrl_sha256 = EXCLUDED.xbrl_sha256,
    filed_at = EXCLUDED.filed_at,
    source = EXCLUDED.source,
    insurance_metrics = EXCLUDED.insurance_metrics,
    ingested_at = now();
"""


def load_ticker_index() -> dict[str, str]:
    """Return {ticker -> bse_code} from the JSON index."""
    if not TICKERS_JSON.exists():
        raise FileNotFoundError(f"missing index: {TICKERS_JSON}")
    data = json.loads(TICKERS_JSON.read_text(encoding="utf-8"))
    return {e["ticker"].upper(): e["bse_code"] for e in data.get("tickers", [])}


def get_db_url() -> str | None:
    return os.environ.get("DATABASE_URL")


def get_db_connection(max_retries: int = 3):
    import psycopg2
    last_exc: Exception | None = None
    for attempt in range(max_retries):
        try:
            db_url = get_db_url()
            if not db_url:
                raise RuntimeError("DATABASE_URL not set")
            conn = psycopg2.connect(db_url)
            conn.autocommit = False
            return conn
        except psycopg2.OperationalError as e:
            last_exc = e
            if attempt == max_retries - 1:
                raise
            wait = 2 ** attempt
            log.warning(
                "DB connect attempt %d failed: %s (retry in %ds)",
                attempt + 1, str(e)[:120], wait,
            )
            time.sleep(wait)
    if last_exc:
        raise last_exc
    raise RuntimeError("unreachable")


def _strip_internal(row: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in row.items() if not k.startswith("_")}


def dry_run_summary(ticker: str, rows: list[dict[str, Any]]) -> None:
    log.info("---- DRY-RUN [%s] %d rows would be upserted ----", ticker, len(rows))
    log.info(
        "%-10s %-6s %-9s %-12s %-12s %-8s",
        "fq", "consol", "schema", "revenue_cr", "net_profit_cr", "eps",
    )
    for r in rows[:8]:
        log.info(
            "%-10s %-6s %-9s %-12s %-12s %-8s",
            r.get("fiscal_quarter"),
            "Y" if r.get("is_consolidated") else "N",
            (r.get("schema_type") or "?")[:9],
            r.get("revenue_cr"),
            r.get("net_profit_cr"),
            r.get("basic_eps"),
        )
    if len(rows) > 8:
        log.info("  ...(+%d more)", len(rows) - 8)


def upsert(conn, rows: list[dict[str, Any]]) -> tuple[int, Any]:
    import psycopg2
    import psycopg2.extras  # noqa: F401  (Json adapter for insurance_metrics JSONB)
    n = 0
    for row in rows:
        payload = _strip_internal(row)
        for key in (
            "is_single_segment", "comprehensive_income_cr",
            "interest_earned_cr", "interest_expended_cr",
            "operating_profit_cr", "provisions_cr",
            "finance_costs_cr", "depreciation_cr", "other_expenses_cr",
            "employee_benefit_cr", "total_expenses_cr",
            "report_period_type",
            "insurance_metrics",
        ):
            payload.setdefault(key, None)
        payload.setdefault("segment", "equities")
        payload.setdefault("source", "bse")
        if payload.get("insurance_metrics") is not None and not isinstance(
            payload["insurance_metrics"], psycopg2.extras.Json
        ):
            payload["insurance_metrics"] = psycopg2.extras.Json(
                payload["insurance_metrics"]
            )

        max_retries = 2
        for attempt in range(max_retries + 1):
            try:
                with conn.cursor() as cur:
                    cur.execute(UPSERT_SQL, payload)
                conn.commit()
                n += 1
                break
            except (psycopg2.InterfaceError, psycopg2.OperationalError) as exc:
                if attempt == max_retries:
                    log.warning(
                        "upsert give-up %s %s after %d reconnects: %s",
                        row.get("ticker"), row.get("fiscal_quarter"),
                        max_retries, str(exc)[:120],
                    )
                    break
                log.info("  [reconnect after %s]", type(exc).__name__)
                try:
                    conn.close()
                except Exception:
                    pass
                conn = get_db_connection()
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = get_db_connection()
                log.warning(
                    "upsert fail %s %s: %s",
                    row.get("ticker"), row.get("fiscal_quarter"), exc,
                )
                break
    return n, conn


async def run(tickers_to_codes: dict[str, str], *,
              dry_run: bool, max_filings: int, sleep_between: float) -> int:
    """Drive a single Playwright session across all tickers."""
    conn = None
    if not dry_run:
        conn = get_db_connection()

    total_rows = 0
    async with BSEXBRLBrowserClient() as client:
        for ticker, bse_code in tickers_to_codes.items():
            log.info(">>> %s (BSE %s)", ticker, bse_code)
            try:
                rows = await fetch_and_parse_async(
                    bse_code, ticker,
                    client=client,
                    max_filings=max_filings,
                    sleep_between=sleep_between,
                )
            except Exception as exc:
                log.warning("%s failed: %s", ticker, exc)
                continue

            if dry_run:
                dry_run_summary(ticker, rows)
            else:
                assert conn is not None
                n, conn = upsert(conn, rows)
                log.info("    upserted %d / %d", n, len(rows))
            total_rows += len(rows)

    if conn is not None:
        try:
            conn.close()
        except Exception:
            pass
    log.info("DONE — total rows parsed across all tickers: %d", total_rows)
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", nargs="+",
                    help="Explicit list of BSE tickers (must exist in bse_only_tickers.json)")
    ap.add_argument("--ticker", help="Single ticker (convenience)")
    ap.add_argument("--all", action="store_true",
                    help="Process every ticker in bse_only_tickers.json")
    ap.add_argument("--limit", type=int, default=22,
                    help="Max XBRL filings per ticker (default 22 = 5.5 FYs)")
    mode = ap.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true",
                      help="Parse and print, NO DB writes")
    mode.add_argument("--apply", action="store_true",
                      help="Upsert to company_quarterly_results")
    ap.add_argument("--sleep", type=float, default=0.5,
                    help="Seconds between XBRL downloads per ticker")
    args = ap.parse_args()

    try:
        index = load_ticker_index()
    except FileNotFoundError as e:
        log.error("%s", e)
        return 2

    if args.all:
        selected = index
    else:
        wanted: list[str] = []
        if args.tickers:
            wanted.extend(t.upper() for t in args.tickers)
        if args.ticker:
            wanted.append(args.ticker.upper())
        if not wanted:
            log.error("must pass --all, --tickers, or --ticker")
            return 2
        missing = [t for t in wanted if t not in index]
        if missing:
            log.error(
                "ticker(s) not in bse_only_tickers.json: %s",
                ", ".join(missing),
            )
            return 2
        selected = {t: index[t] for t in wanted}

    log.info(
        "Mode=%s | %d tickers | limit=%d | sleep=%.2fs",
        "DRY-RUN" if args.dry_run else "APPLY",
        len(selected), args.limit, args.sleep,
    )
    return asyncio.run(run(
        selected,
        dry_run=args.dry_run,
        max_filings=args.limit,
        sleep_between=args.sleep,
    ))


if __name__ == "__main__":
    raise SystemExit(main())
