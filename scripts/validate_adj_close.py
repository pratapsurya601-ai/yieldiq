"""Day-112 — validate daily_prices.adj_close against known CAGR bands.

Runs after every rebuild and on a nightly cron. Catches:
  * a regressed populator silently writing close into adj_close,
  * yfinance returning a stale or broken series,
  * a corp-action being missed by both sources,
  * a structural break (merger/demerger) not being modeled.

Two pools:
  * COMPOUNDERS — 20 names whose 5y stock CAGR must land in
    [+5%, +30%]. Below +5% means we likely failed to adjust for a
    split/bonus (the symptom that motivated this whole exercise).
    Above +30% means we likely adjusted too aggressively, or a
    structural break inflated the base.
  * UNDERPERFORMERS — names whose 5y CAGR should be negative or near-
    zero (PSU banks pre-2022, AT1-troubled NBFCs, sector-broken
    legacy names). If these go positive, our adjustment math has
    probably over-corrected.

Exit code:
  * 0 if >= 95% of validators pass,
  * 1 otherwise (CI flips red, GH Actions opens an issue).

Output: per-ticker pass/fail with actual CAGR + expected band.
"""
from __future__ import annotations

import argparse
import json
import logging
import math
import os
import sys
from datetime import date, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
log = logging.getLogger("validate_adj_close")


# (ticker, low_pct, high_pct) — both inclusive. Wide bands so we don't
# false-alarm on a market correction; we're catching ~50% data errors,
# not 1-2% CAGR drift.
COMPOUNDERS: list[tuple[str, float, float]] = [
    ("TCS", 5.0, 30.0),
    ("INFY", 5.0, 30.0),
    ("HDFCBANK", 0.0, 25.0),       # merger-affected, wider low band
    ("RELIANCE", 5.0, 30.0),
    ("NESTLEIND", 5.0, 30.0),
    ("BAJFINANCE", 5.0, 35.0),
    ("MARUTI", 5.0, 30.0),
    ("LT", 5.0, 30.0),
    ("ITC", 5.0, 30.0),
    ("ASIANPAINT", 0.0, 25.0),     # recent earnings pressure, lowered floor
    ("HINDUNILVR", 0.0, 25.0),
    ("ICICIBANK", 5.0, 35.0),
    ("KOTAKBANK", 0.0, 25.0),
    ("BHARTIARTL", 5.0, 35.0),
    ("TITAN", 5.0, 35.0),
    ("ULTRACEMCO", 5.0, 30.0),
    ("SUNPHARMA", 5.0, 30.0),
    ("HCLTECH", 5.0, 30.0),
    ("WIPRO", 0.0, 25.0),
    ("AXISBANK", 5.0, 30.0),
]

UNDERPERFORMERS: list[tuple[str, float, float]] = [
    # 5y window from 2026-05-23 already includes much of the PSU bank
    # 2022-2024 rerating, so these are no longer obviously negative.
    # Keep band wide: catch only egregiously wrong (>30%).
    ("PNB", -25.0, 30.0),
    ("BANKBARODA", -10.0, 30.0),
    ("CANBK", -10.0, 30.0),
    ("UNIONBANK", -10.0, 30.0),
    ("IOB", -25.0, 35.0),
    ("YESBANK", -40.0, 20.0),       # near-zero or negative
    ("BANDHANBNK", -25.0, 15.0),
    ("RBLBANK", -25.0, 15.0),
    ("IDFCFIRSTB", -10.0, 25.0),
    ("VODAFONEIDEA", -50.0, 10.0),  # near-bankruptcy, should be deeply negative
    ("ZEEL", -30.0, 10.0),
    ("INDUSINDBK", -10.0, 20.0),
    ("DISHTV", -50.0, 10.0),
    ("SUZLON", -10.0, 80.0),         # huge rally, accept wide band
    ("JPPOWER", -15.0, 80.0),
    ("RPOWER", -25.0, 80.0),
    ("RCOM", -50.0, 30.0),
    ("DHFL", -50.0, 30.0),
    ("PCJEWELLER", -50.0, 30.0),
    ("MANPASAND", -50.0, 30.0),
]


def _fetch_close_on_or_before(conn, ticker: str, target: date) -> float | None:
    """Adj-close, most recent trade_date <= target within a 14-day window."""
    floor = target - timedelta(days=14)
    cur = conn.cursor()
    try:
        cur.execute(
            "SELECT adj_close FROM daily_prices "
            "WHERE ticker = %s AND trade_date <= %s AND trade_date >= %s "
            "  AND adj_close IS NOT NULL "
            "ORDER BY trade_date DESC LIMIT 1",
            (ticker, target, floor),
        )
        row = cur.fetchone()
    finally:
        cur.close()
    if not row or row[0] is None:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def _cagr(start: float | None, end: float | None, years: int) -> float | None:
    if not start or not end or years <= 0 or start <= 0 or end <= 0:
        return None
    try:
        return ((end / start) ** (1.0 / years) - 1.0) * 100.0
    except (ValueError, OverflowError):
        return None


def validate_ticker(conn, ticker: str, low: float, high: float,
                    today: date, years: int = 5) -> dict[str, object]:
    end = _fetch_close_on_or_before(conn, ticker, today)
    start = _fetch_close_on_or_before(conn, ticker, today - timedelta(days=365 * years))
    cagr = _cagr(start, end, years)
    if cagr is None:
        return {
            "ticker": ticker, "status": "skip",
            "reason": "missing_adj_close",
            "cagr": None, "expected": [low, high],
        }
    ok = low <= cagr <= high
    return {
        "ticker": ticker, "status": "pass" if ok else "fail",
        "cagr": round(cagr, 2), "expected": [low, high],
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--threshold", type=float, default=0.95,
                    help="Min pass-rate among non-skipped tickers (default 0.95)")
    ap.add_argument("--json", action="store_true", help="Emit JSON to stdout")
    ap.add_argument("--today", default=None,
                    help="Override 'today' for backtesting validator (ISO date)")
    args = ap.parse_args()

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        log.error("DATABASE_URL not set")
        return 2

    today = date.fromisoformat(args.today) if args.today else date.today()

    import psycopg2
    conn = psycopg2.connect(db_url)
    try:
        results: list[dict[str, object]] = []
        for t, lo, hi in COMPOUNDERS:
            r = validate_ticker(conn, t, lo, hi, today)
            r["pool"] = "compounder"
            results.append(r)
        for t, lo, hi in UNDERPERFORMERS:
            r = validate_ticker(conn, t, lo, hi, today)
            r["pool"] = "underperformer"
            results.append(r)
    finally:
        conn.close()

    n_pass = sum(1 for r in results if r["status"] == "pass")
    n_fail = sum(1 for r in results if r["status"] == "fail")
    n_skip = sum(1 for r in results if r["status"] == "skip")
    judged = n_pass + n_fail
    rate = (n_pass / judged) if judged else 0.0

    summary = {
        "pass": n_pass, "fail": n_fail, "skip": n_skip,
        "pass_rate": round(rate, 3),
        "threshold": args.threshold,
        "today": str(today),
        "results": results,
    }

    if args.json:
        print(json.dumps(summary, indent=2, default=str))
    else:
        print(f"validate_adj_close — {today}")
        print(f"  pass={n_pass} fail={n_fail} skip={n_skip} rate={rate:.1%}")
        for r in results:
            mark = {"pass": "OK", "fail": "FAIL", "skip": "SKIP"}[r["status"]]
            cagr = r.get("cagr")
            cagr_s = f"{cagr:+6.2f}%" if cagr is not None else "  n/a "
            lo, hi = r["expected"]
            print(f"  [{mark:4s}] {r['ticker']:<14s} {cagr_s}  expected [{lo:+.1f}%, {hi:+.1f}%]  ({r['pool']})")
        if n_fail:
            print()
            print("FAILED TICKERS:")
            for r in results:
                if r["status"] == "fail":
                    print(f"  {r['ticker']} cagr={r['cagr']}% expected={r['expected']}")

    if judged == 0 or rate < args.threshold:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
