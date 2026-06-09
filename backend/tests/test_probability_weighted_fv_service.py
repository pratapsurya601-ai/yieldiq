# backend/tests/test_probability_weighted_fv_service.py
# ═══════════════════════════════════════════════════════════════
# Unit tests for backend/services/probability_weighted_fv_service.py.
#
# T2.4 Phase A (2026-06-10). The service is pure dataclass + math, no
# DB / cache / external state, so the tests need no fixtures.
#
# Coverage matrix:
#   - Three-scenario default arithmetic (canonical 25/50/25 mix)
#   - Four-scenario with disaster slot
#   - Each adjustment lever in isolation:
#       * beta > 1.5 / beta < 0.7 / beta in middle
#       * cyclical sector vs not
#       * earnings revisions: upgrades / downgrades / mixed / None
#       * macro regime: contraction / expansion / neutral / None
#   - Adjustments chained (cyclical + downgrades + contraction)
#   - Override path bypasses the adjustment chain
#   - Invalid inputs: bear > base (warns), non-positive FV (unavailable)
#   - Expected-range threshold (the 0.20 bear/bull cut)
#   - to_dict shape + JSON-safety
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json

import pytest

from backend.services.probability_weighted_fv_service import (
    DEFAULT_WEIGHTS_THREE,
    ScenarioInputs,
    ScenarioWeights,
    adjust_weights_for_beta,
    adjust_weights_for_cyclical,
    adjust_weights_for_macro,
    adjust_weights_for_revisions,
    compute_default_weights,
    compute_probability_weighted_fv,
    to_dict,
)


# ─────────────────────────────────────────────────────────────────
# Helper assertions
# ─────────────────────────────────────────────────────────────────

def _weights_sum_to_one(w: ScenarioWeights, tol: float = 1e-9) -> bool:
    return abs(w.bull + w.base + w.bear + w.disaster - 1.0) <= tol


# ─────────────────────────────────────────────────────────────────
# compute_default_weights
# ─────────────────────────────────────────────────────────────────

class TestComputeDefaultWeights:
    def test_three_scenario_default(self):
        w = compute_default_weights(scenarios=3)
        assert w.bull == 0.25
        assert w.base == 0.50
        assert w.bear == 0.25
        assert w.disaster == 0.0
        assert _weights_sum_to_one(w)

    def test_four_scenario_default(self):
        w = compute_default_weights(scenarios=4)
        assert w.bull == 0.20
        assert w.base == 0.50
        assert w.bear == 0.25
        assert w.disaster == 0.05
        assert _weights_sum_to_one(w)

    def test_unknown_scenario_count_defaults_to_three(self):
        # Defensive — any other int should land on the three-scenario default.
        w = compute_default_weights(scenarios=7)
        assert w.bull == 0.25
        assert w.disaster == 0.0

    def test_returns_fresh_instance_not_module_constant(self):
        # Mutating the returned weights must not mutate the module constant.
        w = compute_default_weights(scenarios=3)
        w.bull = 0.99
        assert DEFAULT_WEIGHTS_THREE.bull == 0.25  # unchanged


# ─────────────────────────────────────────────────────────────────
# Headline three-scenario arithmetic
# ─────────────────────────────────────────────────────────────────

class TestThreeScenarioDefault:
    def test_canonical_25_50_25_mix(self):
        # 0.25*1500 + 0.50*1200 + 0.25*900 = 375 + 600 + 225 = 1200
        inputs = ScenarioInputs(bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0)
        result = compute_probability_weighted_fv(inputs)
        assert result.method == "three_scenario"
        assert result.weighted_fv is not None
        assert abs(result.weighted_fv - 1200.0) < 1e-6
        # No signals provided → weights remain at canonical default.
        assert result.weights.bull == 0.25
        assert result.weights.base == 0.50
        assert result.weights.bear == 0.25
        assert result.weights.disaster == 0.0

    def test_components_breakdown_shape(self):
        inputs = ScenarioInputs(bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0)
        result = compute_probability_weighted_fv(inputs)
        assert set(result.components.keys()) == {"bull", "base", "bear"}
        bull = result.components["bull"]
        assert bull["fv"] == 1500.0
        assert bull["weight"] == 0.25
        assert abs(bull["contribution"] - 375.0) < 1e-6
        # Sum of contributions equals weighted_fv.
        total = sum(c["contribution"] for c in result.components.values())
        assert abs(total - result.weighted_fv) < 1e-6

    def test_expected_range_returns_bear_and_bull_when_weights_above_threshold(self):
        inputs = ScenarioInputs(bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0)
        result = compute_probability_weighted_fv(inputs)
        p5, p95 = result.expected_range
        assert p5 == 900.0   # bear weight 0.25 >= 0.20 threshold
        assert p95 == 1500.0  # bull weight 0.25 >= 0.20 threshold


# ─────────────────────────────────────────────────────────────────
# Beta adjustment
# ─────────────────────────────────────────────────────────────────

class TestBetaAdjustment:
    def test_high_beta_widens_tails(self):
        # beta=2.0 should push bull +5pp, bear +5pp, base -10pp.
        # Starting from 0.25/0.50/0.25 → 0.30/0.40/0.30.
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_beta(start, beta=2.0)
        assert abs(adjusted.bull - 0.30) < 1e-6
        assert abs(adjusted.base - 0.40) < 1e-6
        assert abs(adjusted.bear - 0.30) < 1e-6
        assert _weights_sum_to_one(adjusted)

    def test_low_beta_tightens_tails(self):
        # beta=0.5 should push bull -5pp, bear -5pp, base +10pp.
        # Starting from 0.25/0.50/0.25 → 0.20/0.60/0.20.
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_beta(start, beta=0.5)
        assert abs(adjusted.bull - 0.20) < 1e-6
        assert abs(adjusted.base - 0.60) < 1e-6
        assert abs(adjusted.bear - 0.20) < 1e-6
        assert _weights_sum_to_one(adjusted)

    def test_midband_beta_unchanged(self):
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_beta(start, beta=1.0)
        assert adjusted.bull == 0.25
        assert adjusted.base == 0.50
        assert adjusted.bear == 0.25

    def test_none_beta_passthrough(self):
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_beta(start, beta=None)
        assert adjusted.bull == 0.25
        assert adjusted.base == 0.50
        assert adjusted.bear == 0.25

    def test_nan_beta_passthrough(self):
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_beta(start, beta=float("nan"))
        assert abs(adjusted.bull - 0.25) < 1e-9

    def test_non_numeric_beta_passthrough(self):
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_beta(start, beta="banana")  # type: ignore
        assert abs(adjusted.bull - 0.25) < 1e-9


# ─────────────────────────────────────────────────────────────────
# Cyclical sector adjustment
# ─────────────────────────────────────────────────────────────────

class TestCyclicalAdjustment:
    @pytest.mark.parametrize("sector", [
        "Metals & Mining",
        "Cement",
        "Auto",
        "Automobile",
        "Oil & Gas",
        "Realty",
        "Capital Goods",
        "metals",  # case-insensitive
    ])
    def test_cyclical_sectors_increase_bear(self, sector):
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_cyclical(start, sector=sector)
        # bear +5pp, base -5pp.
        assert abs(adjusted.bear - 0.30) < 1e-6
        assert abs(adjusted.base - 0.45) < 1e-6
        assert abs(adjusted.bull - 0.25) < 1e-6
        assert _weights_sum_to_one(adjusted)

    @pytest.mark.parametrize("sector", [
        "Information Technology",
        "FMCG",
        "Pharmaceuticals",
        "Banking",
        None,
        "",
    ])
    def test_non_cyclical_sectors_unchanged(self, sector):
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_cyclical(start, sector=sector)
        assert abs(adjusted.bear - 0.25) < 1e-9
        assert abs(adjusted.base - 0.50) < 1e-9
        assert abs(adjusted.bull - 0.25) < 1e-9


# ─────────────────────────────────────────────────────────────────
# Earnings revisions adjustment
# ─────────────────────────────────────────────────────────────────

class TestRevisionsAdjustment:
    def test_downgrades_shift_to_bear(self):
        # bear +10, bull -5, base -5 → 0.20/0.45/0.35.
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_revisions(start, revisions="downgrades")
        assert abs(adjusted.bull - 0.20) < 1e-6
        assert abs(adjusted.base - 0.45) < 1e-6
        assert abs(adjusted.bear - 0.35) < 1e-6
        assert _weights_sum_to_one(adjusted)

    def test_upgrades_shift_to_bull(self):
        # bull +5, bear -5 → 0.30/0.50/0.20.
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_revisions(start, revisions="upgrades")
        assert abs(adjusted.bull - 0.30) < 1e-6
        assert abs(adjusted.base - 0.50) < 1e-6
        assert abs(adjusted.bear - 0.20) < 1e-6

    @pytest.mark.parametrize("revisions", ["mixed", None, "unknown", ""])
    def test_mixed_or_none_unchanged(self, revisions):
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_revisions(start, revisions=revisions)
        assert abs(adjusted.bull - 0.25) < 1e-9
        assert abs(adjusted.base - 0.50) < 1e-9
        assert abs(adjusted.bear - 0.25) < 1e-9

    def test_case_insensitive(self):
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_revisions(start, revisions="DOWNGRADES")
        assert abs(adjusted.bear - 0.35) < 1e-6


# ─────────────────────────────────────────────────────────────────
# Macro regime adjustment
# ─────────────────────────────────────────────────────────────────

class TestMacroAdjustment:
    def test_contraction_shifts_to_bear(self):
        # bear +10, bull -5, base -5 → 0.20/0.45/0.35.
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_macro(start, macro_regime="contraction")
        assert abs(adjusted.bull - 0.20) < 1e-6
        assert abs(adjusted.base - 0.45) < 1e-6
        assert abs(adjusted.bear - 0.35) < 1e-6
        assert _weights_sum_to_one(adjusted)

    def test_expansion_shifts_to_bull(self):
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_macro(start, macro_regime="expansion")
        assert abs(adjusted.bull - 0.30) < 1e-6
        assert abs(adjusted.bear - 0.20) < 1e-6

    @pytest.mark.parametrize("regime", ["neutral", None, "unknown", ""])
    def test_neutral_or_none_unchanged(self, regime):
        start = compute_default_weights(scenarios=3)
        adjusted = adjust_weights_for_macro(start, macro_regime=regime)
        assert abs(adjusted.bull - 0.25) < 1e-9
        assert abs(adjusted.bear - 0.25) < 1e-9


# ─────────────────────────────────────────────────────────────────
# End-to-end signal-driven adjustments
# ─────────────────────────────────────────────────────────────────

class TestEndToEndSignalChain:
    def test_high_beta_adjustment_via_compute(self):
        inputs = ScenarioInputs(
            bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0, beta=2.0,
        )
        result = compute_probability_weighted_fv(inputs)
        # Bear weight should be lifted vs. 0.25 default.
        assert result.weights.bear > 0.25
        assert result.weights.bull > 0.25
        assert _weights_sum_to_one(result.weights)

    def test_cyclical_sector_via_compute(self):
        inputs = ScenarioInputs(
            bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0, sector="Metals & Mining",
        )
        result = compute_probability_weighted_fv(inputs)
        assert result.weights.bear > 0.25  # cyclical lifts bear

    def test_downgrades_via_compute(self):
        inputs = ScenarioInputs(
            bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0,
            recent_earnings_revisions="downgrades",
        )
        result = compute_probability_weighted_fv(inputs)
        # bear=0.25+0.10 → 0.35.
        assert abs(result.weights.bear - 0.35) < 1e-6

    def test_macro_contraction_via_compute(self):
        inputs = ScenarioInputs(
            bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0, macro_regime="contraction",
        )
        result = compute_probability_weighted_fv(inputs)
        assert abs(result.weights.bear - 0.35) < 1e-6

    def test_all_three_bear_signals_chained_lifts_bear_near_half(self):
        # cyclical (+5) + downgrades (+10) + contraction (+10) starting
        # from bear=0.25 → expected near 0.50 after renormalization.
        # Pre-normalization:
        #   bull=0.25 - 0.05 - 0.05 = 0.15
        #   base=0.50 - 0.05 - 0.05 - 0.05 = 0.35
        #   bear=0.25 + 0.05 + 0.10 + 0.10 = 0.50
        # These already sum to 1.0, so the bear slot stays at 0.50.
        inputs = ScenarioInputs(
            bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0,
            sector="Auto",
            recent_earnings_revisions="downgrades",
            macro_regime="contraction",
        )
        result = compute_probability_weighted_fv(inputs)
        assert result.weights.bear >= 0.45  # near 0.50 — allow tolerance
        # Weighted FV pulls toward the bear case.
        # weighted_fv = 1500*0.15 + 1200*0.35 + 900*0.50
        #             =  225  +  420  + 450 = 1095
        assert result.weighted_fv is not None
        assert result.weighted_fv < 1200.0  # below base
        assert abs(result.weighted_fv - 1095.0) < 5.0


# ─────────────────────────────────────────────────────────────────
# Four-scenario path
# ─────────────────────────────────────────────────────────────────

class TestFourScenario:
    def test_four_scenario_with_disaster(self):
        # Default 20/50/25/5 weighting on 1500/1200/900/500 →
        #   0.20*1500 + 0.50*1200 + 0.25*900 + 0.05*500
        # = 300 + 600 + 225 + 25 = 1150.
        inputs = ScenarioInputs(
            bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0, disaster_fv=500.0,
        )
        result = compute_probability_weighted_fv(inputs)
        assert result.method == "four_scenario"
        assert result.weighted_fv is not None
        assert abs(result.weighted_fv - 1150.0) < 1e-6
        assert result.weights.disaster == 0.05
        # components includes disaster.
        assert "disaster" in result.components
        assert result.components["disaster"]["fv"] == 500.0
        assert abs(result.components["disaster"]["contribution"] - 25.0) < 1e-6

    def test_disaster_fv_non_positive_falls_back_to_three_scenario(self):
        inputs = ScenarioInputs(
            bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0, disaster_fv=-100.0,
        )
        result = compute_probability_weighted_fv(inputs)
        assert result.method == "three_scenario"
        assert "disaster" not in result.components


# ─────────────────────────────────────────────────────────────────
# Override path
# ─────────────────────────────────────────────────────────────────

class TestWeightOverrides:
    def test_override_bypasses_adjustment_chain(self):
        # Use 50/50 bull/base — high-beta signal would normally widen
        # tails, but the override pins the weights.
        override = ScenarioWeights(bull=0.50, base=0.50, bear=0.0)
        inputs = ScenarioInputs(
            bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0,
            beta=2.0,            # would normally lift bear
            sector="Metals",     # would normally lift bear
            recent_earnings_revisions="downgrades",
            macro_regime="contraction",
        )
        result = compute_probability_weighted_fv(inputs, weight_overrides=override)
        # Weights match the override (after normalize).
        assert abs(result.weights.bull - 0.50) < 1e-6
        assert abs(result.weights.base - 0.50) < 1e-6
        assert abs(result.weights.bear - 0.0) < 1e-6
        # Weighted FV = 0.5*1500 + 0.5*1200 = 1350.
        assert abs(result.weighted_fv - 1350.0) < 1e-6

    def test_override_with_unnormalized_weights_gets_normalized(self):
        # 1/2/1 unnormalized → 0.25/0.50/0.25 after renormalize.
        override = ScenarioWeights(bull=1.0, base=2.0, bear=1.0)
        inputs = ScenarioInputs(bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0)
        result = compute_probability_weighted_fv(inputs, weight_overrides=override)
        assert abs(result.weights.bull - 0.25) < 1e-6
        assert abs(result.weights.base - 0.50) < 1e-6
        assert abs(result.weights.bear - 0.25) < 1e-6


# ─────────────────────────────────────────────────────────────────
# Invalid / degenerate inputs
# ─────────────────────────────────────────────────────────────────

class TestSanityWarnings:
    def test_bear_greater_than_base_emits_warning_but_still_computes(self):
        inputs = ScenarioInputs(bull_fv=1500.0, base_fv=1000.0, bear_fv=1100.0)
        result = compute_probability_weighted_fv(inputs)
        assert any("bear > base" in w for w in result.sanity_warnings)
        # Still computes a weighted FV.
        assert result.weighted_fv is not None

    def test_bull_less_than_base_emits_warning(self):
        inputs = ScenarioInputs(bull_fv=900.0, base_fv=1000.0, bear_fv=800.0)
        result = compute_probability_weighted_fv(inputs)
        assert any("bull < base" in w for w in result.sanity_warnings)

    def test_disaster_greater_than_bear_emits_warning(self):
        inputs = ScenarioInputs(
            bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0, disaster_fv=950.0,
        )
        result = compute_probability_weighted_fv(inputs)
        assert any("disaster > bear" in w for w in result.sanity_warnings)

    def test_wide_spread_warning(self):
        # spread = 2500 - 100 = 2400; base = 1200; ratio = 200% > 100%.
        inputs = ScenarioInputs(bull_fv=2500.0, base_fv=1200.0, bear_fv=100.0)
        result = compute_probability_weighted_fv(inputs)
        assert any("spread > 100%" in w for w in result.sanity_warnings)

    def test_narrow_spread_warning(self):
        # spread = 1210 - 1200 = 10; base = 1200; ratio = 0.8% < 10%.
        inputs = ScenarioInputs(bull_fv=1210.0, base_fv=1200.0, bear_fv=1190.0)
        result = compute_probability_weighted_fv(inputs)
        assert any("spread < 10%" in w for w in result.sanity_warnings)

    def test_no_warnings_on_clean_inputs(self):
        inputs = ScenarioInputs(bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0)
        result = compute_probability_weighted_fv(inputs)
        assert result.sanity_warnings == []


class TestUnavailableInputs:
    def test_zero_base_fv_unavailable(self):
        inputs = ScenarioInputs(bull_fv=1500.0, base_fv=0.0, bear_fv=900.0)
        result = compute_probability_weighted_fv(inputs)
        assert result.method == "unavailable"
        assert result.weighted_fv is None
        assert result.components == {}
        assert result.expected_range == (None, None)

    def test_negative_bear_unavailable(self):
        inputs = ScenarioInputs(bull_fv=1500.0, base_fv=1200.0, bear_fv=-100.0)
        result = compute_probability_weighted_fv(inputs)
        assert result.method == "unavailable"
        assert result.weighted_fv is None

    def test_none_bull_unavailable(self):
        # Direct None can't be passed to the float-typed field — but
        # the coercer also drops NaN.
        inputs = ScenarioInputs(bull_fv=float("nan"), base_fv=1200.0, bear_fv=900.0)
        result = compute_probability_weighted_fv(inputs)
        assert result.method == "unavailable"
        assert result.weighted_fv is None


# ─────────────────────────────────────────────────────────────────
# Expected range threshold
# ─────────────────────────────────────────────────────────────────

class TestExpectedRange:
    def test_low_bear_weight_pulls_p5_toward_base(self):
        # Override the weights so bear weight < 0.20 and p5 interpolates
        # toward base. weights: bull=0.40, base=0.50, bear=0.10.
        override = ScenarioWeights(bull=0.40, base=0.50, bear=0.10)
        inputs = ScenarioInputs(bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0)
        result = compute_probability_weighted_fv(inputs, weight_overrides=override)
        p5, p95 = result.expected_range
        # bear_w=0.10 / 0.20 = 0.5 → p5 = 1200 + 0.5*(900-1200) = 1050.
        assert abs(p5 - 1050.0) < 1e-6
        # bull_w=0.40 >= 0.20 → p95 = 1500.
        assert abs(p95 - 1500.0) < 1e-6

    def test_low_bull_weight_pulls_p95_toward_base(self):
        override = ScenarioWeights(bull=0.10, base=0.50, bear=0.40)
        inputs = ScenarioInputs(bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0)
        result = compute_probability_weighted_fv(inputs, weight_overrides=override)
        p5, p95 = result.expected_range
        assert abs(p5 - 900.0) < 1e-6
        # bull_w=0.10 / 0.20 = 0.5 → p95 = 1200 + 0.5*(1500-1200) = 1350.
        assert abs(p95 - 1350.0) < 1e-6


# ─────────────────────────────────────────────────────────────────
# to_dict
# ─────────────────────────────────────────────────────────────────

class TestToDict:
    def test_to_dict_shape(self):
        inputs = ScenarioInputs(bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0)
        result = compute_probability_weighted_fv(inputs)
        d = to_dict(result)
        assert set(d.keys()) == {
            "weighted_fv", "method", "weights", "components",
            "expected_range", "sanity_warnings",
        }
        assert d["weighted_fv"] == result.weighted_fv
        assert d["method"] == "three_scenario"
        assert set(d["weights"].keys()) == {"bull", "base", "bear", "disaster"}
        assert d["weights"]["bull"] == 0.25
        # Expected range is a 2-element list (JSON-safe), not a tuple.
        assert isinstance(d["expected_range"], list)
        assert len(d["expected_range"]) == 2

    def test_to_dict_is_json_serializable(self):
        inputs = ScenarioInputs(
            bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0, disaster_fv=500.0,
        )
        result = compute_probability_weighted_fv(inputs)
        d = to_dict(result)
        # round-trip through json.
        wire = json.dumps(d)
        loaded = json.loads(wire)
        assert loaded["method"] == "four_scenario"
        assert loaded["weights"]["disaster"] == 0.05

    def test_to_dict_for_unavailable(self):
        inputs = ScenarioInputs(bull_fv=0.0, base_fv=0.0, bear_fv=0.0)
        result = compute_probability_weighted_fv(inputs)
        d = to_dict(result)
        assert d["weighted_fv"] is None
        assert d["method"] == "unavailable"
        assert d["components"] == {}
        assert d["expected_range"] == [None, None]


# ─────────────────────────────────────────────────────────────────
# Sanity — weights ALWAYS sum to 1.0 (or 0.0 when unavailable)
# ─────────────────────────────────────────────────────────────────

class TestInvariants:
    @pytest.mark.parametrize("beta", [0.3, 0.5, 1.0, 1.5, 2.0, 3.0])
    @pytest.mark.parametrize("sector", ["Metals", "IT", None])
    @pytest.mark.parametrize("revisions", ["upgrades", "downgrades", "mixed", None])
    @pytest.mark.parametrize("macro", ["expansion", "contraction", "neutral", None])
    def test_weights_always_sum_to_one(self, beta, sector, revisions, macro):
        # Coverage sweep — every combination of signals.
        inputs = ScenarioInputs(
            bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0,
            beta=beta, sector=sector,
            recent_earnings_revisions=revisions, macro_regime=macro,
        )
        result = compute_probability_weighted_fv(inputs)
        # Defensive — should never happen with the canonical inputs.
        assert result.method != "unavailable"
        assert _weights_sum_to_one(result.weights, tol=1e-9), (
            f"weights do not sum to 1: {result.weights}"
        )

    def test_weighted_fv_within_bear_bull_range(self):
        # Expected value of any positively-weighted mix of (bear, base, bull)
        # must lie between bear and bull.
        inputs = ScenarioInputs(bull_fv=1500.0, base_fv=1200.0, bear_fv=900.0)
        result = compute_probability_weighted_fv(inputs)
        assert result.weighted_fv is not None
        assert 900.0 <= result.weighted_fv <= 1500.0


# ─────────────────────────────────────────────────────────────────
# Dataclass smoke
# ─────────────────────────────────────────────────────────────────

class TestDataclassSmoke:
    def test_scenario_inputs_minimum_fields(self):
        # All optional signal fields default to None.
        inputs = ScenarioInputs(bull_fv=1.0, base_fv=1.0, bear_fv=1.0)
        assert inputs.disaster_fv is None
        assert inputs.sector is None
        assert inputs.beta is None
        assert inputs.recent_earnings_revisions is None
        assert inputs.macro_regime is None

    def test_scenario_weights_disaster_defaults_zero(self):
        w = ScenarioWeights(bull=0.3, base=0.4, bear=0.3)
        assert w.disaster == 0.0
        assert w.as_tuple() == (0.3, 0.4, 0.3, 0.0)
