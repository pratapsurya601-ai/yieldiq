"""Screener-parity scorecard — measure YieldIQ DB coverage against
the known Screener.in depth (from public index pages, Oct 2026).

Run after any major ingestion to track parity progress over time. Emits
a markdown table and a JSON file (``parity_scorecard.json``) for CI.

Usage
-----
    DATABASE_URL=... python scripts/parity_scorecard.py
    DATABASE_URL=... python scripts/parity_scorecard.py --json-only
    DATABASE_URL=... python scripts/parity_scorecard.py --save snap.json

Scoring
-------
For each metric, we compute (our_value / screener_value) clamped to
[0, 1] and report the row pass/fail against a threshold. Overall score
is the weighted average — universe and fundamentals weigh 2x because
those are what users notice.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta
from pathlib import Path

try:
    import psycopg2
except ImportError:
    print("pip install psycopg2-binary", file=sys.stderr)
    sys.exit(2)


# Screener.in public-index reference (Oct 2026, from sitemap + "Explore")
SCREENER_REF = {
    "universe": 5450,
    "with_10y_annual": 4800,
    "with_5y_annual": 5300,
    "with_quarterly": 5100,
    "with_5y_shareholding": 4900,
    "with_10y_prices": 5200,
    "with_20y_prices": 3200,
    "pe_coverage_pct": 95.0,
    "ev_ebitda_coverage_pct": 85.0,
    "roe_coverage_pct": 98.0,
    "roce_coverage_pct": 98.0,
}


# Metric config: (label, weight, threshold_pct, comparison_mode)
#   threshold_pct: we consider the metric "passed" if ratio >= this
#   comparison_mode: 'count' (higher is better), 'pct' (percentage)
METRICS = [
    ("universe",               2.0, 0.85, "count"),
    ("with_10y_annual",        2.0, 0.75, "count"),
    ("with_5y_annual",         1.5, 0.85, "count"),
    ("with_quarterly",         1.5, 0.75, "count"),
    ("with_5y_shareholding",   1.0, 0.70, "count"),
    ("with_10y_prices",        1.0, 0.60, "count"),
    ("with_20y_prices",        0.5, 0.30, "count"),
    ("pe_coverage_pct",        1.5, 0.70, "pct"),
    ("ev_ebitda_coverage_pct", 1.0, 0.60, "pct"),
    ("roe_coverage_pct",       1.0, 0.90, "pct"),
    ("roce_coverage_pct",      1.0, 0.90, "pct"),
]


def _measure(cur) -> dict[str, float | int]:
    out: dict[str, float | int] = {}

    cur.execute("SELECT COUNT(*) FROM stocks WHERE is_active")
    out["universe"] = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM (
          SELECT ticker FROM financials
          WHERE period_type='annual' AND revenue IS NOT NULL
          GROUP BY ticker HAVING COUNT(*) >= 10
        ) t
    """)
    out["with_10y_annual"] = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM (
          SELECT ticker FROM financials
          WHERE period_type='annual' AND revenue IS NOT NULL
          GROUP BY ticker HAVING COUNT(*) >= 5
        ) t
    """)
    out["with_5y_annual"] = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM (
          SELECT ticker FROM financials
          WHERE period_type='quarterly' GROUP BY ticker HAVING COUNT(*) >= 8
        ) t
    """)
    out["with_quarterly"] = cur.fetchone()[0]

    cur.execute("""
        SELECT COUNT(*) FROM (
          SELECT ticker FROM shareholding_pattern
          GROUP BY ticker HAVING COUNT(*) >= 20
        ) t
    """)
    out["with_5y_shareholding"] = cur.fetchone()[0]

    ten_years_ago = (date.today() - timedelta(days=365 * 10)).isoformat()
    cur.execute(f"""
        SELECT COUNT(DISTINCT ticker) FROM daily_prices
        WHERE trade_date <= '{ten_years_ago}'
    """)
    out["with_10y_prices"] = cur.fetchone()[0]

    twenty_years_ago = (date.today() - timedelta(days=365 * 20)).isoformat()
    cur.execute(f"""
        SELECT COUNT(DISTINCT ticker) FROM daily_prices
        WHERE trade_date <= '{twenty_years_ago}'
    """)
    out["with_20y_prices"] = cur.fetchone()[0]

    cur.execute("SELECT ROUND(COUNT(*) FILTER (WHERE pe_ratio IS NOT NULL)*100.0/NULLIF(COUNT(*),0), 1) FROM ratio_history")
    out["pe_coverage_pct"] = float(cur.fetchone()[0] or 0)

    cur.execute("SELECT ROUND(COUNT(*) FILTER (WHERE ev_ebitda IS NOT NULL)*100.0/NULLIF(COUNT(*),0), 1) FROM ratio_history")
    out["ev_ebitda_coverage_pct"] = float(cur.fetchone()[0] or 0)

    cur.execute("SELECT ROUND(COUNT(*) FILTER (WHERE roe IS NOT NULL)*100.0/NULLIF(COUNT(*),0), 1) FROM ratio_history")
    out["roe_coverage_pct"] = float(cur.fetchone()[0] or 0)

    cur.execute("SELECT ROUND(COUNT(*) FILTER (WHERE roce IS NOT NULL)*100.0/NULLIF(COUNT(*),0), 1) FROM ratio_history")
    out["roce_coverage_pct"] = float(cur.fetchone()[0] or 0)

    return out


def _render_markdown(ours: dict, ref: dict) -> tuple[str, float, int, int]:
    lines = [
        "# YieldIQ vs Screener — Parity Scorecard",
        "",
        f"Generated: {datetime.utcnow().isoformat()}Z",
        "",
        "| Metric | YieldIQ | Screener | Ratio | Weight | Pass? |",
        "|---|---:|---:|---:|---:|:---:|",
    ]
    total_weight = 0.0
    weighted_sum = 0.0
    passed = 0
    total = 0
    for label, weight, thr, mode in METRICS:
        our = ours.get(label, 0)
        scr = ref.get(label, 0) or 1
        ratio = min(our / scr, 1.0) if scr else 0
        ok = ratio >= thr
        passed += 1 if ok else 0
        total += 1
        weighted_sum += ratio * weight
        total_weight += weight

        our_s = f"{our:,}" if mode == "count" else f"{our:.1f}%"
        scr_s = f"{scr:,}" if mode == "count" else f"{scr:.1f}%"
        mark = "PASS" if ok else "FAIL"
        lines.append(f"| {label} | {our_s} | {scr_s} | {ratio*100:.1f}% | {weight}x | {mark} |")

    overall_ratio = weighted_sum / total_weight if total_weight else 0
    lines.append("")
    lines.append(f"**Overall parity: {overall_ratio*100:.1f}%**  ({passed}/{total} thresholds met)")
    return "\n".join(lines), overall_ratio, passed, total


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--json-only", action="store_true")
    ap.add_argument("--save", default=None, help="Write JSON snapshot to this path")
    ap.add_argument("--out", default="parity_scorecard.json")
    args = ap.parse_args()

    url = os.environ.get("DATABASE_URL")
    if not url:
        print("DATABASE_URL not set", file=sys.stderr)
        return 2

    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        ours = _measure(cur)
    finally:
        conn.close()

    md, overall, passed, total = _render_markdown(ours, SCREENER_REF)

    payload = {
        "timestamp": datetime.utcnow().isoformat() + "Z",
        "ours": ours,
        "screener_ref": SCREENER_REF,
        "overall_parity": overall,
        "thresholds_passed": passed,
        "thresholds_total": total,
    }

    out_path = Path(args.save or args.out)
    out_path.write_text(json.dumps(payload, indent=2, default=str))

    if not args.json_only:
        print(md)
        print(f"\nJSON written to: {out_path}")

    # Exit 0 always — this is a scorecard, not a gate
    return 0


if __name__ == "__main__":
    sys.exit(main())
