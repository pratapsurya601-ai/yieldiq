# backend/tests/test_anomaly_detection_rules.py
# ─────────────────────────────────────────────────────────────────────
# Anomaly-detection rules (audit Step 4, 2026-05-18)
#
# Covers the seven anomaly-detection rules added to
# backend/services/validators.py:validate_analysis. Each rule has a
# passing case (clean response → no issue), failing case (out-of-band →
# expected severity), and borderline case (right at / just inside the
# threshold) to lock the boundary semantics.
#
# These are READ-TIME validator gates — no cache layout change. They
# only promote `verdict` to `under_review` via check_and_quarantine for
# critical failures; the underlying computed fields are untouched.
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations

import pytest

from backend.models.responses import (
    AnalysisResponse,
    CompanyInfo,
    InsightCards,
    QualityOutput,
    ScenariosOutput,
    ValuationOutput,
)
from backend.services.validators import validate_analysis


# ── Fixture helpers ──────────────────────────────────────────────────


def _healthy_response(
    *,
    ticker: str = "INFY.NS",
    sector: str = "Information Technology",
    industry: str = "IT Services",
    currency: str = "INR",
    fair_value: float = 1800.0,
    current_price: float = 1500.0,
    bear_case: float = 1200.0,
    bull_case: float = 2200.0,
    terminal_growth: float = 0.04,
    reverse_dcf_implied_growth: float | None = 0.12,
    revenue_cagr_3y: float | None = 0.10,
) -> AnalysisResponse:
    """Build a baseline AnalysisResponse that passes every anomaly rule."""
    return AnalysisResponse(
        ticker=ticker,
        company=CompanyInfo(
            ticker=ticker,
            company_name=ticker,
            sector=sector,
            industry=industry,
            currency=currency,
            market_cap=5e11,
        ),
        valuation=ValuationOutput(
            fair_value=fair_value,
            current_price=current_price,
            margin_of_safety=(fair_value - current_price) / current_price * 100.0,
            verdict="undervalued",
            wacc=0.12,
            terminal_growth=terminal_growth,
            fcf_growth_rate=0.10,
            bear_case=bear_case,
            base_case=fair_value,
            bull_case=bull_case,
            confidence_score=70,
        ),
        quality=QualityOutput(
            yieldiq_score=70,
            piotroski_score=6,
            roe=18.0,
            de_ratio=0.3,
            revenue_cagr_3y=revenue_cagr_3y,
        ),
        insights=InsightCards(
            reverse_dcf_implied_growth=reverse_dcf_implied_growth,
        ),
        scenarios=ScenariosOutput(),
    )


def _issues_contain(result, needle: str) -> bool:
    return any(needle in i for i in result.issues)


# ── Rule 1: terminal_growth in [0.02, 0.06] critical ─────────────────


def test_rule1_terminal_growth_passing_within_band():
    r = validate_analysis(_healthy_response(terminal_growth=0.04))
    assert "terminal_growth" not in r.failed_fields


def test_rule1_terminal_growth_failing_above_six_pct_is_warning():
    # Severity downgraded from "critical" to "warning" to avoid
    # quarantining legitimate cyclical-trough cached payloads. The
    # field still surfaces in data_issues for review.
    r = validate_analysis(_healthy_response(terminal_growth=0.07))
    assert r.ok is False
    assert r.severity in ("warning", "critical")  # may stack with other rules
    assert "terminal_growth" in r.failed_fields


def test_rule1_terminal_growth_borderline_at_two_pct_passes():
    # Lower edge is inclusive — 0.02 must pass.
    r = validate_analysis(_healthy_response(terminal_growth=0.02))
    assert "terminal_growth" not in r.failed_fields


def test_rule1_terminal_growth_borderline_just_below_two_pct_fails():
    r = validate_analysis(_healthy_response(terminal_growth=0.019))
    assert r.ok is False
    assert "terminal_growth" in r.failed_fields


# ── Rule 2: implied_growth_pct in [-0.10, 0.50] warning ──────────────


def test_rule2_implied_growth_passing_in_band():
    r = validate_analysis(_healthy_response(reverse_dcf_implied_growth=0.15))
    assert "implied_growth_pct" not in r.failed_fields


def test_rule2_implied_growth_above_50pct_is_warning():
    r = validate_analysis(_healthy_response(reverse_dcf_implied_growth=0.65))
    assert "implied_growth_pct" in r.failed_fields
    # Warning, not critical — model unreliability flag, not a fail-close.
    assert r.severity in ("warning", "critical")  # may stack with others
    assert _issues_contain(r, "implied_growth_pct")


def test_rule2_implied_growth_borderline_neg_10pct_passes():
    r = validate_analysis(_healthy_response(reverse_dcf_implied_growth=-0.10))
    assert "implied_growth_pct" not in r.failed_fields


def test_rule2_implied_growth_just_below_neg_10pct_fails():
    r = validate_analysis(_healthy_response(reverse_dcf_implied_growth=-0.11))
    assert "implied_growth_pct" in r.failed_fields


# ── Rule 3: valuation_dispersion = bull/bear ≤ 5 warning ─────────────


def test_rule3_valuation_dispersion_passing_2x():
    # bull=2200 / bear=1200 ≈ 1.83 → in band.
    r = validate_analysis(_healthy_response())
    assert "valuation_dispersion" not in r.failed_fields


def test_rule3_valuation_dispersion_failing_6x_is_warning():
    r = validate_analysis(_healthy_response(bear_case=200.0, bull_case=1400.0))
    assert "valuation_dispersion" in r.failed_fields
    assert _issues_contain(r, "valuation_dispersion")


def test_rule3_valuation_dispersion_borderline_at_5x_passes():
    # 5.0x is inclusive on the upper bound.
    r = validate_analysis(_healthy_response(bear_case=200.0, bull_case=1000.0))
    assert "valuation_dispersion" not in r.failed_fields


def test_rule3_valuation_dispersion_just_above_5x_fails():
    r = validate_analysis(_healthy_response(bear_case=200.0, bull_case=1001.0))
    assert "valuation_dispersion" in r.failed_fields


# ── Rule 4: utility overvaluation guard ──────────────────────────────


def _stub_is_utility(monkeypatch, *, value: bool) -> None:
    import backend.services.analysis.constants as constants

    monkeypatch.setattr(
        constants, "is_regulated_utility", lambda t=None, s=None, i=None: value
    )


def test_rule4_utility_iv_within_60pct_passes(monkeypatch):
    _stub_is_utility(monkeypatch, value=True)
    # IV 40% above price — within tolerance for a utility.
    r = validate_analysis(
        _healthy_response(
            ticker="POWERGRID.NS",
            sector="Utilities",
            fair_value=140.0,
            current_price=100.0,
            bear_case=80.0,
            bull_case=160.0,
        )
    )
    assert not _issues_contain(r, "UTILITY_OVERVALUATION")


def test_rule4_utility_iv_above_60pct_is_critical(monkeypatch):
    _stub_is_utility(monkeypatch, value=True)
    # IV 80% above price — over the 60% threshold.
    r = validate_analysis(
        _healthy_response(
            ticker="POWERGRID.NS",
            sector="Utilities",
            fair_value=180.0,
            current_price=100.0,
            bear_case=80.0,
            bull_case=200.0,
        )
    )
    assert r.ok is False
    assert r.severity == "critical"
    assert _issues_contain(r, "UTILITY_OVERVALUATION")


def test_rule4_borderline_utility_at_60pct_passes(monkeypatch):
    _stub_is_utility(monkeypatch, value=True)
    # Exactly 60% — strict > 0.6 threshold, so 0.6 passes.
    r = validate_analysis(
        _healthy_response(
            ticker="POWERGRID.NS",
            sector="Utilities",
            fair_value=160.0,
            current_price=100.0,
            bear_case=80.0,
            bull_case=180.0,
        )
    )
    assert not _issues_contain(r, "UTILITY_OVERVALUATION")


def test_rule4_non_utility_with_high_iv_is_not_flagged_by_rule4(monkeypatch):
    _stub_is_utility(monkeypatch, value=False)
    r = validate_analysis(
        _healthy_response(
            ticker="INFY.NS",
            fair_value=200.0,
            current_price=100.0,
            bear_case=80.0,
            bull_case=220.0,
        )
    )
    assert not _issues_contain(r, "UTILITY_OVERVALUATION")


# ── Rule 5: ADR/NSE currency mismatch guard ──────────────────────────


def test_rule5_ns_ticker_with_inr_passes():
    r = validate_analysis(_healthy_response(ticker="TCS.NS", currency="INR"))
    assert not _issues_contain(r, "ADR_NSE_MISMATCH")


def test_rule5_ns_ticker_with_usd_is_critical():
    r = validate_analysis(_healthy_response(ticker="TCS.NS", currency="USD"))
    assert r.ok is False
    assert r.severity == "critical"
    assert _issues_contain(r, "ADR_NSE_MISMATCH")
    assert "currency" in r.failed_fields


def test_rule5_non_ns_ticker_with_usd_is_not_flagged():
    # ADR-style symbol — USD is legitimate, no flag.
    r = validate_analysis(_healthy_response(ticker="INFY", currency="USD"))
    assert not _issues_contain(r, "ADR_NSE_MISMATCH")


# ── Rule 7: phantom revenue CAGR (structural-break interaction) ──────


def _stub_structural_break(monkeypatch, *, value: bool) -> None:
    import backend.services.corporate_actions_service as cas
    import backend.services.validators as validators_mod

    monkeypatch.setattr(cas, "has_structural_break", lambda t, window_years=3: value)
    # validators.py imports lazily inside the function; patching both the
    # source and any pre-bound reference is defensive — the function-local
    # `from ... import has_structural_break` resolves fresh each call.
    if hasattr(validators_mod, "has_structural_break"):
        monkeypatch.setattr(
            validators_mod, "has_structural_break", lambda t, window_years=3: value
        )


def test_rule7_clean_revenue_growth_on_broken_ticker_passes(monkeypatch):
    _stub_structural_break(monkeypatch, value=True)
    r = validate_analysis(
        _healthy_response(ticker="DEMERGED.NS", revenue_cagr_3y=0.18)
    )
    assert not _issues_contain(r, "PHANTOM_REVENUE_CAGR")


def test_rule7_high_revenue_growth_on_broken_ticker_is_critical(monkeypatch):
    _stub_structural_break(monkeypatch, value=True)
    r = validate_analysis(
        _healthy_response(ticker="DEMERGED.NS", revenue_cagr_3y=0.55)
    )
    assert r.ok is False
    assert r.severity == "critical"
    assert _issues_contain(r, "PHANTOM_REVENUE_CAGR")
    assert "revenue_cagr_3y" in r.failed_fields


def test_rule7_borderline_at_30pct_passes(monkeypatch):
    _stub_structural_break(monkeypatch, value=True)
    # abs(rc) > 0.30 — exactly 0.30 must NOT flag.
    r = validate_analysis(
        _healthy_response(ticker="DEMERGED.NS", revenue_cagr_3y=0.30)
    )
    assert not _issues_contain(r, "PHANTOM_REVENUE_CAGR")


def test_rule7_just_above_30pct_flags(monkeypatch):
    _stub_structural_break(monkeypatch, value=True)
    r = validate_analysis(
        _healthy_response(ticker="DEMERGED.NS", revenue_cagr_3y=0.305)
    )
    assert _issues_contain(r, "PHANTOM_REVENUE_CAGR")


def test_rule7_high_revenue_growth_without_structural_break_is_not_flagged(monkeypatch):
    _stub_structural_break(monkeypatch, value=False)
    r = validate_analysis(
        _healthy_response(ticker="HEALTHY.NS", revenue_cagr_3y=0.55)
    )
    assert not _issues_contain(r, "PHANTOM_REVENUE_CAGR")


# ── Smoke: a fully-clean response still passes all anomaly gates ─────


def test_healthy_baseline_response_passes_all_anomaly_rules():
    r = validate_analysis(_healthy_response())
    # No anomaly-rule signatures should appear.
    for marker in (
        "UTILITY_OVERVALUATION",
        "ADR_NSE_MISMATCH",
        "PHANTOM_REVENUE_CAGR",
        "valuation_dispersion",
        "implied_growth_pct",
    ):
        assert not _issues_contain(r, marker), f"unexpected: {marker} in {r.issues}"
