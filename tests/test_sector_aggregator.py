"""Unit tests for backend.services.sector_aggregator and sector_taxonomy.

Covers the 13-sector taxonomy round-trip, alias normalization, the
median/dispersion helpers, the value-pillar verdict thresholds
(<30 overvalued, >70 undervalued, else fair), and the small-N gate
(insufficient when fewer than 3 constituents have a value score).

No DB dependency — the aggregator takes a list of constituent dicts,
so every test builds its own fixture in memory.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import sector_aggregator as agg  # noqa: E402
from backend.services import sector_taxonomy as tax  # noqa: E402


# ── Helpers ─────────────────────────────────────────────────────

def _mk(ticker: str, sector: str | None, **pillar_scores: float | None) -> dict:
    """Build a constituent dict with the given pillar scores.

    Any pillar not passed is omitted from the analysis (i.e. the
    aggregator should treat it as missing → skip the median).
    Pass `value=None` explicitly to test the null-score path.
    """
    axes: dict = {}
    for k, v in pillar_scores.items():
        axes[k] = {"score": v}
    return {
        "ticker": ticker,
        "sector": sector,
        "analysis": {"hex": {"axes": axes}},
    }


# ── Taxonomy: canonical list ─────────────────────────────────────

def test_canonical_sectors_count_is_13():
    assert len(tax.CANONICAL_SECTORS) == 13


def test_canonical_sectors_are_unique():
    assert len(set(tax.CANONICAL_SECTORS)) == 13


def test_canonical_sectors_contains_expected_names():
    for name in [
        "Auto", "Bank", "Consumer Durables", "Energy", "Financial Services",
        "FMCG", "IT Services", "Media", "Metal", "Pharma",
        "Private Bank", "PSU Bank", "Real Estate",
    ]:
        assert name in tax.CANONICAL_SECTORS


# ── Taxonomy: normalize_sector ───────────────────────────────────

def test_normalize_sector_handles_none_and_empty():
    assert tax.normalize_sector(None) is None
    assert tax.normalize_sector("") is None
    assert tax.normalize_sector("   ") is None


def test_normalize_sector_maps_common_aliases():
    assert tax.normalize_sector("Automobiles") == "Auto"
    assert tax.normalize_sector("auto oem") == "Auto"
    assert tax.normalize_sector("HEALTHCARE") == "Pharma"
    assert tax.normalize_sector("Realty") == "Real Estate"
    assert tax.normalize_sector("Information Technology") == "IT Services"
    assert tax.normalize_sector(" PSU Bank ") == "PSU Bank"


def test_normalize_sector_passes_unknown_through_unchanged():
    # Unknown sector preserved (with whitespace stripped) — never
    # silently erase a label we haven't explicitly mapped.
    assert tax.normalize_sector("  Quantum Cheese  ") == "Quantum Cheese"


# ── Taxonomy: slug round-trip ────────────────────────────────────

def test_sector_slug_round_trip_for_all_canonical():
    for sector in tax.CANONICAL_SECTORS:
        slug = tax.sector_slug(sector)
        assert tax.sector_from_slug(slug) == sector


def test_sector_from_slug_returns_none_for_unknown():
    assert tax.sector_from_slug("not-a-real-sector") is None
    assert tax.sector_from_slug("") is None


# ── Aggregator: helpers ──────────────────────────────────────────

def test_median_and_dispersion_helpers():
    assert agg._median([]) is None
    assert agg._median([5.0]) == 5.0
    assert agg._median([1.0, 2.0, 3.0]) == 2.0
    # dispersion needs n>=2
    assert agg._dispersion([5.0]) is None
    # pstdev of [1,3] is 1.0
    assert agg._dispersion([1.0, 3.0]) == pytest.approx(1.0)


def test_pillar_score_extracts_or_returns_none():
    a = {"hex": {"axes": {"value": {"score": 7.5}, "growth": {"score": None}}}}
    assert agg._pillar_score(a, "value") == 7.5
    assert agg._pillar_score(a, "growth") is None
    assert agg._pillar_score(a, "missing") is None
    assert agg._pillar_score({}, "value") is None
    assert agg._pillar_score(None, "value") is None  # type: ignore[arg-type]


# ── Aggregator: verdict thresholds (the spec) ────────────────────

def test_verdict_overvalued_when_value_median_below_3():
    # value=2.5 → ×10 = 25 → <30 → overvalued
    constituents = [
        _mk("A.NS", "IT Services", value=2.0),
        _mk("B.NS", "IT Services", value=2.5),
        _mk("C.NS", "IT Services", value=3.0),
    ]
    result = agg.build_sector_prism("IT Services", constituents)
    assert result["verdict"] == "overvalued"
    assert result["pillars"]["value"]["median"] == 2.5


def test_verdict_undervalued_when_value_median_above_7():
    # value=8 → ×10 = 80 → >70 → undervalued
    constituents = [
        _mk("A.NS", "Pharma", value=7.5),
        _mk("B.NS", "Pharma", value=8.0),
        _mk("C.NS", "Pharma", value=8.5),
    ]
    result = agg.build_sector_prism("Pharma", constituents)
    assert result["verdict"] == "undervalued"


def test_verdict_fair_in_middle_band():
    # value=5 → ×10 = 50 → 30..70 → fair
    constituents = [
        _mk("A.NS", "Bank", value=4.5),
        _mk("B.NS", "Bank", value=5.0),
        _mk("C.NS", "Bank", value=5.5),
    ]
    result = agg.build_sector_prism("Bank", constituents)
    assert result["verdict"] == "fair"


def test_verdict_thresholds_are_strict():
    # value=3.0 → ×10=30 → NOT <30 → not overvalued (boundary fair)
    constituents = [_mk(f"T{i}.NS", "FMCG", value=3.0) for i in range(3)]
    result = agg.build_sector_prism("FMCG", constituents)
    assert result["verdict"] == "fair"
    # value=7.0 → ×10=70 → NOT >70 → not undervalued (boundary fair)
    constituents = [_mk(f"T{i}.NS", "FMCG", value=7.0) for i in range(3)]
    result = agg.build_sector_prism("FMCG", constituents)
    assert result["verdict"] == "fair"


# ── Aggregator: small-N + filtering ──────────────────────────────

def test_insufficient_when_fewer_than_3_constituents():
    constituents = [
        _mk("A.NS", "Media", value=5.0),
        _mk("B.NS", "Media", value=6.0),
    ]
    result = agg.build_sector_prism("Media", constituents)
    assert result["verdict"] == "insufficient"
    assert result["pillars"]["value"]["median"] is None
    assert result["pillars"]["value"]["n"] == 2
    assert result["constituent_count"] == 2


def test_aggregator_filters_to_matching_sector_via_normalization():
    # Pool contains a mix of sectors and alias variants — only Auto
    # should be counted, including "Automobiles" alias.
    constituents = [
        _mk("A.NS", "Automobiles", value=5.0),  # alias → Auto
        _mk("B.NS", "Auto", value=6.0),
        _mk("C.NS", "Auto OEM", value=7.0),  # alias → Auto
        _mk("D.NS", "Pharma", value=9.0),  # excluded
        _mk("E.NS", "Bank", value=2.0),  # excluded
    ]
    result = agg.build_sector_prism("Auto", constituents)
    assert result["constituent_count"] == 3
    assert result["pillars"]["value"]["median"] == 6.0
    assert result["sector"] == "Auto"
    assert result["slug"] == "auto"


def test_pillar_skips_missing_scores_per_pillar():
    # 3 constituents, but only 2 have a "growth" score — growth
    # should be n=2 and median=None (small-N gate), while value
    # is fully populated.
    constituents = [
        _mk("A.NS", "Bank", value=5.0, growth=4.0),
        _mk("B.NS", "Bank", value=5.0, growth=6.0),
        _mk("C.NS", "Bank", value=5.0),  # no growth
    ]
    result = agg.build_sector_prism("Bank", constituents)
    assert result["pillars"]["value"]["n"] == 3
    assert result["pillars"]["growth"]["n"] == 2
    assert result["pillars"]["growth"]["median"] is None


def test_empty_constituents_returns_insufficient_baseline():
    result = agg.build_sector_prism("Energy", [])
    assert result["sector"] == "Energy"
    assert result["constituent_count"] == 0
    assert result["verdict"] == "insufficient"
    for pillar in ("value", "quality", "growth", "moat", "safety", "pulse"):
        assert pillar in result["pillars"]
        assert result["pillars"][pillar]["n"] == 0
        assert result["pillars"][pillar]["median"] is None
