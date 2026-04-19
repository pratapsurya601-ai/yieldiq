"""Financials audit — read-only sweep of `analysis_cache` payloads.

PR-DATA-1: advisory check (NOT a gate). Walks every payload cached in
the last 48h and flags rows whose surfaced ratios look suspect by
crude bound checks. Useful as a daily eyeballing tool to spot when a
new bug class starts producing absurd numbers, without waiting for a
user to file a screenshot.

Flag rules (each row may trigger multiple):
  - ROCE rounds to exactly 0.0%       — sentinel for the "missing
                                        EBIT silently zero-filled" bug
                                        class (FIX2 fixed it for the
                                        ratios path; this catches any
                                        regression).
  - |rev_cagr_3y| > 50%               — defense-in-depth: clamp at
    OR |rev_cagr_5y| > 50%              response layer should already
                                        null these, so a hit means
                                        the clamp itself is broken.
  - ev_ebitda outside (0.5, 200)      — same logic; existing clamp in
                                        analysis_service should null
                                        these.
  - pe < 0 or pe > 500                — basic sanity (negative PE only
                                        meaningful for loss-makers,
                                        > 500 implies near-zero EPS
                                        and is unusable for valuation).
  - roe < -100% or roe > 100%         — anything outside this range
                                        is essentially always a unit
                                        mixup, not a real business
                                        result.
  - de_ratio < 0 or de_ratio > 20     — > 20× D/E is functionally
                                        insolvent; negative is a sign
                                        flip / accounting artifact.

Always exits 0 — this is advisory output for humans, not a CI gate.

Usage::

    python -m backend.audits.financials_audit
"""
from __future__ import annotations

import json
import sys
from collections import Counter
from typing import Any


# Advisory thresholds (kept loose on purpose — the goal is to catch
# obvious unit/sign mixups, not to QC every borderline value).
ROCE_SENTINEL = 0.0           # exact rounded 0.0% -> sentinel hit
REV_CAGR_ABS_MAX = 0.50       # decimal (0.50 = 50%)
EV_EBITDA_LOW = 0.5
EV_EBITDA_HIGH = 200.0
PE_LOW = 0.0                  # pe < 0 flagged
PE_HIGH = 500.0
ROE_LOW = -100.0              # percent
ROE_HIGH = 100.0
DE_LOW = 0.0
DE_HIGH = 20.0


def _num(v: Any) -> float | None:
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _extract(payload: dict) -> dict:
    """Pull the seven fields we audit out of a cached analysis payload.

    Cached payloads use the `ValuationOutput` / `QualityOutput` shape;
    we read defensively because old cache entries from prior schema
    versions may be missing fields.
    """
    val = payload.get("valuation") or {}
    qual = payload.get("quality") or {}
    return {
        "roce":         _num(qual.get("roce")),
        "rev_cagr_3y":  _num(qual.get("revenue_cagr_3y")),
        "rev_cagr_5y":  _num(qual.get("revenue_cagr_5y")),
        "ev_ebitda":    _num(val.get("ev_ebitda")),
        "roe":          _num(qual.get("roe")),
        "de_ratio":     _num(qual.get("debt_to_equity") or qual.get("de_ratio")),
        "pe":           _num(val.get("pe_ratio") or val.get("trailing_pe")),
    }


def _flag(metrics: dict) -> list[str]:
    flags: list[str] = []
    roce = metrics["roce"]
    if roce is not None and round(roce, 1) == ROCE_SENTINEL:
        flags.append("ROCE=0.0%(sentinel)")

    for key in ("rev_cagr_3y", "rev_cagr_5y"):
        v = metrics[key]
        if v is not None and abs(v) > REV_CAGR_ABS_MAX:
            flags.append(f"{key}={v:+.1%}(>50%)")

    ev = metrics["ev_ebitda"]
    if ev is not None and not (EV_EBITDA_LOW < ev < EV_EBITDA_HIGH):
        flags.append(f"ev_ebitda={ev:.1f}x(out_of_range)")

    pe = metrics["pe"]
    if pe is not None and (pe < PE_LOW or pe > PE_HIGH):
        flags.append(f"pe={pe:.1f}(out_of_range)")

    roe = metrics["roe"]
    if roe is not None and (roe < ROE_LOW or roe > ROE_HIGH):
        flags.append(f"roe={roe:.1f}%(out_of_range)")

    de = metrics["de_ratio"]
    if de is not None and (de < DE_LOW or de > DE_HIGH):
        flags.append(f"de_ratio={de:.2f}(out_of_range)")

    return flags


def _load_rows() -> list[tuple[str, dict]]:
    """Read (ticker, payload) pairs from analysis_cache for last 48h.

    Mirrors the read pattern used by backend/routers/screener.py
    lines 139-149 (data_pipeline.db.Session, raw SQL, json-decode if
    the column came back as a string). Read-only — no writes, no
    schema mutations.
    """
    from data_pipeline.db import Session as _Session
    from sqlalchemy import text as _sql_text

    out: list[tuple[str, dict]] = []
    sess = _Session()
    try:
        rows = sess.execute(_sql_text(
            "SELECT ticker, payload FROM analysis_cache "
            "WHERE computed_at > now() - interval '48 hours'"
        )).fetchall()
    finally:
        sess.close()

    for r in rows:
        ticker = r[0]
        payload = r[1]
        if payload is None:
            continue
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                continue
        if not isinstance(payload, dict):
            continue
        out.append((ticker, payload))
    return out


def main() -> int:
    try:
        rows = _load_rows()
    except Exception as exc:
        print(f"financials_audit: could not read analysis_cache ({exc!r})")
        print("financials_audit: advisory script — exiting 0 anyway")
        return 0

    if not rows:
        print("financials_audit: no cached payloads in the last 48h.")
        return 0

    flagged: list[tuple[str, dict, list[str]]] = []
    counter: Counter[str] = Counter()
    metric_present: Counter[str] = Counter()

    for ticker, payload in rows:
        metrics = _extract(payload)
        for k, v in metrics.items():
            if v is not None:
                metric_present[k] += 1
        flags = _flag(metrics)
        if flags:
            flagged.append((ticker, metrics, flags))
            for f in flags:
                # Bucket by the prefix before "=" for the summary count.
                bucket = f.split("=", 1)[0]
                counter[bucket] += 1

    print(f"financials_audit: scanned {len(rows)} cached payloads "
          f"(last 48h)")
    print(f"financials_audit: {len(flagged)} ticker(s) with at least "
          f"one flag")
    print()

    if flagged:
        print("=== Per-ticker report ===")
        for ticker, metrics, flags in sorted(flagged):
            print(f"  {ticker}")
            for k in ("roce", "rev_cagr_3y", "rev_cagr_5y", "ev_ebitda",
                     "roe", "de_ratio", "pe"):
                v = metrics[k]
                vs = "—" if v is None else f"{v:.4f}"
                print(f"      {k:<13} = {vs}")
            for f in flags:
                print(f"      ! {f}")
        print()

    print("=== Summary counts ===")
    print(f"  total payloads scanned : {len(rows)}")
    print(f"  payloads flagged       : {len(flagged)}")
    if metric_present:
        print("  metric coverage (non-null in payload):")
        for k in sorted(metric_present):
            n = metric_present[k]
            pct = 100.0 * n / len(rows) if rows else 0.0
            print(f"      {k:<13} = {n:>5} / {len(rows)} ({pct:5.1f}%)")
    if counter:
        print("  flag bucket counts:")
        for bucket, n in counter.most_common():
            print(f"      {bucket:<28} = {n}")
    else:
        print("  no flags raised — clamps + source-side guards holding.")

    # Always advisory: never fail the caller.
    return 0


if __name__ == "__main__":
    sys.exit(main())
