"""Backfill pe_ratio / pb_ratio in market_metrics for top-by-mcap tickers.

Scope (intentionally narrow per the data-backfill PR):
  - Top 200 tickers ranked by latest market_metrics.market_cap_cr.
    (Initially scoped to top-100; extended to top-200 only because top-100
    had ZERO NULL pe/pb candidates -- the 5 NULL-pe tickers above 50K Cr
    market cap sit at positions ~101-110.)
  - For any ticker whose LATEST (DISTINCT ON ticker) market_metrics row has
    pe_ratio IS NULL or pb_ratio IS NULL, fetch yfinance .info trailingPE /
    priceToBook and UPDATE that row in place.
  - Rate-limited to 1 request/sec.
  - Read-only Neon URL is loaded from the line-2 bare-URL convention in
    E:/Projects/yieldiq_v7/.env.local (per project memory). DATABASE_URL must
    NEVER be hardcoded into this file.
  - If yfinance returns None for trailingPE (legitimate signal for negative
    earnings, e.g. PAYTM / SWIGGY / IDEA), we LOG it and SKIP -- we do not
    fabricate a value.

Usage:
  /e/Projects/yieldiq_v7/.venv/Scripts/python.exe \\
    /e/Projects/yieldiq_v7/yq-data-backfill/scripts/data_patches/backfill_pe_pb_top100.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import psycopg2
import yfinance as yf

ENV_LOCAL = Path("E:/Projects/yieldiq_v7/.env.local")


def load_neon_url() -> str:
    # Line 2 of .env.local is a bare URL (no KEY= prefix). Project convention.
    with ENV_LOCAL.open("r", encoding="utf-8") as fh:
        lines = fh.read().splitlines()
    if len(lines) < 2 or not lines[1].startswith("postgres"):
        raise RuntimeError("Could not load Neon URL from line 2 of .env.local")
    return lines[1].strip()


TOP_QUERY = """
WITH latest AS (
  SELECT DISTINCT ON (ticker)
    ticker, trade_date, market_cap_cr, pe_ratio, pb_ratio
  FROM market_metrics
  WHERE market_cap_cr IS NOT NULL
  ORDER BY ticker, trade_date DESC
)
SELECT ticker, trade_date, market_cap_cr, pe_ratio, pb_ratio
FROM latest
WHERE market_cap_cr > 50000
ORDER BY market_cap_cr DESC
LIMIT 200;
"""

UPDATE_SQL = """
UPDATE market_metrics
SET pe_ratio = COALESCE(pe_ratio, %s),
    pb_ratio = COALESCE(pb_ratio, %s)
WHERE ticker = %s AND trade_date = %s
RETURNING pe_ratio, pb_ratio;
"""


def yf_pe_pb(ticker: str) -> tuple[float | None, float | None, str]:
    """Return (trailingPE, priceToBook, status_string) for ``ticker``.NS."""
    yticker = f"{ticker}.NS"
    try:
        info = yf.Ticker(yticker).info or {}
    except Exception as exc:  # noqa: BLE001 -- yfinance can raise many things
        return None, None, f"error:{type(exc).__name__}"
    pe = info.get("trailingPE")
    pb = info.get("priceToBook")
    return pe, pb, "ok"


def main() -> int:
    url = load_neon_url()
    log: list[dict] = []
    with psycopg2.connect(url) as conn:
        with conn.cursor() as cur:
            cur.execute(TOP_QUERY)
            rows = cur.fetchall()
        candidates = [
            (t, td, mc, pe, pb)
            for (t, td, mc, pe, pb) in rows
            if pe is None or pb is None
        ]
        print(
            f"[scope] top100 size={len(rows)}  candidates(pe or pb null)={len(candidates)}",
            flush=True,
        )
        for ticker, trade_date, mc, pe_old, pb_old in candidates:
            pe_new, pb_new, status = yf_pe_pb(ticker)
            entry = {
                "ticker": ticker,
                "trade_date": str(trade_date),
                "market_cap_cr": float(mc),
                "pe_old": pe_old,
                "pb_old": pb_old,
                "pe_yf": pe_new,
                "pb_yf": pb_new,
                "yf_status": status,
                "applied": False,
            }
            if pe_new is None and pb_new is None:
                entry["note"] = "yfinance returned no values; skipping"
                log.append(entry)
                print(json.dumps(entry), flush=True)
                time.sleep(1.0)
                continue
            with conn.cursor() as cur:
                cur.execute(UPDATE_SQL, (pe_new, pb_new, ticker, trade_date))
                pe_after, pb_after = cur.fetchone()
            entry.update(
                {
                    "applied": True,
                    "pe_after": float(pe_after) if pe_after is not None else None,
                    "pb_after": float(pb_after) if pb_after is not None else None,
                }
            )
            log.append(entry)
            print(json.dumps(entry), flush=True)
            time.sleep(1.0)
        conn.commit()
    out = Path(__file__).with_name("backfill_pe_pb_top100.log.json")
    out.write_text(json.dumps(log, indent=2, default=str), encoding="utf-8")
    print(f"[done] wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
