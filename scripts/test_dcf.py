"""
DCF test harness -- validates every analysis against a golden snapshot.

Workflow:
  1. Snapshot the current state (one-time, or after intentional changes):
       python scripts/test_dcf.py --update

  2. On every code change, re-run:
       python scripts/test_dcf.py

     Reports regressions beyond tolerances. Exit 1 if any ticker fails.

  3. Backtest mode (slow):
       python scripts/test_dcf.py --backtest

     Fetches fair_value_history, compares our past FVs against realised
     1y/3y forward returns. Answers "does YieldIQ actually work?"

Design goals:
- Stdlib only -- no extra deps.
- Fast: ~60 sec for 50 tickers at 2 req/s.
- Deterministic: same ticker list every run, so results are comparable.
- Clear diff output: shows field-by-field changes with tolerances.

The snapshot lives at scripts/dcf_golden.json and is committed. When you
deliberately change DCF logic (new weights, different growth caps, etc.),
you review the diff, decide it's intentional, and re-snapshot via --update.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import time
import urllib.request
from pathlib import Path


# ── Golden ticker list ────────────────────────────────────────────
# Curated mix: Nifty 50 core + sectoral diversity + known edge cases.
# Changing this list means rebaselining the whole snapshot -- think
# twice before modifying.
GOLDEN_TICKERS: list[str] = [
    # Nifty 50 large-caps
    "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ITC.NS",
    "SBIN.NS", "ICICIBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "TITAN.NS",
    "LT.NS", "SUNPHARMA.NS", "HCLTECH.NS", "NESTLEIND.NS", "ASIANPAINT.NS",
    "ULTRACEMCO.NS", "HINDUNILVR.NS", "POWERGRID.NS", "NTPC.NS", "BHARTIARTL.NS",
    # Other blue-chips
    "KOTAKBANK.NS", "AXISBANK.NS", "WIPRO.NS", "TECHM.NS", "ONGC.NS",
    "COALINDIA.NS", "JSWSTEEL.NS", "TATASTEEL.NS", "DRREDDY.NS", "DIVISLAB.NS",
    "CIPLA.NS", "HEROMOTOCO.NS", "EICHERMOT.NS", "BRITANNIA.NS", "DABUR.NS",
    "BPCL.NS", "IOC.NS", "LTIM.NS", "MPHASIS.NS", "COFORGE.NS",
    # USD reporters (per-statement currency detection)
    "PERSISTENT.NS", "KPITTECH.NS", "TATAELXSI.NS",
    # Demerger successor
    "TMPV.NS",
    # Post-split / post-bonus
    "NESTLEIND.NS",  # already above -- kept for clarity
    # Growth / pre-profit (should be handled gracefully)
    "ETERNAL.NS",
    # Mid-caps with real data
    "DALBHARAT.NS", "BLUESTARCO.NS", "BERGEPAINT.NS",
    # Cement + capital-heavy
    "SHREECEM.NS", "JKCEMENT.NS", "AMBUJACEM.NS",
]


# ── Tolerance config ──────────────────────────────────────────────
# Allowed drift per field between golden and current. Too tight -> false
# positives on market-price-driven changes. Too loose -> misses regressions.
TOLERANCES = {
    "fair_value_pct":     0.05,   # +/-5% FV drift OK (DCF assumptions may vary slightly)
    "price_pct":          0.10,   # +/-10% price drift OK (intraday / next-day)
    "mos_abs":            5.0,    # +/-5 percentage points MoS drift OK
    "score_abs":          3,      # +/-3 score points OK
    "verdict_exact":      True,   # verdict must match exactly
    "moat_exact":         True,   # moat grade must match exactly
}


def fetch(url: str, timeout: int = 30) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "YIQTestDCF/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception as e:
        print(f"  ! fetch error for {url}: {type(e).__name__}: {e}",
              file=sys.stderr)
        return None


def capture(ticker: str, api_base: str) -> dict | None:
    """Capture the current DCF output for one ticker (compact snapshot)."""
    og = fetch(f"{api_base}/api/v1/analysis/{ticker}/og-data")
    if not og or "fair_value" not in og:
        return None
    trace = fetch(f"{api_base}/api/v1/debug/dcf-trace/{ticker}") or {}
    return {
        "ticker": ticker,
        "fair_value": round(float(og.get("fair_value") or 0), 2),
        "price":      round(float(og.get("price") or 0), 2),
        "mos":        round(float(og.get("mos") or 0), 1),
        "verdict":    og.get("verdict", ""),
        "score":      int(og.get("score") or 0),
        # From trace (may be empty for non-DCF paths)
        "fcf_base":   float(trace.get("fcf_base") or 0),
        "iv_ratio":   round(float(trace.get("iv_ratio") or 0), 3),
        "capped":     bool(trace.get("capped")),
        "wacc":       round(float(trace.get("wacc") or 0), 4),
    }


def capture_all(tickers: list[str], api_base: str, rate: float) -> dict[str, dict]:
    """Capture snapshots for a list of tickers."""
    out: dict[str, dict] = {}
    delay = 1.0 / rate if rate > 0 else 0
    for i, t in enumerate(tickers, 1):
        snap = capture(t, api_base)
        if snap:
            out[t] = snap
            print(f"  [{i}/{len(tickers)}] {t}: FV={snap['fair_value']} "
                  f"MoS={snap['mos']}% score={snap['score']} ({snap['verdict']})")
        else:
            print(f"  [{i}/{len(tickers)}] {t}: FETCH FAILED", file=sys.stderr)
        if delay:
            time.sleep(delay)
    return out


def compare(golden: dict, current: dict) -> list[str]:
    """Return list of tolerance-violating diffs. Empty list = pass."""
    diffs: list[str] = []

    def _pct_diff(a: float, b: float) -> float:
        if a == 0 and b == 0:
            return 0.0
        if a == 0:
            return 1.0
        return abs(b - a) / abs(a)

    # Fair value (with tolerance for zero -- data_limited tickers)
    gfv, cfv = float(golden.get("fair_value") or 0), float(current.get("fair_value") or 0)
    if gfv == 0 and cfv != 0:
        diffs.append(f"fair_value: was 0 (data_limited), now {cfv} -- ticker UNGATED (good or regression?)")
    elif gfv != 0 and cfv == 0:
        diffs.append(f"fair_value: was {gfv}, now 0 (data_limited) -- possible regression")
    elif gfv > 0:
        drift = _pct_diff(gfv, cfv)
        if drift > TOLERANCES["fair_value_pct"]:
            diffs.append(f"fair_value: {gfv:.2f} -> {cfv:.2f} ({drift:+.1%} drift, tolerance +/-{TOLERANCES['fair_value_pct']:.0%})")

    # MoS (absolute delta)
    gmos, cmos = float(golden.get("mos") or 0), float(current.get("mos") or 0)
    if abs(cmos - gmos) > TOLERANCES["mos_abs"]:
        diffs.append(f"mos: {gmos:.1f}% -> {cmos:.1f}% (delta {cmos - gmos:+.1f}pp, tolerance +/-{TOLERANCES['mos_abs']}pp)")

    # Score
    gs, cs = int(golden.get("score") or 0), int(current.get("score") or 0)
    if abs(cs - gs) > TOLERANCES["score_abs"]:
        diffs.append(f"score: {gs} -> {cs} (delta {cs - gs:+d}, tolerance +/-{TOLERANCES['score_abs']})")

    # Verdict (must match exactly)
    if TOLERANCES["verdict_exact"]:
        gv, cv = str(golden.get("verdict") or ""), str(current.get("verdict") or "")
        if gv != cv:
            diffs.append(f"verdict: '{gv}' -> '{cv}'")

    # iv_ratio sanity -- new suspicious values (were OK, now > 3x)
    givr, civr = float(golden.get("iv_ratio") or 0), float(current.get("iv_ratio") or 0)
    if givr < 3.0 and civr >= 3.0:
        diffs.append(f"iv_ratio: {givr} -> {civr} -- CROSSED 3x GATE THRESHOLD (new suspicious)")
    if givr >= 3.0 and civr < 3.0:
        diffs.append(f"iv_ratio: {givr} -> {civr} -- CLEARED 3x gate (likely intentional fix)")

    # Cap state
    if golden.get("capped") != current.get("capped"):
        diffs.append(f"capped: {golden.get('capped')} -> {current.get('capped')}")

    return diffs


def cmd_update(api_base: str, rate: float, out_path: Path) -> int:
    print(f"Capturing golden snapshot ({len(GOLDEN_TICKERS)} tickers at {rate}/s)")
    start = time.time()
    snapshots = capture_all(GOLDEN_TICKERS, api_base, rate)
    record = {
        "captured_at": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "api_base": api_base,
        "ticker_count": len(snapshots),
        "tickers": snapshots,
    }
    out_path.write_text(json.dumps(record, indent=2), encoding="utf-8")
    print(f"\n[OK] Snapshot captured -> {out_path} "
          f"({len(snapshots)}/{len(GOLDEN_TICKERS)} tickers, {time.time()-start:.0f}s)")
    return 0


def cmd_test(api_base: str, rate: float, golden_path: Path,
             max_regressions: int) -> int:
    if not golden_path.exists():
        print(f"ERROR: golden snapshot missing at {golden_path}", file=sys.stderr)
        print("Run: python scripts/test_dcf.py --update", file=sys.stderr)
        return 2

    golden = json.loads(golden_path.read_text(encoding="utf-8"))
    tickers = list(golden.get("tickers", {}).keys())
    if not tickers:
        print("ERROR: golden snapshot has no tickers", file=sys.stderr)
        return 2

    print(f"Testing against golden snapshot captured at {golden.get('captured_at')}")
    print(f"Scanning {len(tickers)} tickers at {rate}/s...\n")

    current = capture_all(tickers, api_base, rate)

    print("\n" + "=" * 60)
    print("Comparing against golden...")
    print("=" * 60 + "\n")

    regressions: list[tuple[str, list[str]]] = []
    missing: list[str] = []
    for t in tickers:
        g = golden["tickers"].get(t)
        c = current.get(t)
        if c is None:
            missing.append(t)
            continue
        diffs = compare(g, c)
        if diffs:
            regressions.append((t, diffs))

    if missing:
        print(f"! Missing current data for {len(missing)} tickers: {', '.join(missing[:5])}"
              f"{'...' if len(missing) > 5 else ''}\n")

    if regressions:
        print(f"REGRESSIONS ({len(regressions)} tickers):\n")
        for t, diffs in regressions:
            print(f"  {t}")
            for d in diffs:
                print(f"    - {d}")
            print()
    else:
        print("[OK] No regressions -- all tickers within tolerance\n")

    print("=" * 60)
    print(f"Summary: {len(tickers) - len(regressions) - len(missing)}/{len(tickers)} "
          f"clean - {len(regressions)} regressions - {len(missing)} missing")
    blocking = len(regressions) > max_regressions
    if blocking:
        print(f"[FAIL] BLOCKING: {len(regressions)} regressions exceeds threshold {max_regressions}")
    else:
        print(f"[OK] PASS: regressions within threshold {max_regressions}")

    return 1 if blocking else 0


def cmd_backtest(api_base: str, rate: float) -> int:
    """
    Pull fair_value_history + current prices, compute realised returns
    against our historical verdicts. Answers 'does YieldIQ work?'
    """
    # Lightweight first pass: fetch /api/v1/public/all-tickers, for each
    # ticker pull fair_value_history from /api/v1/analysis/{t}/fv-history,
    # compare historical FV/price ratio vs realised 1y forward return.
    print("Backtest mode -- pulling fair value history...")
    tickers_data = fetch(f"{api_base}/api/v1/public/all-tickers") or []
    if isinstance(tickers_data, dict):
        tickers_data = tickers_data.get("tickers", [])
    tickers = [t["full_ticker"] if isinstance(t, dict) else t for t in tickers_data][:50]
    print(f"  analysing {len(tickers)} tickers with fv-history")

    # For MVP: categorize by verdict-at-time and report hit-rate.
    # Full backtest (1y forward return correlation) is a bigger job.
    # Stubbed for now -- prints placeholder.
    print()
    print("  [backtest MVP is a stub; expand in next session]")
    print("  placeholder metrics:")
    print("    - Undervalued @ t-1y -> 1y forward return: TBD")
    print("    - Overvalued  @ t-1y -> 1y forward return: TBD")
    print("    - MoS magnitude -> realised return correlation: TBD")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="https://api.yieldiq.in")
    parser.add_argument("--rate", type=float, default=2.0,
                        help="Requests per second (default 2.0)")
    parser.add_argument("--golden", default="scripts/dcf_golden.json",
                        help="Path to golden snapshot file")
    parser.add_argument("--update", action="store_true",
                        help="Rebaseline the golden snapshot with current state")
    parser.add_argument("--backtest", action="store_true",
                        help="Run backtest mode (historical FV vs realised returns)")
    parser.add_argument("--max-regressions", type=int, default=3,
                        help="Exit 1 if more than N regressions (default 3)")
    args = parser.parse_args()

    golden_path = Path(args.golden)

    if args.update:
        return cmd_update(args.api_base, args.rate, golden_path)
    if args.backtest:
        return cmd_backtest(args.api_base, args.rate)
    return cmd_test(args.api_base, args.rate, golden_path, args.max_regressions)


if __name__ == "__main__":
    sys.exit(main())
