"""
Post-deploy E2E smoke test for YieldIQ.

Probes /api/v1/public/stock-summary/{ticker} for a hardcoded set of 12 anchor
tickers covering every valuation path the production API can take:

    - Tier 1 stable largecap (DCF):     TCS, INFY, HDFCBANK, HINDUNILVR, RELIANCE
    - Regulated utility (rate_base):    POWERGRID, NTPC
    - Pharma (DCF, often peer-capped):  SUNPHARMA, MANKIND
    - ETF (NAV-based, data_limited):    NIFTYBEES
    - REIT (NAV/DPU, data_limited):     EMBASSY
    - Holdco (SOTP, data_limited):      BAJAJHLDNG

Each ticker is checked against a hardcoded reference table (`SMOKE_TEST_ANCHORS`)
that pins:

    fv_band      : (lo, hi) acceptable fair_value range. Roughly +/-30% of
                   consensus. Skipped for data_limited tickers.
    verdict_set  : tuple of acceptable verdict strings.
    method_set   : tuple of acceptable valuation_model values.
    cmp_band     : (lo, hi) sanity range for current_price.

If a ticker is in `under_review` state (cache_miss_recompute_failed) it counts
as a soft-pass only when the ticker is explicitly marked `transient_ok=True`;
otherwise it's a hard failure (a stale or failing recompute on a flagship
DCF ticker is exactly the regression we want to catch).

Exit codes:
    0  All anchors pass.
    1  One or more anchors fail.

Designed to be run on a fresh post-Railway-deploy state (no warm cache
required) and on a cron during market hours.

Usage:
    python scripts/post_deploy_smoke_test.py
    python scripts/post_deploy_smoke_test.py --api-base https://api.yieldiq.in
    python scripts/post_deploy_smoke_test.py --report smoke_report.json --verbose
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import sys
import urllib.request
from typing import Any

# Force UTF-8 on stdout/stderr so the check-mark / cross summary characters
# don't crash on Windows cp1252.
try:
    sys.stdout.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
    sys.stderr.reconfigure(encoding="utf-8")  # type: ignore[attr-defined]
except Exception:
    pass


# ---------------------------------------------------------------------------
# Anchor table.
#
# fv_band  : acceptable fair_value range in INR. Bands are intentionally wide
#            (~+/-30% of trailing consensus median) -- we are looking for unit
#            bugs and broken pipelines, not valuation disagreements.
# cmp_band : sanity range for current_price.
# verdict_set : allowed verdicts.
# method_set  : allowed valuation_model values returned by the API.
# transient_ok: True iff a 503 under_review response is acceptable for this
#               ticker (only ETFs/REITs/holdcos for which we know the
#               recompute pipeline is intentionally rate-limited).
# ---------------------------------------------------------------------------
SMOKE_TEST_ANCHORS: dict[str, dict[str, Any]] = {
    # ---- Tier 1 stable largecap (full DCF expected) ------------------------
    "TCS.NS": {
        "cmp_band": (2000, 5500),
        "fv_band": (2200, 4000),
        "verdict_set": ("undervalued", "fairly_valued", "overvalued"),
        "method_set": ("dcf", "peer_capped"),
    },
    "INFY.NS": {
        "cmp_band": (900, 2200),
        "fv_band": (1200, 2400),
        "verdict_set": ("undervalued", "fairly_valued", "overvalued"),
        "method_set": ("dcf", "peer_capped"),
    },
    "HDFCBANK.NS": {
        "cmp_band": (600, 1300),
        "fv_band": (600, 1300),
        "verdict_set": ("undervalued", "fairly_valued", "overvalued"),
        # Banks frequently fall back to pb_ratio when DCF is not appropriate.
        "method_set": ("dcf", "pb_ratio", "peer_capped"),
    },
    "HINDUNILVR.NS": {
        "cmp_band": (1800, 3500),
        "fv_band": (1500, 3200),
        "verdict_set": ("undervalued", "fairly_valued", "overvalued"),
        "method_set": ("dcf", "peer_capped"),
    },
    "RELIANCE.NS": {
        "cmp_band": (900, 1800),
        "fv_band": (800, 2000),
        "verdict_set": ("undervalued", "fairly_valued", "overvalued"),
        "method_set": ("dcf", "peer_capped"),
    },
    # ---- Regulated utility (rate_base) ------------------------------------
    "POWERGRID.NS": {
        "cmp_band": (200, 450),
        "fv_band": (250, 380),
        "verdict_set": ("undervalued", "fairly_valued", "overvalued"),
        "method_set": ("rate_base",),
    },
    "NTPC.NS": {
        "cmp_band": (250, 600),
        "fv_band": (300, 700),
        "verdict_set": ("undervalued", "fairly_valued", "overvalued"),
        "method_set": ("rate_base",),
    },
    # ---- Pharma (DCF, sometimes peer_capped) -------------------------------
    "SUNPHARMA.NS": {
        "cmp_band": (1200, 2400),
        "fv_band": (900, 2400),
        "verdict_set": ("undervalued", "fairly_valued", "overvalued"),
        "method_set": ("dcf", "peer_capped"),
    },
    "MANKIND.NS": {
        "cmp_band": (1500, 3200),
        "fv_band": (800, 2500),
        "verdict_set": ("undervalued", "fairly_valued", "overvalued"),
        "method_set": ("dcf", "peer_capped"),
    },
    # ---- ETF (NAV-based, data_limited) -------------------------------------
    # NIFTYBEES has no fundamentals; the API may legitimately respond with
    # either a data_limited payload (valuation_model=etf_nav_based) OR a
    # 503 under_review on a cold cache. Both count as PASS.
    "NIFTYBEES.NS": {
        "cmp_band": (200, 500),
        "fv_band": None,
        "verdict_set": ("data_limited",),
        "method_set": ("etf_nav_based",),
        "transient_ok": True,
    },
    # ---- REIT (NAV/DPU, data_limited) --------------------------------------
    "EMBASSY.NS": {
        "cmp_band": (250, 500),
        "fv_band": None,
        "verdict_set": ("data_limited",),
        "method_set": ("reit_nav_dpu_required", "reit_nav_based"),
        "transient_ok": True,
    },
    # ---- Holdco (SOTP, data_limited) ---------------------------------------
    "BAJAJHLDNG.NS": {
        "cmp_band": (6000, 15000),
        "fv_band": None,
        "verdict_set": ("data_limited",),
        "method_set": ("holding_company_sotp_required", "holding_company_sotp"),
        "transient_ok": True,
    },
}

KNOWN_VERDICTS = {
    "undervalued",
    "fairly_valued",
    "overvalued",
    "data_limited",
}


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------
def fetch(url: str, timeout: int = 30) -> tuple[int, dict | None]:
    """Return (http_status, parsed_json_or_None).

    A 503 under_review response is a valid JSON payload and is returned;
    the caller decides whether to treat it as a pass.
    """
    req = urllib.request.Request(url, headers={"User-Agent": "YIQSmokeTest/1.0"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read().decode("utf-8")
            return r.status, json.loads(body)
    except urllib.error.HTTPError as e:  # noqa: PERF203
        try:
            body = e.read().decode("utf-8")
            return e.code, json.loads(body)
        except Exception:
            return e.code, None
    except Exception as e:
        print(f"  fetch error: {type(e).__name__}: {e}", file=sys.stderr)
        return 0, None


# ---------------------------------------------------------------------------
# Per-ticker checks
# ---------------------------------------------------------------------------
def check_anchor(ticker: str, spec: dict[str, Any], api_base: str) -> list[str]:
    """Return list of failure messages; empty list means pass."""
    url = f"{api_base}/api/v1/public/stock-summary/{ticker}"
    status, data = fetch(url)

    if data is None:
        return [f"API request failed (HTTP {status})"]

    # Transient under_review handling.
    if isinstance(data, dict) and data.get("status") == "under_review":
        if spec.get("transient_ok"):
            return []  # treat as soft-pass
        return [
            f"under_review (status=503, reason={data.get('reason')!r}) -- "
            f"flagship ticker should not be in under_review"
        ]

    if status != 200:
        return [f"unexpected HTTP {status}"]

    failures: list[str] = []

    # ---- Required fields ----
    verdict = data.get("verdict")
    if verdict not in KNOWN_VERDICTS:
        failures.append(f"verdict {verdict!r} not in known set {sorted(KNOWN_VERDICTS)}")

    if verdict not in spec["verdict_set"]:
        failures.append(
            f"verdict {verdict!r} not in expected {spec['verdict_set']}"
        )

    current_price = data.get("current_price") or data.get("price") or 0
    try:
        current_price = float(current_price)
    except (TypeError, ValueError):
        current_price = 0.0
    if current_price <= 0:
        failures.append(f"current_price is {current_price!r} (must be > 0)")
    else:
        lo, hi = spec["cmp_band"]
        if current_price < lo or current_price > hi:
            failures.append(
                f"current_price {current_price:.2f} outside sanity band [{lo}, {hi}]"
            )

    # ---- Method check (valuation_model) ----
    method = data.get("valuation_model")
    if spec.get("method_set") and method not in spec["method_set"]:
        failures.append(
            f"valuation_model {method!r} not in expected {spec['method_set']}"
        )

    # ---- Fair-value band (skip for data_limited / ETF / REIT / holdco) ----
    fv_band = spec.get("fv_band")
    if fv_band is not None:
        fv = data.get("fair_value")
        try:
            fv = float(fv) if fv is not None else 0.0
        except (TypeError, ValueError):
            fv = 0.0
        if fv <= 0:
            failures.append(f"fair_value is {fv!r} (must be > 0 for non-data_limited)")
        else:
            lo, hi = fv_band
            if fv < lo or fv > hi:
                failures.append(
                    f"fair_value {fv:.2f} outside expected band [{lo}, {hi}]"
                )
    else:
        # data_limited path: fair_value should be 0/None and verdict=data_limited
        if verdict != "data_limited":
            failures.append(
                f"data_limited anchor returned verdict {verdict!r} (expected data_limited)"
            )

    return failures


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def run(api_base: str, report_path: str | None, verbose: bool) -> int:
    print(f"Post-deploy smoke test against {api_base}")
    print(f"Checking {len(SMOKE_TEST_ANCHORS)} anchor tickers...\n")

    passed = 0
    failed: list[tuple[str, list[str]]] = []
    results: list[dict[str, Any]] = []

    for ticker, spec in SMOKE_TEST_ANCHORS.items():
        issues = check_anchor(ticker, spec, api_base)
        results.append({"ticker": ticker, "passed": not issues, "issues": issues})
        if issues:
            failed.append((ticker, issues))
            print(f"[FAIL] {ticker}")
            for msg in issues:
                print(f"       - {msg}")
        else:
            passed += 1
            if verbose:
                print(f"[PASS] {ticker}")

    total = len(SMOKE_TEST_ANCHORS)
    blocking = len(failed) > 0

    report = {
        "timestamp": _dt.datetime.now(_dt.timezone.utc).isoformat(),
        "api_base": api_base,
        "total": total,
        "passed": passed,
        "failed": len(failed),
        "blocking": blocking,
        "results": results,
    }
    if report_path:
        try:
            with open(report_path, "w", encoding="utf-8") as fh:
                json.dump(report, fh, indent=2)
        except OSError as e:
            print(f"warning: could not write report to {report_path}: {e}", file=sys.stderr)

    print()
    print("=" * 60)
    if failed:
        print("Failed tickers:")
        for t, msgs in failed:
            print(f"  {t}: {'; '.join(msgs)}")
        print()
        print(f"SMOKE: {passed}/{total} passed ✗ BLOCKING")
        return 1

    print(f"SMOKE: {passed}/{total} passed ✓")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--api-base", default="https://api.yieldiq.in",
                   help="Base URL of the YieldIQ API (default: prod).")
    p.add_argument("--report", default="smoke_report.json",
                   help="Path to write machine-readable JSON report. "
                        "Pass empty string '' to skip.")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()
    report_path = args.report or None
    return run(args.api_base, report_path, args.verbose)


if __name__ == "__main__":
    sys.exit(main())
