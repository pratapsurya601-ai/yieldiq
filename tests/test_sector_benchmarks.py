"""
Tests for backend.services.sector_benchmarks and the sector-aware
path of backend.services.retrospective_service.summarize_for_period.

Fixture-driven, no DB. Verifies:
  * sector → benchmark mapping resolution (incl. aliases, default).
  * Per-sector aggregation correctness for benchmark='auto'.
  * Backward compat: benchmark='nifty500' shape unchanged from prior.
  * Edge cases: 1-stock sector, sector with no resolvable benchmark.
"""
from __future__ import annotations

import os
import sys
from datetime import date

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT not in sys.path:
    sys.path.insert(0, ROOT)

from backend.services.sector_benchmarks import (  # noqa: E402
    SECTOR_BENCHMARK_MAP,
    SECTOR_ALIASES,
    all_benchmark_tickers,
    mapped_sectors,
    resolve,
)
from backend.services.retrospective_service import (  # noqa: E402
    summarize_for_period,
)


# ─────────────────────────────────────────────────────────────────
# Mapping
# ─────────────────────────────────────────────────────────────────

def test_resolve_exact_match():
    assert resolve("IT Services") == "^CNXIT"
    assert resolve("Banks")       == "^NSEBANK"
    assert resolve("Pharma")      == "^CNXPHARMA"
    assert resolve("Realty")      == "^CNXREALTY"


def test_resolve_alias_case_insensitive():
    # "Information Technology" → IT Services → ^CNXIT
    assert resolve("Information Technology") == "^CNXIT"
    assert resolve("information technology") == "^CNXIT"
    assert resolve("IT")                     == "^CNXIT"
    # Banking variants
    assert resolve("Bank")                   == "^NSEBANK"
    assert resolve("Private Sector Bank")    == "^NSEBANK"
    assert resolve("PSU Banks")              == "^CNXPSUBANK"
    # Energy
    assert resolve("Oil & Gas")              == "^CNXENERGY"
    # NBFCs / insurance route to Financial Services index
    assert resolve("NBFC")                   == "^CNXFIN"
    assert resolve("Insurance")              == "^CNXFIN"


def test_resolve_unknown_falls_back_to_default():
    assert resolve("ChemicalsThatDoNotExist") == SECTOR_BENCHMARK_MAP["_default"]
    assert resolve(None) == SECTOR_BENCHMARK_MAP["_default"]
    assert resolve("")   == SECTOR_BENCHMARK_MAP["_default"]


def test_mapping_is_stable_and_complete():
    # Spec: at least these 10 sectors must be mapped.
    required = ["IT Services", "Banks", "Pharma", "FMCG", "Auto",
                "Metals", "Energy", "Realty", "Media", "PSU Bank"]
    for r in required:
        assert r in SECTOR_BENCHMARK_MAP, f"missing canonical sector: {r}"
    assert "_default" in SECTOR_BENCHMARK_MAP
    # Default is the legacy Nifty 500 — must not change without deliberation.
    assert SECTOR_BENCHMARK_MAP["_default"] == "NIFTY500.NS"


def test_all_benchmark_tickers_unique():
    tickers = all_benchmark_tickers()
    assert len(tickers) == len(set(tickers))
    assert "NIFTY500.NS" in tickers
    assert "^CNXIT" in tickers


def test_mapped_sectors_excludes_default():
    sectors = mapped_sectors()
    assert "_default" not in sectors
    assert "IT Services" in sectors


# ─────────────────────────────────────────────────────────────────
# summarize_for_period — sector-aware (benchmark='auto')
# ─────────────────────────────────────────────────────────────────

def _mixed_sector_predictions():
    """Synthetic predictions across IT, Banks, Pharma + one unknown."""
    return [
        # IT Services — 3 picks, all qualifying. Sector bench return: 5.0%
        {"ticker": "INFY.NS",  "sector": "IT Services",
         "margin_of_safety_pct": 35.0, "return_pct": 12.0},
        {"ticker": "TCS.NS",   "sector": "IT Services",
         "margin_of_safety_pct": 32.0, "return_pct":  8.0},
        {"ticker": "WIPRO.NS", "sector": "IT Services",
         "margin_of_safety_pct": 31.0, "return_pct":  3.0},  # underperforms IT bench (5.0)
        # Banks — 2 picks. Sector bench return: 10.0%
        {"ticker": "HDFCBANK.NS", "sector": "Banks",
         "margin_of_safety_pct": 33.0, "return_pct": 15.0},
        {"ticker": "ICICIBANK.NS","sector": "Banks",
         "margin_of_safety_pct": 30.0, "return_pct":  7.0},  # underperforms bank bench
        # Pharma — 1 pick (edge case n=1). Sector bench return: 4.0%
        {"ticker": "SUNPHARMA.NS","sector": "Pharma",
         "margin_of_safety_pct": 40.0, "return_pct": 22.0},
        # Unknown sector — falls through to default (NIFTY500.NS)
        {"ticker": "WEIRD.NS", "sector": "GalacticConglomerate",
         "margin_of_safety_pct": 30.0, "return_pct":  1.0},
    ]


def test_auto_per_sector_aggregation():
    out = summarize_for_period(
        date(2025, 4, 1), date(2025, 6, 30),
        predictions=_mixed_sector_predictions(),
        benchmark="auto",
        sector_benchmark_returns={
            "^CNXIT":     5.0,
            "^NSEBANK":  10.0,
            "^CNXPHARMA": 4.0,
            "NIFTY500.NS": 6.0,
        },
    )
    assert "sector_breakdown" in out
    breakdown = {r["sector"]: r for r in out["sector_breakdown"]}

    # IT: 3 stocks, mean = (12+8+3)/3 = 7.67, bench=5.0, outperform 2/3
    it = breakdown["IT Services"]
    assert it["n"] == 3
    assert it["benchmark_ticker"] == "^CNXIT"
    assert it["benchmark_return"] == 5.0
    assert it["outperform_rate"]  == round(2 / 3, 4)

    # Banks: 2 stocks, bench=10, outperform 1/2 (15>10, 7<10)
    bk = breakdown["Banks"]
    assert bk["n"] == 2
    assert bk["outperform_rate"] == 0.5

    # Pharma: 1 stock, bench=4, 22>4 → outperform_rate=1.0
    ph = breakdown["Pharma"]
    assert ph["n"] == 1
    assert ph["outperform_rate"] == 1.0

    # Aggregate outperform_rate = total_winners / total = (2+1+1+0) / 7
    # WEIRD pred: bench=6 (default), return=1 → underperforms.
    assert out["outperform_rate"] == round(4 / 7, 4)


def test_auto_includes_sector_breakdown_field():
    out = summarize_for_period(
        date(2025, 4, 1), date(2025, 6, 30),
        predictions=_mixed_sector_predictions(),
        benchmark="auto",
        sector_benchmark_returns={
            "^CNXIT": 5.0, "^NSEBANK": 10.0, "^CNXPHARMA": 4.0,
            "NIFTY500.NS": 6.0,
        },
    )
    assert isinstance(out["sector_breakdown"], list)
    # Sorted by n descending — IT (n=3) first.
    assert out["sector_breakdown"][0]["sector"] == "IT Services"


def test_auto_skips_sector_with_unresolvable_benchmark():
    # Don't supply benchmark return for ^NSEBANK, _fetch_benchmark_return
    # will be called and (in tests, no DB) return None → sector omitted.
    out = summarize_for_period(
        date(2025, 4, 1), date(2025, 6, 30),
        predictions=_mixed_sector_predictions(),
        benchmark="auto",
        sector_benchmark_returns={
            "^CNXIT":     5.0,
            "^CNXPHARMA": 4.0,
            "NIFTY500.NS": 6.0,
            # ^NSEBANK omitted on purpose.
        },
    )
    sectors = {r["sector"] for r in out["sector_breakdown"]}
    assert "IT Services" in sectors
    assert "Pharma" in sectors
    # Banks is skipped because its benchmark didn't resolve.
    assert "Banks" not in sectors


# ─────────────────────────────────────────────────────────────────
# Backward compat
# ─────────────────────────────────────────────────────────────────

def test_nifty500_mode_shape_unchanged():
    """benchmark='nifty500' must return the legacy shape exactly:
    no sector_breakdown key, benchmark.ticker='NIFTY500.NS'."""
    preds = _mixed_sector_predictions()
    out = summarize_for_period(
        date(2025, 4, 1), date(2025, 6, 30),
        predictions=preds,
        benchmark="nifty500",
        benchmark_return_pct=6.2,
    )
    assert "sector_breakdown" not in out
    assert out["benchmark"]["ticker"]     == "NIFTY500.NS"
    assert out["benchmark"]["return_pct"] == 6.2
    # Outperform rate is computed against the single benchmark.
    rets = [p["return_pct"] for p in preds
            if p["margin_of_safety_pct"] >= 30.0]
    expected = round(sum(1 for r in rets if r > 6.2) / len(rets), 4)
    assert out["outperform_rate"] == expected


def test_default_call_unchanged_when_benchmark_omitted():
    """Calls that pass no benchmark kwarg get the legacy single-bench
    behaviour — no surprise 'auto' switch for old callers."""
    out = summarize_for_period(
        date(2025, 4, 1), date(2025, 6, 30),
        predictions=_mixed_sector_predictions(),
        benchmark_return_pct=6.0,
    )
    assert "sector_breakdown" not in out
    assert out["benchmark"]["ticker"] == "NIFTY500.NS"


def test_explicit_sector_ticker_treated_as_single_benchmark():
    out = summarize_for_period(
        date(2025, 4, 1), date(2025, 6, 30),
        predictions=_mixed_sector_predictions(),
        benchmark="^CNXIT",
        benchmark_return_pct=5.0,
    )
    assert out["benchmark"]["ticker"] == "^CNXIT"
    assert "sector_breakdown" not in out


# ─────────────────────────────────────────────────────────────────
# Edge cases
# ─────────────────────────────────────────────────────────────────

def test_auto_with_empty_predictions():
    out = summarize_for_period(
        date(2025, 4, 1), date(2025, 6, 30),
        predictions=[],
        benchmark="auto",
        sector_benchmark_returns={},
    )
    assert out["n_predictions"] == 0
    # Empty-summary path doesn't include sector_breakdown — that's
    # the early-return shape — but we still want a clean response.
    # It's acceptable for the field to be absent here.


def test_auto_zero_outcomes_in_sector_omits_sector():
    """A sector with no qualifying predictions (all sub-MoS) must
    not appear in sector_breakdown."""
    preds = [
        {"ticker": "INFY.NS",  "sector": "IT Services",
         "margin_of_safety_pct": 35.0, "return_pct": 10.0},
        # Banks pick — sub-threshold MoS, must be filtered out.
        {"ticker": "HDFCBANK.NS","sector": "Banks",
         "margin_of_safety_pct": 12.0, "return_pct": 50.0},
    ]
    out = summarize_for_period(
        date(2025, 4, 1), date(2025, 6, 30),
        predictions=preds,
        benchmark="auto",
        sector_benchmark_returns={"^CNXIT": 5.0, "^NSEBANK": 8.0},
    )
    sectors = {r["sector"] for r in out["sector_breakdown"]}
    assert sectors == {"IT Services"}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items())
           if k.startswith("test_") and callable(v)]
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
