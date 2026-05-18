"""Tests for the Tier 2 vs custom-engine head-to-head harness.

Covers the three pure functions in ``scripts/tier2_head_to_head.py``:

  * ``label_winner``           — per-ticker verdict on mocked FVs
  * ``aggregate_by_engine``    — per-engine roll-up
  * ``deprecation_recommendations`` — Week-5 deprecation candidate list

The script is importable as a top-level module because ``scripts/`` is
on the same PYTHONPATH layer as the rest of the repo helpers (mirrors
the import strategy used by ``test_benchmark_reconciliation`` for
``backend.services.benchmark_reconciliation_service``).
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


# ── Module loader (scripts/ is not a package) ────────────────────────


_HERE = Path(__file__).resolve().parents[2]
_SCRIPT = _HERE / "scripts" / "tier2_head_to_head.py"


def _load_module():
    spec = importlib.util.spec_from_file_location("tier2_head_to_head", _SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(mod)
    return mod


t2hh = _load_module()


# ── 1. label_winner — per-ticker verdict ─────────────────────────────


def test_tier2_wins_when_significantly_closer():
    v = t2hh.label_winner(
        current_fv=80, tier2_fv=98, consensus_fv=100, analyst_count=10,
        threshold_pct=5,
    )
    assert v["winner"] == "tier2_wins"
    assert v["delta_current"] == pytest.approx(0.20)
    assert v["delta_tier2"] == pytest.approx(0.02)
    assert v["delta_gap_pp"] == pytest.approx(18.0)


def test_current_wins_when_significantly_closer():
    v = t2hh.label_winner(
        current_fv=98, tier2_fv=70, consensus_fv=100, analyst_count=10,
        threshold_pct=5,
    )
    assert v["winner"] == "current_wins"


def test_tie_when_within_threshold():
    # 3pp gap, threshold 5pp → tie
    v = t2hh.label_winner(
        current_fv=97, tier2_fv=100, consensus_fv=100, analyst_count=10,
        threshold_pct=5,
    )
    assert v["winner"] == "tie"


def test_no_consensus_when_consensus_fv_missing():
    v = t2hh.label_winner(
        current_fv=100, tier2_fv=110, consensus_fv=None, analyst_count=10,
    )
    assert v["winner"] == "no_consensus"
    assert v["delta_current"] is None
    assert v["delta_tier2"] is None


def test_no_consensus_when_analyst_floor_not_met():
    v = t2hh.label_winner(
        current_fv=100, tier2_fv=110, consensus_fv=120, analyst_count=2,
        min_analysts=3,
    )
    assert v["winner"] == "no_consensus"


def test_no_consensus_when_consensus_zero_or_negative():
    v = t2hh.label_winner(
        current_fv=100, tier2_fv=110, consensus_fv=0, analyst_count=10,
    )
    assert v["winner"] == "no_consensus"


def test_tier2_wins_by_default_when_current_fv_missing():
    v = t2hh.label_winner(
        current_fv=None, tier2_fv=100, consensus_fv=100, analyst_count=10,
    )
    assert v["winner"] == "tier2_wins"
    assert v["delta_tier2"] == pytest.approx(0.0)


def test_current_wins_by_default_when_tier2_fv_missing():
    v = t2hh.label_winner(
        current_fv=100, tier2_fv=None, consensus_fv=100, analyst_count=10,
    )
    assert v["winner"] == "current_wins"


def test_no_consensus_when_both_fvs_missing():
    v = t2hh.label_winner(
        current_fv=None, tier2_fv=None, consensus_fv=100, analyst_count=10,
    )
    assert v["winner"] == "no_consensus"


def test_threshold_is_in_percentage_points():
    # Gap of exactly 4pp with threshold 5pp → tie
    v = t2hh.label_winner(
        current_fv=104, tier2_fv=100, consensus_fv=100, analyst_count=10,
        threshold_pct=5,
    )
    assert v["winner"] == "tie", v
    # Same FVs with threshold 3pp → tier2 wins
    v = t2hh.label_winner(
        current_fv=104, tier2_fv=100, consensus_fv=100, analyst_count=10,
        threshold_pct=3,
    )
    assert v["winner"] == "tier2_wins", v


# ── 2. aggregate_by_engine — per-engine roll-up ──────────────────────


def test_aggregate_by_engine_rolls_up_each_outcome():
    rows = [
        {"current_engine": "pharma_rd_adjusted", "winner": "tier2_wins"},
        {"current_engine": "pharma_rd_adjusted", "winner": "tier2_wins"},
        {"current_engine": "pharma_rd_adjusted", "winner": "current_wins"},
        {"current_engine": "pharma_rd_adjusted", "winner": "tie"},
        {"current_engine": "dcf", "winner": "tier2_wins"},
        {"current_engine": "dcf", "winner": "no_consensus"},
        {"current_engine": "fmcg_brand_overlay", "winner": "tier2_wins"},
    ]
    agg = t2hh.aggregate_by_engine(rows)
    assert agg["pharma_rd_adjusted"] == {
        "tier2_wins": 2, "current_wins": 1, "ties": 1, "no_consensus": 0,
    }
    assert agg["dcf"] == {
        "tier2_wins": 1, "current_wins": 0, "ties": 0, "no_consensus": 1,
    }
    assert agg["fmcg_brand_overlay"] == {
        "tier2_wins": 1, "current_wins": 0, "ties": 0, "no_consensus": 0,
    }


def test_aggregate_buckets_unknown_engine_as_unknown():
    rows = [
        {"current_engine": None, "winner": "tier2_wins"},
        {"current_engine": "", "winner": "current_wins"},
    ]
    agg = t2hh.aggregate_by_engine(rows)
    assert "unknown" in agg
    assert agg["unknown"]["tier2_wins"] == 1
    assert agg["unknown"]["current_wins"] == 1


# ── 3. deprecation_recommendations ───────────────────────────────────


def test_recommends_engine_with_high_tier2_win_rate():
    summary = {
        "pharma_rd_adjusted": {
            "tier2_wins": 18, "current_wins": 6, "ties": 2, "no_consensus": 0,
        },
    }
    recs = t2hh.deprecation_recommendations(summary)
    assert len(recs) == 1
    assert "pharma_rd_adjusted" in recs[0]
    assert "75%" in recs[0]


def test_skips_engine_below_min_samples():
    summary = {
        "fmcg_brand_overlay": {
            "tier2_wins": 4, "current_wins": 1, "ties": 0, "no_consensus": 0,
        },  # 5 decisive < 10 floor
    }
    recs = t2hh.deprecation_recommendations(summary)
    assert recs == []


def test_skips_engine_below_win_rate():
    summary = {
        "capital_goods_7y_fcf": {
            "tier2_wins": 11, "current_wins": 10, "ties": 0, "no_consensus": 0,
        },  # ~52% win rate
    }
    recs = t2hh.deprecation_recommendations(summary)
    assert recs == []


def test_never_recommends_dcf_for_deprecation():
    # Even a 100% win rate against generic DCF doesn't recommend
    # deprecation — DCF is the fallback engine.
    summary = {
        "dcf": {
            "tier2_wins": 500, "current_wins": 0, "ties": 0, "no_consensus": 0,
        },
    }
    recs = t2hh.deprecation_recommendations(summary)
    assert recs == []


# ── 4. Self-test entry point ─────────────────────────────────────────


def test_selftest_passes():
    rc = t2hh._selftest()
    assert rc == 0
