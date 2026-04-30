"""Backfill corporate_actions via yfinance splits feed.

The existing download_corporate_actions in data_pipeline.sources.nse_bhavcopy
hard-codes adjustment_factor=1.0 (useless for price adjustment) and parses
the NSE "subject" string as both action_type and ratio.

yfinance exposes clean splits and dividends feeds:
    Ticker("RELIANCE.NS").splits    → pandas Series indexed by date, values = factor
    Ticker("RELIANCE.NS").dividends → same shape, values = dividend amount

Splits come through as a factor directly — e.g., a 1:1 bonus shows as 2.0
(each share became 2), a 1:10 split shows as 10.0. That IS the
adjustment_factor we need.

Usage:
    DATABASE_URL=... python scripts/backfill_corporate_actions_yf.py --all
    DATABASE_URL=... python scripts/backfill_corporate_actions_yf.py --top 500
    DATABASE_URL=... python scripts/backfill_corporate_actions_yf.py --tickers RELIANCE,TCS

Rate-limited to be polite to Yahoo.
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("corp_actions_backfill")


def _load_tickers(sess, args) -> list[str]:
    if args.tickers:
        return [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    if args.top:
        sql = text("""
            SELECT s.ticker FROM stocks s
            LEFT JOIN (
                SELECT DISTINCT ON (ticker) ticker, market_cap_cr
                FROM market_metrics ORDER BY ticker, trade_date DESC
            ) mm USING (ticker)
            WHERE s.is_active = true
            ORDER BY mm.market_cap_cr DESC NULLS LAST
            LIMIT :n
        """)
        return [r[0] for r in sess.execute(sql, {"n": args.top}).fetchall()]
    # --all
    return [r[0] for r in sess.execute(
        text("SELECT ticker FROM stocks WHERE is_active = true ORDER BY ticker")
    ).fetchall()]


# ── per-row source precedence ────────────────────────────────────────
# Mirrors scripts/data_pipelines/fetch_corporate_actions.py and
# db/migrations/010_corporate_actions_quality_rank.sql. yfinance is
# rank 50 — strictly worse than any NSE-sourced row, so this script
# can no longer demote existing NSE rows even after the migration.
_RANK_BY_SOURCE = {
    "NSE_CORP_ANN":  10,
    "NSE_ARCHIVE":   15,
    "BSE_CORP_FILE": 30,
    "finnhub":       40,
    "yfinance":      50,
}


def _rank_for(source: str | None) -> int:
    return _RANK_BY_SOURCE.get(source or "", 60)


# UPSERT precedence guard: yfinance rows (rank 50) cannot overwrite
# a lower-rank NSE row for the same (ticker, ex_date, action_type).
# Backed by uq_corporate_actions_natural_key (migration 010).
UPSERT_SQL = text("""
    INSERT INTO corporate_actions
        (ticker, action_type, ex_date, ratio, remarks, adjustment_factor,
         data_source, data_quality_rank)
    VALUES
        (:ticker, :action_type, :ex_date, :ratio, :remarks, :adjustment_factor,
         :data_source, :data_quality_rank)
    ON CONFLICT (ticker, ex_date, action_type) DO UPDATE SET
        ratio = CASE WHEN EXCLUDED.data_quality_rank <= corporate_actions.data_quality_rank
                     THEN COALESCE(EXCLUDED.ratio, corporate_actions.ratio)
                     ELSE corporate_actions.ratio END,
        remarks = CASE WHEN EXCLUDED.data_quality_rank <= corporate_actions.data_quality_rank
                       THEN COALESCE(EXCLUDED.remarks, corporate_actions.remarks)
                       ELSE corporate_actions.remarks END,
        adjustment_factor = CASE WHEN EXCLUDED.data_quality_rank <= corporate_actions.data_quality_rank
                                 THEN COALESCE(EXCLUDED.adjustment_factor, corporate_actions.adjustment_factor)
                                 ELSE corporate_actions.adjustment_factor END,
        data_source = CASE WHEN EXCLUDED.data_quality_rank <= corporate_actions.data_quality_rank
                           THEN COALESCE(EXCLUDED.data_source, corporate_actions.data_source)
                           ELSE corporate_actions.data_source END,
        data_quality_rank = LEAST(EXCLUDED.data_quality_rank, corporate_actions.data_quality_rank)
""")


def process_ticker(sess, ticker: str) -> dict:
    """Returns {splits, dividends, errors}."""
    try:
        import yfinance as yf
    except ImportError:
        logger.error("yfinance not installed")
        return {"splits": 0, "dividends": 0, "errors": 1}

    symbol = f"{ticker}.NS"
    try:
        yt = yf.Ticker(symbol)
        splits = yt.splits           # pandas Series
        divs = yt.dividends          # pandas Series
    except Exception as e:
        logger.warning("%s: yf fetch failed: %s", ticker, e)
        return {"splits": 0, "dividends": 0, "errors": 1}

    rows_to_insert: list[dict] = []

    # Splits / bonuses
    if splits is not None and len(splits) > 0:
        for ex, factor in splits.items():
            try:
                ex_d = ex.date() if hasattr(ex, "date") else date.fromisoformat(str(ex)[:10])
                f = float(factor)
                if f <= 0 or f > 100:
                    continue   # sanity — ignore weird values
                action_type = "SPLIT" if f < 1 else "BONUS_OR_SPLIT"
                # yfinance represents both splits and bonuses as a single factor
                # (e.g. 1:1 bonus → 2.0, 1:5 split → 5.0). Both expand shares
                # post-event, so we store factor uniformly; the action_type
                # label is informational.
                rows_to_insert.append({
                    "ticker": ticker,
                    "action_type": action_type,
                    "ex_date": ex_d,
                    "ratio": f"factor={f:g}",
                    "remarks": f"yfinance splits: {f:g}",
                    "adjustment_factor": f,
                    "data_source": "yfinance",
                    "data_quality_rank": _rank_for("yfinance"),
                })
            except Exception:
                continue

    # Dividends
    if divs is not None and len(divs) > 0:
        for ex, amt in divs.items():
            try:
                ex_d = ex.date() if hasattr(ex, "date") else date.fromisoformat(str(ex)[:10])
                a = float(amt)
                if a <= 0:
                    continue
                rows_to_insert.append({
                    "ticker": ticker,
                    "action_type": "DIVIDEND",
                    "ex_date": ex_d,
                    "ratio": f"Rs {a:.4f}",
                    "remarks": f"yfinance dividend Rs {a:.4f}",
                    "adjustment_factor": 1.0,   # dividends don't adjust the share count
                    "data_source": "yfinance",
                    "data_quality_rank": _rank_for("yfinance"),
                })
            except Exception:
                continue

    if not rows_to_insert:
        return {"splits": 0, "dividends": 0, "errors": 0}

    # ON CONFLICT precedence guard (migration 010): yfinance rows
    # (rank 50) can no longer demote an existing NSE_CORP_ANN row
    # (rank 10) for the same (ticker, ex_date, action_type). Replaces
    # the old DELETE-then-INSERT, which silently lost NSE provenance.
    try:
        for r in rows_to_insert:
            sess.execute(UPSERT_SQL, r)
        sess.commit()
    except Exception as e:
        logger.error("%s: commit failed: %s", ticker, e)
        sess.rollback()
        return {"splits": 0, "dividends": 0, "errors": 1}

    n_splits = sum(1 for r in rows_to_insert if r["action_type"] != "DIVIDEND")
    n_divs = sum(1 for r in rows_to_insert if r["action_type"] == "DIVIDEND")
    return {"splits": n_splits, "dividends": n_divs, "errors": 0}


def main() -> int:
    ap = argparse.ArgumentParser()
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--all", action="store_true")
    g.add_argument("--top", type=int, help="Top-N by market cap")
    g.add_argument("--tickers", default=None)
    ap.add_argument("--sleep", type=float, default=0.5)
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]

    engine = create_engine(url, pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    sess = Session()

    tickers = _load_tickers(sess, args)
    logger.info("processing %d tickers", len(tickers))

    totals = {"splits": 0, "dividends": 0, "errors": 0}
    n_with_splits = 0

    for i, t in enumerate(tickers, 1):
        r = process_ticker(sess, t)
        for k, v in r.items():
            totals[k] = totals.get(k, 0) + v
        if r["splits"]:
            n_with_splits += 1
        if i % 50 == 0:
            logger.info(
                "[%d/%d] splits=%d dividends=%d errors=%d (tickers with splits=%d)",
                i, len(tickers), totals["splits"], totals["dividends"],
                totals["errors"], n_with_splits,
            )
        time.sleep(args.sleep)

    logger.info(
        "done. splits=%d dividends=%d errors=%d (tickers with splits=%d)",
        totals["splits"], totals["dividends"], totals["errors"], n_with_splits,
    )
    sess.close()
    engine.dispose()
    return 0


if __name__ == "__main__":
    sys.exit(main())
