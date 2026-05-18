"""Audit `financials.currency` for USD/INR mistags.

Background
----------
Indian issuers report financial statements in INR. A small set of IT-services
and pharma tickers historically had their consolidated XBRL filings (and
yfinance feeds) tagged in USD, which the pipeline obediently persisted. PRs
v50 / v75 / v90 repatriated 4 IT-services tickers (MPHASIS, COFORGE,
PERSISTENT, KPITTECH) and ~14 pharma tickers back to INR.

As of 2026-05-18, a DRREDDY investigation showed yfinance has FLIPPED its
`financialCurrency` field back to INR for those same tickers. That means
new rows are landing as INR while older rows in the table still claim USD,
producing a mixed-currency long tail that breaks every downstream consumer
(revenue per share, DCF, peer ratios).

What this script does
---------------------
Read-only audit. For every (ticker, period_end) row in `financials` with
`currency='USD'`:

  1. Pull stored numerics (revenue, shares_outstanding, country/sector from
     the `stocks` table).
  2. Probe `yf.Ticker(t).info['financialCurrency']` and `.info['country']`
     for the *current* truth-of-the-day.
  3. Compute revenue-per-share. For an Indian-domiciled issuer without an
     ADR, revenue/share > $50 USD is implausible — flag as
     "magnitude_says_inr".

Output: one JSON report at
`scripts/snapshots/currency_mistag_audit_<ts>.json` plus a console summary.

Hard rules: NO writes. NO mutations. Dry-run only. Operators review the
JSON, then make repatriation decisions (probably via a follow-up
`scripts/repatriate_currency.py` that this audit does NOT touch).

Usage
-----
    DATABASE_URL="postgresql://..." \
        python scripts/audit_currency_mistags.py

    # skip yfinance probes (offline / rate-limited):
    DATABASE_URL=... python scripts/audit_currency_mistags.py --no-yfinance

    # restrict to known suspects:
    DATABASE_URL=... python scripts/audit_currency_mistags.py \
        --tickers MPHASIS,COFORGE,PERSISTENT,KPITTECH,DRREDDY
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from sqlalchemy import create_engine, text

# Per-share USD revenue above this is implausible for an Indian issuer
# without an ADR. Set deliberately high to minimise false positives — even
# a USD-denominated giant like TCS is ~$25/share revenue.
IMPLAUSIBLE_USD_REV_PER_SHARE = 50.0

# shares_outstanding is stored in LAKHS per data_pipeline/models.py.
LAKH = 100_000.0


def _connect():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(2)
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url)


def _fetch_usd_rows(engine, tickers: set[str] | None) -> list[dict[str, Any]]:
    sql = text(
        """
        SELECT  f.ticker,
                f.period_end,
                f.period_type,
                f.currency,
                f.revenue,
                f.pat,
                f.shares_outstanding,
                f.data_source,
                f.data_quality_rank,
                s.sector,
                s.industry,
                s.company_name
        FROM    financials f
        LEFT JOIN stocks s ON s.ticker = f.ticker
        WHERE   f.currency = 'USD'
        ORDER BY f.ticker, f.period_end DESC
        """
    )
    out: list[dict[str, Any]] = []
    with engine.connect() as conn:
        for row in conn.execute(sql):
            t = (row.ticker or "").upper()
            if tickers and t not in tickers:
                continue
            out.append({
                "ticker": t,
                "period_end": row.period_end.isoformat()
                              if row.period_end else None,
                "period_type": row.period_type,
                "currency": row.currency,
                "revenue": float(row.revenue) if row.revenue is not None
                           else None,
                "pat": float(row.pat) if row.pat is not None else None,
                "shares_outstanding_lakh": float(row.shares_outstanding)
                    if row.shares_outstanding is not None else None,
                "data_source": row.data_source,
                "data_quality_rank": row.data_quality_rank,
                "sector": row.sector,
                "industry": row.industry,
                "company_name": row.company_name,
            })
    return out


def _probe_yfinance(ticker: str) -> dict[str, Any]:
    """Return {financialCurrency, country, longName, error?}.

    Wrapped in broad try/except — yfinance is famously flaky and we never
    want a single bad ticker to abort the audit."""
    try:
        import yfinance as yf
    except ImportError:
        return {"error": "yfinance not installed"}

    # YieldIQ stores bare NSE symbols (e.g. "MPHASIS"); yfinance needs
    # `.NS` suffix.
    yf_sym = ticker if "." in ticker else f"{ticker}.NS"
    try:
        info = yf.Ticker(yf_sym).info or {}
        return {
            "yf_symbol": yf_sym,
            "financialCurrency": info.get("financialCurrency"),
            "country": info.get("country"),
            "longName": info.get("longName"),
            "quoteType": info.get("quoteType"),
        }
    except Exception as exc:  # noqa: BLE001 — defensive
        return {"yf_symbol": yf_sym, "error": f"{type(exc).__name__}: {exc}"}


def _classify_row(row: dict[str, Any], yf_info: dict[str, Any] | None
                  ) -> list[str]:
    """Return a list of flag strings explaining why this row is suspect."""
    flags: list[str] = []

    # Heuristic 1: yfinance currently says INR for this ticker → stored
    # USD tag is stale.
    if yf_info and yf_info.get("financialCurrency") == "INR":
        flags.append("yfinance_says_inr")

    # Heuristic 2: yfinance country is India and quoteType isn't ADR.
    if (yf_info
            and yf_info.get("country") == "India"
            and yf_info.get("quoteType") != "ADR"):
        flags.append("country_india")

    # Heuristic 3: implausibly high USD revenue-per-share.
    rev = row.get("revenue")
    sh_lakh = row.get("shares_outstanding_lakh")
    if rev and sh_lakh and sh_lakh > 0:
        shares_raw = sh_lakh * LAKH
        rps = rev / shares_raw if shares_raw else None
        if rps is not None and rps > IMPLAUSIBLE_USD_REV_PER_SHARE:
            flags.append(
                f"magnitude_says_inr(rps={rps:,.0f})"
            )
    return flags


def _summarise(rows: list[dict[str, Any]],
               by_ticker: dict[str, dict[str, Any]]) -> dict[str, Any]:
    suspects = [t for t, d in by_ticker.items() if d["any_flag"]]
    yf_inr = [t for t, d in by_ticker.items()
              if d["yf_info"]
              and d["yf_info"].get("financialCurrency") == "INR"]
    magnitude_suspects = [
        t for t, d in by_ticker.items()
        if any("magnitude_says_inr" in f for f in d["flags"])
    ]
    return {
        "total_usd_rows": len(rows),
        "unique_usd_tickers": len(by_ticker),
        "suspect_tickers_total": len(suspects),
        "yfinance_now_reports_inr": len(yf_inr),
        "magnitude_implies_inr": len(magnitude_suspects),
        "suspect_ticker_list": sorted(suspects),
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out-dir", default="scripts/snapshots",
                    help="Output directory for the JSON report")
    ap.add_argument("--tickers",
                    help="Comma-separated ticker filter (e.g. MPHASIS,DRREDDY)")
    ap.add_argument("--no-yfinance", action="store_true",
                    help="Skip yfinance probes (DB-only)")
    ap.add_argument("--yf-sleep", type=float, default=0.4,
                    help="Seconds between yfinance probes (rate-limit)")
    args = ap.parse_args()

    ticker_filter: set[str] | None = None
    if args.tickers:
        ticker_filter = {t.strip().upper() for t in args.tickers.split(",")
                         if t.strip()}

    engine = _connect()
    print(f"[audit_currency_mistags] connected; "
          f"filter={sorted(ticker_filter) if ticker_filter else 'ALL'}")
    rows = _fetch_usd_rows(engine, ticker_filter)
    print(f"[audit_currency_mistags] fetched {len(rows):,} USD-tagged rows")

    by_ticker: dict[str, dict[str, Any]] = {}
    for r in rows:
        by_ticker.setdefault(r["ticker"], {
            "rows": [],
            "yf_info": None,
            "flags": set(),
            "any_flag": False,
        })["rows"].append(r)

    if not args.no_yfinance:
        print(f"[audit_currency_mistags] probing yfinance for "
              f"{len(by_ticker)} tickers...")
        for i, t in enumerate(sorted(by_ticker), 1):
            yf_info = _probe_yfinance(t)
            by_ticker[t]["yf_info"] = yf_info
            cur = yf_info.get("financialCurrency")
            ctry = yf_info.get("country")
            print(f"  [{i:>3}/{len(by_ticker)}] {t:<14} "
                  f"financialCurrency={cur!s:<6} country={ctry!s}")
            time.sleep(args.yf_sleep)
    else:
        print("[audit_currency_mistags] --no-yfinance: skipping yf probes")

    # Apply flags per row, aggregate at ticker level.
    for t, bucket in by_ticker.items():
        flags_for_ticker: set[str] = set()
        for r in bucket["rows"]:
            row_flags = _classify_row(r, bucket["yf_info"])
            r["flags"] = row_flags
            flags_for_ticker.update(row_flags)
        bucket["flags"] = sorted(flags_for_ticker)
        bucket["any_flag"] = bool(flags_for_ticker)

    summary = _summarise(rows, by_ticker)

    # Render to JSON-safe form (sets → lists).
    out = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "database_url_host": (os.environ.get("DATABASE_URL", "")
                              .split("@")[-1].split("/")[0]),
        "thresholds": {
            "implausible_usd_rev_per_share": IMPLAUSIBLE_USD_REV_PER_SHARE,
        },
        "summary": summary,
        "tickers": {
            t: {
                "company_name": bucket["rows"][0].get("company_name"),
                "sector": bucket["rows"][0].get("sector"),
                "industry": bucket["rows"][0].get("industry"),
                "row_count": len(bucket["rows"]),
                "yf_info": bucket["yf_info"],
                "ticker_flags": bucket["flags"],
                "rows": bucket["rows"],
            }
            for t, bucket in sorted(by_ticker.items())
        },
    }

    ts = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"currency_mistag_audit_{ts}.json"
    out_path.write_text(json.dumps(out, indent=2, default=str),
                        encoding="utf-8")

    print("=" * 64)
    print(f"USD-tagged rows scanned         : {summary['total_usd_rows']:,}")
    print(f"Unique USD-tagged tickers       : {summary['unique_usd_tickers']:,}")
    print(f"yfinance now reports INR        : "
          f"{summary['yfinance_now_reports_inr']:,}")
    print(f"Magnitude implies INR           : "
          f"{summary['magnitude_implies_inr']:,}")
    print(f"Total suspect tickers           : "
          f"{summary['suspect_tickers_total']:,}")
    print("=" * 64)
    print(f"wrote {out_path}")
    print("REMEMBER: this audit is read-only. No DB rows were modified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
