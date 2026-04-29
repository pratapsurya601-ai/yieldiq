"""Compute PE / PB / D-E / ROE locally — no downloads.

These four metrics are deterministic functions of values already in
``financials`` + ``market_metrics``:

    pe_ratio  = market_cap_cr / pat
    pb_ratio  = market_cap_cr / total_equity
    de_ratio  = total_debt    / total_equity
    roe       = pat           / total_equity * 100

yfinance's ``trailingPE`` / ``priceToBook`` are stale-cached and lag by
weeks for thinly-traded Indian symbols. Recomputing from our own
canonical financials gives faster + more accurate values for any
ticker that has both an annual financial row AND a recent market_cap.

This is a pure-SQL job — no per-ticker network IO, no yfinance, no
threading. Designed to run AFTER ``fetch_annual_financials`` so the
NSE XBRL rows are already in.

Usage:
    DATABASE_URL=$(sed -n '2p' .env.local) \\
        python -m scripts.data_pipelines.compute_derived_metrics
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date
from pathlib import Path

if __package__ in (None, ""):
    sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
    from scripts.data_pipelines import _common as C
else:
    from . import _common as C

logger = logging.getLogger(__name__)


# Single SQL statement that:
#   - finds the latest ANNUAL financials row per ticker
#   - finds the latest market_metrics row per ticker (for market_cap_cr)
#   - computes pe / pb / de / roe with NULLIF guards
#   - UPSERTs into market_metrics for trade_date = today
#
# We only OVERWRITE values that compute_derived produces (pe / pb /
# debt_equity / roe). Other columns on the same row (eg market_cap_cr)
# are preserved by the COALESCE on the conflict path.
COMPUTE_SQL = """
    WITH latest_fin AS (
        SELECT DISTINCT ON (ticker)
               ticker, pat, total_equity, total_debt
          FROM financials
         WHERE period_type = 'annual'
         ORDER BY ticker, period_end DESC
    ),
    latest_mc AS (
        SELECT DISTINCT ON (ticker)
               ticker, market_cap_cr
          FROM market_metrics
         WHERE market_cap_cr IS NOT NULL
         ORDER BY ticker, trade_date DESC
    )
    INSERT INTO market_metrics (ticker, trade_date, pe_ratio, pb_ratio,
                                debt_equity, roe)
    SELECT  f.ticker,
            :trade_date AS trade_date,
            CASE WHEN f.pat > 0
                 THEN m.market_cap_cr / NULLIF(f.pat, 0)
                 ELSE NULL END AS pe_ratio,
            CASE WHEN f.total_equity > 0
                 THEN m.market_cap_cr / NULLIF(f.total_equity, 0)
                 ELSE NULL END AS pb_ratio,
            CASE WHEN f.total_equity > 0
                 THEN f.total_debt / NULLIF(f.total_equity, 0)
                 ELSE NULL END AS debt_equity,
            CASE WHEN f.total_equity > 0
                 THEN (f.pat / NULLIF(f.total_equity, 0)) * 100.0
                 ELSE NULL END AS roe
      FROM latest_fin f
      JOIN latest_mc  m USING (ticker)
    ON CONFLICT (ticker, trade_date) DO UPDATE SET
        pe_ratio    = COALESCE(EXCLUDED.pe_ratio, market_metrics.pe_ratio),
        pb_ratio    = COALESCE(EXCLUDED.pb_ratio, market_metrics.pb_ratio),
        debt_equity = COALESCE(EXCLUDED.debt_equity, market_metrics.debt_equity),
        roe         = COALESCE(EXCLUDED.roe, market_metrics.roe)
"""


def compute(session, *, trade_date: date | None = None) -> int:
    """Run the compute. Returns # rows written."""
    from sqlalchemy import text
    trade_date = trade_date or date.today()
    res = session.execute(text(COMPUTE_SQL), {"trade_date": trade_date})
    n = res.rowcount or 0
    session.commit()
    return n


def coverage_stats(session) -> dict:
    """Pre-flight: how many tickers have the inputs needed?"""
    from sqlalchemy import text
    rows = session.execute(text("""
        SELECT
          (SELECT COUNT(DISTINCT ticker) FROM financials WHERE period_type='annual') AS fin_n,
          (SELECT COUNT(DISTINCT ticker) FROM market_metrics WHERE market_cap_cr IS NOT NULL) AS mc_n,
          (SELECT COUNT(*) FROM (
              SELECT DISTINCT f.ticker FROM financials f
                JOIN market_metrics m ON m.ticker = f.ticker
               WHERE f.period_type='annual' AND m.market_cap_cr IS NOT NULL
          ) t) AS both_n
    """)).fetchone()
    return {"financials_n": rows[0], "market_cap_n": rows[1], "joined_n": rows[2]}


# ── CLI ──────────────────────────────────────────────────────────────

def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="Print coverage stats without writing")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    C.setup_logging(logging.DEBUG if args.verbose else logging.INFO)
    try:
        C.get_database_url()
    except RuntimeError as e:
        logger.error("%s", e)
        return 2

    session = C.make_session()
    try:
        stats = coverage_stats(session)
        logger.info("coverage: financials=%d, market_cap=%d, joined=%d",
                    stats["financials_n"], stats["market_cap_n"], stats["joined_n"])
        if args.dry_run:
            print(stats)
            return 0
        n = compute(session)
        logger.info("compute_derived_metrics: %d rows upserted", n)
        print(f"compute_derived_metrics: {n} rows upserted")
    finally:
        session.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
