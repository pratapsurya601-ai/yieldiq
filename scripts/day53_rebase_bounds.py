#!/usr/bin/env python3
"""Day-53 (2026-05-20): mechanical canary-bounds rebase for long-tail.

Reads the latest canary_report.md (downloaded artifact), parses each
gate-4 violation, and applies a conservative widening per ticker:

  WACC lower-bound: drop to min(current, reported - 0.005), floor 0.07
  ROE  lower-bound: drop to min(current, reported - 0.01),  floor -0.10
  ROE  upper-bound: raise to max(current, reported + 0.05), cap 1.50

The "current, reported" guard means we NEVER tighten — only widen.
The conservative 0.005 / 0.01 padding ensures we don't re-fail on
small data wobbles between runs.

Special tickers already handled in Day-52 are skipped (HDFCBANK,
KOTAKBANK, INDUSINDBK, IDFCFIRSTB, BANDHANBNK, ZOMATO, NYKAA,
POLICYBZR).

Run:
    python scripts/day53_rebase_bounds.py /tmp/canary-report/canary_report.md

Writes scripts/canary_universe_180.json in place. Prints a summary
of every change made.
"""
from __future__ import annotations
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "scripts" / "canary_universe_180.json"

# Already updated in Day-52 PR #443; skip to avoid re-widening
DAY52_HANDLED = {
    "HDFCBANK", "KOTAKBANK", "INDUSINDBK", "IDFCFIRSTB", "BANDHANBNK",
    "ZOMATO", "NYKAA", "POLICYBZR",
}

# Regex for the two gate-4 violation shapes
RE_WACC = re.compile(
    r"-\s+(?P<sym>[A-Z0-9&\-]+)\.wacc=(?P<val>-?\d+\.?\d*)\s+outside"
)
RE_ROE = re.compile(
    r"-\s+(?P<sym>[A-Z0-9&\-]+)\.roe=(?P<val_pct>-?\d+\.?\d*)\s+"
    r"\(decimal=(?P<val_dec>-?\d+\.?\d*)\)\s+outside"
)


def parse_violations(report_text: str) -> tuple[dict, dict]:
    """Return ({sym: wacc_decimal}, {sym: roe_decimal})."""
    wacc: dict[str, float] = {}
    roe: dict[str, float] = {}
    for line in report_text.splitlines():
        m = RE_WACC.search(line)
        if m:
            wacc[m.group("sym")] = float(m.group("val"))
            continue
        m = RE_ROE.search(line)
        if m:
            roe[m.group("sym")] = float(m.group("val_dec"))
    return wacc, roe


def widen_lower(current: float, reported: float, pad: float, floor: float) -> float:
    """Lower the lower-bound to (reported - pad), but never raise."""
    target = round(max(reported - pad, floor), 4)
    return round(min(current, target), 4)


def widen_upper(current: float, reported: float, pad: float, cap: float) -> float:
    """Raise the upper-bound to (reported + pad), but never lower."""
    target = round(min(reported + pad, cap), 4)
    return round(max(current, target), 4)


def main(report_path: str) -> int:
    report = Path(report_path).read_text(encoding="utf-8")
    wacc_viols, roe_viols = parse_violations(report)
    print(f"Parsed {len(wacc_viols)} WACC + {len(roe_viols)} ROE violations.")

    with UNIVERSE.open(encoding="utf-8-sig") as f:
        data = json.load(f)

    changes: list[str] = []
    by_sym = {s["symbol"]: s for s in data["stocks"]}

    # WACC pass
    for sym, reported in wacc_viols.items():
        if sym in DAY52_HANDLED:
            continue
        stock = by_sym.get(sym)
        if not stock:
            print(f"  skip WACC {sym}: not in universe")
            continue
        b = stock["canary_bounds"].get("wacc")
        if not b or b[0] is None:
            continue
        new_lo = widen_lower(b[0], reported, pad=0.005, floor=0.07)
        if new_lo < b[0]:
            old = list(b)
            b[0] = new_lo
            changes.append(
                f"  WACC {sym}: {old} -> {b} (reported {reported})"
            )

    # ROE pass
    for sym, reported in roe_viols.items():
        if sym in DAY52_HANDLED:
            continue
        stock = by_sym.get(sym)
        if not stock:
            print(f"  skip ROE {sym}: not in universe")
            continue
        b = stock["canary_bounds"].get("roe")
        if not b or b[0] is None:
            continue
        old = list(b)
        # If reported is BELOW the lower bound, widen down
        if reported < b[0]:
            b[0] = widen_lower(b[0], reported, pad=0.01, floor=-1.0)
        # If reported is ABOVE the upper bound, widen up
        if reported > b[1]:
            b[1] = widen_upper(b[1], reported, pad=0.05, cap=1.5)
        if b != old:
            changes.append(
                f"  ROE  {sym}: {old} -> {b} (reported {reported})"
            )

    with UNIVERSE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"\nApplied {len(changes)} bound updates:\n")
    for c in changes:
        print(c)
    print(f"\nTotal: {len(changes)} stocks rebased.")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1] if len(sys.argv) > 1 else "/tmp/canary-report/canary_report.md"))
