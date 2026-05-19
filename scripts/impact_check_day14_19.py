"""Impact-check report for the 24 named tickers fixed Days 14-19.

Run this 24-48h after merging PR #408 (Day-18-19, 2026-05-20) so the
analysis_cache has had time to repopulate via natural user traffic.

For each ticker, compares:
  - PRE  FV (the value we saw in the Day-13 stale-cache scan)
  - POST FV (the value currently in analysis_cache)
  - Consensus median (from consensus_estimates)
  - The engine string that produced POST (lets us see if the new
    safety-net rungs actually fired)

Buckets the 24 tickers by which Day-XX fix targeted them, so success
or non-recompute is visible at a glance.

Usage:
    DATABASE_URL=... py scripts/impact_check_day14_19.py
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402


# ── The 24 named fixes, grouped by the day they shipped ──────────
FIXES: list[tuple[str, str, float, float]] = [
    # (ticker, fix_day_label, pre_fv_from_day13_scan, consensus_at_scan)
    # Day-16: hospital chain (WACC floor + TG lift)
    ("MAXHEALTH",  "16/hospital",   197.2, 1215.0),
    ("FORTIS",     "16/hospital",   353.4, 1105.0),
    ("MEDANTA",    "16/hospital",   342.1, 1337.5),
    ("KIMS",       "16/hospital",   289.5, 800.0),
    ("APOLLOHOSP", "16/hospital",  3492.7, 9000.0),
    ("NH",         "16/hospital",   985.8, 2000.0),
    ("ASTERDM",    "16/hospital",   461.2, 785.0),
    ("RAINBOW",    "16/hospital",   929.8, 1512.5),
    ("VIJAYA",     "16/hospital",   206.7, 1398.0),
    ("AGARWALEYE", "16/hospital",    45.7, 531.0),
    # Day-17: recent-IPO routing
    ("ITCHOTELS",  "17/qsr",         15.6, 210.0),
    ("ABLBL",      "17/qsr",         10.3, 149.0),
    ("FIVESTAR",   "17/hfc",         45.3, 620.0),
    ("AADHARHFC",  "17/hfc",         45.5, 620.0),
    ("CANHLIFE",   "17/insurance",   13.8, 180.0),
    # Day-18: logistics platforms via story-DCF
    ("DELHIVERY",  "18/logistics",   63.7, 528.0),
    ("MAHLOG",     "18/logistics",   None, None),
    ("ALLCARGO",   "18/logistics",   None, None),
    # Day-19: pharma CDMO sub-bucket
    ("DIVISLAB",   "19/cdmo",         0.0, 6822.5),
    ("SYNGENE",    "19/cdmo",       307.7, 542.5),
    ("COHANCE",    "19/cdmo",        92.0, 440.0),
    ("ANTHEM",     "19/cdmo",       133.9, 790.0),
    ("SAGILITY",   "19/cdmo",        34.6, 57.0),
    ("IKS",        "19/cdmo",       672.4, 1940.0),
]


def _normalize_url(url: str) -> str:
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return url


SQL = text("""
    SELECT
        replace(replace(ticker, '.NS', ''), '.BO', '') AS t,
        (payload->'valuation'->>'fair_value')::float       AS post_fv,
        (payload->'valuation'->>'current_price')::float    AS cmp,
        (payload->'valuation'->>'valuation_engine_used')   AS engine,
        cache_version,
        computed_at
    FROM analysis_cache
    WHERE replace(replace(ticker, '.NS', ''), '.BO', '') = :t
    ORDER BY computed_at DESC
    LIMIT 1
""")


def main() -> int:
    db = os.environ.get("DATABASE_URL")
    if not db:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2
    engine = create_engine(_normalize_url(db), pool_pre_ping=True)
    Session = sessionmaker(bind=engine)

    rows: list[dict] = []
    with Session() as sess:
        for ticker, day_label, pre_fv, consensus in FIXES:
            r = sess.execute(SQL, {"t": ticker}).first()
            if not r:
                rows.append({
                    "ticker": ticker, "day": day_label,
                    "pre_fv": pre_fv, "consensus": consensus,
                    "post_fv": None, "cmp": None, "engine": "(no row)",
                    "cache_version": None, "recomputed": False,
                })
                continue
            rows.append({
                "ticker": ticker, "day": day_label,
                "pre_fv": pre_fv, "consensus": consensus,
                "post_fv": float(r.post_fv) if r.post_fv else None,
                "cmp": float(r.cmp) if r.cmp else None,
                "engine": r.engine or "?",
                "cache_version": r.cache_version,
                "recomputed": (r.cache_version or "") >= "118",
            })

    # ── Header ─────────────────────────────────────────────────
    print(f"{'ticker':<12} {'fix-day':<14} "
          f"{'pre_fv':>9} {'post_fv':>9} {'consensus':>10} "
          f"{'pre_ratio':>10} {'post_ratio':>11} "
          f"{'engine':<32} {'v':<4} delta")
    print("-" * 130)

    for r in rows:
        pre_r = (r["pre_fv"] / r["consensus"]) if (r["pre_fv"] and r["consensus"]) else None
        post_r = (r["post_fv"] / r["consensus"]) if (r["post_fv"] and r["consensus"]) else None
        delta = ""
        if pre_r is not None and post_r is not None:
            mv = post_r - pre_r
            if mv > 0.10:
                delta = f"↑↑ +{mv:.2f}x (real movement)"
            elif mv > 0.03:
                delta = f"↑  +{mv:.2f}x"
            elif mv < -0.10:
                delta = f"↓↓ {mv:.2f}x"
            elif abs(mv) < 0.03:
                delta = "—  (no recompute? stale?)"
            else:
                delta = f"   {mv:+.2f}x"
        print(
            f"{r['ticker']:<12} "
            f"{r['day']:<14} "
            f"{(f'{r['pre_fv']:.0f}' if r['pre_fv'] is not None else '?'):>9} "
            f"{(f'{r['post_fv']:.0f}' if r['post_fv'] is not None else '?'):>9} "
            f"{(f'{r['consensus']:.0f}' if r['consensus'] is not None else '?'):>10} "
            f"{(f'{pre_r:.2f}x' if pre_r is not None else '?'):>10} "
            f"{(f'{post_r:.2f}x' if post_r is not None else '?'):>11} "
            f"{(r['engine'] or '?')[:32]:<32} "
            f"{(r['cache_version'] or '?'):<4} "
            f"{delta}"
        )

    # ── Summary stats ──────────────────────────────────────────
    print()
    total = len(rows)
    recomputed = sum(1 for r in rows if r["recomputed"])
    real_moves = sum(
        1 for r in rows
        if r["pre_fv"] and r["post_fv"] and r["consensus"]
        and (r["post_fv"] / r["consensus"]) - (r["pre_fv"] / r["consensus"]) > 0.10
    )
    in_band_now = sum(
        1 for r in rows
        if r["post_fv"] and r["consensus"]
        and 0.30 <= (r["post_fv"] / r["consensus"]) <= 3.50
    )
    print(f"SUMMARY: {recomputed}/{total} recomputed (cache_version >= 118)")
    print(f"         {real_moves}/{total} showed a real FV move (>+0.10x vs pre)")
    print(f"         {in_band_now}/{total} are now in the [0.30, 3.50] safety-net band")
    print()
    print("Next-action heuristic:")
    print("  If recomputed count is LOW (< 12/24), wait another 24h — natural")
    print("  cache warming is still in progress. Or trigger a forced batch")
    print("  recompute via the /admin endpoint.")
    print("  If recomputed count is HIGH (>= 18) but real_moves is LOW (< 12),")
    print("  the fixes need re-tuning — investigate specific tickers.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
