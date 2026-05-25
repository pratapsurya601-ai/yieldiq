"""Unit tests for backend/services/analysis/worry_index.py.

Covers:
  * Score lands in each of the 5 tiers given representative inputs
    (sleep_well, normal, watch_closely, read_bears, significant_concerns).
  * Tier boundaries are correct (19→sleep_well, 20→normal, 39→normal,
    40→watch_closely, etc.).
  * Headline strings are SEBI-safe (no banned word in any tier copy).
  * Missing inputs degrade gracefully — score is still a 0-100 int and
    the function never raises.
  * Contributors output sums weights to exactly 100 and every entry has
    the documented keys.
  * peer_context PE-premium increases valuation-stretch worry.
"""
from __future__ import annotations

from backend.services.analysis.worry_index import (
    compute_worry_index,
    WorryIndex,
    _tier_for,
)
from backend.services.analysis.sebi_filter import find_banned, BANNED_WORDS


def _assert_sebi_safe(text: str) -> None:
    hit = find_banned(text)
    assert hit is None, f"banned token {hit!r} in: {text!r}"


# ─── Tier boundaries ───────────────────────────────────────────


def test_tier_boundaries_are_exact():
    assert _tier_for(0)   == "sleep_well"
    assert _tier_for(19)  == "sleep_well"
    assert _tier_for(20)  == "normal"
    assert _tier_for(39)  == "normal"
    assert _tier_for(40)  == "watch_closely"
    assert _tier_for(59)  == "watch_closely"
    assert _tier_for(60)  == "read_bears"
    assert _tier_for(79)  == "read_bears"
    assert _tier_for(80)  == "significant_concerns"
    assert _tier_for(100) == "significant_concerns"


# ─── Per-tier representative inputs ────────────────────────────


def test_sleep_well_blue_chip():
    """Low D/E, fat margins, modest PE, low beta, no flags."""
    wi = compute_worry_index(
        valuation={"margin_of_safety": 20, "current_price": 100},
        quality={
            "de_ratio": 0.15, "current_ratio": 2.3,
            "interest_coverage": 25, "debt_ebitda": 0.4,
            "roe": 22, "net_margin": 22, "revenue_cagr_3y": 0.18,
            "yieldiq_score": 85, "promoter_pledge_pct": 0.0,
        },
        insights={
            "pe_ratio": 18, "beta": 0.7,
            "drawdown_from_52w_high": -3,
            "red_flags_structured": [],
        },
    )
    assert isinstance(wi, WorryIndex)
    assert wi.tier == "sleep_well"
    assert 0 <= wi.score < 20


def test_normal_market_risk():
    wi = compute_worry_index(
        valuation={"margin_of_safety": 5},
        quality={
            "de_ratio": 0.6, "current_ratio": 1.5,
            "interest_coverage": 8, "debt_ebitda": 1.5,
            "roe": 14, "net_margin": 12, "revenue_cagr_3y": 0.10,
            "yieldiq_score": 65,
        },
        insights={
            "pe_ratio": 22, "beta": 1.0,
            "drawdown_from_52w_high": -12,
            "red_flags_structured": [],
        },
    )
    assert wi.tier == "normal"


def test_watch_closely_mid_signal():
    wi = compute_worry_index(
        valuation={"margin_of_safety": -10},
        quality={
            "de_ratio": 1.1, "current_ratio": 1.1,
            "interest_coverage": 3.0, "debt_ebitda": 3.0,
            "roe": 9, "net_margin": 7, "revenue_cagr_3y": 0.04,
            "yieldiq_score": 50,
        },
        insights={
            "pe_ratio": 35, "beta": 1.3,
            "drawdown_from_52w_high": -22,
            "red_flags_structured": [{"k": "x"}, {"k": "y"}],
        },
    )
    assert wi.tier == "watch_closely"


def test_read_bears_loud_signal():
    wi = compute_worry_index(
        valuation={"margin_of_safety": -18},
        quality={
            "de_ratio": 1.3, "current_ratio": 1.0,
            "interest_coverage": 2.2, "debt_ebitda": 3.5,
            "roe": 7, "net_margin": 5, "revenue_cagr_3y": 0.01,
            "yieldiq_score": 40, "promoter_pledge_pct": 18,
        },
        insights={
            "pe_ratio": 42, "beta": 1.5,
            "drawdown_from_52w_high": -28,
            "red_flags_structured": [{"k": i} for i in range(3)],
        },
    )
    assert wi.tier == "read_bears", f"got {wi.tier} score={wi.score}"


def test_significant_concerns_distressed_signal():
    wi = compute_worry_index(
        valuation={"margin_of_safety": -45},
        quality={
            "de_ratio": 2.5, "current_ratio": 0.6,
            "interest_coverage": 0.8, "debt_ebitda": 7.0,
            "roe": -3, "net_margin": -2, "revenue_cagr_3y": -0.05,
            "yieldiq_score": 18, "promoter_pledge_pct": 65,
        },
        insights={
            "pe_ratio": 90, "beta": 2.0,
            "drawdown_from_52w_high": -55,
            "red_flags_structured": [{"k": i} for i in range(8)],
        },
    )
    assert wi.tier == "significant_concerns"
    assert wi.score >= 80


# ─── SEBI safety ───────────────────────────────────────────────


def test_all_tier_headlines_are_sebi_safe():
    from backend.services.analysis.worry_index import _TIER_COPY
    for tier, copy in _TIER_COPY.items():
        _assert_sebi_safe(copy)


def test_banned_words_actually_loaded():
    # Guard against accidentally truncating BANNED_WORDS in a refactor.
    assert "buy" in BANNED_WORDS and "sell" in BANNED_WORDS


# ─── Graceful degradation ──────────────────────────────────────


def test_all_inputs_none_returns_neutral_score():
    wi = compute_worry_index()
    assert isinstance(wi.score, int)
    assert 0 <= wi.score <= 100
    # All components return 50, so composite ~= 50 → watch_closely band
    assert wi.tier == "watch_closely"


def test_partial_inputs_do_not_raise():
    wi = compute_worry_index(quality={"de_ratio": 0.5})
    assert 0 <= wi.score <= 100


# ─── Contributors shape ────────────────────────────────────────


def test_contributors_sum_to_weight_100_and_have_keys():
    wi = compute_worry_index(
        quality={"de_ratio": 0.5, "roe": 12},
        insights={"pe_ratio": 20, "beta": 1.0},
    )
    assert len(wi.contributors) == 5
    assert sum(c["weight"] for c in wi.contributors) == 100
    for c in wi.contributors:
        assert set(c.keys()) >= {"component", "label", "weight", "score", "detail"}
        assert 0 <= c["score"] <= 100
        _assert_sebi_safe(c["detail"])


# ─── peer_context wiring ───────────────────────────────────────


def test_peer_pe_premium_increases_valuation_stretch_worry():
    base_q = {"de_ratio": 0.6, "roe": 14, "yieldiq_score": 60}
    base_i = {"pe_ratio": 40, "beta": 1.0, "drawdown_from_52w_high": -10}
    cheap_peers = {"pe_ratio": {"median": 40}}    # ticker == peer median
    rich_peers  = {"pe_ratio": {"median": 15}}    # ticker is at 2.7x peer median

    wi_neutral = compute_worry_index(
        valuation={"margin_of_safety": 0},
        quality=base_q, insights=base_i, peer_context=cheap_peers,
    )
    wi_stretched = compute_worry_index(
        valuation={"margin_of_safety": 0},
        quality=base_q, insights=base_i, peer_context=rich_peers,
    )
    val_neutral = next(c for c in wi_neutral.contributors
                       if c["component"] == "valuation_stretch")["score"]
    val_stretched = next(c for c in wi_stretched.contributors
                         if c["component"] == "valuation_stretch")["score"]
    assert val_stretched > val_neutral
