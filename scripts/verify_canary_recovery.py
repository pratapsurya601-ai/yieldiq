#!/usr/bin/env python3
"""
verify_canary_recovery.py — probe prod API for 20 canary tickers and
report CFO populated / score in range / FV sanity in a single table.

Used as a one-command sanity check after the `financials` →
`company_financials` transform lands in prod. The five known-broken
defensives (HCLTECH, NESTLEIND, ASIANPAINT, HINDUNILVR, POWERGRID)
should recover CFO; the other 15 should not regress.

Read-only, API-only. Does not touch the DB.

Usage:
    python scripts/verify_canary_recovery.py
    python scripts/verify_canary_recovery.py --base-url https://staging.yieldiq.in
    python scripts/verify_canary_recovery.py --fail-on-regression
    python scripts/verify_canary_recovery.py --verbose

Failure modes distinguished:
    regression       — data came back but out of bounds / CFO missing
    auth_required    — endpoint returned 401, score check skipped
    request_failed   — timeout / connection error / 5xx
    parse_error      — response JSON missing expected fields
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any

import requests

REPO_ROOT = Path(__file__).resolve().parent.parent
CANARY_FILE = REPO_ROOT / "scripts" / "canary_stocks_50.json"
DEFAULT_BASE = "https://api.yieldiq.in"
TIMEOUT_S = 10.0
THROTTLE_S = 0.5
N_CANARY = 20

# Known-broken defensives — CFO MUST be populated post-transform.
KNOWN_BROKEN_CFO = {"HCLTECH", "NESTLEIND", "ASIANPAINT", "HINDUNILVR", "POWERGRID"}

# Score band: the canary file only carries per-metric bounds
# (roe / debt_to_equity / wacc / mcap / revenue_cagr), not a score
# range. We treat "score present and 0..100" as PASS; individual
# regressions below expected are flagged when a later revision adds
# expected_score_min/max to the canary file.
DEFAULT_SCORE_MIN = 0.0
DEFAULT_SCORE_MAX = 100.0

# FV sanity band — anything outside [1, 1_000_000] INR is almost
# certainly a unit bug (we've shipped FV=0 and FV=1e9 bugs before).
FV_SANE_MIN = 1.0
FV_SANE_MAX = 1_000_000.0


def load_canary(path: Path, n: int) -> list[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as fh:
        doc = json.load(fh)
    stocks = doc.get("stocks", [])
    out: list[dict[str, Any]] = []
    for s in stocks[:n]:
        ticker = s.get("symbol") or s.get("ticker")
        if not ticker:
            continue
        # Support future schema: expected_score_min/max if added.
        smin = s.get("expected_score_min", DEFAULT_SCORE_MIN)
        smax = s.get("expected_score_max", DEFAULT_SCORE_MAX)
        out.append({"ticker": ticker, "score_min": smin, "score_max": smax})
    return out


def fetch_cfo(base: str, ticker: str, verbose: bool) -> tuple[str, Any]:
    """Return (status, detail). status in {'populated','missing','auth_required','request_failed','parse_error'}."""
    url = f"{base}/api/v1/analysis/{ticker}/financials?years=5"
    try:
        r = requests.get(url, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        return "request_failed", str(e)[:60]
    if r.status_code == 401:
        return "auth_required", None
    if r.status_code >= 500 or r.status_code >= 400:
        return "request_failed", f"HTTP {r.status_code}"
    try:
        body = r.json()
    except ValueError:
        return "parse_error", "non-json"
    rows = body.get("cash_flow") or []
    if not rows:
        return "missing", "no cash_flow rows"
    latest = rows[0]
    # Canonical field is `operating_cash_flow` in the API response;
    # `cfo` is the DB column name and is accepted as a fallback.
    cfo_val = latest.get("operating_cash_flow")
    if cfo_val is None:
        cfo_val = latest.get("cfo")
    if verbose and cfo_val in (None, 0):
        print(f"  [{ticker}] cash_flow[0] keys={list(latest.keys())[:8]}", file=sys.stderr)
    if cfo_val in (None, 0):
        return "missing", cfo_val
    return "populated", cfo_val


def fetch_analysis(base: str, ticker: str, verbose: bool) -> tuple[str, dict[str, Any]]:
    """Return (status, payload). status in {'ok','auth_required','request_failed','parse_error'}."""
    url = f"{base}/api/v1/analysis/{ticker}?include_summary=false"
    try:
        r = requests.get(url, timeout=TIMEOUT_S)
    except requests.RequestException as e:
        return "request_failed", {"err": str(e)[:60]}
    if r.status_code == 401:
        return "auth_required", {}
    if r.status_code >= 400:
        return "request_failed", {"err": f"HTTP {r.status_code}"}
    try:
        body = r.json()
    except ValueError:
        return "parse_error", {"err": "non-json"}
    # The /analysis endpoint returns score / fair_value / margin_of_safety
    # at the top level of the envelope (see backend/routers/analysis.py ~L442).
    score = body.get("score")
    fv = body.get("fair_value")
    mos = body.get("margin_of_safety")
    if verbose and (score is None or fv is None):
        print(f"  [{ticker}] /analysis keys={list(body.keys())[:10]}", file=sys.stderr)
    return "ok", {"score": score, "fair_value": fv, "margin_of_safety": mos}


def classify(
    ticker: str,
    cfo_status: str,
    analysis_status: str,
    analysis_payload: dict[str, Any],
    score_min: float,
    score_max: float,
    check_cfo: bool,
) -> tuple[bool, bool, str]:
    """Return (pass, is_regression, notes)."""
    notes: list[str] = []
    regression = False
    passed = True

    if check_cfo:
        if cfo_status == "populated":
            pass
        elif cfo_status == "auth_required":
            notes.append("cfo:auth")
            passed = False
        elif cfo_status == "request_failed":
            notes.append("cfo:req_failed")
            passed = False
        elif cfo_status == "parse_error":
            notes.append("cfo:parse")
            passed = False
        else:  # missing
            notes.append("cfo:MISSING")
            passed = False
            regression = True

    if analysis_status == "auth_required":
        notes.append("score:auth")
        # Do not count as regression; endpoint may just be gated.
    elif analysis_status == "request_failed":
        notes.append("score:req_failed")
        passed = False
    elif analysis_status == "parse_error":
        notes.append("score:parse")
        passed = False
    else:  # ok
        score = analysis_payload.get("score")
        fv = analysis_payload.get("fair_value")
        if score is None:
            notes.append("score:null")
            passed = False
        else:
            if not (score_min <= score <= score_max):
                notes.append(f"score:{score:.0f}<{score_min:.0f}|>{score_max:.0f}")
                passed = False
                regression = True
        if fv is None:
            notes.append("fv:null")
            passed = False
            regression = True
        else:
            if not (FV_SANE_MIN <= fv <= FV_SANE_MAX):
                notes.append(f"fv:{fv:.0f}_oob")
                passed = False
                regression = True

    return passed, regression, ",".join(notes) if notes else "ok"


def fmt_row(
    ticker: str,
    cfo_status: str,
    analysis_status: str,
    payload: dict[str, Any],
    score_min: float,
    score_max: float,
    passed: bool,
    notes: str,
) -> str:
    cfo_cell = {
        "populated": "Y",
        "missing": "N",
        "auth_required": "AUTH",
        "request_failed": "REQF",
        "parse_error": "PARS",
    }.get(cfo_status, "?")
    if analysis_status != "ok":
        score_cell = {
            "auth_required": "AUTH",
            "request_failed": "REQF",
            "parse_error": "PARS",
        }.get(analysis_status, "?")
        fv_cell = "-"
        mos_cell = "-"
    else:
        s = payload.get("score")
        score_cell = f"{s:.0f}" if isinstance(s, (int, float)) else "-"
        fv = payload.get("fair_value")
        fv_cell = f"{fv:.0f}" if isinstance(fv, (int, float)) else "-"
        mos = payload.get("margin_of_safety")
        mos_cell = f"{mos:.1f}" if isinstance(mos, (int, float)) else "-"
    expect_cell = f"{score_min:.0f}-{score_max:.0f}"
    pass_cell = "PASS" if passed else "FAIL"
    return (
        f"{ticker:<12} {cfo_cell:<4} {score_cell:>5} {expect_cell:>7}  "
        f"{pass_cell:<5} {fv_cell:>7} {mos_cell:>6}  {notes}"
    )


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--base-url", default=DEFAULT_BASE)
    p.add_argument("--verbose", action="store_true")
    p.add_argument("--fail-on-regression", action="store_true")
    p.add_argument(
        "--expected-cfo-populated",
        default=None,
        help="Comma-sep tickers whose CFO must be populated. Default: all 20.",
    )
    args = p.parse_args()

    canary = load_canary(CANARY_FILE, N_CANARY)
    if not canary:
        print(f"no canary tickers loaded from {CANARY_FILE}", file=sys.stderr)
        return 2

    all_tickers = {c["ticker"] for c in canary}
    if args.expected_cfo_populated:
        cfo_check_set = {
            t.strip().upper() for t in args.expected_cfo_populated.split(",") if t.strip()
        }
    else:
        cfo_check_set = set(all_tickers)

    header = (
        f"{'TICKER':<12} {'CFO?':<4} {'SCORE':>5} {'EXPECT':>7}  "
        f"{'PASS?':<5} {'FV':>7} {'MoS%':>6}  NOTES"
    )

    rows: list[tuple[bool, bool, str]] = []  # (passed, regression, formatted_row)
    n_ok = 0
    n_regression = 0

    for i, entry in enumerate(canary):
        ticker = entry["ticker"]
        if i > 0:
            time.sleep(THROTTLE_S)
        cfo_status, _ = fetch_cfo(args.base_url, ticker, args.verbose)
        analysis_status, payload = fetch_analysis(args.base_url, ticker, args.verbose)
        check_cfo = ticker in cfo_check_set
        passed, regression, notes = classify(
            ticker,
            cfo_status,
            analysis_status,
            payload,
            entry["score_min"],
            entry["score_max"],
            check_cfo,
        )
        # Highlight known-broken defensives in notes.
        if ticker in KNOWN_BROKEN_CFO and cfo_status == "populated":
            notes = (notes + ",recovered").lstrip(",")
        line = fmt_row(
            ticker,
            cfo_status,
            analysis_status,
            payload,
            entry["score_min"],
            entry["score_max"],
            passed,
            notes,
        )
        rows.append((passed, regression, line))
        if passed:
            n_ok += 1
        if regression:
            n_regression += 1

    # Failures first, then passes; preserve within-group order.
    rows.sort(key=lambda r: (0 if not r[0] else 1))

    print(header)
    print("-" * len(header))
    for _, _, line in rows:
        print(line)

    summary = f"{n_ok}/{len(canary)} passed | {n_regression} regressions"
    print("-" * len(header))
    print(summary)

    if args.fail_on_regression and n_regression > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
