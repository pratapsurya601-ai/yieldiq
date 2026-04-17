"""
Canary check: validate 20 well-known Indian stocks against expected ranges.

Runs against production API. Fails (exit 1) if any canary is out of range.
Designed to be run nightly via GitHub Actions.

Usage:
    python scripts/canary_check.py [--api-base URL]
"""
from __future__ import annotations
import argparse
import json
import sys
import urllib.request


# Hardcoded expected ranges for 20 canary stocks.
# These are well-known Indian stocks with relatively stable fundamentals.
# If YieldIQ's output falls outside these ranges, something is broken.
#
# Ranges are deliberately WIDE to account for market fluctuation —
# we're catching bugs (e.g. WACC 1200%), not valuation disagreements.
CANARIES = {
    # Ticker:          (cmp_min, cmp_max,  fv_min,  fv_max,  score_min, score_max)
    "RELIANCE.NS":     (1000,    3500,     800,     5000,    40,        95),
    "TCS.NS":          (2500,    5000,     2000,    7000,    50,        95),
    "HDFCBANK.NS":     (1200,    2200,     1000,    3500,    50,        95),
    "INFY.NS":         (1100,    2200,     800,     3500,    50,        95),
    "ITC.NS":          (200,     600,      200,     900,     50,        95),
    "SBIN.NS":         (400,     1100,     300,     1800,    40,        95),
    "ICICIBANK.NS":    (700,     1600,     500,     2500,    50,        95),
    "BAJFINANCE.NS":   (5000,    10000,    3000,    15000,   40,        95),
    "MARUTI.NS":       (8000,    15000,    6000,    20000,   40,        95),
    "TITAN.NS":        (2500,    5000,     1500,    6500,    40,        95),
    "LT.NS":           (2500,    5000,     2000,    7000,    40,        95),
    "SUNPHARMA.NS":    (1200,    2200,     900,     3000,    40,        95),
    "HCLTECH.NS":      (1000,    2500,     800,     4000,    50,        95),
    "NESTLEIND.NS":    (2000,    4000,     1200,    4500,    40,        95),
    "ASIANPAINT.NS":   (1800,    4000,     1500,    5000,    40,        95),
    "ULTRACEMCO.NS":   (8000,    15000,    5000,    20000,   40,        95),
    "HINDUNILVR.NS":   (2000,    4000,     1500,    4500,    40,        95),
    "POWERGRID.NS":    (200,     500,      150,     700,     40,        95),
    "NTPC.NS":         (200,     500,      150,     700,     40,        95),
    "BHARTIARTL.NS":   (1000,    2500,     800,     3500,    40,        95),
}


def fetch(url: str, timeout: int = 30) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "YIQCanary/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  fetch error: {type(e).__name__}: {e}", file=sys.stderr)
        return None


def check_canary(ticker: str, expected: tuple, api_base: str) -> list[str]:
    """Return list of failure messages (empty = all good)."""
    data = fetch(f"{api_base}/api/v1/analysis/{ticker}/og-data")
    if not data:
        return ["API request failed"]

    cmp_min, cmp_max, fv_min, fv_max, score_min, score_max = expected
    failures: list[str] = []

    price = float(data.get("price", 0) or 0)
    fv = float(data.get("fair_value", 0) or 0)
    mos = float(data.get("mos", 0) or 0)
    score = int(data.get("score", 0) or 0)

    if price < cmp_min or price > cmp_max:
        failures.append(f"CMP {price:.0f} outside expected [{cmp_min}, {cmp_max}]")
    if fv <= 0:
        failures.append(f"Fair value is {fv}")
    elif fv < fv_min or fv > fv_max:
        failures.append(f"Fair value {fv:.0f} outside expected [{fv_min}, {fv_max}]")
    if score < score_min or score > score_max:
        failures.append(f"Score {score} outside expected [{score_min}, {score_max}]")

    # Extreme MoS detection
    if abs(mos) > 200:
        failures.append(f"MoS {mos:.1f}% extreme (likely unit bug)")

    # FV/CMP ratio sanity
    if price > 0 and fv > 0:
        ratio = fv / price
        if ratio > 4.0 or ratio < 0.25:
            failures.append(f"FV/CMP ratio {ratio:.1f}x — likely unit bug")

    return failures


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="https://api.yieldiq.in")
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()

    print(f"Canary check against {args.api_base}")
    print(f"Checking {len(CANARIES)} stocks...\n")

    total = len(CANARIES)
    passed = 0
    failed_tickers: list[tuple[str, list[str]]] = []

    for ticker, expected in CANARIES.items():
        failures = check_canary(ticker, expected, args.api_base)
        if failures:
            failed_tickers.append((ticker, failures))
            print(f"[FAIL] {ticker}")
            for f in failures:
                print(f"       - {f}")
        else:
            passed += 1
            if args.verbose:
                print(f"[ok]   {ticker}")

    print()
    print("=" * 60)
    print(f"Canary result: {passed}/{total} passed, {len(failed_tickers)} failed")

    if failed_tickers:
        print("\nFailed tickers:")
        for t, fs in failed_tickers:
            print(f"  {t}: {'; '.join(fs)}")
        return 1
    print("\nAll canaries healthy.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
