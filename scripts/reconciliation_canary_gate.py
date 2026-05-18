"""Reconciliation Canary Gate — post-deploy regression alarm.

Reads the live `analysis_cache` (current FV per canary ticker) and the
live `consensus_estimates` (latest consensus per canary ticker), then
computes the per-ticker deviation

    deviation_i = | our_fv_i - consensus_i | / consensus_i

and diffs against a baseline snapshot file (the previous run's report).

Failure rules (matching the PR brief):

  1. If ANY canary ticker's deviation INCREASED by more than
     10 percentage points vs baseline   → EXIT 2 (hard fail).
  2. If MORE THAN 5 canary tickers' deviations worsened by ANY amount
                                       → EXIT 3 (broad regression).
  3. Otherwise                          → EXIT 0.

The gate is designed to run **post-deploy** in the canary refresh cron
(see ``.github/workflows/cron-reconciliation-canary-gate.yml``). The
GH Actions job that invokes it opens a follow-up issue on a non-zero
exit. This is the simpler of the two options the PR brief lists — the
preview-env alternative would require spinning up a full preview stack
per PR, which is not justified for a sanity-check layer.

Tested in ``backend/tests/test_benchmark_reconciliation.py`` against
mocked consensus data so the workflow's "Gate self-test" step runs
without DB access.

Usage
-----
    python scripts/reconciliation_canary_gate.py \\
        --baseline canary_reconciliation_baseline.json \\
        --canary   scripts/canary_stocks_50.json \\
        --output   canary_reconciliation_report.json

    # offline self-test (no DB) — used by CI:
    python scripts/reconciliation_canary_gate.py --self-test
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import Optional

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("reconciliation_canary_gate")


# Worsening tolerance — a single ticker drifting > this fraction (in
# absolute deviation units) is a hard fail. 0.10 = 10 percentage points.
SINGLE_TICKER_HARD_FAIL_PP = 0.10
# Broad-regression threshold — more than this many tickers worsening
# at all (any positive delta) is a soft fail. Tuned to catch a global
# engine regression (PR #337's capital-goods rewrite would have moved
# many tickers at once) while ignoring single-ticker noise.
BROAD_REGRESSION_TICKER_COUNT = 5


# ── Canary loading ──────────────────────────────────────────────────


def load_canary_symbols(path: Path) -> list[str]:
    with open(path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [s["symbol"] for s in data["stocks"]]


# ── Deviation computation ───────────────────────────────────────────


def compute_deviation(our_fv: Optional[float], consensus_fv: Optional[float]) -> Optional[float]:
    """|delta| / consensus, or None if inputs unusable. Pure function."""
    if our_fv is None or consensus_fv is None:
        return None
    if consensus_fv <= 0 or our_fv <= 0:
        return None
    return abs(our_fv - consensus_fv) / consensus_fv


def compute_deviations_for_canary(rows_by_ticker: dict) -> dict[str, float]:
    """Given a dict {ticker -> {our_fv, consensus_fv}} return the
    subset that has both values populated and a non-None deviation."""
    out: dict[str, float] = {}
    for tk, payload in rows_by_ticker.items():
        d = compute_deviation(payload.get("our_fv"), payload.get("consensus_fv"))
        if d is not None:
            out[tk] = d
    return out


# ── Gate logic ──────────────────────────────────────────────────────


def evaluate_gate(
    current: dict[str, float],
    baseline: dict[str, float],
    *,
    single_pp: float = SINGLE_TICKER_HARD_FAIL_PP,
    broad_count: int = BROAD_REGRESSION_TICKER_COUNT,
) -> dict:
    """Pure-function gate evaluation. Returns a verdict dict.

    Verdict shape::

        {
          "status": "pass" | "hard_fail" | "broad_fail",
          "reasons": [str, ...],
          "per_ticker": {ticker: {"baseline": float, "current": float, "delta": float}},
          "worsened_tickers": [ticker, ...],
          "hard_fail_tickers": [ticker, ...],
        }

    A ticker that's present in ``current`` but missing from
    ``baseline`` is treated as "new coverage" — its delta is reported
    as ``None`` and it does NOT contribute to either fail mode (no
    regression possible without a baseline to compare to).
    """
    per_ticker: dict[str, dict] = {}
    worsened: list[str] = []
    hard_fail: list[str] = []

    for tk, cur_dev in current.items():
        base_dev = baseline.get(tk)
        if base_dev is None:
            per_ticker[tk] = {"baseline": None, "current": cur_dev, "delta": None}
            continue
        delta = cur_dev - base_dev
        per_ticker[tk] = {"baseline": base_dev, "current": cur_dev, "delta": delta}
        if delta > 0:
            worsened.append(tk)
        if delta > single_pp:
            hard_fail.append(tk)

    reasons: list[str] = []
    status = "pass"
    if hard_fail:
        status = "hard_fail"
        for tk in hard_fail:
            d = per_ticker[tk]
            reasons.append(
                f"{tk}: deviation worsened by {d['delta'] * 100:.1f}pp "
                f"({d['baseline'] * 100:.1f}% -> {d['current'] * 100:.1f}%) "
                f"— exceeds {single_pp * 100:.0f}pp single-ticker threshold."
            )
    elif len(worsened) > broad_count:
        status = "broad_fail"
        reasons.append(
            f"{len(worsened)} canary tickers worsened (limit: {broad_count}). "
            f"Tickers: {', '.join(sorted(worsened))}."
        )
    else:
        reasons.append(
            f"OK — {len(worsened)} ticker(s) drifted, none exceeded "
            f"{single_pp * 100:.0f}pp; broad limit {broad_count}."
        )

    return {
        "status": status,
        "reasons": reasons,
        "per_ticker": per_ticker,
        "worsened_tickers": sorted(worsened),
        "hard_fail_tickers": sorted(hard_fail),
    }


# ── Self-test (no DB, mocked consensus data) ────────────────────────


def _selftest() -> int:
    """Used by CI to prove the gate logic without DB / network access.

    Three scenarios:
      1. No drift → pass
      2. SIEMENS-style single-ticker blowup → hard_fail
      3. Broad multi-ticker mild drift → broad_fail
    """
    print("=== reconciliation gate self-test ===")

    # Scenario 1: clean
    baseline = {"RELIANCE": 0.05, "TCS": 0.04, "INFY": 0.06, "SIEMENS": 0.07}
    current  = {"RELIANCE": 0.06, "TCS": 0.04, "INFY": 0.05, "SIEMENS": 0.08}
    v1 = evaluate_gate(current, baseline)
    assert v1["status"] == "pass", v1
    print(f"  scenario 1 (clean): {v1['status']}  -- {v1['reasons'][0]}")

    # Scenario 2: SIEMENS regression (-55% vs +5% baseline → 50pp drift)
    baseline2 = {"RELIANCE": 0.05, "SIEMENS": 0.05}
    current2  = {"RELIANCE": 0.06, "SIEMENS": 0.55}
    v2 = evaluate_gate(current2, baseline2)
    assert v2["status"] == "hard_fail", v2
    assert "SIEMENS" in v2["hard_fail_tickers"], v2
    print(f"  scenario 2 (SIEMENS regression): {v2['status']}")
    for r in v2["reasons"]:
        print(f"    - {r}")

    # Scenario 3: broad small drift on 6 tickers
    baseline3 = {f"T{i}": 0.05 for i in range(10)}
    current3 = {f"T{i}": 0.05 for i in range(10)}
    for i in range(6):
        current3[f"T{i}"] = 0.07  # +2pp drift each
    v3 = evaluate_gate(current3, baseline3)
    assert v3["status"] == "broad_fail", v3
    print(f"  scenario 3 (broad drift): {v3['status']}")
    for r in v3["reasons"]:
        print(f"    - {r}")

    print("=== self-test PASSED ===")
    return 0


# ── DB-backed loader (live mode) ────────────────────────────────────


def _load_live_data(canary_symbols: list[str]) -> dict[str, dict]:
    """Fetch our_fv from analysis_cache and consensus_fv from the
    latest_consensus_per_ticker view for the given canary symbols.

    Returns a dict {ticker -> {"our_fv": float|None, "consensus_fv": float|None}}.
    """
    from sqlalchemy import create_engine, text
    from sqlalchemy.orm import sessionmaker

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        raise SystemExit("DATABASE_URL not set; required for live mode")
    engine = create_engine(db_url, future=True)
    Sess = sessionmaker(bind=engine, future=True)
    sess = Sess()
    try:
        rows = sess.execute(text("""
            SELECT
                ac.ticker                                       AS ticker,
                (ac.payload->'valuation'->>'fair_value')::float AS our_fv,
                lc.target_median::float                         AS consensus_fv
            FROM (
                SELECT DISTINCT ON (ticker) ticker, payload
                FROM analysis_cache
                WHERE ticker = ANY(:tickers)
                ORDER BY ticker, computed_at DESC
            ) ac
            LEFT JOIN latest_consensus_per_ticker lc
              ON lc.ticker = ac.ticker
        """), {"tickers": canary_symbols}).mappings().all()
    finally:
        sess.close()
    out = {}
    for r in rows:
        out[r["ticker"]] = {"our_fv": r["our_fv"], "consensus_fv": r["consensus_fv"]}
    return out


# ── Main ────────────────────────────────────────────────────────────


def _exit_for_status(status: str) -> int:
    return {"pass": 0, "hard_fail": 2, "broad_fail": 3}.get(status, 1)


def main(argv: Optional[list[str]] = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--self-test", action="store_true",
                   help="Run the in-process gate self-test (no DB).")
    p.add_argument("--baseline",
                   help="Path to baseline JSON snapshot.")
    p.add_argument("--canary", default="scripts/canary_stocks_50.json",
                   help="Path to canary universe JSON.")
    p.add_argument("--output", default="canary_reconciliation_report.json",
                   help="Where to write this run's report.")
    args = p.parse_args(argv)

    if args.self_test:
        return _selftest()

    canary_path = Path(args.canary)
    if not canary_path.exists():
        logger.error("canary file missing: %s", canary_path)
        return 4
    symbols = load_canary_symbols(canary_path)
    logger.info("loaded %d canary symbols", len(symbols))

    live = _load_live_data(symbols)
    devs = compute_deviations_for_canary(live)
    logger.info("computed %d deviations (out of %d canaries)", len(devs), len(symbols))

    baseline_devs: dict[str, float] = {}
    if args.baseline and Path(args.baseline).exists():
        with open(args.baseline, "r", encoding="utf-8") as f:
            prev = json.load(f)
        baseline_devs = prev.get("deviations", {})
    else:
        logger.info(
            "no baseline supplied — first run will pass-by-default and "
            "write a baseline for next run to diff against."
        )

    verdict = evaluate_gate(devs, baseline_devs)
    report = {
        "version": 1,
        "canary_count": len(symbols),
        "covered_count": len(devs),
        "deviations": devs,
        "verdict": verdict,
    }
    Path(args.output).write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    logger.info("report written: %s (status=%s)", args.output, verdict["status"])
    for r in verdict["reasons"]:
        logger.info("  %s", r)
    return _exit_for_status(verdict["status"])


if __name__ == "__main__":
    sys.exit(main())
