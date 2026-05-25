"""Unit tests for backend/services/analysis/honest_card_generator.py.

Covers each rule (fires / skips), output caps, SEBI-safe strings, and
graceful degradation on None / empty inputs.
"""
from __future__ import annotations

from backend.services.analysis.honest_card_generator import (
    generate_honest_card,
)
from backend.services.analysis.sebi_filter import find_banned


def _assert_sebi_safe(lines):
    for line in lines:
        hit = find_banned(line)
        assert hit is None, f"banned token {hit!r} in: {line!r}"


def _assert_card_sebi_safe(card) -> None:
    _assert_sebi_safe(card.confident_facts)
    _assert_sebi_safe([card.best_estimate])
    _assert_sebi_safe(card.uncertainty_factors)
    _assert_sebi_safe(card.invalidating_conditions)


# ─── Test 1: empty inputs degrade gracefully ──────────────────


def test_empty_inputs_do_not_crash():
    card = generate_honest_card()
    # confident_facts has a safety-net entry; uncertainty too.
    assert len(card.confident_facts) >= 1
    assert card.best_estimate  # always non-empty string
    assert len(card.uncertainty_factors) >= 1
    assert len(card.invalidating_conditions) == 3
    _assert_card_sebi_safe(card)


# ─── Test 2: best_estimate format includes FV + scenarios + confidence ──


def test_best_estimate_assembles_full_line():
    card = generate_honest_card(
        valuation={
            "fair_value": 1131,
            "bear_case": 942,
            "bull_case": 1507,
            "confidence_score": 90,
        },
    )
    assert "₹1,131" in card.best_estimate
    assert "Bear ₹942" in card.best_estimate
    assert "bull ₹1,507" in card.best_estimate
    assert "90/100" in card.best_estimate
    _assert_card_sebi_safe(card)


# ─── Test 3: confident_facts surfaces dividend + market cap ─────


def test_confident_facts_dividend_and_marketcap():
    card = generate_honest_card(
        company={"market_cap": 24_000_000_000_000, "company_name": "HDFC Bank"},
        insights={
            "dividend": {
                "has_dividends": True,
                "dividend_rate_per_share": 19.5,
                "consecutive_years": 7,
            }
        },
        quality={"promoter_pct": 0.0},
    )
    assert any("Market cap" in f for f in card.confident_facts)
    assert any("19.5" in f and "share" in f for f in card.confident_facts)
    assert any("7 consecutive" in f for f in card.confident_facts)
    # cap is 4
    assert len(card.confident_facts) <= 4
    _assert_card_sebi_safe(card)


# ─── Test 4: leverage uncertainty fires above 1.5× sector median ──


def test_uncertainty_leverage_fires():
    card = generate_honest_card(
        valuation={"fair_value": 100, "confidence_score": 90},
        quality={"de_ratio": 1.5},
        sector_de_median=0.6,
    )
    assert any("Leverage at 1.50" in f for f in card.uncertainty_factors)
    _assert_card_sebi_safe(card)


def test_uncertainty_leverage_skipped_when_in_range():
    card = generate_honest_card(
        valuation={"fair_value": 100, "confidence_score": 90},
        quality={"de_ratio": 0.7},
        sector_de_median=0.6,
    )
    assert not any("Leverage" in f for f in card.uncertainty_factors)


# ─── Test 5: low confidence fires uncertainty bullet ──────────


def test_uncertainty_low_confidence_fires():
    card = generate_honest_card(
        valuation={"fair_value": 100, "confidence_score": 45},
    )
    assert any("confidence 45/100" in f for f in card.uncertainty_factors)


# ─── Test 6: invalidating_conditions always returns exactly 3 ──


def test_invalidating_conditions_exactly_three():
    card_bank = generate_honest_card(
        valuation={"fair_value": 1500},
        quality={"is_bank": True},
        company={"sector": "Financial Services"},
    )
    assert len(card_bank.invalidating_conditions) == 3
    assert any("GNPA" in c or "NPA" in c for c in card_bank.invalidating_conditions)
    assert any("Loan" in c or "advances" in c for c in card_bank.invalidating_conditions)
    _assert_card_sebi_safe(card_bank)

    card_generic = generate_honest_card(
        valuation={"fair_value": 1500, "confidence_score": 80},
        quality={"revenue_cagr_3y": 0.20},
        company={"sector": "Information Technology"},
    )
    assert len(card_generic.invalidating_conditions) == 3
    # 60% of 20 = 12 → threshold should appear
    assert any("12%" in c for c in card_generic.invalidating_conditions)


# ─── Test 7: cyclical sector swaps in commodity triggers ────────


def test_cyclical_sector_invalidators():
    card = generate_honest_card(
        valuation={"fair_value": 500},
        company={"sector": "Metals & Mining"},
    )
    assert any("Commodity cycle" in c for c in card.invalidating_conditions)
    assert len(card.invalidating_conditions) == 3
    _assert_card_sebi_safe(card)


# ─── Test 8: SEBI-safety across a populated payload ─────────────


def test_full_payload_is_sebi_safe():
    card = generate_honest_card(
        company={
            "market_cap": 5_000_000_000_000,
            "sector": "Banks",
            "company_name": "HDFC Bank Limited",
        },
        valuation={
            "fair_value": 1131,
            "bear_case": 942,
            "bull_case": 1507,
            "confidence_score": 90,
            "fair_value_source": "peer_capped",
            "data_limited": False,
        },
        quality={
            "de_ratio": 0.95,
            "revenue_cagr_3y": 0.03,
            "promoter_pct": 25.6,
            "roe": 16.4,
            "is_bank": True,
            "latest_filing_period_end": "2025-03-31",
        },
        insights={
            "dividend": {
                "has_dividends": True,
                "dividend_rate_per_share": 19.5,
                "consecutive_years": 7,
            }
        },
        scenarios={
            "bear": {"iv": 942},
            "bull": {"iv": 1507},
        },
        sector_de_median=0.6,
    )
    _assert_card_sebi_safe(card)
    # All four sections populated.
    assert len(card.confident_facts) >= 2
    assert card.best_estimate
    assert len(card.uncertainty_factors) >= 2
    assert len(card.invalidating_conditions) == 3
