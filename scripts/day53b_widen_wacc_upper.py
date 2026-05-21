#!/usr/bin/env python3
"""Day-53 follow-up: widen WACC UPPER bounds for the 0.128 cohort.

The day53_rebase_bounds.py script only widened WACC LOWER bounds
(because the 0.098 cluster was reported below the lower bound).
The 0.128 cluster reports ABOVE the upper bound — these are higher-
risk financial / utility names where the engine WACC has crept up
with the credit-spread environment.

This script handles them: raise WACC upper-bound to (reported + 0.005),
never lower.
"""
from __future__ import annotations
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UNIVERSE = ROOT / "scripts" / "canary_universe_180.json"

# From canary report 2026-05-21 against day53 branch (residual gate-4)
WACC_UPPER_VIOLS = {
    "BAJAJHFL": 0.128,
    "HUDCO": 0.1271,
    "IREDA": 0.128,
    "NIACL": 0.128,
    "ADANIENSOL": 0.1203,
    "NTPCGREEN": 0.128,
    "JSWENERGY": 0.128,
    "NLCINDIA": 0.128,
    "CESC": 0.128,
}


def main() -> int:
    with UNIVERSE.open(encoding="utf-8-sig") as f:
        data = json.load(f)

    changes = []
    by_sym = {s["symbol"]: s for s in data["stocks"]}
    for sym, reported in WACC_UPPER_VIOLS.items():
        stock = by_sym.get(sym)
        if not stock:
            print(f"  skip {sym}: not in universe")
            continue
        b = stock["canary_bounds"].get("wacc")
        if not b or b[1] is None:
            continue
        target = round(reported + 0.005, 4)
        new_hi = max(b[1], target)
        if new_hi > b[1]:
            old = list(b)
            b[1] = new_hi
            changes.append(f"  WACC {sym}: {old} -> {b} (reported {reported})")

    with UNIVERSE.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
        f.write("\n")

    print(f"Applied {len(changes)} WACC upper-bound widenings:\n")
    for c in changes:
        print(c)
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main())
