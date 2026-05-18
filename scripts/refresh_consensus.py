"""Refresh `consensus_estimates` table from yfinance + Finnhub.

Nightly entry point invoked by `.github/workflows/cron-consensus-refresh.yml`.

What it does
------------
1. Loads the top-N tickers by market cap from the `stocks` /
   `market_metrics` join (no dependency on a static text file).
2. Pulls yfinance `.info` consensus targets for the top
   `--limit-yfinance` tickers (default 1500).
3. Pulls Finnhub `/stock/price-target` for the top `--limit-finnhub`
   tickers (default 500), rate-limited to <=60 req/min.
4. UPSERTs each result into `consensus_estimates` with
   `ON CONFLICT DO NOTHING` — re-running for the same
   (ticker, source, fetched_at) is a no-op.

Idempotency
-----------
The primary key (ticker, source, fetched_at) plus
`ON CONFLICT DO NOTHING` means re-running with frozen time produces
zero duplicate rows. We snapshot `pre_count` and emit a diff so the
GH Actions log shows exactly how many rows were added.

Cost / coverage logging
-----------------------
At the end the script logs JSON metrics:

    {"yfinance": {"attempted": 1500, "wrote": 1418, "skipped": 82},
     "finnhub":  {"attempted":  500, "wrote":  463, "skipped": 37},
     "rows_added_total": 1881}

No CACHE_VERSION bump — consensus does not enter the analysis_cache key.

Usage
-----
    DATABASE_URL=... FINNHUB_API_KEY=... \\
        python scripts/refresh_consensus.py \\
            --limit-yfinance 1500 \\
            --limit-finnhub 500
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Iterable, Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from data_pipeline.sources import consensus_finnhub, consensus_yfinance  # noqa: E402

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("refresh_consensus")


# Stay well under Finnhub free tier (60/min). 1.1s gives ~54/min.
_FINNHUB_SLEEP_S = 1.1
# yfinance has a soft ~2k/hr cap; 0.1s gives ~36k/hr nominal but the .info
# call itself takes ~250ms so the effective rate is ~3/sec. Plenty safe.
_YFINANCE_SLEEP_S = 0.05


# ── Ticker selection ────────────────────────────────────────────────


def _load_top_tickers(sess, limit: int) -> list[str]:
    """Top-N tickers by latest market_cap_cr. Active stocks only."""
    sql = text("""
        SELECT s.ticker
        FROM stocks s
        LEFT JOIN (
            SELECT DISTINCT ON (ticker) ticker, market_cap_cr
            FROM market_metrics
            ORDER BY ticker, trade_date DESC
        ) mm USING (ticker)
        WHERE s.is_active = true
        ORDER BY mm.market_cap_cr DESC NULLS LAST
        LIMIT :n
    """)
    return [r[0] for r in sess.execute(sql, {"n": limit}).fetchall()]


# ── UPSERT ──────────────────────────────────────────────────────────

_UPSERT_SQL = text("""
    INSERT INTO consensus_estimates (
        ticker, source,
        target_mean, target_median, target_high, target_low,
        analyst_count, currency
    )
    VALUES (
        :ticker, :source,
        :target_mean, :target_median, :target_high, :target_low,
        :analyst_count, :currency
    )
    ON CONFLICT (ticker, source, fetched_at) DO NOTHING
""")


def _write_row(sess, row) -> bool:
    res = sess.execute(_UPSERT_SQL, {
        "ticker":        row["ticker"],
        "source":        row["source"],
        "target_mean":   row.get("target_mean"),
        "target_median": row.get("target_median"),
        "target_high":   row.get("target_high"),
        "target_low":    row.get("target_low"),
        "analyst_count": row.get("analyst_count"),
        "currency":      row.get("currency") or "INR",
    })
    return (res.rowcount or 0) > 0


# ── Passes ──────────────────────────────────────────────────────────


def _pass_yfinance(
    sess, tickers: Iterable[str], *, yf_module=None,
    sleep_s: float = _YFINANCE_SLEEP_S,
) -> dict:
    attempted = wrote = skipped = 0
    for t in tickers:
        attempted += 1
        try:
            row = consensus_yfinance.fetch_one(t, yf_module=yf_module)
        except Exception as e:  # noqa: BLE001
            logger.warning("yfinance fetch raised for %s: %s", t, e)
            skipped += 1
            continue
        if row is None:
            skipped += 1
        else:
            if _write_row(sess, row):
                wrote += 1
            else:
                skipped += 1
        if sleep_s:
            time.sleep(sleep_s)
    sess.commit()
    return {"attempted": attempted, "wrote": wrote, "skipped": skipped}


def _pass_finnhub(
    sess, tickers: Iterable[str], *, requests_module=None,
    api_key: Optional[str] = None, sleep_s: float = _FINNHUB_SLEEP_S,
) -> dict:
    attempted = wrote = skipped = 0
    for t in tickers:
        attempted += 1
        try:
            row = consensus_finnhub.fetch_one(
                t, api_key=api_key, requests_module=requests_module,
            )
        except Exception as e:  # noqa: BLE001
            logger.warning("finnhub fetch raised for %s: %s", t, e)
            skipped += 1
            continue
        if row is None:
            skipped += 1
        else:
            if _write_row(sess, row):
                wrote += 1
            else:
                skipped += 1
        if sleep_s:
            time.sleep(sleep_s)
    sess.commit()
    return {"attempted": attempted, "wrote": wrote, "skipped": skipped}


# ── Main ────────────────────────────────────────────────────────────


def _count_rows(sess) -> int:
    return int(sess.execute(text("SELECT COUNT(*) FROM consensus_estimates")).scalar() or 0)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit-yfinance", type=int, default=1500)
    parser.add_argument("--limit-finnhub", type=int, default=500)
    parser.add_argument(
        "--skip-yfinance", action="store_true", help="Skip the yfinance pass entirely.",
    )
    parser.add_argument(
        "--skip-finnhub", action="store_true", help="Skip the Finnhub pass entirely.",
    )
    parser.add_argument(
        "--database-url", default=os.environ.get("DATABASE_URL"),
        help="Postgres URL (default: $DATABASE_URL).",
    )
    args = parser.parse_args(argv)

    if not args.database_url:
        logger.error("DATABASE_URL not set")
        return 2

    engine = create_engine(args.database_url, future=True)
    Session = sessionmaker(bind=engine, future=True)
    sess = Session()

    try:
        pre_count = _count_rows(sess)

        yf_tickers = (
            _load_top_tickers(sess, args.limit_yfinance) if not args.skip_yfinance else []
        )
        fh_tickers = (
            _load_top_tickers(sess, args.limit_finnhub) if not args.skip_finnhub else []
        )

        logger.info(
            "starting refresh: yfinance=%d tickers, finnhub=%d tickers (pre_count=%d)",
            len(yf_tickers), len(fh_tickers), pre_count,
        )

        yf_stats = _pass_yfinance(sess, yf_tickers) if yf_tickers else {
            "attempted": 0, "wrote": 0, "skipped": 0,
        }
        fh_stats = _pass_finnhub(sess, fh_tickers) if fh_tickers else {
            "attempted": 0, "wrote": 0, "skipped": 0,
        }

        post_count = _count_rows(sess)
        metrics = {
            "yfinance": yf_stats,
            "finnhub": fh_stats,
            "rows_added_total": post_count - pre_count,
            "table_row_count": post_count,
        }
        logger.info("consensus_refresh metrics: %s", json.dumps(metrics))

        # Fail-loud guard from design §4: skip rate > 25% on yfinance pass.
        if yf_stats["attempted"] >= 100:
            skip_rate = yf_stats["skipped"] / yf_stats["attempted"]
            if skip_rate > 0.25:
                logger.error(
                    "yfinance skip rate %.1f%% exceeds 25%% threshold", skip_rate * 100,
                )
                return 3

        return 0
    finally:
        sess.close()


if __name__ == "__main__":
    raise SystemExit(main())
