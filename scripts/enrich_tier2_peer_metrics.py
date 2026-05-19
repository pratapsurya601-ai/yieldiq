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


def _fetch_piotroski(sess, ticker: str, sector: str = "") -> Optional[int]:
    """Compute Piotroski via screener.piotroski.compute_piotroski_fscore.

    Long-term fix (2026-05-19): the screener's signal functions expect
    a richly-enriched dict with pandas DataFrames (income_df, cf_df) and
    canonical flat-field key names (lt_debt_prev, total_assets_prev,
    shares_prev_year, etc.). We build that here from two annual rows of
    ``financials`` — the same shape the analysis pipeline assembles in
    backend/services/analysis/service.py.

    Schema mapping (financials table, verified 2026-05-19):
        pat                  → income_df.net_income
        ebit                 → income_df.operating_income
        revenue              → income_df.revenue
        revenue*gross_margin → income_df.gross_profit (derived)
        cfo                  → cf_df.ocf
        free_cash_flow       → cf_df.fcf  (also used for latest_fcf)
        total_debt           → lt_debt / total_debt (no LT/ST split in schema)
        cash_and_equivalents → total_cash
        shares_outstanding   → shares
        debt_to_equity       → de_ratio
        roe                  → roe (fallback for f1 when ROA unavailable)
        fcf_growth_yoy       → fcf_growth (fallback for f9)
    Missing (current_assets) → f6 falls back to cash/debt ratio.

    Sector/industry classification matters: bank-like tickers run a
    4-signal reduced Piotroski (banks fail f4/f5/f6/f8/f9 mechanically
    because of their balance-sheet structure). We pass the cohort
    sector key so `is_bank_like` routes correctly.
    """
    import pandas as pd
    try:
        from screener.piotroski import compute_piotroski_fscore
    except Exception:
        return None
    db_t = _db_ticker(ticker)
    try:
        rows = sess.execute(text("""
            SELECT pat, ebit, revenue, gross_margin,
                   cfo, free_cash_flow,
                   total_assets, total_debt, cash_and_equivalents,
                   shares_outstanding, debt_to_equity, roe,
                   fcf_growth_yoy, current_liabilities,
                   period_end
            FROM financials
            WHERE ticker = :t
              AND period_type = 'annual'
              AND period_end IS NOT NULL
            ORDER BY period_end DESC
            LIMIT 2
        """), {"t": db_t}).mappings().all()
    except Exception as exc:
        logger.warning("piotroski rows fetch failed for %s: %s", ticker, exc)
        try:
            sess.rollback()
        except Exception:
            pass
        return None
    if not rows:
        return None

    def _f(v):
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    def _norm_pct(v):
        # gross_margin / roe etc. may be stored as percentage (e.g. 25.4)
        # or as a decimal (e.g. 0.254). Anything with |v| > 1.5 is almost
        # certainly stored as percent; rescale to decimal.
        if v is None:
            return None
        return v / 100.0 if abs(v) > 1.5 else v

    # Build chronologically-ordered DataFrames so _series_last (.iloc[-1])
    # picks up the most recent row, _series_prev (.iloc[-2]) picks the
    # prior. We pulled DESC so reverse to ascending.
    ordered = list(reversed(rows))
    income_data = []
    cf_data = []
    for r in ordered:
        rev = _f(r.get("revenue"))
        gm = _norm_pct(_f(r.get("gross_margin")))
        gp = (rev * gm) if (rev is not None and gm is not None) else None
        income_data.append({
            "net_income":       _f(r.get("pat")),
            "operating_income": _f(r.get("ebit")),
            "revenue":          rev,
            "gross_profit":     gp,
        })
        cf_data.append({
            "ocf": _f(r.get("cfo")),
            "fcf": _f(r.get("free_cash_flow")),
        })

    income_df = pd.DataFrame(income_data)
    cf_df = pd.DataFrame(cf_data)

    latest = rows[0]
    prev = rows[1] if len(rows) > 1 else {}

    enriched = {
        "ticker":             ticker,
        "sector":             sector,
        "industry":           sector,  # cohort key doubles as industry hint
        "income_df":          income_df,
        "cf_df":              cf_df,
        # Flat fields the signal helpers read directly via .get(...).
        "total_assets":       _f(latest.get("total_assets")),
        "total_assets_prev":  _f(prev.get("total_assets")),
        "lt_debt":            _f(latest.get("total_debt")),
        "lt_debt_prev":       _f(prev.get("total_debt")),
        "total_debt":         _f(latest.get("total_debt")),
        "total_cash":         _f(latest.get("cash_and_equivalents")),
        "de_ratio":           _f(latest.get("debt_to_equity")),
        "shares":             _f(latest.get("shares_outstanding")),
        "shares_prev_year":   _f(prev.get("shares_outstanding")),
        "latest_fcf":         _f(latest.get("free_cash_flow")),
        "latest_revenue":     _f(latest.get("revenue")),
        "roe":                _norm_pct(_f(latest.get("roe"))),
        "fcf_growth":         _norm_pct(_f(latest.get("fcf_growth_yoy"))),
        "gross_margin":       _norm_pct(_f(latest.get("gross_margin"))),
        # current_ratio / current_ratio_prev intentionally absent — the
        # financials table has no current_assets column. f6 falls back
        # to cash/(debt+1) which still produces a meaningful signal.
    }

    try:
        result = compute_piotroski_fscore(enriched)
        if isinstance(result, dict):
            sc = result.get("score")
            return int(sc) if sc is not None else None
        return None
    except Exception as exc:
        logger.warning("piotroski compute failed for %s: %s", ticker, exc)
        return None


# ── Driver ───────────────────────────────────────────────────────
def _all_cohort_tickers() -> list[tuple[str, str]]:
    """Return [(ticker, sector_key), ...] with first-seen sector winning."""
    seen: set[str] = set()
    out: list[tuple[str, str]] = []
    for sector_key, peers in DIRECT_PEERS.items():
        for t in peers:
            if t not in seen:
                seen.add(t)
                out.append((t, sector_key))
    return out


def _sector_counts() -> dict[str, int]:
    return {k: len(v) for k, v in DIRECT_PEERS.items()}


def enrich_one(sess, ticker: str, sector: str = "") -> dict:
    roce = _fetch_roce_pct(sess, ticker)
    piotroski = _fetch_piotroski(sess, ticker, sector=sector)
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
        # CLI subset — try to recover sector from DIRECT_PEERS, else "".
        wanted = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        ticker_to_sector: dict[str, str] = {}
        for sec, peers in DIRECT_PEERS.items():
            for t in peers:
                ticker_to_sector.setdefault(t.upper(), sec)
        ticker_pairs: list[tuple[str, str]] = [
            (t, ticker_to_sector.get(t, "")) for t in wanted
        ]
    else:
        ticker_pairs = _all_cohort_tickers()

    logger.info(
        "enriching %d tier-2 cohort peers (sectors=%d, dry_run=%s)",
        len(ticker_pairs), len(DIRECT_PEERS), args.dry_run,
    )

    n_written = 0
    n_failed = 0
    bucket_counter: Counter[str] = Counter()
    coverage = {"roce": 0, "piotroski": 0, "market_cap_cr": 0}
    rows_for_summary: list[dict] = []

    for i, (t, sec) in enumerate(ticker_pairs, 1):
        try:
            rec = enrich_one(sess, t, sector=sec)
        except Exception as exc:
            logger.warning("%s: enrich failed: %s", t, exc)
            try:
                sess.rollback()
            except Exception:
                pass
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
                i, len(ticker_pairs), n_written, n_failed, dict(bucket_counter),
            )

    summary = {
        "total_tickers": len(ticker_pairs),
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
