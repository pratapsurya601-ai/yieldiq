"""Snapshot FV/MoS/scenarios/ratios for 50 stocks BEFORE the SoT collapse.

Used by Agent B's canary-diff to confirm the Single-Source-of-Truth collapse
(public/stock-summary now reads analysis_cache, no longer recomputes) produces
NO unintended drift on the 50 reference tickers.

Output: scripts/snapshots/before_unified_source.json

Why we run BEFORE the merge of PR1:
    The whole point of "collapse to one source" is that public should serve
    the IDENTICAL FV/MoS/scenarios as the authed app endpoint. Snapshotting
    the analysis_cache state right before the change lets us prove that:
        - public's user-visible numbers match analysis_cache numbers, AND
        - the change does not perturb analysis_cache itself.

How to run (DATABASE_URL must point at Aiven prod replica or an Aiven snapshot):

    # Windows (PowerShell)
    $env:DATABASE_URL = "<aiven uri>"
    py scripts/snapshot_50_stocks.py

    # *nix
    DATABASE_URL="<aiven uri>" python scripts/snapshot_50_stocks.py

The script is read-only. It writes one file under scripts/snapshots/ and
prints a 1-line summary. It never mutates the analysis_cache table.
"""
from __future__ import annotations

import datetime as _dt
import json
import os
import sys
from pathlib import Path

# Make the repo root importable so `data_pipeline.db` resolves.
sys.path.insert(0, str(Path(__file__).parent.parent))

from sqlalchemy import text  # noqa: E402

from data_pipeline.db import Session  # noqa: E402

# 20 from the existing Phase-2.0 canary set (preserve order so the
# coordinated review with Agent B's canary diff is easy to eyeball)
# + 30 across sector + cap to widen coverage.
TICKERS = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ITC.NS",
    "HCLTECH.NS", "ICICIBANK.NS", "BHARTIARTL.NS", "SBIN.NS", "LT.NS",
    "BAJFINANCE.NS", "KOTAKBANK.NS", "AXISBANK.NS", "MARUTI.NS", "WIPRO.NS",
    "SUNPHARMA.NS", "TITAN.NS", "ULTRACEMCO.NS", "POWERGRID.NS", "HINDUNILVR.NS",
    # Sector + cap fill
    "DRREDDY.NS", "ONGC.NS", "NTPC.NS", "TATAMOTORS.NS", "M&M.NS",
    "HEROMOTOCO.NS", "DIVISLAB.NS", "COALINDIA.NS", "TATASTEEL.NS", "JSWSTEEL.NS",
    "ADANIPORTS.NS", "BAJAJ-AUTO.NS", "ASIANPAINT.NS", "NESTLEIND.NS", "BRITANNIA.NS",
    "DABUR.NS", "GODREJCP.NS", "PIDILITIND.NS", "TECHM.NS", "INDUSINDBK.NS",
    "GRASIM.NS", "HINDALCO.NS", "ADANIENT.NS", "BPCL.NS", "EICHERMOT.NS",
    "CIPLA.NS", "TATACONSUM.NS", "BAJAJFINSV.NS", "SHRIRAMFIN.NS", "VEDL.NS",
]

OUT_PATH = Path(__file__).parent / "snapshots" / "before_unified_source.json"
OUT_PATH.parent.mkdir(parents=True, exist_ok=True)


def main() -> int:
    if not os.environ.get("DATABASE_URL"):
        print("ERROR: DATABASE_URL not set. Point at the Aiven prod replica.", file=sys.stderr)
        return 2

    rows: list[dict] = []
    with Session() as s:
        for tk in TICKERS:
            r = s.execute(
                text(
                    """
                    SELECT
                        ticker,
                        (payload->>'cached')                                         AS cached_flag,
                        (payload->'valuation'->>'fair_value')::float                 AS fair_value,
                        (payload->'valuation'->>'current_price')::float              AS current_price,
                        (payload->'valuation'->>'margin_of_safety')::float           AS margin_of_safety,
                         payload->'valuation'->>'verdict'                            AS verdict,
                        (payload->'valuation'->>'bear_case')::float                  AS bear_case,
                        (payload->'valuation'->>'base_case')::float                  AS base_case,
                        (payload->'valuation'->>'bull_case')::float                  AS bull_case,
                        (payload->'quality'->>'piotroski_score')::int                AS piotroski,
                         payload->'quality'->>'moat'                                 AS moat,
                        (payload->'quality'->>'roe')::float                          AS roe,
                        (payload->'quality'->>'roce')::float                         AS roce,
                        (payload->'quality'->>'de_ratio')::float                     AS de_ratio,
                        (payload->'valuation'->>'wacc')::float                       AS wacc,
                        (payload->'insights'->>'ev_ebitda')::float                   AS ev_ebitda,
                        (payload->'quality'->>'revenue_cagr_3y')::float              AS rev_cagr_3y,
                        (payload->'quality'->>'yieldiq_score')::int                  AS yieldiq_score,
                         cache_version                                               AS cache_version
                    FROM analysis_cache
                    WHERE ticker = :tk
                    """
                ),
                {"tk": tk},
            ).mappings().fetchone()
            if r:
                rows.append({"ticker": tk, "source": "analysis_cache", **dict(r)})
            else:
                rows.append({"ticker": tk, "source": "analysis_cache", "missing": True})

    OUT_PATH.write_text(
        json.dumps(
            {
                "snapshot_at": _dt.datetime.utcnow().isoformat() + "Z",
                "purpose": "before_unified_source_collapse",
                "ticker_count": len(TICKERS),
                "rows": rows,
            },
            indent=2,
            default=str,
        )
    )
    missing = sum(1 for r in rows if r.get("missing"))
    print(f"Wrote {len(rows)} rows ({missing} missing) to {OUT_PATH}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
