"""Scan all Nifty 50 stocks for errors after bug-fix deploy.

Hits /api/v1/analysis/{ticker}/og-data for each ticker and checks:
- price > 0
- fair_value is reasonable (0.3x to 4x of price)
- mos is between -80% and +200%
- score is between 0 and 100

Reports each failing stock with the specific issue.
"""
from __future__ import annotations
import json
import sys
import urllib.request

NIFTY50 = [
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ITC.NS",
    "SBIN.NS", "ICICIBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "TITAN.NS",
    "WIPRO.NS", "AXISBANK.NS", "KOTAKBANK.NS", "LT.NS", "SUNPHARMA.NS",
    "HCLTECH.NS", "NESTLEIND.NS", "ASIANPAINT.NS", "ULTRACEMCO.NS", "ADANIENT.NS",
    "ADANIPORTS.NS", "POWERGRID.NS", "NTPC.NS", "ONGC.NS", "COALINDIA.NS",
    "BHARTIARTL.NS", "DIVISLAB.NS", "DRREDDY.NS", "CIPLA.NS", "EICHERMOT.NS",
    "HINDUNILVR.NS", "TATASTEEL.NS", "TECHM.NS", "APOLLOHOSP.NS", "BRITANNIA.NS",
    "HEROMOTOCO.NS", "BAJAJ-AUTO.NS", "INDUSINDBK.NS", "GRASIM.NS", "JSWSTEEL.NS",
    "BPCL.NS", "HINDALCO.NS", "M&M.NS", "TRENT.NS", "BEL.NS",
    "SHRIRAMFIN.NS", "ETERNAL.NS", "HAL.NS", "DMART.NS", "TATACONSUM.NS",
]

BASE = "https://api.yieldiq.in"


def check(ticker: str) -> tuple[str, dict | None, list[str]]:
    url = f"{BASE}/api/v1/analysis/{ticker}/og-data"
    issues: list[str] = []
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "YIQScan/1.0"})
        with urllib.request.urlopen(req, timeout=30) as r:
            data = json.loads(r.read().decode("utf-8"))
    except Exception as e:
        return ticker, None, [f"request_failed: {type(e).__name__}: {e}"]

    price = float(data.get("price", 0) or 0)
    fv = float(data.get("fair_value", 0) or 0)
    mos = float(data.get("mos", 0) or 0)
    score = int(data.get("score", 0) or 0)

    if price <= 0:
        issues.append(f"price={price} (zero or negative)")
    if fv <= 0:
        issues.append(f"fair_value={fv} (zero or negative)")
    if price > 0 and fv > 0:
        ratio = fv / price
        if ratio > 4.0:
            issues.append(f"fair_value={fv:.0f} is {ratio:.1f}x price — likely unit bug")
        elif ratio < 0.25:
            issues.append(f"fair_value={fv:.0f} is {ratio:.2f}x price — extremely low, check data")
    if mos < -80 or mos > 200:
        issues.append(f"mos={mos:.1f}% outside reasonable range")
    if score < 0 or score > 100:
        issues.append(f"score={score} outside 0-100")

    return ticker, data, issues


def main():
    print(f"Scanning {len(NIFTY50)} Nifty 50 tickers...\n")
    failures: list[tuple[str, dict | None, list[str]]] = []
    ok = 0
    for i, ticker in enumerate(NIFTY50, 1):
        t, data, issues = check(ticker)
        if issues:
            failures.append((t, data, issues))
            print(f"[{i:2d}/50] FAIL {t}")
            for iss in issues:
                print(f"         {iss}")
            if data:
                print(f"         price=\u20B9{data.get('price', 0):.0f}, fv=\u20B9{data.get('fair_value', 0):.0f}, mos={data.get('mos', 0):.1f}%, score={data.get('score', 0)}")
        else:
            ok += 1
            if data:
                print(f"[{i:2d}/50] ok   {t:15} p=\u20B9{data.get('price', 0):>6.0f} fv=\u20B9{data.get('fair_value', 0):>6.0f} mos={data.get('mos', 0):>+6.1f}% score={data.get('score', 0)}")

    print(f"\n{'='*60}")
    print(f"Summary: {ok}/{len(NIFTY50)} OK, {len(failures)} failures")
    if failures:
        print("\nFailures summary:")
        for t, _, issues in failures:
            print(f"  {t}: {'; '.join(issues)}")
    return 0 if not failures else 1


if __name__ == "__main__":
    sys.exit(main())
