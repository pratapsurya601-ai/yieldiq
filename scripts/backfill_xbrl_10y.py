"""Backfill 10Y of XBRL/yfinance fundamentals into company_financials.

Wraps data_pipeline/xbrl/pipeline.py with LOOKBACK_YEARS bumped from 5
to 10 so we cover FY16 → FY26 instead of FY21 → FY26. The pipeline is
idempotent thanks to the
  UNIQUE(ticker_nse, period_type, period_end_date, statement_type, source)
constraint on company_financials, so re-running is safe.

Resume support: tickers with >= --skip-threshold annual rows already in
company_financials are skipped. Default threshold is 8 annual rows
(empirical proxy for "we already pulled most of the 10Y window").

Usage:
    DATABASE_URL=... python scripts/backfill_xbrl_10y.py --top 500
    DATABASE_URL=... python scripts/backfill_xbrl_10y.py --tickers RELIANCE,TCS,INFY
    DATABASE_URL=... python scripts/backfill_xbrl_10y.py --all
    DATABASE_URL=... python scripts/backfill_xbrl_10y.py --top 500 --skip-existing

Runtime estimate (with the existing 2 sec yfinance + 3 sec NSE per
ticker):
    top-500 tickers, 10Y depth, both sources : ~4-5 hours
    top-500, --skip-nse                       : ~2 hours
    full universe (~2,500 tickers)            : ~14-18 hours

Sharding (SHARD_INDEX / SHARD_COUNT env vars, inherited from the
underlying pipeline.run() function) lets you split this across N
runners for ~N× wall-clock improvement.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("xbrl_10y")

DEFAULT_LOOKBACK = 10
DEFAULT_SKIP_THRESHOLD = 8


def _resolve_universe(args) -> list[str]:
    from sqlalchemy import text
    from data_pipeline.db import Session

    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]

    sess = Session()
    try:
        if args.all:
            rows = sess.execute(text(
                "SELECT s.ticker FROM stocks s "
                "WHERE s.is_active = TRUE "
                "ORDER BY s.ticker"
            )).fetchall()
        else:
            n = args.top or 500
            rows = sess.execute(text(
                "SELECT s.ticker FROM stocks s "
                "LEFT JOIN market_metrics mm ON mm.ticker = s.ticker "
                "WHERE s.is_active = TRUE "
                "ORDER BY COALESCE(mm.market_cap_cr, 0) DESC "
                "LIMIT :n"
            ), {"n": n}).fetchall()
        return [r[0] for r in rows if r and r[0]]
    finally:
        sess.close()


def _filter_already_done(tickers: list[str], threshold: int) -> list[str]:
    """Drop tickers that already have >= threshold annual rows.

    Uses company_financials (the legacy table the xbrl pipeline writes
    to via db_writer.upsert_records); the modern Financials ORM table
    is a different beast populated by data_pipeline.xbrl.bse_xbrl. We
    check both — a ticker is "done" if either side has enough history.
    """
    from sqlalchemy import text
    from data_pipeline.db import Session

    if not tickers:
        return tickers

    sess = Session()
    try:
        # company_financials uses ticker_nse + period_type='annual'
        rows = sess.execute(text(
            "SELECT ticker_nse, COUNT(DISTINCT period_end_date) AS n "
            "FROM company_financials "
            "WHERE period_type = 'annual' "
            "  AND ticker_nse = ANY(:tickers) "
            "GROUP BY ticker_nse"
        ), {"tickers": tickers}).fetchall()
        annual_counts = {r[0]: int(r[1] or 0) for r in rows}

        # Also check the modern Financials table (period_type stored as
        # 'annual' there too). Defensive — table may not exist on older DBs.
        try:
            rows2 = sess.execute(text(
                "SELECT ticker, COUNT(DISTINCT period_end) AS n "
                "FROM financials "
                "WHERE period_type = 'annual' "
                "  AND ticker = ANY(:tickers) "
                "GROUP BY ticker"
            ), {"tickers": tickers}).fetchall()
            for r in rows2:
                tk = r[0]
                annual_counts[tk] = max(annual_counts.get(tk, 0), int(r[1] or 0))
        except Exception as exc:
            logger.debug("financials check skipped: %s", exc)
    finally:
        sess.close()

    keep, skipped = [], 0
    for t in tickers:
        if annual_counts.get(t, 0) >= threshold:
            skipped += 1
            continue
        keep.append(t)
    logger.info(
        "skip-existing: dropped %d / %d tickers with >= %d annual rows",
        skipped, len(tickers), threshold,
    )
    return keep


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--top", type=int, help="Top-N tickers by market cap (default 500)")
    g.add_argument("--tickers", help="Comma-separated ticker list")
    g.add_argument("--all", action="store_true", help="Every active ticker")

    ap.add_argument("--lookback-years", type=int, default=DEFAULT_LOOKBACK,
                    help=f"Years of history to fetch (default {DEFAULT_LOOKBACK})")
    ap.add_argument("--skip-existing", action="store_true",
                    help="Skip tickers already at full depth (see --skip-threshold)")
    ap.add_argument("--skip-threshold", type=int, default=DEFAULT_SKIP_THRESHOLD,
                    help=f"Min annual rows to consider a ticker 'done' "
                         f"(default {DEFAULT_SKIP_THRESHOLD})")
    ap.add_argument("--skip-nse", action="store_true",
                    help="Skip the NSE quarterly supplement (faster yfinance-only)")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    # 1) Override LOOKBACK_YEARS BEFORE the pipeline imports it.
    #    pipeline.py does `from config import YFINANCE_DELAY` but
    #    yf_fetcher / nse_fetcher read LOOKBACK_YEARS at call time, so
    #    monkey-patching the config module here flows through.
    xbrl_dir = REPO_ROOT / "data_pipeline" / "xbrl"
    sys.path.insert(0, str(xbrl_dir))
    import config as xbrl_config  # type: ignore  # noqa: E402
    original = xbrl_config.LOOKBACK_YEARS
    xbrl_config.LOOKBACK_YEARS = args.lookback_years
    os.environ["LOOKBACK_YEARS"] = str(args.lookback_years)
    logger.info("LOOKBACK_YEARS: %d → %d", original, args.lookback_years)

    # 2) Resolve the ticker universe.
    universe = _resolve_universe(args)
    logger.info("universe size: %d tickers", len(universe))

    if args.skip_existing:
        universe = _filter_already_done(universe, args.skip_threshold)
        logger.info("after skip-existing: %d tickers remain", len(universe))

    if not universe:
        logger.info("nothing to do")
        return 0

    # 3) Hand off to the existing pipeline. It honours SHARD_INDEX /
    #    SHARD_COUNT env vars, and calling create_tables() is idempotent.
    from pipeline import run as run_pipeline  # type: ignore  # noqa: E402

    result = run_pipeline(
        tickers=universe,
        mode="custom_10y",
        skip_nse=args.skip_nse,
    )
    logger.info(
        "DONE — inserted=%d errors=%d failed=%d",
        result.get("inserted", 0),
        result.get("errors", 0),
        len(result.get("failed", []) or []),
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
