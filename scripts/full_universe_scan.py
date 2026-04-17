"""
Full-universe quality scan for YieldIQ.

For every ticker in the production universe:
  1. Calls /api/v1/analysis/{ticker}/og-data to trigger a fresh DCF
  2. Calls /api/v1/debug/dcf-trace/{ticker} to fetch the structured trace
  3. Runs 10 deterministic quality rules (no hardcoded per-ticker bounds)
  4. Aggregates issues into a machine-readable JSON report

Unlike the 20-stock canary, this scan uses UNIVERSAL rules that apply to
any ticker — so it scales to 2,900+ stocks without per-ticker knowledge.

Usage:
    python scripts/full_universe_scan.py
    python scripts/full_universe_scan.py --limit 100          # smoke test
    python scripts/full_universe_scan.py --rate 2.0 --report out.json
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import time
import urllib.request
from collections import Counter


# ── Quality rules ────────────────────────────────────────────────
# Each rule: (rule_id, severity, predicate, message_template)
# predicate(trace, og) → bool (True = issue present)
# Universal — no per-ticker knowledge, only DCF sanity.
RULES: list[tuple[str, str, callable, str]] = [
    (
        "fcf_base_nonpositive", "critical",
        lambda t, o: (t or {}).get("fcf_base", 0) <= 0,
        "fcf_base={fcf_base:.2e} ≤ 0 — DCF not applicable",
    ),
    (
        "iv_ratio_high", "critical",
        lambda t, o: (t or {}).get("iv_ratio", 0) > 3.0,
        "iv_ratio={iv_ratio:.2f}x — fair value suspiciously high (possible unit bug)",
    ),
    (
        "iv_ratio_low", "warning",
        lambda t, o: 0 < (t or {}).get("iv_ratio", 1) < 0.33,
        "iv_ratio={iv_ratio:.2f}x — fair value suspiciously low",
    ),
    (
        "tv_dominance", "warning",
        lambda t, o: (t or {}).get("tv_pct_ev", 0) > 0.95,
        "tv_pct_ev={tv_pct_ev:.2%} — terminal value dominates EV (fragile)",
    ),
    (
        "impl_g_unrealistic", "critical",
        lambda t, o: (t or {}).get("impl_g", 0) > 0.50,
        "impl_g={impl_g:.1%} — implied FCF compound growth unrealistic",
    ),
    (
        "wacc_g_tight_spread", "critical",
        lambda t, o: (t or {}).get("wacc", 1) - (t or {}).get("g", 0) < 0.03,
        "WACC-g spread={spread:.2%} — terminal value will explode",
    ),
    (
        "capped", "info",
        lambda t, o: bool((t or {}).get("capped")),
        "DCF raw IV was clamped by 5x price cap",
    ),
    (
        "price_zero", "critical",
        lambda t, o: float((o or {}).get("price", 0) or 0) <= 0,
        "price=0 — price pipeline failed",
    ),
    (
        "fair_value_zero", "critical",
        lambda t, o: float((o or {}).get("fair_value", 0) or 0) <= 0,
        "fair_value=0 — DCF produced no result",
    ),
    (
        "score_zero", "warning",
        lambda t, o: int((o or {}).get("score", 0) or 0) == 0,
        "score=0 — quality computation failed",
    ),
    (
        "mos_extreme", "critical",
        lambda t, o: abs(float((o or {}).get("mos", 0) or 0)) > 500,
        "mos={mos:.0f}% — extreme margin of safety (unit bug candidate)",
    ),
]


def fetch(url: str, timeout: int = 30) -> dict | None:
    try:
        req = urllib.request.Request(url, headers={"User-Agent": "YIQUniverseScan/1.0"})
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read().decode("utf-8"))
    except Exception:
        return None


def evaluate(ticker: str, api_base: str) -> list[dict]:
    """Return list of issue dicts for a ticker (empty = clean)."""
    og = fetch(f"{api_base}/api/v1/analysis/{ticker}/og-data")
    if og is None:
        return [{"rule": "fetch_failed", "severity": "critical",
                 "message": "og-data endpoint unreachable"}]
    trace = fetch(f"{api_base}/api/v1/debug/dcf-trace/{ticker}")
    # trace may be None if the DCF ring buffer hasn't captured this ticker;
    # rules that need it will skip via the `(t or {})` guard.

    issues = []
    fmt_ctx = {
        **(trace or {}),
        "price": (og or {}).get("price", 0),
        "fair_value": (og or {}).get("fair_value", 0),
        "score": (og or {}).get("score", 0),
        "mos": (og or {}).get("mos", 0),
        "spread": (trace or {}).get("wacc", 0) - (trace or {}).get("g", 0),
    }
    for rule_id, severity, predicate, template in RULES:
        try:
            if predicate(trace, og):
                try:
                    msg = template.format(**fmt_ctx)
                except Exception:
                    msg = template
                issues.append({"rule": rule_id, "severity": severity, "message": msg})
        except Exception:
            pass
    return issues


def get_universe(api_base: str, limit: int | None) -> list[str]:
    """Fetch the list of tickers to scan."""
    data = fetch(f"{api_base}/api/v1/public/all-tickers")
    if not data:
        # Fallback: hardcoded Nifty 200 from canary + common Nifty tickers
        print("warning: /all-tickers unreachable, using fallback list", file=sys.stderr)
        return [
            "RELIANCE.NS", "TCS.NS", "HDFCBANK.NS", "INFY.NS", "ITC.NS",
            "SBIN.NS", "ICICIBANK.NS", "BAJFINANCE.NS", "MARUTI.NS", "TITAN.NS",
            "LT.NS", "SUNPHARMA.NS", "HCLTECH.NS", "NESTLEIND.NS", "ASIANPAINT.NS",
            "ULTRACEMCO.NS", "HINDUNILVR.NS", "POWERGRID.NS", "NTPC.NS", "BHARTIARTL.NS",
        ]
    if isinstance(data, dict) and "tickers" in data:
        data = data["tickers"]
    tickers = []
    for entry in data:
        if isinstance(entry, dict):
            t = entry.get("full_ticker") or entry.get("ticker")
        else:
            t = entry
        if t:
            if not t.endswith(".NS") and not t.endswith(".BO"):
                t = f"{t}.NS"
            tickers.append(t)
    return tickers[:limit] if limit else tickers


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--api-base", default="https://api.yieldiq.in")
    parser.add_argument("--limit", type=int, default=None,
                        help="Max tickers to scan (default: all)")
    parser.add_argument("--rate", type=float, default=2.0,
                        help="Requests per second rate limit (default 2.0)")
    parser.add_argument("--report", default="universe_scan_report.json")
    parser.add_argument("--fail-threshold", type=int, default=200,
                        help="Exit 1 if failure count exceeds this")
    args = parser.parse_args()

    tickers = get_universe(args.api_base, args.limit)
    print(f"Universe scan against {args.api_base}")
    print(f"Scanning {len(tickers)} tickers (rate {args.rate}/s, ETA ~{len(tickers) / (args.rate * 60):.0f} min)\n")

    start = time.time()
    delay = 1.0 / args.rate if args.rate > 0 else 0.0
    failures: dict[str, list[dict]] = {}
    severity_counter: Counter = Counter()
    rule_counter: Counter = Counter()
    done = 0

    for t in tickers:
        issues = evaluate(t, args.api_base)
        if issues:
            failures[t] = issues
            for iss in issues:
                severity_counter[iss["severity"]] += 1
                rule_counter[iss["rule"]] += 1
        done += 1
        if done % 50 == 0 or done == len(tickers):
            elapsed = time.time() - start
            eta = elapsed / done * (len(tickers) - done)
            print(f"  [{done}/{len(tickers)}] {len(failures)} failed "
                  f"({elapsed:.0f}s elapsed, {eta:.0f}s ETA)")
        if delay:
            time.sleep(delay)

    total = len(tickers)
    passed = total - len(failures)

    report = {
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "api_base": args.api_base,
        "total": total,
        "passed": passed,
        "failed": len(failures),
        "pass_rate": round(passed / total, 4) if total else 0,
        "severity_breakdown": dict(severity_counter),
        "rule_breakdown": dict(rule_counter.most_common()),
        "failures": [
            {"ticker": t, "issues": issues}
            for t, issues in sorted(failures.items())
        ],
        "duration_seconds": round(time.time() - start, 1),
    }

    try:
        with open(args.report, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2, ensure_ascii=False)
        print(f"\nReport written: {args.report}")
    except OSError as e:
        print(f"warning: could not write report: {e}", file=sys.stderr)

    print()
    print("=" * 60)
    print(f"FULL UNIVERSE SCAN — {total} tickers")
    print(f"✓ Passed: {passed} ({passed / max(total, 1):.1%})")
    print(f"✗ Failed: {len(failures)} ({len(failures) / max(total, 1):.1%})")
    print()
    if severity_counter:
        print("Severity breakdown:")
        for sev in ("critical", "warning", "info"):
            n = severity_counter.get(sev, 0)
            if n:
                print(f"  {sev:<10} {n}")
        print()
    if rule_counter:
        print("Top issues:")
        for rule, n in rule_counter.most_common(10):
            print(f"  {n:>4}  {rule}")
        print()
    if failures:
        print("Worst offenders (first 20):")
        # Sort by critical-issue count desc
        def _crit_count(items):
            return sum(1 for i in items if i.get("severity") == "critical")
        sorted_fail = sorted(failures.items(),
                             key=lambda kv: (-_crit_count(kv[1]), kv[0]))
        for t, issues in sorted_fail[:20]:
            messages = "; ".join(i["message"] for i in issues[:2])
            print(f"  {t:<18} {messages}")

    blocking = len(failures) > args.fail_threshold
    print()
    if blocking:
        print(f"UNIVERSE: FAIL — {len(failures)} failures exceeds threshold {args.fail_threshold}")
    else:
        print(f"UNIVERSE: OK — {len(failures)} failures within threshold {args.fail_threshold}")

    return 1 if blocking else 0


if __name__ == "__main__":
    sys.exit(main())
