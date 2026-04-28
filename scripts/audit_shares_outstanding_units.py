"""Audit `financials.shares_outstanding` for unit-mismatch bugs.

Background: the column is documented as "Lakhs" in data_pipeline/models.py
but a non-trivial fraction of rows are stored in crore (or other units)
because XBRL/BSE backfill paths sometimes write the source-filing's value
without re-scaling.

This script is read-only. It infers the unit per row by comparing
`price * stored_shares` against the canonical `stocks.market_cap_cr` (or
the most recent `stock_metrics.market_cap_cr`) and writes a CSV of
`(ticker, period_end, stored_value, inferred_unit, suggested_raw,
ratio)`.

Usage:
    DATABASE_URL="postgresql://..." \
        python scripts/audit_shares_outstanding_units.py \
        --out reports/shares_outstanding_audit.csv

    # restrict to the canary 50:
    DATABASE_URL=... python scripts/audit_shares_outstanding_units.py \
        --tickers-file scripts/canary_stocks_50.json

The output CSV feeds `scripts/normalize_shares_outstanding.py`.
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from pathlib import Path

from sqlalchemy import create_engine, text

# ---- Unit detection thresholds ----------------------------------------
#
# Compare expected_mcap_raw = price * stored_shares against the canonical
# market_cap_cr * 1e7. The ratio identifies the unit:
#
#   ratio ≈ 1            → stored value is RAW share count (canonical)
#   ratio ≈ 1/100        → stored value is in LAKHS  (×1e5 → raw)
#   ratio ≈ 1/10_000     → stored value is in CRORE  (×1e7 → raw)
#   ratio ≈ 1/1_000      → stored value is in THOUSANDS (×1e3 → raw)
#   ratio ≈ 1/1_000_000  → stored value is in MILLIONS  (×1e6 → raw)
#
# Tolerance band: ±15% accommodates intra-quarter share-count drift,
# split timing, ESOP issuance.
TOLERANCE = 0.15

UNIT_TABLE = [
    # (label,        scale_to_raw, expected_ratio)
    ("raw",          1.0,          1.0),
    ("thousands",    1_000.0,      1.0 / 1_000),
    ("lakh",         100_000.0,    1.0 / 100_000),
    ("million",      1_000_000.0,  1.0 / 1_000_000),
    ("crore",        10_000_000.0, 1.0 / 10_000_000),
]


def classify_unit(ratio: float) -> tuple[str, float] | tuple[None, None]:
    """Return (unit_label, scale_to_raw) for the unit closest to `ratio`,
    or (None, None) if no candidate is within TOLERANCE."""
    if ratio is None or ratio <= 0:
        return (None, None)
    best = None
    best_err = float("inf")
    for label, scale, expected in UNIT_TABLE:
        err = abs(ratio - expected) / expected
        if err < best_err:
            best_err = err
            best = (label, scale)
    if best is not None and best_err <= TOLERANCE:
        return best
    return (None, None)


def _connect():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        print("ERROR: DATABASE_URL not set", file=sys.stderr)
        sys.exit(2)
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url)


def _load_ticker_filter(path: str | None) -> set[str] | None:
    if not path:
        return None
    p = Path(path)
    if not p.exists():
        print(f"ERROR: tickers file not found: {path}", file=sys.stderr)
        sys.exit(2)
    data = json.loads(p.read_text())
    if isinstance(data, list):
        return {str(t).upper() for t in data}
    if isinstance(data, dict) and "tickers" in data:
        return {str(t).upper() for t in data["tickers"]}
    print(f"ERROR: unexpected tickers-file shape in {path}", file=sys.stderr)
    sys.exit(2)


def audit(engine, tickers: set[str] | None) -> list[dict]:
    """Return one row dict per (ticker, period_end) audited."""
    # We pull the most-recent close from daily_prices and the most-recent
    # market_cap_cr from market_metrics. For pre-IPO/decade-old rows the
    # market_cap won't match cleanly — that's fine, we just report
    # "unknown" and let ops triage.
    #
    # NOTE: PR #144 referenced `stock_metrics` (table doesn't exist in
    # prod Neon DB); corrected to `market_metrics` per PR #150. Schema
    # confirmed via backend/routers/screener.py — market_metrics has
    # (ticker, market_cap_cr, trade_date) and is the canonical source.
    sql = text(
        """
        WITH latest_price AS (
            SELECT DISTINCT ON (ticker)
                   ticker, close_price, trade_date
            FROM   daily_prices
            WHERE  close_price IS NOT NULL AND close_price > 0
            ORDER  BY ticker, trade_date DESC
        ),
        latest_mcap AS (
            SELECT DISTINCT ON (ticker)
                   ticker, market_cap_cr, trade_date
            FROM   market_metrics
            WHERE  market_cap_cr IS NOT NULL AND market_cap_cr > 0
            ORDER  BY ticker, trade_date DESC
        )
        SELECT  f.ticker,
                f.period_end,
                f.period_type,
                f.shares_outstanding   AS stored_shares,
                lp.close_price         AS price,
                lm.market_cap_cr       AS market_cap_cr,
                f.data_source
        FROM    financials      f
        LEFT JOIN latest_price  lp ON lp.ticker = f.ticker
        LEFT JOIN latest_mcap   lm ON lm.ticker = f.ticker
        WHERE   f.shares_outstanding IS NOT NULL
          AND   f.shares_outstanding > 0
        ORDER BY f.ticker, f.period_end DESC
        """
    )
    out: list[dict] = []
    with engine.connect() as conn:
        for row in conn.execute(sql):
            ticker = row.ticker
            if tickers is not None and ticker.upper() not in tickers:
                continue
            stored = float(row.stored_shares) if row.stored_shares else None
            price = float(row.price) if row.price else None
            mcap_cr = float(row.market_cap_cr) if row.market_cap_cr else None

            inferred = None
            scale = None
            ratio = None
            suggested_raw = None
            if stored and price and mcap_cr and mcap_cr > 0:
                expected_raw_mcap = price * stored
                canonical_raw_mcap = mcap_cr * 1e7
                ratio = expected_raw_mcap / canonical_raw_mcap
                inferred, scale = classify_unit(ratio)
                if scale is not None:
                    suggested_raw = stored * scale
            out.append({
                "ticker": ticker,
                "period_end": row.period_end.isoformat()
                              if row.period_end else "",
                "period_type": row.period_type or "",
                "stored_value": stored,
                "price": price,
                "market_cap_cr": mcap_cr,
                "ratio": ratio,
                "inferred_unit": inferred or "unknown",
                "suggested_raw": suggested_raw,
                "data_source": row.data_source or "",
            })
    return out


def summarize(rows: list[dict]) -> None:
    n = len(rows)
    by_unit: dict[str, int] = {}
    affected_tickers: set[str] = set()
    non_canonical_tickers: set[str] = set()
    for r in rows:
        u = r["inferred_unit"]
        by_unit[u] = by_unit.get(u, 0) + 1
        affected_tickers.add(r["ticker"])
        if u not in ("raw", "unknown"):
            non_canonical_tickers.add(r["ticker"])
    print("=" * 60)
    print(f"shares_outstanding audit — {n:,} rows scanned")
    print(f"unique tickers audited           : {len(affected_tickers):,}")
    print(f"tickers in non-canonical units   : "
          f"{len(non_canonical_tickers):,}")
    print("rows by inferred unit:")
    for u, c in sorted(by_unit.items(), key=lambda kv: -kv[1]):
        print(f"  {u:<12} : {c:>6}")
    print("=" * 60)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out",
                    default="reports/shares_outstanding_audit.csv",
                    help="CSV output path")
    ap.add_argument("--tickers-file",
                    help="JSON list/object restricting tickers")
    args = ap.parse_args()

    engine = _connect()
    ticker_filter = _load_ticker_filter(args.tickers_file)
    rows = audit(engine, ticker_filter)

    out_path = Path(args.out)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = [
        "ticker", "period_end", "period_type", "stored_value",
        "price", "market_cap_cr", "ratio", "inferred_unit",
        "suggested_raw", "data_source",
    ]
    with out_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)

    summarize(rows)
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
