#!/usr/bin/env python
"""Backfill ``stocks.industry`` / ``stocks.sector`` from NSE official sources.

Two-tier source cascade (no yfinance):
  1. NSE index master CSVs (Total Market / 500 / 100 / Smallcap / Microcap)
     — bulk, ~5 HTTP calls, classifies ~750 unique tickers.
  2. Per-ticker NSE quote-equity API for everything else, throttled to
     ~5 req/sec with 429 backoff.

Usage::

    DATABASE_URL=$(sed -n '2p' .env.local) \
        python scripts/data_pipelines/backfill_nse_industry_master.py

Flags:
    --force           Overwrite already-populated industry rows.
    --skip-quote-api  Run only the bulk CSV stage (debugging / smoke).
    --limit-quote N   Cap quote-API calls to N tickers (debugging).
    --dry-run         Fetch only, no DB writes; prints what would change.

Resumable via ``BACKFILL_CHECKPOINT_DIR`` env var (default
``reports/_backfill_checkpoints``); the per-ticker quote-API stage
writes ``nse_industry_master.json`` after every 50 tickers.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.data_pipelines import _common as C
else:
    from . import _common as C

from data_pipeline.sources import nse_industry_master as nim


CHECKPOINT_FIELD = "nse_industry_master"


# ── Universe selection ───────────────────────────────────────────────

def _missing_industry_tickers(session, force: bool) -> list[str]:
    from sqlalchemy import text
    if force:
        sql = text("SELECT ticker FROM stocks WHERE is_active = TRUE ORDER BY ticker")
    else:
        sql = text("""
            SELECT ticker FROM stocks
             WHERE is_active = TRUE
               AND (industry IS NULL OR industry = '')
             ORDER BY ticker
        """)
    return [r[0] for r in session.execute(sql).fetchall()]


# ── Source-distribution snapshot ─────────────────────────────────────

def _source_distribution(session) -> dict[str, int]:
    from sqlalchemy import text
    rows = session.execute(text("""
        SELECT COALESCE(NULLIF(industry, ''), '<missing>') AS bucket,
               COUNT(*) AS n
          FROM stocks
         WHERE is_active = TRUE
         GROUP BY 1 ORDER BY n DESC LIMIT 20
    """)).fetchall()
    return {r[0]: int(r[1]) for r in rows}


def _top_missing(session, n: int = 20) -> list[tuple[str, str]]:
    from sqlalchemy import text
    rows = session.execute(text("""
        SELECT ticker, COALESCE(company_name, '')
          FROM stocks
         WHERE is_active = TRUE
           AND (industry IS NULL OR industry = '')
         ORDER BY ticker
         LIMIT :n
    """), {"n": n}).fetchall()
    return [(r[0], r[1]) for r in rows]


# ── Main ─────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--force", action="store_true",
                   help="Overwrite tickers that already have an industry.")
    p.add_argument("--skip-quote-api", action="store_true",
                   help="Bulk-CSV stage only; skip per-ticker quote API.")
    p.add_argument("--limit-quote", type=int, default=0,
                   help="Cap quote-API calls (debugging).")
    p.add_argument("--dry-run", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    C.setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    C.install_signal_handlers()

    if not args.dry_run:
        try:
            C.get_database_url()
        except RuntimeError as e:
            logging.error("%s", e)
            return 2

    run_id = C.now_run_id()
    C.init_jsonl_log(run_id)

    sess = C.make_session()
    try:
        before = nim.coverage_breakdown(sess)
        logging.info("BEFORE: %s", before)
        todo = _missing_industry_tickers(sess, args.force)
        logging.info("Tickers to classify: %d (force=%s)", len(todo), args.force)
    finally:
        sess.close()

    todo_set = set(todo)

    # ── Stage 1: bulk CSV masters ────────────────────────────────────
    logging.info("Stage 1: NSE index master CSVs")
    bulk = nim.fetch_index_master_classifications()
    logging.info("Bulk classifications: %d unique tickers", len(bulk))

    # Restrict to our actual universe (don't write rows for tickers
    # we don't track — keeps the UPDATE rowcount honest).
    bulk_in_scope = {t: v for t, v in bulk.items() if t in todo_set}
    logging.info("Bulk in scope (todo & in CSV): %d", len(bulk_in_scope))

    by_source: dict[str, int] = {}
    if not args.dry_run and bulk_in_scope:
        sess = C.make_session()
        try:
            res = nim.upsert_to_neon(bulk_in_scope, sess, force=args.force)
            logging.info("Bulk upsert: %s", res)
        finally:
            sess.close()
        for v in bulk_in_scope.values():
            by_source[v["source"]] = by_source.get(v["source"], 0) + 1

    bulk_handled = set(bulk_in_scope.keys())
    remaining = [t for t in todo if t not in bulk_handled]
    logging.info("After bulk: %d tickers still need quote-API", len(remaining))

    # ── Stage 2: per-ticker quote API ────────────────────────────────
    if args.skip_quote_api:
        logging.info("Stage 2: skipped (--skip-quote-api)")
    else:
        if args.limit_quote and args.limit_quote < len(remaining):
            logging.info("Capping quote-API to %d tickers", args.limit_quote)
            remaining = remaining[: args.limit_quote]

        # Resume from checkpoint.
        done = C.load_checkpoint(CHECKPOINT_FIELD)
        run_list = [t for t in remaining if t not in done]
        logging.info("Stage 2: %d todo (%d already in checkpoint)",
                     len(run_list), len(done))

        quote_results: dict[str, dict] = {}
        commit_every = 50

        def _on_progress(seen: int, classified: int) -> None:
            logging.info("quote-api progress: seen=%d classified=%d",
                         seen, classified)

        # Drive the bulk loop in chunks so we can checkpoint + commit.
        idx = 0
        while idx < len(run_list):
            chunk = run_list[idx: idx + commit_every]
            results = nim.fetch_quote_api_bulk(
                chunk, rate_per_sec=5.0, progress_every=25,
                on_progress=_on_progress,
            )
            quote_results.update(results)
            if not args.dry_run and results:
                sess = C.make_session()
                try:
                    res = nim.upsert_to_neon(results, sess, force=args.force)
                    for t in results.keys():
                        C.log_event(field=CHECKPOINT_FIELD, ticker=t,
                                    status="ok", source="quote_api",
                                    industry=results[t].get("industry"))
                    logging.info(
                        "quote-api chunk %d-%d upsert: %s "
                        "(classified=%d/%d)",
                        idx, idx + len(chunk), res, len(results), len(chunk),
                    )
                finally:
                    sess.close()
            for t in chunk:
                done.add(t)
            C.save_checkpoint(CHECKPOINT_FIELD, done)
            idx += commit_every
            if C.SHUTDOWN.is_set():
                logging.warning("shutdown signalled — stopping after chunk")
                break

        by_source["quote_api"] = len(quote_results)
        logging.info("Stage 2 total classifications: %d", len(quote_results))

    # ── Final coverage report ────────────────────────────────────────
    sess = C.make_session()
    try:
        after = nim.coverage_breakdown(sess)
        logging.info("AFTER: %s", after)
        still_missing = _top_missing(sess, n=20)
    finally:
        sess.close()

    report = {
        "run_id": run_id,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "force": args.force,
        "dry_run": args.dry_run,
        "before": before,
        "after": after,
        "by_source": by_source,
        "delta_filled": after["with_industry"] - before["with_industry"],
        "still_missing_top_20": [
            {"ticker": t, "company_name": n} for t, n in still_missing
        ],
    }
    out_dir = C.REPORTS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"nse_industry_master_{date.today().isoformat()}.json"
    out_path.write_text(json.dumps(report, indent=2), encoding="utf-8")
    logging.info("Report: %s", out_path)

    print("\n=== NSE industry master backfill ===")
    print(f"Before:  filled={before['with_industry']}  missing={before['missing_industry']}")
    print(f"After:   filled={after['with_industry']}  missing={after['missing_industry']}")
    print(f"By source: {by_source}")
    print(f"Top 20 still-missing tickers:")
    for t, n in still_missing:
        print(f"  - {t}  {n}")
    print(f"Full report: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
