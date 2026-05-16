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
    segment, report_period_type,
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
    %(segment)s, %(report_period_type)s,
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
    segment = EXCLUDED.segment,
    report_period_type = EXCLUDED.report_period_type,
    xbrl_url = EXCLUDED.xbrl_url,
    xbrl_sha256 = EXCLUDED.xbrl_sha256,
    filed_at = EXCLUDED.filed_at,
    ingested_at = now();
"""


def get_db_url() -> str | None:
    return os.environ.get("DATABASE_URL")


def get_db_connection(max_retries: int = 3):
    """Open a fresh Neon connection with exponential-backoff retry.

    Used at script start AND on reconnect after a Neon idle-timeout drop
    (psycopg2.InterfaceError / OperationalError) during long backfills.
    """
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
            log.warning("DB connect attempt %d failed: %s (retry in %ds)",
                        attempt + 1, str(e)[:120], wait)
            time.sleep(wait)
    if last_exc:
        raise last_exc
    raise RuntimeError("get_db_connection: unreachable")


def _strip_internal(row: dict[str, Any]) -> dict[str, Any]:
    """Drop keys not present in the UPSERT SQL (internal markers like _resolved_symbol)."""
    return {k: v for k, v in row.items() if not k.startswith("_")}


def dry_run_summary(ticker: str, rows: list[dict[str, Any]]) -> None:
    log.info("---- DRY-RUN [%s] %d rows would be upserted ----", ticker, len(rows))
    log.info("%-10s %-6s %-7s %-8s %-11s %-12s %-12s %-8s",
             "fq", "consol", "schema", "segment", "report_pt",
             "revenue_cr", "net_profit_cr", "eps")
    for r in rows[:8]:
        log.info(
            "%-10s %-6s %-7s %-8s %-11s %-12s %-12s %-8s",
            r.get("fiscal_quarter"),
            "Y" if r.get("is_consolidated") else "N",
            (r.get("schema_type") or "?")[:7],
            (r.get("segment") or "?")[:8],
            (r.get("report_period_type") or "?")[:11],
            r.get("revenue_cr"),
            r.get("net_profit_cr"),
            r.get("basic_eps"),
        )
    if len(rows) > 8:
        log.info("  ...(+%d more)", len(rows) - 8)


def upsert(conn, rows: list[dict[str, Any]]) -> tuple[int, Any]:
    """Upsert rows, returning (n_inserted, possibly_new_conn).

    If Neon drops the connection mid-loop (InterfaceError/OperationalError),
    reconnect via get_db_connection() and retry the failing row up to 2 times
    before giving up on it.
    """
    import psycopg2
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
            "report_period_type",
        ):
            payload.setdefault(key, None)
        # `segment` has a server-side default of 'equities' but the
        # NOT-NULL safe payload contract is to always send a value.
        payload.setdefault("segment", "equities")

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
                    log.warning("upsert give-up %s %s after %d reconnects: %s",
                                row.get("ticker"), row.get("fiscal_quarter"),
                                max_retries, str(exc)[:120])
                    break
                log.info("  [reconnect after %s: %s]",
                         type(exc).__name__, str(exc)[:80])
                try:
                    conn.close()
                except Exception:
                    pass
                conn = get_db_connection()
            except Exception as exc:
                try:
                    conn.rollback()
                except Exception:
                    # rollback itself may fail if conn died
                    try:
                        conn.close()
                    except Exception:
                        pass
                    conn = get_db_connection()
                log.warning("upsert fail %s %s: %s",
                            row.get("ticker"), row.get("fiscal_quarter"), exc)
                break
    return n, conn


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--tickers", nargs="+",
        help="Explicit list of NSE tickers (overrides --batch)",
    )
    ap.add_argument(
        "--tickers-file", type=Path,
        help="Path to a file with tickers (one per line, or comma-separated). "
             "Blank lines and lines starting with '#' are ignored.",
    )
    ap.add_argument(
        "--batch", choices=list(BATCHES.keys()) + ["sme_all"],
        help="Named ticker batch. 'sme_all' loads the cached NSE SME "
             "EMERGE constituent list from data_pipeline/data/nse_sme_tickers.txt.",
    )
    ap.add_argument(
        "--segment", choices=["equities", "sme"], default="equities",
        help="Listing channel: 'equities' (main-board, Quarterly only) or "
             "'sme' (NSE EMERGE — Quarterly + Half-Yearly cadence). "
             "Rows are tagged with this value in `company_quarterly_results.segment`.",
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
    elif args.tickers_file:
        raw = args.tickers_file.read_text(encoding="utf-8")
        tickers = []
        for line in raw.splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            # support comma-separated too
            for tok in line.split(","):
                tok = tok.strip()
                if tok:
                    tickers.append(tok)
        if not tickers:
            log.error("--tickers-file %s is empty", args.tickers_file)
            return 2
    elif args.batch == "sme_all":
        sme_path = ROOT / "data_pipeline" / "data" / "nse_sme_tickers.txt"
        if not sme_path.exists():
            log.error(
                "--batch sme_all requires %s — run "
                "`python scripts/fetch_nse_sme_tickers.py` first",
                sme_path,
            )
            return 2
        tickers = [
            line.strip() for line in sme_path.read_text(encoding="utf-8").splitlines()
            if line.strip() and not line.startswith("#")
        ]
        # sme_all only makes sense with --segment sme
        if args.segment != "sme":
            log.warning(
                "--batch sme_all auto-sets --segment sme (was %s)", args.segment,
            )
            args.segment = "sme"
    elif args.batch:
        tickers = BATCHES[args.batch]
    else:
        log.error("must specify --tickers, --tickers-file, or --batch")
        return 2

    log.info("mode=%s  segment=%s  tickers=%d  limit=%d/ticker",
             "DRY-RUN" if args.dry_run else "APPLY",
             args.segment, len(tickers), args.limit)
    # Log the first ~10 to keep CI logs readable when --batch sme_all
    # passes 514 tickers in.
    log.info("tickers[:10]=%s%s",
             ",".join(tickers[:10]),
             " ..." if len(tickers) > 10 else "")

    conn = None
    if args.apply:
        db_url = get_db_url()
        if not db_url:
            log.error("--apply requires DATABASE_URL")
            return 2
        conn = get_db_connection()

    session = _get_session()
    t0 = time.time()
    grand_total = 0
    all_rows: dict[str, list[dict[str, Any]]] = {}
    per_ticker_stats: dict[str, dict[str, Any]] = {}
    failed_tickers: list[dict[str, str]] = []

    for tk in tickers:
        log.info("=== %s ===", tk)
        try:
            rows = fetch_and_parse(
                tk, limit=args.limit, session=session, sleep_between=args.sleep,
                segment=args.segment,
            )
        except Exception as exc:
            log.error("%s failed: %s", tk, exc)
            failed_tickers.append({"ticker": tk, "stage": "fetch_and_parse",
                                   "error": str(exc)[:240]})
            per_ticker_stats[tk] = {"fetched": 0, "upserted": 0,
                                    "error": str(exc)[:240]}
            continue
        all_rows[tk] = rows
        grand_total += len(rows)
        if args.dry_run:
            dry_run_summary(tk, rows)
            per_ticker_stats[tk] = {"fetched": len(rows), "upserted": 0}
        elif conn is not None:
            n, conn = upsert(conn, rows)
            log.info("[%s] upserted %d/%d rows", tk, n, len(rows))
            per_ticker_stats[tk] = {"fetched": len(rows), "upserted": n}

    elapsed = time.time() - t0
    log.info("=" * 60)
    log.info("DONE  tickers=%d  rows=%d  wall=%.1fs",
             len(tickers), grand_total, elapsed)

    if args.json_out:
        # Serialize dates as ISO strings
        def _enc(o):
            if hasattr(o, "isoformat"):
                return o.isoformat()
            raise TypeError(f"unserializable {type(o)}")
        if args.dry_run:
            payload = {tk: [_strip_internal(r) for r in rows]
                       for tk, rows in all_rows.items()}
        else:
            # apply mode: write summary stats, not full row dump
            payload = {
                "mode": "apply",
                "tickers_total": len(tickers),
                "tickers_with_rows": sum(
                    1 for s in per_ticker_stats.values() if s.get("upserted", 0) > 0
                ),
                "rows_fetched_total": grand_total,
                "rows_upserted_total": sum(
                    s.get("upserted", 0) for s in per_ticker_stats.values()
                ),
                "wall_seconds": round(elapsed, 1),
                "per_ticker": per_ticker_stats,
                "failed": failed_tickers,
            }
        args.json_out.parent.mkdir(parents=True, exist_ok=True)
        args.json_out.write_text(
            json.dumps(payload, indent=2, default=_enc),
            encoding="utf-8",
        )
        log.info("wrote %s", args.json_out)

    if conn is not None:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
