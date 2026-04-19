"""Generate scripts/canary_stocks_top500.json from the public top-tickers
endpoint. Used by the weekly sweep workflow to widen canary coverage from
50 → 500 without hand-curating bounds for each ticker.

Schema: each entry has canary_bounds=null, so the harness skips Gate 4
(per-stock bounds) but still runs Gates 1/2/3/5 — those catch FORMULA
bugs that apply to all stocks (MoS math, scenario dispersion, single-
source-of-truth, forbidden values).

Usage:
    python scripts/build_canary_top500.py
    → writes scripts/canary_stocks_top500.json (~500 entries)
"""
from __future__ import annotations
import json
import os
import sys
import urllib.request
from pathlib import Path

API_BASE = os.environ.get("CANARY_API_BASE", "https://api.yieldiq.in")
LIMIT = int(os.environ.get("SWEEP_LIMIT", "500"))
OUT = Path(__file__).parent / "canary_stocks_top500.json"


def main() -> int:
    url = f"{API_BASE}/api/v1/public/top-tickers?limit={LIMIT}"
    print(f"fetch {url}")
    try:
        with urllib.request.urlopen(url, timeout=30) as r:
            payload = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"FAIL: {e}", file=sys.stderr)
        return 1

    tickers = payload.get("tickers", [])
    if not tickers:
        print("no tickers returned", file=sys.stderr)
        return 1

    stocks = []
    for t in tickers:
        # Strip .NS / .BO suffix — canary_diff appends .NS itself
        bare = t.replace(".NS", "").replace(".BO", "")
        stocks.append({
            "symbol": bare,
            "sector": "unknown",
            "mcap_tier": "large",
            # canary_bounds=null → harness skips Gate 4 for this ticker.
            # Sweep relies on Gates 1/2/3/5 to catch formula bugs.
            "canary_bounds": {
                "roe": None,
                "debt_to_equity": None,
                "wacc": None,
                "market_cap_cr": None,
                "revenue_cagr_3y": None,
            },
        })

    out_doc = {
        "_meta": {
            "version": 1,
            "generated_by": "scripts/build_canary_top500.py",
            "source": url,
            "ticker_count": len(stocks),
            "description": "Auto-generated top-N stock list for the weekly canary sweep. canary_bounds=null on every entry → Gate 4 is effectively disabled for the sweep; Gates 1/2/3/5 still fire on every stock.",
        },
        "stocks": stocks,
    }
    OUT.write_text(json.dumps(out_doc, indent=2), encoding="utf-8")
    print(f"wrote {len(stocks)} entries to {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
