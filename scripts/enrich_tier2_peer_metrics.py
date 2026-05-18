"""Populate tier2_peer_metrics for the curated Tier 2 cohort peers.

Reads every ticker from screener.sector_relative.DIRECT_PEERS, computes
ROCE / Piotroski / market_cap_cr from existing tables (financials,
company_financials, market_metrics), assigns a Premium/Core/Tail
quality_bucket using the same thresholds as the Tier 2 service, and
upserts into tier2_peer_metrics.

Usage:
    DATABASE_URL=... python scripts/enrich_tier2_peer_metrics.py
    DATABASE_URL=... python scripts/enrich_tier2_peer_metrics.py --tickers TCS.NS,INFY.NS
    DATABASE_URL=... python scripts/enrich_tier2_peer_metrics.py --dry-run

Prints a JSON summary of buckets populated. Idempotent — running again
overwrites prior rows with the latest computed values and refreshes the
refreshed_at timestamp.

Hard rules honoured:
  * Additive table only; no CACHE_VERSION bump.
  * Read-only against financials / company_financials / market_metrics.
  * No long-running side effects — single pass over ~120 tickers.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import Counter
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from screener.sector_relative import DIRECT_PEERS  # noqa: E402
from backend.services.ratios_service import compute_roce  # noqa: E402
from backend.services.tier2_cohort_valuation_service import (  # noqa: E402
    _bucket_for,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("tier2_peer_enrich")


# ── DB helpers ───────────────────────────────────────────────────
def _normalize_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _db_ticker(t: str) -> str:
    """Strip .NS / .BO suffix to match financials.ticker convention."""
    return (t or "").replace(".NS", "").replace(".BO", "").upper()


# ── Per-peer fetchers ────────────────────────────────────────────
ROCE_INPUTS_SQL = text("""
    SELECT ebit, ebitda, total_assets, current_liabilities
    FROM financials
    WHERE ticker = :t
      AND period_type = 'annual'
      AND period_end IS NOT NULL
    ORDER BY
      (current_liabilities IS NOT NULL) DESC,
      (total_assets IS NOT NULL) DESC,
      (ebit IS NOT NULL OR ebitda IS NOT NULL) DESC,
      period_end DESC
    LIMIT 1
""")

MARKET_CAP_SQL = text("""
    SELECT market_cap_cr
    FROM market_metrics
    WHERE ticker = :t
      AND market_cap_cr IS NOT NULL
    ORDER BY trade_date DESC
    LIMIT 1
""")

UPSERT_SQL = text("""
    INSERT INTO tier2_peer_metrics
        (ticker, roce_pct, piotroski, market_cap_cr, quality_bucket, refreshed_at)
    VALUES
        (:ticker, :roce_pct, :piotroski, :market_cap_cr, :quality_bucket, now())
    ON CONFLICT (ticker) DO UPDATE SET
        roce_pct       = EXCLUDED.roce_pct,
        piotroski      = EXCLUDED.piotroski,
        market_cap_cr  = EXCLUDED.market_cap_cr,
        quality_bucket = EXCLUDED.quality_bucket,
        refreshed_at   = now()
""")


def _fetch_roce_pct(sess, ticker: str) -> Optional[float]:
    db_t = _db_ticker(ticker)
    row = sess.execute(ROCE_INPUTS_SQL, {"t": db_t}).mappings().first()
    if not row:
        return None
    ebit = row.get("ebit") or row.get("ebitda")
    ta = row.get("total_assets")
    cl = row.get("current_liabilities")
    return compute_roce(ebit, ta, cl)


def _fetch_market_cap_cr(sess, ticker: str) -> Optional[float]:
    """Try the bare ticker first, then the suffix form. market_metrics
    storage convention varies across rows."""
    for cand in (_db_ticker(ticker), ticker):
        row = sess.execute(MARKET_CAP_SQL, {"t": cand}).mappings().first()
        if row and row.get("market_cap_cr") is not None:
            try:
                return float(row["market_cap_cr"])
            except (TypeError, ValueError):
                continue
    return None


def _fetch_piotroski(sess, ticker: str) -> Optional[int]:
    """Compute Piotroski via screener.piotroski.compute_piotroski_fscore.

    The screener function expects an 'enriched' dict — we don't rebuild
    the full enrichment here (that's the analysis pipeline's job). For
    the cohort peers we approximate the F-score from the persisted
    annual financials row only, and degrade to None when inputs are
    insufficient. The Tier 2 service treats None as "unknown" and never
    promotes a peer with unknown Piotroski to Premium.
    """
    try:
        from screener.piotroski import compute_piotroski_fscore
    except Exception:
        return None
    db_t = _db_ticker(ticker)
    try:
        row = sess.execute(text("""
            SELECT net_income, operating_cf, total_assets,
                   total_debt, current_assets, current_liabilities,
                   shares, revenue, gross_profit, period_end
            FROM financials
            WHERE ticker = :t
              AND period_type = 'annual'
              AND period_end IS NOT NULL
            ORDER BY period_end DESC
            LIMIT 2
        """), {"t": db_t}).mappings().all()
    except Exception as exc:
        logger.debug("piotroski rows fetch failed for %s: %s", ticker, exc)
        return None
    if not row:
        return None
    latest = row[0]
    prev = row[1] if len(row) > 1 else {}

    def _num(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    ni = _num(latest.get("net_income"))
    cfo = _num(latest.get("operating_cf"))
    ta = _num(latest.get("total_assets"))
    ta_prev = _num(prev.get("total_assets"))
    td = _num(latest.get("total_debt"))
    td_prev = _num(prev.get("total_debt"))
    ca = _num(latest.get("current_assets"))
    cl = _num(latest.get("current_liabilities"))
    ca_prev = _num(prev.get("current_assets"))
    cl_prev = _num(prev.get("current_liabilities"))
    shares = _num(latest.get("shares"))
    shares_prev = _num(prev.get("shares"))
    rev = _num(latest.get("revenue"))
    rev_prev = _num(prev.get("revenue"))
    gp = _num(latest.get("gross_profit"))
    gp_prev = _num(prev.get("gross_profit"))

    enriched = {
        "ticker": ticker,
        "net_income": ni,
        "operating_cf": cfo,
        "total_assets": ta,
        "prev_total_assets": ta_prev,
        "total_debt": td,
        "prev_total_debt": td_prev,
        "current_assets": ca,
        "current_liabilities": cl,
        "prev_current_assets": ca_prev,
        "prev_current_liabilities": cl_prev,
        "shares": shares,
        "prev_shares": shares_prev,
        "revenue": rev,
        "prev_revenue": rev_prev,
        "gross_profit": gp,
        "prev_gross_profit": gp_prev,
        "sector": "",
    }
    try:
        result = compute_piotroski_fscore(enriched)
        if isinstance(result, dict):
            sc = result.get("score")
            return int(sc) if sc is not None else None
        return None
    except Exception as exc:
        logger.debug("piotroski compute failed for %s: %s", ticker, exc)
        return None


# ── Driver ───────────────────────────────────────────────────────
def _all_cohort_tickers() -> list[str]:
    seen: set[str] = set()
    out: list[str] = []
    for peers in DIRECT_PEERS.values():
        for t in peers:
            if t not in seen:
                seen.add(t)
                out.append(t)
    return out


def _sector_counts() -> dict[str, int]:
    return {k: len(v) for k, v in DIRECT_PEERS.items()}


def enrich_one(sess, ticker: str) -> dict:
    roce = _fetch_roce_pct(sess, ticker)
    piotroski = _fetch_piotroski(sess, ticker)
    mcap = _fetch_market_cap_cr(sess, ticker)
    bucket = _bucket_for(roce, piotroski, mcap)
    return {
        "ticker": ticker,
        "roce_pct": roce,
        "piotroski": piotroski,
        "market_cap_cr": mcap,
        "quality_bucket": bucket,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--tickers", default=None,
        help="comma-separated subset; default = all DIRECT_PEERS",
    )
    ap.add_argument(
        "--dry-run", action="store_true",
        help="compute but do not write",
    )
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("error: DATABASE_URL not set", file=sys.stderr)
        return 2
    engine = create_engine(_normalize_url(url), pool_pre_ping=True)
    Session = sessionmaker(bind=engine)
    sess = Session()

    if args.tickers:
        tickers = [
            t.strip().upper() for t in args.tickers.split(",") if t.strip()
        ]
    else:
        tickers = _all_cohort_tickers()

    logger.info(
        "enriching %d tier-2 cohort peers (sectors=%d, dry_run=%s)",
        len(tickers), len(DIRECT_PEERS), args.dry_run,
    )

    n_written = 0
    n_failed = 0
    bucket_counter: Counter[str] = Counter()
    coverage = {"roce": 0, "piotroski": 0, "market_cap_cr": 0}
    rows_for_summary: list[dict] = []

    for i, t in enumerate(tickers, 1):
        try:
            rec = enrich_one(sess, t)
        except Exception as exc:
            logger.warning("%s: enrich failed: %s", t, exc)
            n_failed += 1
            continue

        bucket_counter[rec["quality_bucket"]] += 1
        if rec["roce_pct"] is not None:
            coverage["roce"] += 1
        if rec["piotroski"] is not None:
            coverage["piotroski"] += 1
        if rec["market_cap_cr"] is not None:
            coverage["market_cap_cr"] += 1
        rows_for_summary.append(rec)

        if not args.dry_run:
            try:
                sess.execute(UPSERT_SQL, rec)
                sess.commit()
                n_written += 1
            except Exception as exc:
                logger.warning("%s: upsert failed: %s", t, exc)
                sess.rollback()
                n_failed += 1

        if i % 25 == 0:
            logger.info(
                "[%d/%d] written=%d failed=%d buckets=%s",
                i, len(tickers), n_written, n_failed, dict(bucket_counter),
            )

    summary = {
        "total_tickers": len(tickers),
        "written": n_written,
        "failed": n_failed,
        "dry_run": bool(args.dry_run),
        "bucket_distribution": dict(bucket_counter),
        "field_coverage": coverage,
        "sector_counts": _sector_counts(),
    }
    print(json.dumps(summary, indent=2, default=str))
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
