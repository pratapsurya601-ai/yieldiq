# backend/tests/test_phase_b_estimator_surfacing.py
# ═══════════════════════════════════════════════════════════════
# Phase B — additive standalone-estimator surfacing (2026-06-10).
#
# Tests the five inject helpers added to backend/routers/analysis.py
# that populate ddm_fv, epv_per_share, three_stage_fv,
# liquidation_per_share, and probability_weighted_fv on the
# AnalysisResponse payload.
#
# Critical invariants we verify:
#   1. Each inject attaches the expected field(s) when prerequisites
#      are present.
#   2. Each inject leaves field=None when prerequisites are missing
#      (bank ticker -> no liquidation, no dividends -> no DDM, etc).
#   3. Each inject NEVER raises — bad payloads degrade to None.
#   4. The full chain (composite + 5 estimators) leaves
#      composite_intrinsic_value byte-identical to the composite-only
#      pre-Phase-B output. The Phase-B changes are PURELY additive.
#   5. SEBI vocab guard — built from fragments per CLAUDE.md rule #5
#      (the file is scanned in --diff-only mode; literal banned words
#      in added lines fail the lint even inside test assertions).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import copy
import pytest

from backend.routers.analysis import (
    _inject_composite_iv_dict,
    _inject_ddm_dict,
    _inject_epv_dict,
    _inject_liquidation_dict,
    _inject_multiples_fv_dict,
    _inject_phase_b_estimators_dict,
    _inject_probability_weighted_dict,
    _inject_three_stage_dict,
)


# ─────────────────────────────────────────────────────────────────
# Fixture builders — hand-built payloads matching the
# AnalysisResponse dict shape the cache paths surface.
# ─────────────────────────────────────────────────────────────────


def _payload_ddm_eligible() -> dict:
    """Mature FMCG-shaped payload that should trigger Gordon DDM.

    Uses the CANONICAL AnalysisResponse shape — `payout_ratio_pct` on
    DividendData (60.0 not 0.60), `consecutive_years` on DividendData,
    `wacc` on ValuationOutput. The inject derives the decimal payout
    from the pct field.

    Payout 60%, dividend streak 15y, FMCG sector — sails through
    is_ddm_applicable cleanly. Dividend ₹20/share, k=11.5%, g=4% ->
    Gordon FV = 20 * 1.04 / (0.115 - 0.04) = ₹277.33/share.
    """
    return {
        "ticker": "HINDUNILVR",
        "company": {
            "ticker": "HINDUNILVR",
            "sector": "FMCG",
            "industry": "Personal Care",
        },
        "quality": {
            "is_bank": False,
            "is_holdco": False,
            "beta": 0.7,
            "shares_outstanding": 100_000_000,
        },
        "valuation": {
            "fair_value": 2500.0,
            "current_price": 2300.0,
            "bull_case": 3000.0,
            "base_case": 2500.0,
            "bear_case": 2000.0,
            "wacc": 0.115,
            "discount_rate": 0.115,
            "terminal_growth": 0.04,
            "fcf_growth_rate": 0.10,
            "valuation_model": "dcf",
        },
        "insights": {
            "dividend": {
                "dividend_rate_per_share": 20.0,
                "consecutive_years": 15,
                "payout_ratio_pct": 60.0,
            },
        },
    }


def _payload_ddm_ineligible_low_payout() -> dict:
    """Same shape but payout drops to 5% — should skip DDM.

    Pure growth stock — most of shareholder return comes from
    retention, not dividends. DDM understates FV badly.
    """
    p = _payload_ddm_eligible()
    p["insights"]["dividend"]["payout_ratio_pct"] = 5.0
    p["company"]["sector"] = "Information Technology"  # also IT-heavy
    return p


def _payload_ddm_ineligible_short_streak() -> dict:
    """Payout fine but streak < 5y — should skip DDM."""
    p = _payload_ddm_eligible()
    p["insights"]["dividend"]["consecutive_years"] = 2
    return p


def _payload_liquidation_eligible_metals() -> dict:
    """Asset-heavy metals ticker with balance-sheet snapshot.

    Should produce a meaningful liquidation_per_share. PP&E 100 +
    cash 50 + receivables 30 + inventory 20 = ₹200 gross assets at
    metals (0.55 PPE recovery), 100M shares.
    """
    return {
        "ticker": "TATASTEEL",
        "company": {"ticker": "TATASTEEL", "sector": "metals"},
        "quality": {
            "is_bank": False,
            "is_holdco": False,
            "shares_outstanding": 100_000_000,
            "beta": 1.4,
        },
        "valuation": {
            "fair_value": 150.0,
            "current_price": 120.0,
            "bull_case": 180.0,
            "base_case": 150.0,
            "bear_case": 110.0,
            "wacc": 0.13,
            "terminal_growth": 0.04,
            "fcf_growth_rate": 0.08,
        },
        "insights": {},
        "computation_inputs": {
            "liquidation": {
                "cash_and_equivalents": 50.0,
                "short_term_investments": 0.0,
                "receivables": 30.0,
                "inventory": 20.0,
                "ppe_net": 100.0,
                "intangibles": 0.0,
                "goodwill": 0.0,
                "long_term_investments": 0.0,
                "other_assets": 5.0,
                "short_term_debt": 5.0,
                "long_term_debt": 30.0,
                "accounts_payable": 10.0,
                "other_liabilities": 5.0,
                "shares_outstanding": 100_000_000,
            },
        },
    }


def _payload_liquidation_skip_bank() -> dict:
    """Bank ticker — liquidation should always be None (capital-adequacy
    framework applies, NOT asset-recovery)."""
    p = _payload_liquidation_eligible_metals()
    p["ticker"] = "HDFCBANK"
    p["company"]["sector"] = "bank"
    p["quality"]["is_bank"] = True
    return p


def _payload_epv_eligible() -> dict:
    """5+ years of stable EBIT history — EPV is applicable."""
    return {
        "ticker": "ITC",
        "company": {"ticker": "ITC", "sector": "FMCG"},
        "quality": {
            "is_bank": False,
            "shares_outstanding": 1_200_000_000,
            "payout_ratio": 0.85,
            "dividend_streak_years": 20,
            "beta": 0.7,
        },
        "valuation": {
            "fair_value": 500.0,
            "current_price": 450.0,
            "bull_case": 600.0,
            "base_case": 500.0,
            "bear_case": 400.0,
            "wacc": 0.12,
            "discount_rate": 0.12,
            "terminal_growth": 0.04,
            "fcf_growth_rate": 0.08,
        },
        "insights": {},
        "computation_inputs": {
            "epv": {
                "revenue_history": [600.0, 650.0, 700.0, 720.0, 760.0, 800.0],
                "ebit_history": [180.0, 200.0, 220.0, 230.0, 245.0, 260.0],
                "da_history": [30.0, 32.0, 35.0, 36.0, 38.0, 40.0],
                "capex_history": [40.0, 42.0, 45.0, 46.0, 48.0, 50.0],
                "working_capital_history": [60.0, 64.0, 70.0, 72.0, 76.0, 80.0],
                "current_revenue": 800.0,
                "tax_rate": 0.25,
                "shares_outstanding": 1_200_000_000,
            },
        },
    }


def _payload_epv_ineligible_recent_ipo() -> dict:
    """Recent IPO — only 2y history, EPV should not fire."""
    p = _payload_epv_eligible()
    p["ticker"] = "FRESH_IPO"
    p["computation_inputs"]["epv"]["revenue_history"] = [600.0, 650.0]
    p["computation_inputs"]["epv"]["ebit_history"] = [180.0, 200.0]
    return p


def _payload_three_stage_eligible() -> dict:
    """Positive base FCF + non-skip sector — three-stage should fire."""
    return {
        "ticker": "INFY",
        "company": {"ticker": "INFY", "sector": "Information Technology"},
        "quality": {
            "is_bank": False,
            "is_holdco": False,
            "normalized_fcf_cr": 200.0,
            "shares_outstanding": 4_000_000_000,
            "net_debt": -300.0,  # net cash
            "payout_ratio": 0.50,
            "dividend_streak_years": 10,
            "beta": 0.8,
        },
        "valuation": {
            "fair_value": 1600.0,
            "current_price": 1500.0,
            "bull_case": 1800.0,
            "base_case": 1600.0,
            "bear_case": 1400.0,
            "wacc": 0.115,
            "discount_rate": 0.115,
            "terminal_growth": 0.04,
            "fcf_growth_rate": 0.10,
        },
        "insights": {},
    }


def _payload_three_stage_holdco_skip() -> dict:
    """Holdco — three-stage should skip (SOTP is the right framework)."""
    p = _payload_three_stage_eligible()
    p["ticker"] = "BAJAJHLDNG"
    p["company"]["sector"] = "Diversified Holding"
    p["quality"]["is_holdco"] = True
    return p


def _payload_prob_weighted_eligible() -> dict:
    """All three scenarios positive — probability-weighted should fire."""
    return {
        "ticker": "RELIANCE",
        "company": {"ticker": "RELIANCE", "sector": "Oil & Gas"},
        "quality": {
            "is_bank": False,
            "beta": 1.1,
        },
        "valuation": {
            "fair_value": 2800.0,
            "current_price": 2600.0,
            "bull_case": 3200.0,
            "base_case": 2800.0,
            "bear_case": 2200.0,
            "wacc": 0.13,
            "terminal_growth": 0.04,
            "fcf_growth_rate": 0.09,
        },
        "insights": {},
    }


def _payload_prob_weighted_missing_bear() -> dict:
    """Bear case = 0 — probability-weighted should skip."""
    p = _payload_prob_weighted_eligible()
    p["valuation"]["bear_case"] = 0
    return p


# ─────────────────────────────────────────────────────────────────
# DDM
# ─────────────────────────────────────────────────────────────────


class TestDDMInject:
    """Coverage for ``_inject_ddm_dict`` — DDM standalone surfacing."""

    def test_eligible_fmcg_attaches_gordon_fv(self):
        p = _payload_ddm_eligible()
        _inject_ddm_dict(p)
        assert p.get("ddm_fv") is not None
        # Gordon: 20 * (1+0.04) / (0.115-0.04) ≈ 277.33
        assert abs(p["ddm_fv"] - 277.33) < 1.0
        # FMCG routes to Gordon by sector heuristic.
        assert p.get("ddm_method") == "gordon"

    def test_low_payout_leaves_fields_none(self):
        p = _payload_ddm_ineligible_low_payout()
        _inject_ddm_dict(p)
        assert p.get("ddm_fv") is None
        assert p.get("ddm_method") is None

    def test_short_streak_leaves_fields_none(self):
        p = _payload_ddm_ineligible_short_streak()
        _inject_ddm_dict(p)
        assert p.get("ddm_fv") is None
        assert p.get("ddm_method") is None

    def test_never_raises_on_bad_payload(self):
        # Intentionally bad: missing every section.
        bad = {"ticker": "X"}
        _inject_ddm_dict(bad)
        # Field absence is fine — what matters is no exception.
        assert bad.get("ddm_fv") is None

    def test_never_raises_on_garbage_types(self):
        garbage = {"ticker": "X", "quality": "not a dict", "valuation": 42}
        _inject_ddm_dict(garbage)
        assert garbage.get("ddm_fv") is None

    def test_non_dict_payload_returns_unchanged(self):
        # Guard against the cache-tier pre-condition handler.
        out = _inject_ddm_dict("not a dict")  # type: ignore[arg-type]
        assert out == "not a dict"


# ─────────────────────────────────────────────────────────────────
# EPV
# ─────────────────────────────────────────────────────────────────


class TestEPVInject:
    """Coverage for ``_inject_epv_dict`` — EPV (Greenwald) surfacing."""

    def test_eligible_attaches_per_share_and_gap(self):
        p = _payload_epv_eligible()
        _inject_epv_dict(p)
        assert p.get("epv_per_share") is not None
        # Sanity range — should be a positive per-share number, not 0.
        assert p["epv_per_share"] > 0
        # Growth-value gap = DCF FV (500) - EPV per share. Sign agnostic.
        assert p.get("epv_growth_value_gap") is not None

    def test_recent_ipo_leaves_fields_none(self):
        p = _payload_epv_ineligible_recent_ipo()
        _inject_epv_dict(p)
        assert p.get("epv_per_share") is None
        assert p.get("epv_growth_value_gap") is None

    def test_missing_computation_inputs_leaves_fields_none(self):
        # No `computation_inputs` block — cache paths that don't snapshot
        # EPV inputs surface None cleanly.
        p = _payload_ddm_eligible()
        _inject_epv_dict(p)
        assert p.get("epv_per_share") is None

    def test_never_raises_on_bad_payload(self):
        bad = {"ticker": "X", "computation_inputs": "not a dict"}
        _inject_epv_dict(bad)
        assert bad.get("epv_per_share") is None

    def test_non_dict_payload_returns_unchanged(self):
        out = _inject_epv_dict(None)  # type: ignore[arg-type]
        assert out is None


# ─────────────────────────────────────────────────────────────────
# Three-stage DCF
# ─────────────────────────────────────────────────────────────────


class TestThreeStageInject:
    """Coverage for ``_inject_three_stage_dict``."""

    def test_eligible_attaches_fv_and_method(self):
        p = _payload_three_stage_eligible()
        _inject_three_stage_dict(p)
        assert p.get("three_stage_fv") is not None
        # IT services routes to (7, 5) horizons — explicit window is wider.
        assert p["three_stage_fv"] > 0
        assert p.get("three_stage_method") == "three_stage_dcf"

    def test_holdco_skips_with_none(self):
        p = _payload_three_stage_holdco_skip()
        _inject_three_stage_dict(p)
        assert p.get("three_stage_fv") is None
        assert p.get("three_stage_method") is None

    def test_missing_base_fcf_leaves_fields_none(self):
        p = _payload_three_stage_eligible()
        p["quality"]["normalized_fcf_cr"] = None
        # No fallback computation_inputs either.
        _inject_three_stage_dict(p)
        assert p.get("three_stage_fv") is None

    def test_never_raises_on_bad_payload(self):
        bad = {"ticker": "X", "valuation": None, "quality": None}
        _inject_three_stage_dict(bad)
        assert bad.get("three_stage_fv") is None

    def test_non_dict_payload_returns_unchanged(self):
        out = _inject_three_stage_dict(42)  # type: ignore[arg-type]
        assert out == 42


# ─────────────────────────────────────────────────────────────────
# Liquidation
# ─────────────────────────────────────────────────────────────────


class TestLiquidationInject:
    """Coverage for ``_inject_liquidation_dict``."""

    def test_eligible_metals_attaches_per_share_and_margin(self):
        p = _payload_liquidation_eligible_metals()
        _inject_liquidation_dict(p)
        assert p.get("liquidation_per_share") is not None
        # Should compute SOMETHING — sign-agnostic; the metals fixture
        # has limited assets so per-share may be small or negative
        # depending on the recovery math. What matters is it's not None.
        assert isinstance(p["liquidation_per_share"], (int, float))
        # floor_safety_margin = current_price (120) - per_share
        assert p.get("liquidation_floor_safety_margin") is not None

    def test_bank_skips_with_none(self):
        p = _payload_liquidation_skip_bank()
        _inject_liquidation_dict(p)
        assert p.get("liquidation_per_share") is None
        assert p.get("liquidation_floor_safety_margin") is None

    def test_missing_balance_sheet_leaves_fields_none(self):
        p = _payload_liquidation_eligible_metals()
        del p["computation_inputs"]
        _inject_liquidation_dict(p)
        assert p.get("liquidation_per_share") is None

    def test_it_services_skips_with_none(self):
        # Asset-light cohort — is_liquidation_meaningful returns False
        # via the sector-level IT-services fallback.
        p = _payload_liquidation_eligible_metals()
        p["company"]["sector"] = "it services"
        _inject_liquidation_dict(p)
        assert p.get("liquidation_per_share") is None

    def test_never_raises_on_bad_payload(self):
        bad = {"ticker": "X", "computation_inputs": {"liquidation": "garbage"}}
        _inject_liquidation_dict(bad)
        assert bad.get("liquidation_per_share") is None


# ─────────────────────────────────────────────────────────────────
# Probability-weighted FV
# ─────────────────────────────────────────────────────────────────


class TestProbabilityWeightedInject:
    """Coverage for ``_inject_probability_weighted_dict``."""

    def test_three_scenario_attaches_weighted_fv(self):
        p = _payload_prob_weighted_eligible()
        _inject_probability_weighted_dict(p)
        assert p.get("probability_weighted_fv") is not None
        # Should land BETWEEN bear (2200) and bull (3200) — the
        # weighted mix can never escape the scenario hull.
        assert 2200 <= p["probability_weighted_fv"] <= 3200
        assert p.get("probability_weighted_method") == "three_scenario"

    def test_missing_bear_leaves_fields_none(self):
        p = _payload_prob_weighted_missing_bear()
        _inject_probability_weighted_dict(p)
        assert p.get("probability_weighted_fv") is None
        assert p.get("probability_weighted_method") is None

    def test_garbage_scenario_values_leave_fields_none(self):
        p = _payload_prob_weighted_eligible()
        p["valuation"]["bull_case"] = "not a number"
        _inject_probability_weighted_dict(p)
        assert p.get("probability_weighted_fv") is None

    def test_never_raises_on_bad_payload(self):
        bad = {"ticker": "X"}
        _inject_probability_weighted_dict(bad)
        assert bad.get("probability_weighted_fv") is None

    def test_non_dict_payload_returns_unchanged(self):
        out = _inject_probability_weighted_dict([])  # type: ignore[arg-type]
        assert out == []


# ─────────────────────────────────────────────────────────────────
# Composite invariant — Phase B is purely additive
# ─────────────────────────────────────────────────────────────────


class TestCompositeByteIdenticalInvariant:
    """The CRITICAL Phase-B invariant.

    ``composite_intrinsic_value`` MUST be byte-identical pre and post
    Phase-B injects. The Phase-A canary baseline was refreshed on PR
    #794; the composite weight set has NOT changed in Phase B — only
    new fields have been added.

    These tests build a payload, run the multiples + composite
    injects, snapshot the composite, then run the 5 new estimators on
    top and confirm the composite is unchanged.
    """

    def _payload_with_multiples_for_composite(self) -> dict:
        """Pre-multiples-injected payload that the composite path can read."""
        return {
            "ticker": "INFY",
            "company": {"ticker": "INFY", "sector": "Information Technology"},
            "quality": {
                "is_bank": False,
                "is_holdco": False,
                "pe_ratio": 28.0,
                "pb_ratio": 7.0,
                "payout_ratio": 0.50,
                "dividend_streak_years": 10,
                "beta": 0.8,
            },
            "valuation": {
                "fair_value": 1700.0,
                "current_price": 1500.0,
                "bull_case": 1900.0,
                "base_case": 1700.0,
                "bear_case": 1400.0,
                "wacc": 0.115,
                "terminal_growth": 0.04,
                "fcf_growth_rate": 0.10,
            },
            "insights": {
                "wall_street_avg_target": 1650.0,
                "analyst_consensus": {
                    "price_target": {"mean": 1650.0},
                },
            },
            "sector_medians": {
                "pe": 25.0,
                "pb": 6.0,
            },
        }

    def test_composite_unchanged_after_phase_b_injects(self):
        # Snapshot the composite-only result.
        p1 = self._payload_with_multiples_for_composite()
        _inject_multiples_fv_dict(p1)
        _inject_composite_iv_dict(p1)
        composite_before = p1.get("composite_intrinsic_value")
        components_before = copy.deepcopy(p1.get("composite_components"))
        multiples_before = p1.get("multiples_based_fv")
        # Now run the FULL Phase-B chain.
        p2 = self._payload_with_multiples_for_composite()
        _inject_multiples_fv_dict(p2)
        _inject_composite_iv_dict(p2)
        _inject_phase_b_estimators_dict(p2)
        # Composite + components + multiples remain byte-identical.
        assert p2.get("composite_intrinsic_value") == composite_before
        assert p2.get("composite_components") == components_before
        assert p2.get("multiples_based_fv") == multiples_before

    def test_phase_b_chain_attaches_new_fields_without_touching_old(self):
        p = self._payload_with_multiples_for_composite()
        # Snapshot every pre-existing key.
        keys_before = set(p.keys())
        _inject_multiples_fv_dict(p)
        _inject_composite_iv_dict(p)
        _inject_phase_b_estimators_dict(p)
        # The Phase-B injects added exactly the 10 new fields plus the
        # composite + multiples ones — but never mutated existing
        # AnalysisResponse fields like fair_value / current_price /
        # bull_case / bear_case.
        assert p["valuation"]["fair_value"] == 1700.0
        assert p["valuation"]["current_price"] == 1500.0
        assert p["valuation"]["bull_case"] == 1900.0
        assert p["valuation"]["bear_case"] == 1400.0
        # And the 10 new fields are all present (None or value).
        for field_name in (
            "ddm_fv",
            "ddm_method",
            "epv_per_share",
            "epv_growth_value_gap",
            "three_stage_fv",
            "three_stage_method",
            "liquidation_per_share",
            "liquidation_floor_safety_margin",
            "probability_weighted_fv",
            "probability_weighted_method",
        ):
            assert field_name in p, f"Phase-B field '{field_name}' missing after inject chain"


# ─────────────────────────────────────────────────────────────────
# Full-chain integration smoke test
# ─────────────────────────────────────────────────────────────────


class TestFullChainSmoke:
    """End-to-end: run sector_medians + multiples + composite + Phase-B
    on a representative payload and confirm nothing raises."""

    def test_full_chain_on_fmcg_payload(self):
        p = _payload_ddm_eligible()
        # Add multiples + sector medians + analyst slots that the
        # composite chain reads.
        p["sector_medians"] = {"pe": 50.0, "pb": 12.0}
        p["quality"]["pe_ratio"] = 55.0
        p["quality"]["pb_ratio"] = 14.0
        p["insights"]["analyst_consensus"] = {
            "price_target": {"mean": 2400.0},
        }
        _inject_multiples_fv_dict(p)
        _inject_composite_iv_dict(p)
        _inject_phase_b_estimators_dict(p)
        # FMCG-eligible DDM should fire.
        assert p.get("ddm_fv") is not None
        # Composite still populated by DCF + Multiples + Wall St.
        assert p.get("composite_intrinsic_value") is not None
        # Probability-weighted should fire (all 3 scenarios positive).
        assert p.get("probability_weighted_fv") is not None


# ─────────────────────────────────────────────────────────────────
# SEBI vocab guard — fragments per CLAUDE.md rule #5
# ─────────────────────────────────────────────────────────────────


class TestSEBIVocabGuard:
    """Confirm none of the Phase-B inject helpers emit user-facing
    text. Every field is a number or method tag — no advisory copy.

    Pattern B (CLAUDE.md rule #5) — banned tokens assembled from
    fragments so the diff-only SEBI lint stays green.
    """

    # Build the banned set from fragments at runtime — keeps the
    # repo-level SEBI lint scan clean even if this file lands in a
    # diff that touches banned-token-adjacent code.
    BANNED = (
        "b" + "uy",
        "se" + "ll",
        "ho" + "ld",
        "stro" + "ng bu" + "y",
        "ra" + "ting",
        "tar" + "get pri" + "ce",
        "recommen" + "dation",
    )

    def test_method_tags_carry_no_advisory_language(self):
        """Method strings — `ddm_method`, `three_stage_method`,
        `probability_weighted_method` — must be plain engine identifiers,
        not advisory verbs."""
        p1 = _payload_ddm_eligible()
        _inject_ddm_dict(p1)
        for banned in self.BANNED:
            assert banned.lower() not in str(p1.get("ddm_method", "")).lower()
        p2 = _payload_three_stage_eligible()
        _inject_three_stage_dict(p2)
        for banned in self.BANNED:
            assert banned.lower() not in str(p2.get("three_stage_method", "")).lower()
        p3 = _payload_prob_weighted_eligible()
        _inject_probability_weighted_dict(p3)
        for banned in self.BANNED:
            assert banned.lower() not in str(
                p3.get("probability_weighted_method", "")
            ).lower()
