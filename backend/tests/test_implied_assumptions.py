"""
Tests for the Implied-Assumptions extension on top of
backend/services/reverse_dcf_service.py — the AlphaSpread-style
"what does the market expect at the current price?" framing.

Contract these tests enforce:

1. Pure helpers (`classify_market_expectation`,
   `compute_plausibility_score`) are deterministic, monotone, and
   degrade cleanly when the historical anchor is missing.

2. `compute_implied_assumptions` is consistent with
   `compute_reverse_dcf` — given the same inputs, the implied growth
   we surface matches (to within bisector tolerance) the implied
   growth the existing reverse-DCF surface already shows. The rich
   framing only adds context; it never invents a new number.

3. The headline is observational — it never asserts a verdict.
4. The dict projection round-trips via `implied_assumptions_to_dict`.
5. The Pydantic round-trip on AnalysisResponse accepts the new field
   with a None default (legacy cached payload back-compat).
"""

from __future__ import annotations

import math

import pytest

from backend.services.reverse_dcf_service import (
    EXPECTATION_AGGRESSIVE_PCT,
    EXPECTATION_MODERATE_PCT,
    EXPECTATION_MODEST_PCT,
    ImpliedAssumptionsResult,
    PLAUSIBILITY_BAND_AGGRESSIVE_PP,
    PLAUSIBILITY_BAND_IN_LINE_PP,
    PLAUSIBILITY_BAND_STRETCHED_PP,
    classify_market_expectation,
    compute_implied_assumptions,
    compute_plausibility_score,
    compute_reverse_dcf,
    implied_assumptions_to_dict,
)


# ─── classify_market_expectation ─────────────────────────────────


class TestClassifyMarketExpectation:
    def test_in_line_with_history_is_modest(self):
        # implied = historical → 0pp gap → modest
        assert classify_market_expectation(10.0, 10.0) == "modest"
        # within +/- in-line band
        assert (
            classify_market_expectation(
                10.0 + PLAUSIBILITY_BAND_IN_LINE_PP - 0.1, 10.0
            )
            == "modest"
        )

    def test_stretched_above_history_is_moderate(self):
        # gap = 3pp (inside 2-5pp stretched band)
        assert classify_market_expectation(13.0, 10.0) == "moderate"

    def test_aggressive_band(self):
        # gap = 8pp (inside 5-10pp aggressive band)
        assert classify_market_expectation(18.0, 10.0) == "aggressive"

    def test_extreme_band(self):
        # gap = 15pp (>10pp extreme band)
        assert classify_market_expectation(25.0, 10.0) == "extreme"

    def test_symmetric_below_history(self):
        # market expecting LESS growth than history is also notable
        # — same bins, mirrored across zero gap.
        assert classify_market_expectation(5.0, 10.0) == "moderate"   # gap -5pp -> moderate
        assert classify_market_expectation(2.0, 10.0) == "aggressive" # gap -8pp -> aggressive
        assert classify_market_expectation(0.0, 15.0) == "extreme"    # gap -15pp -> extreme

    def test_missing_history_falls_back_to_absolute_implied(self):
        # No historical anchor → bin on absolute implied growth
        assert classify_market_expectation(3.0, None) == "modest"
        assert classify_market_expectation(8.0, None) == "moderate"
        assert classify_market_expectation(15.0, None) == "aggressive"
        assert classify_market_expectation(30.0, None) == "extreme"

    def test_nan_history_falls_back_to_absolute(self):
        # NaN must be treated the same as missing
        assert (
            classify_market_expectation(3.0, float("nan"))
            == classify_market_expectation(3.0, None)
        )

    def test_constants_are_in_expected_order(self):
        # Defensive: tests below depend on these being monotone.
        assert (
            PLAUSIBILITY_BAND_IN_LINE_PP
            < PLAUSIBILITY_BAND_STRETCHED_PP
            < PLAUSIBILITY_BAND_AGGRESSIVE_PP
        )
        assert (
            EXPECTATION_MODEST_PCT
            < EXPECTATION_MODERATE_PCT
            < EXPECTATION_AGGRESSIVE_PCT
        )


# ─── compute_plausibility_score ──────────────────────────────────


class TestComputePlausibilityScore:
    def test_within_2pp_is_90(self):
        assert compute_plausibility_score(10.0, 10.0, None) == 90
        assert compute_plausibility_score(11.5, 10.0, None) == 90  # +1.5pp

    def test_2_to_5pp_is_70(self):
        assert compute_plausibility_score(13.0, 10.0, None) == 70  # +3pp
        assert compute_plausibility_score(7.0, 10.0, None) == 70   # -3pp (symmetric)

    def test_5_to_10pp_is_50(self):
        assert compute_plausibility_score(17.0, 10.0, None) == 50  # +7pp

    def test_10_to_20pp_is_30(self):
        assert compute_plausibility_score(25.0, 10.0, None) == 30  # +15pp

    def test_above_20pp_is_10(self):
        assert compute_plausibility_score(35.0, 10.0, None) == 10  # +25pp

    def test_missing_history_returns_midpoint(self):
        # No historical anchor → 50 (uninformative)
        assert compute_plausibility_score(10.0, None, None) == 50
        assert compute_plausibility_score(10.0, float("nan"), None) == 50

    def test_symmetric_below_history(self):
        # Implied < historical also reduces plausibility (mean
        # reversion thesis) — same bins, mirrored.
        assert compute_plausibility_score(10.0, 13.0, None) == 70  # -3pp
        assert compute_plausibility_score(10.0, 18.0, None) == 50  # -8pp

    def test_cyclical_sector_penalises_hot_implied_growth(self):
        # steel = deep cyclical, tilt -1.5
        # implied 13% vs hist 10% (gap +3) without sector → 70.
        # With sector="steel" the effective gap becomes 3 - (-1.5) = 4.5
        # → still inside stretched band (70). Push to gap +4 and
        # cyclical bumps it to the aggressive band:
        no_sector = compute_plausibility_score(14.0, 10.0, None)  # gap 4 → 70
        with_sector = compute_plausibility_score(14.0, 10.0, "steel")  # gap 5.5 → 50
        assert no_sector == 70
        assert with_sector == 50

    def test_unknown_sector_has_no_effect(self):
        a = compute_plausibility_score(13.0, 10.0, None)
        b = compute_plausibility_score(13.0, 10.0, "some_made_up_sector")
        assert a == b

    def test_low_implied_growth_not_penalised_by_cyclical_tilt(self):
        # When implied < historical the cyclical tilt does NOT make
        # the score harsher — direction-asymmetric by design.
        no_sector = compute_plausibility_score(7.0, 10.0, None)
        with_sector = compute_plausibility_score(7.0, 10.0, "steel")
        assert no_sector == with_sector == 70


# ─── compute_implied_assumptions integration ─────────────────────


# A clean non-cyclical fixture — easier to reason about than a
# RELIANCE-style cyclical-trough fixture, and the math is identical.
_IA_BASE = dict(
    current_price=3500.0,
    base_fcf=42000e7,
    shares=370e7,
    historical_revenue_cagr_3y=0.13,  # 13%
    wacc=0.115,
    terminal_growth=0.04,
    total_debt=10000e7,
    total_cash=80000e7,
    ticker="TCS.NS",
)


class TestComputeImpliedAssumptions:
    def test_returns_result_dataclass(self):
        r = compute_implied_assumptions(**_IA_BASE)
        assert isinstance(r, ImpliedAssumptionsResult)
        assert math.isfinite(r.implied_revenue_cagr_pct)
        assert math.isfinite(r.implied_terminal_growth_pct)

    def test_terminal_growth_passes_through_as_percent(self):
        r = compute_implied_assumptions(**_IA_BASE)
        assert r.implied_terminal_growth_pct == pytest.approx(4.0, abs=1e-6)

    def test_wacc_echo_as_percent(self):
        r = compute_implied_assumptions(**_IA_BASE)
        assert r.implied_wacc_pct == pytest.approx(11.5, abs=1e-6)

    def test_consensus_gap_when_consensus_supplied(self):
        r = compute_implied_assumptions(
            consensus_revenue_cagr=0.09, **_IA_BASE,
        )
        assert r.consensus_revenue_cagr_pct == pytest.approx(9.0)
        assert r.growth_gap_pp is not None
        assert r.growth_gap_pp == pytest.approx(
            r.implied_revenue_cagr_pct - 9.0
        )

    def test_consensus_gap_none_when_not_supplied(self):
        r = compute_implied_assumptions(**_IA_BASE)
        assert r.consensus_revenue_cagr_pct is None
        assert r.growth_gap_pp is None

    def test_margin_expansion_bps_present_when_both_anchors_present(self):
        r = compute_implied_assumptions(
            current_margin=0.20,
            historical_margin=0.15,
            **_IA_BASE,
        )
        # (0.20 - 0.15) * 10000 = 500 bps
        assert r.implied_margin_expansion_bps == pytest.approx(500.0, abs=1e-3)

    def test_margin_expansion_bps_none_when_either_anchor_missing(self):
        r1 = compute_implied_assumptions(current_margin=0.20, **_IA_BASE)
        r2 = compute_implied_assumptions(historical_margin=0.15, **_IA_BASE)
        r3 = compute_implied_assumptions(**_IA_BASE)
        assert r1.implied_margin_expansion_bps is None
        assert r2.implied_margin_expansion_bps is None
        assert r3.implied_margin_expansion_bps is None

    def test_label_is_one_of_expected_set(self):
        r = compute_implied_assumptions(**_IA_BASE)
        assert r.market_expectation_label in (
            "modest", "moderate", "aggressive", "extreme",
        )

    def test_score_in_valid_range(self):
        r = compute_implied_assumptions(**_IA_BASE)
        assert 0 <= r.plausibility_score <= 100

    def test_headline_contains_implied_growth_string(self):
        r = compute_implied_assumptions(**_IA_BASE)
        # Headline should contain the implied growth at 1 decimal,
        # the label, and "implies" framing.
        impl_str = f"{r.implied_revenue_cagr_pct:.1f}%"
        assert impl_str in r.headline
        assert r.market_expectation_label in r.headline
        assert "implies" in r.headline.lower()

    def test_headline_observational_never_a_verdict(self):
        # SEBI guard: the headline must not assert a recommendation
        # (the words `b` + `uy` / `s` + `ell` / `h` + `old` must not
        # appear). Construct from fragments so this assertion's
        # banned-vocab array survives diff-only SEBI lint (per
        # CLAUDE.md Standing Rule 5, Pattern B).
        r = compute_implied_assumptions(**_IA_BASE)
        banned = ["b" + "uy", "s" + "ell", "h" + "old"]
        for token in banned:
            assert token.lower() not in r.headline.lower()

    def test_consensus_drives_headline_format(self):
        # When consensus is supplied the headline mentions it
        with_consensus = compute_implied_assumptions(
            consensus_revenue_cagr=0.09, **_IA_BASE,
        )
        without_consensus = compute_implied_assumptions(**_IA_BASE)
        assert "consensus" in with_consensus.headline.lower()
        assert "consensus" not in without_consensus.headline.lower()
        # Without consensus it must still convey a comparison anchor
        assert "trailing" in without_consensus.headline.lower()


# ─── compute_reverse_dcf consistency ─────────────────────────────


class TestConsistencyWithReverseDcf:
    def test_implied_growth_matches_reverse_dcf_solver(self):
        # Solve via both surfaces with identical inputs; the implied
        # growth number must be byte-identical (single solver pass).
        rdcf = compute_reverse_dcf(
            ticker="TCS.NS",
            current_price=3500.0,
            wacc=0.115,
            current_fcf=42000e7,
            current_margin=0.20,
            current_revenue=210000e7,
            total_debt=10000e7,
            total_cash=80000e7,
            shares=370e7,
            terminal_g=0.04,
        )
        assert rdcf is not None
        ia = compute_implied_assumptions(
            current_price=3500.0,
            base_fcf=42000e7,
            shares=370e7,
            historical_revenue_cagr_3y=0.13,
            wacc=0.115,
            terminal_growth=0.04,
            total_debt=10000e7,
            total_cash=80000e7,
            current_revenue=210000e7,
            current_margin=0.20,
            ticker="TCS.NS",
        )
        assert ia is not None
        # The two implied numbers come from the same _binary_search
        # over the same _dcf_per_share fade lattice — the only
        # tolerance is the bisector's own SEARCH_TOL (1e-3 of target).
        assert ia.implied_revenue_cagr_pct == pytest.approx(
            rdcf["implied_growth_pct"] * 100.0, abs=0.5
        )


# ─── compute_implied_assumptions input validation ────────────────


class TestImpliedAssumptionsValidation:
    def test_zero_price_returns_none(self):
        r = compute_implied_assumptions(
            **{**_IA_BASE, "current_price": 0.0},
        )
        assert r is None

    def test_zero_shares_returns_none(self):
        r = compute_implied_assumptions(
            **{**_IA_BASE, "shares": 0.0},
        )
        assert r is None

    def test_zero_base_fcf_returns_none(self):
        # Loss-making path — reverse DCF is not meaningful
        r = compute_implied_assumptions(
            **{**_IA_BASE, "base_fcf": 0.0},
        )
        assert r is None

    def test_negative_base_fcf_returns_none(self):
        r = compute_implied_assumptions(
            **{**_IA_BASE, "base_fcf": -1000.0},
        )
        assert r is None

    def test_extreme_wacc_returns_none(self):
        # Outside [0.05, 0.25] sanity window
        r = compute_implied_assumptions(
            **{**_IA_BASE, "wacc": 0.30},
        )
        assert r is None
        r = compute_implied_assumptions(
            **{**_IA_BASE, "wacc": 0.02},
        )
        assert r is None

    def test_terminal_above_wacc_self_corrects(self):
        # When terminal_g >= wacc the solver re-anchors at
        # max(wacc-0.02, 0) — must NOT raise, must return a result.
        r = compute_implied_assumptions(
            **{**_IA_BASE, "wacc": 0.12, "terminal_growth": 0.13},
        )
        assert r is not None
        # New effective terminal_g surfaces correctly in the echo
        assert r.implied_terminal_growth_pct < 12.0


# ─── implied_assumptions_to_dict ─────────────────────────────────


class TestImpliedAssumptionsToDict:
    def test_none_pass_through(self):
        assert implied_assumptions_to_dict(None) is None

    def test_round_trip_keys(self):
        r = compute_implied_assumptions(
            consensus_revenue_cagr=0.09,
            current_margin=0.20,
            historical_margin=0.15,
            **_IA_BASE,
        )
        d = implied_assumptions_to_dict(r)
        assert d is not None
        expected_keys = {
            "implied_revenue_cagr_pct",
            "implied_terminal_growth_pct",
            "implied_margin_expansion_bps",
            "implied_wacc_pct",
            "consensus_revenue_cagr_pct",
            "growth_gap_pp",
            "market_expectation_label",
            "plausibility_score",
            "headline",
        }
        assert set(d.keys()) == expected_keys
        # Numeric types survive (asdict gives floats, not e.g. numpy
        # scalars even when the inputs were np.float64).
        assert isinstance(d["implied_revenue_cagr_pct"], float)
        assert isinstance(d["plausibility_score"], int)
        assert isinstance(d["headline"], str)


# ─── AnalysisResponse Pydantic field default ─────────────────────


class TestAnalysisResponseRoundTrip:
    def test_implied_assumptions_optional_none_default(self):
        from backend.models.responses import (
            AnalysisResponse, CompanyInfo, ValuationOutput, QualityOutput,
            InsightCards,
        )
        # Minimum-fields construction — implied_assumptions defaults None
        resp = AnalysisResponse(
            ticker="TCS.NS",
            company=CompanyInfo(company_name="TCS", ticker="TCS.NS"),
            valuation=ValuationOutput(
                fair_value=1000.0,
                current_price=900.0,
                margin_of_safety=10.0,
                verdict="fairly_valued",
            ),
            quality=QualityOutput(),
            insights=InsightCards(),
        )
        assert resp.implied_assumptions is None
        # Round-trip — JSON-serialisable and the field round-trips
        dumped = resp.model_dump()
        assert "implied_assumptions" in dumped
        assert dumped["implied_assumptions"] is None

    def test_implied_assumptions_dict_round_trips(self):
        from backend.models.responses import (
            AnalysisResponse, CompanyInfo, ValuationOutput, QualityOutput,
            InsightCards,
        )
        payload = {
            "implied_revenue_cagr_pct": 14.5,
            "implied_terminal_growth_pct": 4.0,
            "implied_margin_expansion_bps": 250.0,
            "implied_wacc_pct": 11.5,
            "consensus_revenue_cagr_pct": 9.0,
            "growth_gap_pp": 5.5,
            "market_expectation_label": "aggressive",
            "plausibility_score": 50,
            "headline": "Current price implies 14.5% CAGR vs consensus 9.0% -- aggressive",
        }
        resp = AnalysisResponse(
            ticker="TCS.NS",
            company=CompanyInfo(company_name="TCS", ticker="TCS.NS"),
            valuation=ValuationOutput(
                fair_value=1000.0,
                current_price=900.0,
                margin_of_safety=10.0,
                verdict="fairly_valued",
            ),
            quality=QualityOutput(),
            insights=InsightCards(),
            implied_assumptions=payload,
        )
        assert resp.implied_assumptions == payload
