"""
Day-110c (2026-05-23) — REIT / InvIT sector cohort overrides.

Indian REITs and InvITs are SEBI-regulated pass-through trusts that
distribute >=90% of NDCF. Standard DCF mis-prices them by ~50%.

This cohort layer adds (on top of the existing PR #333 REIT
short-circuit + the new Day-110c is_invit classifier):
  - Sub-segment classifier (office_reit / retail_reit / roads_invit /
    transmission_invit / other_invit).
  - Sub-segment-aware fair distribution yield (band + anchor).
  - compute_distribution_yield_fair_value(ticker, distribution) →
    implied fair price = distribution / anchor (+/-10% on distribution
    growth boost gate).

Acceptance criteria covered here:
  1. EMBASSY detected, office REIT, fair yield in 6.5-7.5% band.
  2. MINDSPACE / BIRET also office REIT.
  3. NEXUSSELECT (and legacy NEXUS) retail REIT, 7.0-8.0% band.
  4. IRBINVIT detected, roads InvIT, fair yield in 10-12% band.
  5. POWERGRIDIT / INDIGRID transmission InvIT, 8-10% band.
  6. VIRTUS other_invit, 9-11% band.
  7. Non-REIT operating companies (HDFCBANK, TCS) NOT in cohort.
  8. Distribution-growth boost fires when CAGR > 8% (+10%).
  9. Distribution-growth de-rating fires when CAGR < 3% (-10%).
 10. Implied fair price math: EMBASSY 22 / 0.07 = 314.29.
 11. Graceful degradation when distribution data missing.
 12. is_invit classifier matches the InvIT cohort.
 13. Cache manifest entry present and timestamped correctly.
"""
from __future__ import annotations

from datetime import datetime, timezone

import pytest

from backend.services.analysis.constants import (
    INVIT_TICKERS,
    is_invit,
    is_reit,
)
from backend.services.analysis.sector_overrides import (
    REIT_INVIT_COHORT_TICKERS_INLINE,
    REIT_INVIT_DIST_GROWTH_HIGH_MULT,
    REIT_INVIT_DIST_GROWTH_LOW_MULT,
    REIT_INVIT_YIELD_ANCHOR_OFFICE,
    REIT_INVIT_YIELD_ANCHOR_RETAIL,
    REIT_INVIT_YIELD_ANCHOR_ROADS,
    REIT_INVIT_YIELD_ANCHOR_TRANSMISSION,
    REIT_INVIT_YIELD_ANCHOR_OTHER_INVIT,
    compute_distribution_yield_fair_value,
    is_invit_cohort_ticker,
    is_reit_invit_cohort_ticker,
    reit_invit_distribution_growth_boost,
    reit_invit_fair_yield,
    reit_invit_subsegment,
)


# ─────────────────────────────────────────────────────────────────
# 1. Cohort detection
# ─────────────────────────────────────────────────────────────────

@pytest.mark.parametrize(
    "ticker",
    [
        "EMBASSY", "EMBASSY.NS", "EMBASSY.BO",
        "MINDSPACE", "MINDSPACE.NS",
        "BIRET", "BIRET.NS",
        "BROOKFIELD",
        "NEXUSSELECT", "NEXUSSELECT.NS", "NEXUS",
        "IRBINVIT", "IRBINVIT.NS",
        "POWERGRIDIT", "POWERGRIDIT.NS",
        "INDIGRID", "INDIGRID.NS",
        "VIRTUS",
    ],
)
def test_cohort_positives(ticker):
    assert is_reit_invit_cohort_ticker(ticker) is True


@pytest.mark.parametrize(
    "ticker",
    [
        "HDFCBANK", "TCS", "RELIANCE", "INFY", "POWERGRID",
        "NTPC", "HINDUNILVR", "ITC", "DLF", "OBEROIRLTY",
        None, "",
    ],
)
def test_cohort_negatives(ticker):
    assert is_reit_invit_cohort_ticker(ticker) is False


# ─────────────────────────────────────────────────────────────────
# 2. Sub-segment classifier
# ─────────────────────────────────────────────────────────────────

def test_office_reit_subsegment():
    assert reit_invit_subsegment("EMBASSY.NS") == "office_reit"
    assert reit_invit_subsegment("MINDSPACE.NS") == "office_reit"
    assert reit_invit_subsegment("BIRET.NS") == "office_reit"
    assert reit_invit_subsegment("BROOKFIELD") == "office_reit"


def test_retail_reit_subsegment():
    assert reit_invit_subsegment("NEXUSSELECT.NS") == "retail_reit"
    assert reit_invit_subsegment("NEXUS") == "retail_reit"


def test_roads_invit_subsegment():
    assert reit_invit_subsegment("IRBINVIT.NS") == "roads_invit"


def test_transmission_invit_subsegment():
    assert reit_invit_subsegment("POWERGRIDIT.NS") == "transmission_invit"
    assert reit_invit_subsegment("INDIGRID.NS") == "transmission_invit"


def test_other_invit_subsegment():
    assert reit_invit_subsegment("VIRTUS") == "other_invit"


def test_subsegment_returns_none_for_non_cohort():
    assert reit_invit_subsegment("HDFCBANK.NS") is None
    assert reit_invit_subsegment("TCS.NS") is None
    assert reit_invit_subsegment(None) is None
    assert reit_invit_subsegment("") is None


# ─────────────────────────────────────────────────────────────────
# 3. Fair distribution yield bands
# ─────────────────────────────────────────────────────────────────

def test_office_reit_fair_yield_band_6_5_to_7_5():
    anchor, (low, high) = reit_invit_fair_yield("EMBASSY.NS")
    assert low == pytest.approx(0.065)
    assert high == pytest.approx(0.075)
    assert anchor == pytest.approx(REIT_INVIT_YIELD_ANCHOR_OFFICE)
    assert low <= anchor <= high


def test_retail_reit_fair_yield_band_7_to_8():
    anchor, (low, high) = reit_invit_fair_yield("NEXUSSELECT.NS")
    assert low == pytest.approx(0.070)
    assert high == pytest.approx(0.080)
    assert anchor == pytest.approx(REIT_INVIT_YIELD_ANCHOR_RETAIL)


def test_roads_invit_fair_yield_band_10_to_12():
    anchor, (low, high) = reit_invit_fair_yield("IRBINVIT.NS")
    assert low == pytest.approx(0.10)
    assert high == pytest.approx(0.12)
    assert anchor == pytest.approx(REIT_INVIT_YIELD_ANCHOR_ROADS)


def test_transmission_invit_fair_yield_band_8_to_10():
    anchor, (low, high) = reit_invit_fair_yield("INDIGRID.NS")
    assert low == pytest.approx(0.08)
    assert high == pytest.approx(0.10)
    assert anchor == pytest.approx(REIT_INVIT_YIELD_ANCHOR_TRANSMISSION)


def test_other_invit_fair_yield_band_9_to_11():
    anchor, (low, high) = reit_invit_fair_yield("VIRTUS")
    assert low == pytest.approx(0.09)
    assert high == pytest.approx(0.11)
    assert anchor == pytest.approx(REIT_INVIT_YIELD_ANCHOR_OTHER_INVIT)


def test_fair_yield_returns_none_for_non_cohort():
    assert reit_invit_fair_yield("HDFCBANK.NS") is None
    assert reit_invit_fair_yield(None) is None


# ─────────────────────────────────────────────────────────────────
# 4. Implied fair price math
# ─────────────────────────────────────────────────────────────────

def test_embassy_fair_price_22_over_7pct_equals_314():
    """Spec example: EMBASSY pays Rs.22 distribution, fair yield
    anchor 7.0% (office REIT) → implied fair price Rs.314."""
    result = compute_distribution_yield_fair_value(
        "EMBASSY.NS", annual_distribution_per_unit=22.0,
    )
    assert result is not None
    assert result["subsegment"] == "office_reit"
    assert result["fair_yield_anchor"] == pytest.approx(0.07)
    # 22 / 0.07 = 314.2857...
    assert result["implied_fair_price"] == pytest.approx(314.2857, abs=0.01)
    # No growth supplied → boost = 1.0
    assert result["distribution_growth_boost"] == pytest.approx(1.0)
    assert result["implied_fair_price_boosted"] == pytest.approx(
        314.2857, abs=0.01,
    )


def test_irbinvit_fair_price_at_11pct_anchor():
    """IRBINVIT pays Rs.10/yr distribution; fair yield anchor 11%.
    Implied fair price = 10 / 0.11 = 90.91."""
    result = compute_distribution_yield_fair_value(
        "IRBINVIT.NS", annual_distribution_per_unit=10.0,
    )
    assert result is not None
    assert result["subsegment"] == "roads_invit"
    assert result["implied_fair_price"] == pytest.approx(90.909, abs=0.01)


def test_indigrid_fair_price_at_9pct_anchor():
    """INDIGRID Rs.12/yr distribution; transmission anchor 9%.
    Implied fair price = 12 / 0.09 = 133.33."""
    result = compute_distribution_yield_fair_value(
        "INDIGRID", annual_distribution_per_unit=12.0,
    )
    assert result is not None
    assert result["subsegment"] == "transmission_invit"
    assert result["implied_fair_price"] == pytest.approx(133.333, abs=0.01)


# ─────────────────────────────────────────────────────────────────
# 5. Distribution-growth boost gates
# ─────────────────────────────────────────────────────────────────

def test_distribution_growth_boost_above_8pct_fires():
    boost = reit_invit_distribution_growth_boost(
        "EMBASSY.NS", distribution_cagr_3y=0.10,
    )
    assert boost == pytest.approx(REIT_INVIT_DIST_GROWTH_HIGH_MULT)
    assert boost == pytest.approx(1.10)


def test_distribution_growth_boost_below_3pct_derates():
    boost = reit_invit_distribution_growth_boost(
        "IRBINVIT.NS", distribution_cagr_3y=0.02,
    )
    assert boost == pytest.approx(REIT_INVIT_DIST_GROWTH_LOW_MULT)
    assert boost == pytest.approx(0.90)


def test_distribution_growth_boost_neutral_band():
    boost = reit_invit_distribution_growth_boost(
        "EMBASSY.NS", distribution_cagr_3y=0.05,
    )
    assert boost == pytest.approx(1.0)


def test_distribution_growth_boost_none_input_neutral():
    assert reit_invit_distribution_growth_boost(
        "EMBASSY.NS", distribution_cagr_3y=None,
    ) == pytest.approx(1.0)


def test_distribution_growth_boost_non_cohort_neutral():
    assert reit_invit_distribution_growth_boost(
        "HDFCBANK.NS", distribution_cagr_3y=0.20,
    ) == pytest.approx(1.0)


def test_compute_fv_applies_growth_boost():
    """EMBASSY Rs.22 distribution + 10% CAGR → 314.29 * 1.10 = 345.71."""
    result = compute_distribution_yield_fair_value(
        "EMBASSY.NS",
        annual_distribution_per_unit=22.0,
        distribution_cagr_3y=0.10,
    )
    assert result is not None
    assert result["distribution_growth_boost"] == pytest.approx(1.10)
    assert result["implied_fair_price_boosted"] == pytest.approx(
        345.7143, abs=0.01,
    )


# ─────────────────────────────────────────────────────────────────
# 6. Graceful degradation
# ─────────────────────────────────────────────────────────────────

def test_compute_fv_returns_none_for_missing_distribution():
    """Phase 2: when annual distribution is unknown the helper must
    return None rather than fabricating a fair value."""
    assert compute_distribution_yield_fair_value(
        "EMBASSY.NS", annual_distribution_per_unit=None,
    ) is None


def test_compute_fv_returns_none_for_zero_or_negative_distribution():
    assert compute_distribution_yield_fair_value(
        "EMBASSY.NS", annual_distribution_per_unit=0.0,
    ) is None
    assert compute_distribution_yield_fair_value(
        "EMBASSY.NS", annual_distribution_per_unit=-1.0,
    ) is None


def test_compute_fv_returns_none_for_non_cohort_ticker():
    assert compute_distribution_yield_fair_value(
        "HDFCBANK.NS", annual_distribution_per_unit=22.0,
    ) is None


def test_compute_fv_handles_garbage_input():
    assert compute_distribution_yield_fair_value(
        "EMBASSY.NS", annual_distribution_per_unit="not-a-number",
    ) is None
    assert compute_distribution_yield_fair_value(
        "EMBASSY.NS", annual_distribution_per_unit=float("nan"),
    ) is None


# ─────────────────────────────────────────────────────────────────
# 7. is_invit classifier (parallel to is_reit)
# ─────────────────────────────────────────────────────────────────

def test_is_invit_curated_positives():
    assert is_invit("IRBINVIT.NS") is True
    assert is_invit("POWERGRIDIT.NS") is True
    assert is_invit("INDIGRID.NS") is True
    assert is_invit("VIRTUS") is True


def test_is_invit_curated_set_contents():
    assert INVIT_TICKERS == {
        "IRBINVIT", "POWERGRIDIT", "INDIGRID", "VIRTUS",
    }


def test_is_invit_keyword_fallback_endswith():
    assert is_invit("FUTUREINVIT.NS") is True
    assert is_invit("SOMETHINGINVIT") is True


def test_is_invit_keyword_negative_midstring():
    assert is_invit("INVITESOMETHING") is False


def test_is_invit_industry_signal():
    assert is_invit(
        "UNKNOWN.NS", industry="Infrastructure Investment Trust",
    ) is True
    assert is_invit("UNKNOWN.NS", industry="InvIT - Roads") is True


def test_is_invit_negatives():
    # REITs are NOT InvITs
    assert is_invit("EMBASSY.NS") is False
    assert is_invit("MINDSPACE.NS") is False
    # Operating companies
    assert is_invit("HDFCBANK.NS") is False
    assert is_invit("TCS.NS") is False
    assert is_invit("POWERGRID.NS") is False  # parent, not the InvIT
    assert is_invit(None) is False
    assert is_invit("") is False


def test_is_reit_and_is_invit_are_disjoint_on_curated_sets():
    """Per PR #335 test_invits_are_not_reits — InvIT classifier must
    not flip is_reit() True, and REIT classifier must not flip
    is_invit() True. The cohort union (Day-110c) is built from the
    disjoint union of these two ticker sets plus aliases."""
    for t in ("IRBINVIT", "POWERGRIDIT", "INDIGRID", "VIRTUS"):
        assert is_reit(t) is False
        assert is_invit(t) is True
    for t in ("EMBASSY", "MINDSPACE", "BROOKFIELD", "NEXUS"):
        assert is_reit(t) is True
        assert is_invit(t) is False


def test_is_invit_cohort_ticker_helper():
    assert is_invit_cohort_ticker("IRBINVIT.NS") is True
    assert is_invit_cohort_ticker("INDIGRID") is True
    assert is_invit_cohort_ticker("EMBASSY.NS") is False
    assert is_invit_cohort_ticker("HDFCBANK") is False


# ─────────────────────────────────────────────────────────────────
# 8. Cohort union shape
# ─────────────────────────────────────────────────────────────────

def test_cohort_inline_set_contents():
    """Spec-locked tickers in scope for Day-110c.
    Aliases (BROOKFIELD/NEXUS) are kept so the PR #335 curated
    REIT_TICKERS set continues to overlap with the cohort, ensuring
    the existing 4 REIT verdicts still gain cohort metadata."""
    assert "EMBASSY" in REIT_INVIT_COHORT_TICKERS_INLINE
    assert "MINDSPACE" in REIT_INVIT_COHORT_TICKERS_INLINE
    assert "BIRET" in REIT_INVIT_COHORT_TICKERS_INLINE
    assert "NEXUSSELECT" in REIT_INVIT_COHORT_TICKERS_INLINE
    assert "IRBINVIT" in REIT_INVIT_COHORT_TICKERS_INLINE
    assert "POWERGRIDIT" in REIT_INVIT_COHORT_TICKERS_INLINE
    assert "INDIGRID" in REIT_INVIT_COHORT_TICKERS_INLINE
    assert "VIRTUS" in REIT_INVIT_COHORT_TICKERS_INLINE


# ─────────────────────────────────────────────────────────────────
# 9. Cache manifest entry
# ─────────────────────────────────────────────────────────────────

def test_manifest_has_day110c_entry():
    from backend.services.cache_invalidation_manifest import MANIFEST

    entry = next(
        (
            e for e in MANIFEST
            if e.get("version_id") == "v_day110c_reit_invit_cohort_2026_05_23"
        ),
        None,
    )
    assert entry is not None, "Day-110c manifest entry missing"
    assert entry["applied_at"] == datetime(
        2026, 5, 23, 21, 5, 0, tzinfo=timezone.utc,
    )
    tickers = entry["scope"]["tickers"]
    assert "EMBASSY" in tickers
    assert "IRBINVIT" in tickers
    assert "INDIGRID" in tickers
    assert "VIRTUS" in tickers


def test_manifest_day110c_does_not_collide_with_day110b_at_21_00():
    """The Day-110b insurance cohort agent ran at 21:00 UTC; Day-110c
    is intentionally placed at 21:05 UTC to avoid a collision."""
    from backend.services.cache_invalidation_manifest import MANIFEST

    entry = next(
        e for e in MANIFEST
        if e.get("version_id") == "v_day110c_reit_invit_cohort_2026_05_23"
    )
    assert entry["applied_at"].minute == 5
    assert entry["applied_at"].hour == 21
