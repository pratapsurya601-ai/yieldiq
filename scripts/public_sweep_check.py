"""Quick public-endpoint sweep — checks all 57 stocks for obvious issues.

No auth needed. Hits /api/v1/public/stock-summary/{ticker} and validates:
  1. MoS math: |reported_mos - computed_mos| < 2pp
  2. Scenarios: bear < base < bull (5%+ spread each side)
  3. Score in [0,100], grade is one of A+/A/B/C/D/F
  4. fair_value > 0 and < 100x current (sanity bound)
  5. Forbidden: ROCE > 100%, ROE < -100%, sentinel values

Run: python scripts/public_sweep_check.py
"""
from __future__ import annotations
import json
import sys
import time
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError, HTTPError

API_BASE = "https://api.yieldiq.in"
ROOT = Path(__file__).resolve().parent

def load_universe() -> list[str]:
    tickers: list[str] = []
    for f in ("canary_stocks_50.json", "canary_outliers_7.json"):
        p = ROOT / f
        if not p.exists():
            print(f"missing: {p}", file=sys.stderr)
            continue
        data = json.loads(p.read_text(encoding="utf-8"))
        for s in data.get("stocks", []):
            sym = s["symbol"]
            if not sym.endswith(".NS") and not sym.endswith(".BO"):
                sym = f"{sym}.NS"
            if sym not in tickers:
                tickers.append(sym)
    return tickers

def fetch(ticker: str) -> dict | None:
    url = f"{API_BASE}/api/v1/public/stock-summary/{ticker}"
    try:
        req = Request(url, headers={"User-Agent": "yieldiq-public-sweep/1.0"})
        with urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except HTTPError as e:
        return {"_err": f"HTTP {e.code}"}
    except URLError as e:
        return {"_err": f"URL {e.reason}"}
    except Exception as e:
        return {"_err": f"{type(e).__name__}: {e}"}

def check(ticker: str, d: dict) -> list[str]:
    if "_err" in d:
        return [f"FETCH: {d['_err']}"]
    issues: list[str] = []
    fv = d.get("fair_value")
    cp = d.get("current_price")
    mos = d.get("mos")
    bear = d.get("bear_case")
    base = d.get("base_case")
    bull = d.get("bull_case")
    score = d.get("score")
    grade = d.get("grade")
    roce = d.get("roce")
    roe = d.get("roe")

    # 1. MoS math
    if fv is not None and cp not in (None, 0) and mos is not None:
        computed = (fv - cp) / cp * 100
        if abs(computed - mos) > 2.0:
            issues.append(f"MOS_MATH: reported {mos:+.1f}% vs computed {computed:+.1f}%")

    # 2. Scenarios (only if all 3 present)
    if all(x is not None for x in (bear, base, bull)):
        if not (bear < base < bull):
            issues.append(f"SCEN_ORDER: bear={bear}, base={base}, bull={bull}")
        elif base > 0:
            if (base - bear) / base < 0.05:
                issues.append(f"SCEN_BEAR_TIGHT: spread {(base-bear)/base*100:.1f}% < 5%")
            if (bull - base) / base < 0.05:
                issues.append(f"SCEN_BULL_TIGHT: spread {(bull-base)/base*100:.1f}% < 5%")

    # 3. Score / grade
    if score is not None and not (0 <= score <= 100):
        issues.append(f"SCORE_RANGE: {score}")
    if grade not in (None, "A+", "A", "B+", "B", "C+", "C", "D", "F"):
        issues.append(f"GRADE_INVALID: {grade!r}")

    # 4. FV sanity
    if fv is not None and cp not in (None, 0):
        if fv <= 0:
            issues.append(f"FV_NONPOSITIVE: {fv}")
        elif fv > cp * 100:
            issues.append(f"FV_RUNAWAY: fv={fv} cp={cp} ratio={fv/cp:.1f}x")

    # 5. Forbidden values
    if roce is not None and (roce > 100 or roce < -100):
        issues.append(f"ROCE_OUTLIER: {roce}")
    if roe is not None and (roe < -100 or roe > 200):
        issues.append(f"ROE_OUTLIER: {roe}")
    # known sentinels
    for k in ("fair_value", "mos", "score"):
        v = d.get(k)
        if v == -439:
            issues.append(f"SENTINEL_-439 in {k}")

    return issues

def main():
    tickers = load_universe()
    print(f"Sweeping {len(tickers)} tickers against {API_BASE}\n")
    print(f"{'TICKER':<14} {'CP':>10} {'FV':>10} {'MOS%':>7} {'SCORE':>5} {'GRADE':>5}  STATUS")
    print("-" * 90)
    clean = 0
    flagged: list[tuple[str, list[str]]] = []
    for i, t in enumerate(tickers):
        d = fetch(t)
        cp = d.get("current_price")
        fv = d.get("fair_value")
        mos = d.get("mos")
        sc = d.get("score")
        gr = d.get("grade")
        issues = check(t, d)
        status = "OK" if not issues else f"{len(issues)} issue(s)"
        cp_s = f"{cp:>10.2f}" if isinstance(cp, (int, float)) else f"{'—':>10}"
        fv_s = f"{fv:>10.2f}" if isinstance(fv, (int, float)) else f"{'—':>10}"
        mos_s = f"{mos:>+7.1f}" if isinstance(mos, (int, float)) else f"{'—':>7}"
        sc_s = f"{sc:>5}" if sc is not None else f"{'—':>5}"
        gr_s = f"{(gr or '—'):>5}"
        print(f"{t:<14} {cp_s} {fv_s} {mos_s} {sc_s} {gr_s}  {status}")
        if issues:
            flagged.append((t, issues))
        else:
            clean += 1
        time.sleep(0.1)  # gentle on Railway

    print("\n" + "=" * 90)
    print(f"Clean: {clean}/{len(tickers)} | Flagged: {len(flagged)}")
    if flagged:
        print("\nDETAILS:")
        for t, issues in flagged:
            print(f"  {t}:")
            for issue in issues:
                print(f"    - {issue}")
    sys.exit(0 if not flagged else 1)

if __name__ == "__main__":
    main()
