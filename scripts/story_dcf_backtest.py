"""Back-testing harness for the Story-DCF engine.

Purpose
═══════
The 10 platform/fintech tickers in ``config/story_dcf_overrides.json``
ship with APPROXIMATE operator-curated parameters (per the
``_NOTE_2026_05_19_DAY6`` field). Until those are validated against
real-world data, the story-DCF rescue can produce FVs that drift far
from CMP. This script makes the drift visible and actionable.

For each ticker with a story-DCF override (or that lives in a
story-DCF-eligible sector via ``INDUSTRY_STORY_DEFAULTS``), it:

  1. Pulls the latest annual revenue + shares + closing price from
     ``financials`` / ``market_metrics``.
  2. Pulls up to 5 prior years of annual revenue to compute an
     observed historical CAGR.
  3. Runs ``compute_story_dcf_fair_value`` with the live overrides.
  4. Builds a comparison row:
       - FV from story-DCF
       - CMP from market_metrics
       - FV/CMP ratio
       - observed_cagr vs assumed initial_growth
       - flag: NEEDS_REVIEW if FV/CMP outside [0.30, 3.5] OR
         |assumed_g - observed_cagr| > 0.15

Output: ``scripts/snapshots/story_dcf_backtest_<YYYYMMDD>.json``
plus a human-readable Markdown table written to stdout.

Why this is a "back-test" and not a forward simulation
──────────────────────────────────────────────────────
Most of these names IPO'd in 2021-2024 (PAYTM-2021, NYKAA-2021,
ZOMATO-2021, NUVAMA-2023, MEESHO/SWIGGY-2024-25). There is not
enough history to do a true 5-year forward-rolling back-test.
What we CAN do — and what this script does — is compare the
operator's assumed initial_growth to the actual recent CAGR. A
large gap means the override needs revision before it ships any
more rescue FVs to production.

Hard rules honoured
───────────────────
* Read-only against financials / market_metrics
* No CACHE_VERSION bump
* Idempotent — running again overwrites the JSON snapshot

Usage
─────
    DATABASE_URL=... python scripts/story_dcf_backtest.py
    DATABASE_URL=... python scripts/story_dcf_backtest.py --tickers PAYTM,ZOMATO
    DATABASE_URL=... python scripts/story_dcf_backtest.py --json-only
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import logging
import math
import os
import sys
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from backend.services.story_dcf_engine import (  # noqa: E402
    INDUSTRY_STORY_DEFAULTS,
    _load_overrides,
    _params_for,
    _SECTOR_TO_INDUSTRY_KEY,
    compute_story_dcf_fair_value,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("story_dcf_backtest")

# Flag thresholds
FV_CMP_LO = 0.30      # safety-net rescue band lower bound
FV_CMP_HI = 3.50      # safety-net rescue band upper bound
CAGR_DRIFT_MAX = 0.15  # |assumed_g - observed_cagr| flag threshold


def _normalize_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


def _db_ticker(t: str) -> str:
    return (t or "").replace(".NS", "").replace(".BO", "").upper()


# ── SQL ────────────────────────────────────────────────────────
REVENUE_HIST_SQL = text("""
    SELECT period_end, revenue, shares_outstanding, current_liabilities
    FROM financials
    WHERE ticker = :t
      AND period_type = 'annual'
      AND revenue IS NOT NULL
      AND period_end IS NOT NULL
    ORDER BY period_end DESC
    LIMIT 6
""")

PRICE_SQL = text("""
    SELECT trade_date, close_price, market_cap_cr
    FROM market_metrics
    WHERE ticker = :t
      AND close_price IS NOT NULL
    ORDER BY trade_date DESC
    LIMIT 1
""")

SECTOR_SQL = text("""
    SELECT sector FROM company_financials
    WHERE ticker = :t
    LIMIT 1
""")


def _fetch_revenue_history(sess, ticker: str) -> list[dict]:
    for cand in (_db_ticker(ticker), ticker):
        rows = sess.execute(REVENUE_HIST_SQL, {"t": cand}).mappings().all()
        if rows:
            return [dict(r) for r in rows]
    return []


def _fetch_price(sess, ticker: str) -> Optional[dict]:
    for cand in (_db_ticker(ticker), ticker):
        row = sess.execute(PRICE_SQL, {"t": cand}).mappings().first()
        if row:
            return dict(row)
    return None


def _fetch_sector(sess, ticker: str) -> Optional[str]:
    for cand in (_db_ticker(ticker), ticker):
        row = sess.execute(SECTOR_SQL, {"t": cand}).mappings().first()
        if row and row.get("sector"):
            return row["sector"]
    return None


def _observed_cagr(rev_hist: list[dict]) -> Optional[float]:
    """CAGR over the available history (oldest → newest revenue).
    Returns None if <2 distinct-year rows or non-positive revenue."""
    if len(rev_hist) < 2:
        return None
    # rev_hist is DESC by period_end; reverse to ascending
    ordered = list(reversed(rev_hist))
    first = ordered[0]
    last = ordered[-1]
    r0 = first.get("revenue")
    r1 = last.get("revenue")
    if not r0 or not r1 or r0 <= 0 or r1 <= 0:
        return None
    years = len(ordered) - 1  # n transitions
    if years < 1:
        return None
    return (r1 / r0) ** (1.0 / years) - 1.0


def _backtest_one(
    sess, ticker: str, override_industry_key: Optional[str] = None,
) -> dict:
    """Build the comparison row for a single ticker."""
    row: dict = {"ticker": ticker, "status": "ok"}

    sector = _fetch_sector(sess, ticker)
    row["sector"] = sector

    industry_key = override_industry_key
    if industry_key is None and sector:
        industry_key = _SECTOR_TO_INDUSTRY_KEY.get(sector.strip().lower())
    if industry_key is None:
        # Fall back to ecommerce only if the ticker has an override
        if _load_overrides().get(_db_ticker(ticker)):
            industry_key = "ecommerce"
    row["industry_key"] = industry_key
    if industry_key is None:
        row["status"] = "skip_unsupported_sector"
        return row

    params = _params_for(ticker, industry_key)
    if params is None:
        row["status"] = "skip_no_params"
        return row
    row["assumed_initial_growth"] = params.initial_growth
    row["assumed_target_op_margin"] = params.target_op_margin
    row["assumed_wacc"] = params.wacc
    row["assumed_reinvestment_rate"] = params.reinvestment_rate

    rev_hist = _fetch_revenue_history(sess, ticker)
    row["history_years"] = len(rev_hist)
    if not rev_hist:
        row["status"] = "skip_no_revenue_history"
        return row

    latest = rev_hist[0]
    rev0 = float(latest.get("revenue") or 0)
    shares = float(latest.get("shares_outstanding") or 0)
    row["latest_revenue_cr"] = round(rev0 / 1e7, 1) if rev0 else None
    row["shares_cr"] = round(shares / 1e7, 2) if shares else None

    price_row = _fetch_price(sess, ticker)
    if not price_row or not price_row.get("close_price"):
        row["status"] = "skip_no_price"
        return row
    cmp_ = float(price_row["close_price"])
    row["cmp"] = round(cmp_, 2)

    if rev0 <= 0 or shares <= 0:
        row["status"] = "skip_zero_inputs"
        return row

    obs_cagr = _observed_cagr(rev_hist)
    row["observed_cagr"] = (
        round(obs_cagr, 4) if obs_cagr is not None else None
    )

    # Run story-DCF
    result = compute_story_dcf_fair_value(
        ticker=ticker,
        sector=sector or industry_key,
        financials={
            "revenue": rev0,
            "shares": shares,
            "current_price": cmp_,
        },
    )
    if result is None:
        row["status"] = "story_dcf_returned_none"
        return row

    fv = float(result["fair_value"])
    row["story_fv"] = round(fv, 2)
    row["fv_cmp_ratio"] = round(fv / cmp_, 3) if cmp_ else None
    row["confidence_score"] = result.get("confidence_score")
    row["tv_pct_of_ev"] = result.get("_meta", {}).get("tv_pct_of_ev")

    # Flags
    flags: list[str] = []
    if row["fv_cmp_ratio"] is not None:
        if row["fv_cmp_ratio"] < FV_CMP_LO:
            flags.append("FV_BELOW_RESCUE_BAND")
        elif row["fv_cmp_ratio"] > FV_CMP_HI:
            flags.append("FV_ABOVE_RESCUE_BAND")
    if obs_cagr is not None and params.initial_growth is not None:
        drift = abs(params.initial_growth - obs_cagr)
        row["cagr_drift"] = round(drift, 4)
        if drift > CAGR_DRIFT_MAX:
            flags.append("CAGR_DRIFT_GT_15PCT")
    if row.get("tv_pct_of_ev") is not None and row["tv_pct_of_ev"] > 0.85:
        flags.append("TV_DOMINATED")

    row["flags"] = flags
    row["needs_review"] = bool(flags)
    return row


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--tickers",
        help="Comma-separated list of bare tickers (default: all overrides)",
    )
    ap.add_argument(
        "--json-only", action="store_true",
        help="Skip the Markdown table on stdout — only write JSON",
    )
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.error("DATABASE_URL not set")
        return 2
    engine = create_engine(_normalize_url(db_url), pool_pre_ping=True)
    Session = sessionmaker(bind=engine)

    overrides = _load_overrides()
    override_tickers = [
        t for t in overrides.keys() if not t.startswith("_")
    ]
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    else:
        tickers = override_tickers

    rows: list[dict] = []
    with Session() as sess:
        for t in tickers:
            try:
                rows.append(_backtest_one(sess, t))
            except Exception as exc:  # noqa: BLE001
                logger.warning("backtest failed for %s: %s", t, exc)
                rows.append({"ticker": t, "status": f"error: {exc}"})

    # Persist snapshot
    snap_dir = Path(__file__).resolve().parent / "snapshots"
    snap_dir.mkdir(exist_ok=True)
    today = _dt.date.today().strftime("%Y%m%d")
    out_path = snap_dir / f"story_dcf_backtest_{today}.json"
    summary = {
        "generated_at": _dt.datetime.utcnow().isoformat() + "Z",
        "fv_cmp_band": [FV_CMP_LO, FV_CMP_HI],
        "cagr_drift_max": CAGR_DRIFT_MAX,
        "total": len(rows),
        "needs_review": sum(1 for r in rows if r.get("needs_review")),
        "rows": rows,
    }
    with open(out_path, "w", encoding="utf-8") as fh:
        json.dump(summary, fh, indent=2, default=str)
    logger.info("wrote %s", out_path)

    if not args.json_only:
        _print_markdown_table(rows)
    return 0


def _print_markdown_table(rows: list[dict]) -> None:
    header = (
        "| ticker | CMP | Story FV | FV/CMP | "
        "assumed_g | observed_cagr | drift | flags |"
    )
    sep = "|" + "|".join(["---"] * 8) + "|"
    print(header)
    print(sep)
    for r in rows:
        if r.get("status") != "ok":
            print(
                f"| {r['ticker']} | — | — | — | — | — | — | "
                f"{r.get('status')} |"
            )
            continue
        flags = ",".join(r.get("flags") or []) or "—"
        print(
            f"| {r['ticker']} "
            f"| {r.get('cmp')} "
            f"| {r.get('story_fv')} "
            f"| {r.get('fv_cmp_ratio')} "
            f"| {r.get('assumed_initial_growth')} "
            f"| {r.get('observed_cagr')} "
            f"| {r.get('cagr_drift')} "
            f"| {flags} |"
        )


if __name__ == "__main__":
    sys.exit(main())
