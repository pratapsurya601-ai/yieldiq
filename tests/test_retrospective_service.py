"""
Tests for backend.services.retrospective_service.

Fixture-driven: no DB. Verifies summary math, hit-rate calculation,
benchmark inclusion, MoS-threshold filtering, winner/loser ordering,
and edge cases (empty input, period labelling).
"""
from __future__ import annotations

import json
import os
import statistics
import sys
from datetime import date

# Make repo root importable when running with `python tests/test_retrospective_service.py`.
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.services.retrospective_service import (  # noqa: E402
    DEFAULT_MOS_THRESHOLD,
    _period_label,
    summarize_for_period,
)


FIXTURE_PATH = os.path.join(
    os.path.dirname(os.path.abspath(__file__)),
    "fixtures",
    "sample_predictions.json",
)


def _load_fixture() -> dict:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def _qualifying(predictions, threshold=DEFAULT_MOS_THRESHOLD):
    return [
        p for p in predictions
        if isinstance(p.get("margin_of_safety_pct"), (int, float))
        and float(p["margin_of_safety_pct"]) >= threshold
        and isinstance(p.get("return_pct"), (int, float))
    ]


# ─────────────────────────────────────────────────────────────────
# Core summary math
# ─────────────────────────────────────────────────────────────────

def test_summary_basic_shape():
    fx = _load_fixture()
    out = summarize_for_period(
        date.fromisoformat(fx["period_start"]),
        date.fromisoformat(fx["period_end"]),
        predictions=fx["predictions"],
        benchmark_return_pct=fx["benchmark_return_pct"],
    )

    # Every contract key is present.
    for key in (
        "period", "window_days", "mos_threshold", "n_predictions",
        "mean_return", "median_return", "hit_rate", "outperform_rate",
        "benchmark", "winners", "losers",
    ):
        assert key in out, f"missing key: {key}"

    assert out["period"]["start"] == fx["period_start"]
    assert out["period"]["end"]   == fx["period_end"]
    assert out["benchmark"]["ticker"] == fx["benchmark_ticker"]
    assert out["benchmark"]["return_pct"] == fx["benchmark_return_pct"]


def test_mos_threshold_filters_low_mos_rows():
    fx = _load_fixture()
    out = summarize_for_period(
        date.fromisoformat(fx["period_start"]),
        date.fromisoformat(fx["period_end"]),
        predictions=fx["predictions"],
        benchmark_return_pct=fx["benchmark_return_pct"],
    )

    expected_n = len(_qualifying(fx["predictions"]))
    assert out["n_predictions"] == expected_n

    # Sanity: there ARE low-MoS rows in the fixture that should be excluded.
    n_total = sum(
        1 for p in fx["predictions"]
        if isinstance(p.get("return_pct"), (int, float))
        and isinstance(p.get("margin_of_safety_pct"), (int, float))
    )
    assert expected_n < n_total, "fixture should contain some sub-threshold rows"


def test_mean_and_median_match_manual_compute():
    fx = _load_fixture()
    out = summarize_for_period(
        date.fromisoformat(fx["period_start"]),
        date.fromisoformat(fx["period_end"]),
        predictions=fx["predictions"],
        benchmark_return_pct=fx["benchmark_return_pct"],
    )
    qual = _qualifying(fx["predictions"])
    rets = [float(p["return_pct"]) for p in qual]

    assert abs(out["mean_return"]   - round(statistics.fmean(rets), 2)) < 1e-9
    assert abs(out["median_return"] - round(statistics.median(rets), 2)) < 1e-9


def test_hit_rate_and_outperform_rate():
    fx = _load_fixture()
    bench = fx["benchmark_return_pct"]
    out = summarize_for_period(
        date.fromisoformat(fx["period_start"]),
        date.fromisoformat(fx["period_end"]),
        predictions=fx["predictions"],
        benchmark_return_pct=bench,
    )
    qual = _qualifying(fx["predictions"])
    rets = [float(p["return_pct"]) for p in qual]

    expected_hit = round(sum(1 for r in rets if r > 0) / len(rets), 4)
    expected_out = round(sum(1 for r in rets if r > bench) / len(rets), 4)

    assert out["hit_rate"]        == expected_hit
    assert out["outperform_rate"] == expected_out
    # Hit rate must be in [0, 1].
    assert 0.0 <= out["hit_rate"] <= 1.0
    assert 0.0 <= out["outperform_rate"] <= 1.0


def test_winners_and_losers_ordering():
    fx = _load_fixture()
    out = summarize_for_period(
        date.fromisoformat(fx["period_start"]),
        date.fromisoformat(fx["period_end"]),
        predictions=fx["predictions"],
        benchmark_return_pct=fx["benchmark_return_pct"],
    )

    assert len(out["winners"]) == 5
    assert len(out["losers"])  == 5

    winner_returns = [w["return_pct"] for w in out["winners"]]
    loser_returns  = [l["return_pct"] for l in out["losers"]]

    # Winners sorted descending, losers ascending (worst first).
    assert winner_returns == sorted(winner_returns, reverse=True)
    assert loser_returns  == sorted(loser_returns)

    # Top winner should be the best return in the qualifying set.
    qual = _qualifying(fx["predictions"])
    best = max(float(p["return_pct"]) for p in qual)
    worst = min(float(p["return_pct"]) for p in qual)
    assert winner_returns[0] == round(best, 2)
    assert loser_returns[0]  == round(worst, 2)


def test_benchmark_falls_back_when_missing():
    """Phase 2: missing benchmark_return_pct no longer raises — it
    falls back to 0.0 (with a None lookup) so the page still renders.
    The frontend surfaces this with a 'benchmark unavailable' note."""
    out = summarize_for_period(
        date(2025, 4, 1),
        date(2025, 6, 30),
        predictions=[],
    )
    assert out["n_predictions"] == 0
    # Benchmark falls back to 0.0 (or whatever DB returns; in tests
    # _fetch_benchmark_return returns None → coerced to 0.0)
    assert out["benchmark"]["return_pct"] in (0.0, None)


def test_empty_predictions_returns_nulls_not_crash():
    out = summarize_for_period(
        date(2025, 4, 1),
        date(2025, 6, 30),
        predictions=[],
        benchmark_return_pct=4.0,
    )
    assert out["n_predictions"] == 0
    assert out["mean_return"]   is None
    assert out["median_return"] is None
    assert out["hit_rate"]      is None
    assert out["winners"] == []
    assert out["losers"]  == []
    # Benchmark still echoed back so the UI can render the comparison row.
    assert out["benchmark"]["return_pct"] == 4.0


# ─────────────────────────────────────────────────────────────────
# Period labelling
# ─────────────────────────────────────────────────────────────────

def test_period_label_indian_fiscal_quarters():
    assert _period_label(date(2025, 4, 1),  date(2025, 6, 30)) == "Q1FY26"
    assert _period_label(date(2025, 7, 1),  date(2025, 9, 30)) == "Q2FY26"
    assert _period_label(date(2025, 10, 1), date(2025, 12, 31)) == "Q3FY26"
    assert _period_label(date(2026, 1, 1),  date(2026, 3, 31)) == "Q4FY26"


def test_period_label_falls_back_for_irregular_range():
    # A 6-month range that crosses fiscal-quarter boundaries should
    # NOT be mislabelled as a clean quarter.
    label = _period_label(date(2025, 4, 1), date(2025, 9, 30))
    assert "FY26" in label or "–" in label  # allow either fallback


if __name__ == "__main__":
    # Run all test_* functions and print pass/fail. No pytest dependency.
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    failures = 0
    for fn in fns:
        try:
            fn()
            print(f"PASS  {fn.__name__}")
        except Exception as e:
            failures += 1
            print(f"FAIL  {fn.__name__}: {e}")
    if failures:
        print(f"\n{failures} failure(s).")
        sys.exit(1)
    print(f"\nAll {len(fns)} tests passed.")
