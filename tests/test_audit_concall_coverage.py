"""Unit tests for scripts/audit_concall_coverage.py.

Synthetic only — no live DB. Covers the pure helpers:
 * canary loader (v3 schema with `stocks[].symbol`, plus v2 fallback)
 * histogram bucketer
 * verdict logic on the three score regimes (HARD STOP / CAUTION / PROCEED)
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import audit_concall_coverage as acc  # type: ignore[import-not-found]


# ---------- canary loader ---------------------------------------------------

def test_canary_loader_v3_shape(tmp_path, monkeypatch):
    p = tmp_path / "canary.json"
    p.write_text(json.dumps({
        "_meta": {"version": 3, "universe_version": "v3_test"},
        "buckets": {"a": ["unused"], "b": ["unused"]},
        "stocks": [
            {"symbol": "RELIANCE", "bucket": "a"},
            {"symbol": "TCS", "bucket": "b"},
            {"symbol": "RELIANCE", "bucket": "a"},  # dupe
        ],
    }), encoding="utf-8")
    monkeypatch.setattr(acc, "CANARY_PATH", p)
    out = acc._load_canary_tickers()
    assert out == ["RELIANCE", "TCS"]


def test_canary_loader_v2_legacy_shape(tmp_path, monkeypatch):
    p = tmp_path / "canary.json"
    p.write_text(json.dumps({
        "_meta": {"version": 2},
        "top": ["A", "B"],
        "banks": ["C", "A"],  # A is a dupe across buckets
    }), encoding="utf-8")
    monkeypatch.setattr(acc, "CANARY_PATH", p)
    out = acc._load_canary_tickers()
    assert out == ["A", "B", "C"]


# ---------- histogram --------------------------------------------------------

def test_hist_buckets_assign_each_value_once():
    buckets = [(0, 1, "0"), (1, 5, "1-4"), (5, None, "5+")]
    h = acc._hist([0, 0, 3, 4, 5, 10], buckets)
    assert h == {"0": 2, "1-4": 2, "5+": 2}


# ---------- verdict ---------------------------------------------------------

def _mk_counts(per_ticker: dict[str, dict]) -> dict:
    """Fill defaults so build_summary doesn't KeyError."""
    base = {"total": 0, "in_1y": 0, "in_5y": 0,
            "with_summary": 0, "withheld": 0, "with_text": 0,
            "oldest": None, "newest": None}
    return {t: {**base, **v} for t, v in per_ticker.items()}


def test_verdict_hard_stop_when_coverage_below_20pct():
    top200 = [f"T{i}" for i in range(200)]
    # Only 10 tickers have any 5y rows → 5% < 20% bar
    counts = _mk_counts({
        **{f"T{i}": {"in_5y": 5} for i in range(10)},
        **{f"T{i}": {} for i in range(10, 200)},
    })
    s = acc.build_summary(top200, [], top200, counts, [])
    assert s["verdict"] == "HARD STOP"
    assert "20%" in s["verdict_reason"] or "Below" in s["verdict_reason"]


def test_verdict_caution_when_coverage_above_20pct_but_thin_cadence():
    top200 = [f"T{i}" for i in range(200)]
    # 90% have *some* coverage, but only 10% clear the ≥20 cadence bar
    counts = _mk_counts({
        **{f"T{i}": {"in_5y": 25} for i in range(20)},   # clear cadence
        **{f"T{i}": {"in_5y": 3}  for i in range(20, 180)},  # any-only
        **{f"T{i}": {} for i in range(180, 200)},
    })
    s = acc.build_summary(top200, [], top200, counts, [])
    assert s["verdict"] == "PROCEED WITH CAUTION"


def test_verdict_proceed_when_cadence_is_dense():
    top200 = [f"T{i}" for i in range(200)]
    # 90% any, 30% clear cadence — above the 25% caution gate
    counts = _mk_counts({
        **{f"T{i}": {"in_5y": 25} for i in range(60)},
        **{f"T{i}": {"in_5y": 3}  for i in range(60, 180)},
        **{f"T{i}": {} for i in range(180, 200)},
    })
    s = acc.build_summary(top200, [], top200, counts, [])
    assert s["verdict"] == "PROCEED"
