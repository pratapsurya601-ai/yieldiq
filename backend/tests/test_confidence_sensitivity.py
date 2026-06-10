"""Tests for compute_sensitivity_score (T2.7, 2026-06-09).

Pure-function tests for the 4th Confidence pillar. Verifies:
  - Stable inputs (MoS well above an undervalued threshold) -> >80
  - Borderline inputs (MoS near a verdict boundary)         -> <60
  - Holdcos and bank-sector inputs                          -> None
  - Missing base_inputs / base_verdict                      -> None
  - Determinism under fixed seed
  - Different seeds produce different score distributions

These tests run with no DB / network / yfinance access.
"""

from __future__ import annotations

import pytest

from backend.services.confidence_service import compute_sensitivity_score


# ───────────────────────────────────────────────────────────────────
# Fixtures
# ───────────────────────────────────────────────────────────────────
def _stable_undervalued_inputs() -> dict:
    """FV is 25% above price -> MoS=0.25, squarely in the middle
    of the 'undervalued' band (0.10 <= mos < 0.40). Boundaries are
    far enough away that the +/-0.5pp WACC, +/-2pp FCF, +/-0.5pp TG
    perturbations rarely flip the verdict — score should land >80.
    """
    return {
        "wacc": 0.115,
        "fcf_growth": 0.08,
        "terminal_growth": 0.04,
        "tax_rate": 0.25,
        "current_fv": 1250.0,
        "current_price": 1000.0,
    }


def _borderline_inputs() -> dict:
    """MoS sits at +10.1% — right on top of the 'undervalued' / 'fairly_valued'
    boundary at +10.0%. With perturbation noise of roughly +/-1.2% on FV,
    well over 40% of runs flip to 'fairly_valued'. Score should land <60.
    """
    return {
        "wacc": 0.115,
        "fcf_growth": 0.06,
        "terminal_growth": 0.04,
        "tax_rate": 0.25,
        "current_fv": 1101.0,
        "current_price": 1000.0,
    }


# ───────────────────────────────────────────────────────────────────
# Happy paths
# ───────────────────────────────────────────────────────────────────
def test_stable_inputs_score_above_80():
    score = compute_sensitivity_score(
        "TCS",
        base_inputs=_stable_undervalued_inputs(),
        base_verdict="undervalued",
        sector="Information Technology",
    )
    assert isinstance(score, int)
    assert score > 80, f"expected >80 for deeply-undervalued shape, got {score}"


def test_borderline_inputs_score_below_60():
    score = compute_sensitivity_score(
        "TCS",
        base_inputs=_borderline_inputs(),
        base_verdict="undervalued",
        sector="Information Technology",
    )
    assert isinstance(score, int)
    assert score < 60, f"expected <60 for borderline shape, got {score}"


# ───────────────────────────────────────────────────────────────────
# Carve-outs: holdco + bank-sector + missing inputs
# ───────────────────────────────────────────────────────────────────
def test_holdco_returns_none():
    """BAJAJHLDNG is in HOLDING_COMPANIES; SOTP-shaped so sensitivity
    is meaningless until T1.4. Score must be None."""
    score = compute_sensitivity_score(
        "BAJAJHLDNG",
        base_inputs=_stable_undervalued_inputs(),
        base_verdict="undervalued",
        sector="Diversified Holdings",
    )
    assert score is None


def test_bank_sector_returns_none():
    """Banking sector routes through residual-income / P-B engines;
    DCF-input perturbation is not the right exercise."""
    score = compute_sensitivity_score(
        "HDFCBANK",
        base_inputs=_stable_undervalued_inputs(),
        base_verdict="undervalued",
        sector="Banking",
    )
    assert score is None


def test_nbfc_sector_returns_none():
    score = compute_sensitivity_score(
        "BAJFINANCE",
        base_inputs=_stable_undervalued_inputs(),
        base_verdict="undervalued",
        sector="NBFC",
    )
    assert score is None


def test_insurance_sector_returns_none():
    score = compute_sensitivity_score(
        "HDFCLIFE",
        base_inputs=_stable_undervalued_inputs(),
        base_verdict="undervalued",
        sector="Insurance",
    )
    assert score is None


def test_financial_services_sector_returns_none():
    score = compute_sensitivity_score(
        "RANDOMFIN",
        base_inputs=_stable_undervalued_inputs(),
        base_verdict="undervalued",
        sector="Financial Services",
    )
    assert score is None


def test_missing_base_inputs_returns_none():
    score = compute_sensitivity_score(
        "TCS",
        base_inputs=None,
        base_verdict="undervalued",
        sector="Information Technology",
    )
    assert score is None


def test_missing_base_verdict_returns_none():
    score = compute_sensitivity_score(
        "TCS",
        base_inputs=_stable_undervalued_inputs(),
        base_verdict=None,
        sector="Information Technology",
    )
    assert score is None


def test_malformed_base_inputs_returns_none():
    bad = dict(_stable_undervalued_inputs())
    bad["wacc"] = "not-a-number"
    score = compute_sensitivity_score(
        "TCS",
        base_inputs=bad,
        base_verdict="undervalued",
        sector="Information Technology",
    )
    assert score is None


def test_zero_fv_returns_none():
    bad = dict(_stable_undervalued_inputs())
    bad["current_fv"] = 0.0
    score = compute_sensitivity_score(
        "TCS",
        base_inputs=bad,
        base_verdict="undervalued",
        sector="Information Technology",
    )
    assert score is None


def test_zero_price_returns_none():
    bad = dict(_stable_undervalued_inputs())
    bad["current_price"] = 0.0
    score = compute_sensitivity_score(
        "TCS",
        base_inputs=bad,
        base_verdict="undervalued",
        sector="Information Technology",
    )
    assert score is None


# ───────────────────────────────────────────────────────────────────
# Determinism
# ───────────────────────────────────────────────────────────────────
def test_same_seed_deterministic():
    """Two calls with the same explicit seed must produce identical scores."""
    inputs = _borderline_inputs()
    a = compute_sensitivity_score(
        "TCS", base_inputs=inputs, base_verdict="undervalued",
        sector="IT", seed=12345,
    )
    b = compute_sensitivity_score(
        "TCS", base_inputs=inputs, base_verdict="undervalued",
        sector="IT", seed=12345,
    )
    assert a == b


def test_implicit_seed_deterministic_per_ticker():
    """Without an explicit seed the function hashes the ticker, so
    repeated calls with the same ticker land on the same RNG path
    and must produce identical scores. This is what makes the
    field cache-friendly."""
    inputs = _borderline_inputs()
    a = compute_sensitivity_score(
        "TCS", base_inputs=inputs, base_verdict="undervalued",
        sector="IT",
    )
    b = compute_sensitivity_score(
        "TCS", base_inputs=inputs, base_verdict="undervalued",
        sector="IT",
    )
    assert a == b


def test_different_seeds_can_differ():
    """Different explicit seeds should generate different RNG paths.
    At n_runs=200 on a borderline shape, the score variance across
    seeds is small but nonzero — assert at least one pair differs."""
    inputs = _borderline_inputs()
    scores = [
        compute_sensitivity_score(
            "TCS", base_inputs=inputs, base_verdict="undervalued",
            sector="IT", seed=s,
        )
        for s in (1, 2, 3, 7, 11, 13, 17, 19)
    ]
    assert len(set(scores)) > 1, (
        f"all 8 seeds produced the same score {scores[0]} — "
        "RNG is not actually different across seeds"
    )


# ───────────────────────────────────────────────────────────────────
# Range invariant
# ───────────────────────────────────────────────────────────────────
@pytest.mark.parametrize("base_verdict", [
    "notably_undervalued", "undervalued", "fairly_valued",
    "overvalued", "notably_overvalued",
])
def test_score_in_0_100_range(base_verdict):
    score = compute_sensitivity_score(
        "TCS",
        base_inputs=_stable_undervalued_inputs(),
        base_verdict=base_verdict,
        sector="IT",
    )
    if score is not None:
        assert 0 <= score <= 100
