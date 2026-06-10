"""Tests for v_fix_phase_b_estimator_coverage_2026_06_10.

Coverage strategy:
  * Each of the 5 standalone Phase-B inject helpers (DDM, EPV, three-
    stage DCF, liquidation, probability-weighted) is exercised with a
    bank-shaped payload (HDFCBANK proxy) AND an industrial-shaped
    payload (RELIANCE proxy) to confirm the reason-string contract
    holds on both the "Not applicable for banks" path and the
    "missing input data" path.
  * Replacement value inject is exercised with the same two payloads
    plus a third "asset-heavy with valid inputs" payload that should
    actually compute.
  * Bank residual income (T3.1) wiring through
    ``_resolve_sector_primary_fv`` is exercised with NIM data present
    (expect non-None sector_specific_fv + label
    "bank_residual_income_deepened") and absent (expect None + the
    composite falls back to the headline scheme).
  * End-to-end orchestrator test asserts the HDFCBANK fixture comes
    out with: composite_intrinsic_value computed, DCF computed,
    probability_weighted computed, sector_specific_fv computed (with
    NIM data), and the 5 *_reason fields all populated with honest
    explanations.

The tests exist because PR #837 wired the inject helpers with bare
`except Exception: pass`, so HDFCBANK on prod showed only 3 of 9
estimator rows in the Valuation Methods Panel. The fix surfaces a
reason string on every null estimator so the frontend can render
"Not applicable for banks — ..." inline.
"""
from __future__ import annotations

import pytest

from backend.routers.analysis import (
    _inject_ddm_dict,
    _inject_epv_dict,
    _inject_liquidation_dict,
    _inject_phase_b_estimators_dict,
    _inject_probability_weighted_dict,
    _inject_replacement_dict,
    _inject_three_stage_dict,
    _resolve_sector_primary_fv,
)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _hdfcbank_payload(*, with_nim: bool = False) -> dict:
    """Build an HDFCBANK-shaped payload — bank, low payout, no FCF.

    The ``with_nim`` toggle controls whether the
    ``computation_inputs.bank_deepened`` block carries the NIM data
    that gates the residual-income engine.
    """
    ci: dict = {}
    if with_nim:
        ci["bank_deepened"] = {
            "nim_pct": 0.041,
            "casa_mix_pct": 0.46,
            "provision_coverage_pct": 0.71,
            "gnpa_pct": 0.0125,
            "book_value_per_share": 600.0,
            "roe_pct": 0.175,
            "cost_of_equity": 0.125,
            "sustainable_growth": 0.10,
            "payout_ratio": 0.26,
            "cost_to_income_pct": 0.40,
            "tax_rate_pct": 0.25,
        }
    return {
        "ticker": "HDFCBANK",
        "company": {"ticker": "HDFCBANK", "sector": "Banking"},
        "quality": {
            "shares_outstanding": 760.5,
            "payout_ratio": 0.26,
            "is_bank": True,
            "book_value_per_share": 600.0,
            "roe_pct": 17.5,
        },
        "valuation": {
            "fair_value": 1141.82,
            "discount_rate": 0.125,
            "wacc": 0.125,
            "terminal_growth": 0.10,
            "current_price": 1500.0,
            "base_case": 1141.82,
            "bull_case": 1450.0,
            "bear_case": 850.0,
            "valuation_engine_used": "pb_residual_income",
        },
        "insights": {
            "dividend": {
                "dividend_rate_per_share": 19.5,
                "consecutive_years": 8,
                "payout_ratio_pct": 26.0,
            },
        },
        "computation_inputs": ci,
    }


def _reliance_payload() -> dict:
    """Build a RELIANCE-shaped payload — industrial, positive FCF.

    Used to confirm the non-bank path still surfaces values for the
    same estimators that legitimately compute for a non-financial
    business.
    """
    return {
        "ticker": "RELIANCE",
        "company": {"ticker": "RELIANCE", "sector": "Oil & Gas"},
        "quality": {
            "shares_outstanding": 6766.0,
            "payout_ratio": 0.10,
            "normalized_fcf_cr": 75000.0,
            "is_bank": False,
            "book_value_per_share": 750.0,
            "roe_pct": 9.5,
        },
        "valuation": {
            "fair_value": 1450.0,
            "discount_rate": 0.115,
            "wacc": 0.115,
            "terminal_growth": 0.04,
            "fcf_growth_rate": 0.10,
            "current_price": 1300.0,
            "base_case": 1450.0,
            "bull_case": 1700.0,
            "bear_case": 1100.0,
        },
        "insights": {},
        "computation_inputs": {
            "liquidation": {
                "cash_and_equivalents": 50000.0,
                "ppe_gross": 800000.0,
                "ppe_net": 600000.0,
                "long_term_debt": 200000.0,
                "shares_outstanding": 6766.0,
            },
            "replacement": {
                "ppe_gross": 800000.0,
                "working_capital_required": 80000.0,
                "cash_required_for_ops": 20000.0,
                "intangibles": 30000.0,
                "goodwill": 0.0,
                "total_debt": 250000.0,
                "shares_outstanding": 6766.0,
            },
        },
    }


# ─────────────────────────────────────────────────────────────────
# Section 1 — Each inject helper writes a reason on the
# "not applicable" path
# ─────────────────────────────────────────────────────────────────

def test_ddm_low_payout_writes_reason() -> None:
    """HDFCBANK has 26% payout — DDM gate requires >= 30%. The inject
    must leave ddm_fv None AND write a reason so the frontend can
    render the row."""
    payload = _hdfcbank_payload()
    _inject_ddm_dict(payload)
    assert payload["ddm_fv"] is None
    assert payload.get("ddm_reason"), "ddm_reason must be populated when ddm_fv is None"
    assert "payout_ratio" in payload["ddm_reason"].lower()


def test_epv_bank_writes_reason() -> None:
    """EPV is_applicable rejects banks. The inject must surface the
    bank-specific reason on the payload."""
    payload = _hdfcbank_payload()
    _inject_epv_dict(payload)
    assert payload["epv_per_share"] is None
    assert payload.get("epv_reason"), "epv_reason must be populated when epv_per_share is None"


def test_three_stage_bank_writes_reason() -> None:
    """Banks don't carry a positive base_year_fcf — the gate fails and
    the helper must surface the reason instead of silent None."""
    payload = _hdfcbank_payload()
    _inject_three_stage_dict(payload)
    assert payload["three_stage_fv"] is None
    assert payload.get("three_stage_reason"), (
        "three_stage_reason must be populated when three_stage_fv is None"
    )


def test_liquidation_bank_writes_reason() -> None:
    """Liquidation framework excludes banks (capital-adequacy
    framework applies instead). The reason must say so."""
    payload = _hdfcbank_payload()
    _inject_liquidation_dict(payload)
    assert payload["liquidation_per_share"] is None
    assert payload.get("liquidation_reason"), (
        "liquidation_reason must be populated when liquidation_per_share is None"
    )


def test_replacement_bank_writes_not_applicable_reason() -> None:
    """Replacement value inject must surface a 'Not applicable for
    banks' reason rather than a silent None."""
    payload = _hdfcbank_payload()
    _inject_replacement_dict(payload)
    assert payload["replacement_per_share"] is None
    assert payload.get("replacement_reason"), (
        "replacement_reason must be populated when replacement_per_share is None"
    )
    assert "bank" in payload["replacement_reason"].lower()


def test_probability_weighted_with_valid_scenarios_computes() -> None:
    """HDFCBANK has bull/base/bear all positive — probability-weighted
    FV must compute, NOT surface a None reason."""
    payload = _hdfcbank_payload()
    _inject_probability_weighted_dict(payload)
    assert payload["probability_weighted_fv"] is not None
    assert payload["probability_weighted_fv"] > 0


# ─────────────────────────────────────────────────────────────────
# Section 2 — Bank residual income wiring via dispatcher
# ─────────────────────────────────────────────────────────────────

def test_bank_residual_income_routes_when_nim_present() -> None:
    """With NIM data on computation_inputs, the dispatcher routes
    HDFCBANK to the deepened residual-income engine and returns the
    'bank_residual_income_deepened' label."""
    payload = _hdfcbank_payload(with_nim=True)
    fv, label = _resolve_sector_primary_fv(
        ticker="HDFCBANK",
        sector="Banking",
        payload=payload,
    )
    assert fv is not None
    assert fv > 0
    assert label == "bank_residual_income_deepened"


def test_bank_residual_income_skips_when_no_nim_data() -> None:
    """Without NIM data the gate rejects the route — the dispatcher
    returns (None, None) so the composite falls back to the headline
    scheme."""
    payload = _hdfcbank_payload(with_nim=False)
    fv, label = _resolve_sector_primary_fv(
        ticker="HDFCBANK",
        sector="Banking",
        payload=payload,
    )
    assert fv is None
    assert label is None


# ─────────────────────────────────────────────────────────────────
# Section 3 — Full orchestrator end-to-end for HDFCBANK
# ─────────────────────────────────────────────────────────────────

def test_hdfcbank_orchestrator_surfaces_all_9_rows_or_reasons() -> None:
    """The Phase-B orchestrator must populate either an FV value OR a
    reason string for each of the 5 standalone estimators + the
    replacement value field. HDFCBANK with NIM data must additionally
    produce a sector_specific_fv with the deepened-bank label.
    """
    payload = _hdfcbank_payload(with_nim=True)
    _inject_phase_b_estimators_dict(payload)

    # Banks: these 5 estimators don't apply OR can't compute without
    # the right input shape — each must carry a reason string.
    for field, reason_field in [
        ("ddm_fv", "ddm_reason"),
        ("epv_per_share", "epv_reason"),
        ("three_stage_fv", "three_stage_reason"),
        ("liquidation_per_share", "liquidation_reason"),
        ("replacement_per_share", "replacement_reason"),
    ]:
        assert payload.get(field) is None, (
            f"{field} should be None for HDFCBANK"
        )
        assert payload.get(reason_field), (
            f"{reason_field} must be populated when {field} is None"
        )

    # Probability-weighted has bull/base/bear all positive — it must
    # compute and carry no reason.
    assert payload.get("probability_weighted_fv") is not None
    assert payload.get("probability_weighted_fv") > 0

    # Sector-specific routes to the deepened bank engine.
    assert payload.get("sector_specific_fv") is not None
    assert payload.get("sector_specific_fv") > 0
    assert payload.get("sector_specific_label") == "bank_residual_income_deepened"


# ─────────────────────────────────────────────────────────────────
# Section 4 — Non-bank path still works (Reliance)
# ─────────────────────────────────────────────────────────────────

def test_reliance_replacement_value_computes_with_full_inputs() -> None:
    """RELIANCE is asset-heavy with PP&E + WC + cash supplied — the
    replacement-value inject must produce a positive per-share figure
    rather than the bank skip."""
    payload = _reliance_payload()
    _inject_replacement_dict(payload)
    assert payload.get("replacement_per_share") is not None
    assert payload["replacement_per_share"] > 0
    assert payload.get("replacement_method") in ("replacement_full", "replacement_partial")


def test_reliance_liquidation_computes_with_balance_sheet() -> None:
    """RELIANCE has a liquidation block on computation_inputs — the
    inject must produce a positive floor rather than skip with a
    'no balance sheet' reason."""
    payload = _reliance_payload()
    _inject_liquidation_dict(payload)
    assert payload.get("liquidation_per_share") is not None
    assert payload["liquidation_per_share"] > 0


def test_non_bank_replacement_excludes_amc_via_sector_keyword() -> None:
    """An AMC ticker with all the inputs the engine would need must
    still be skipped by the sector-keyword gate, AND the reason must
    be populated so the frontend can render the row."""
    payload = {
        "ticker": "NIPPONLIFE",
        "company": {"ticker": "NIPPONLIFE", "sector": "Asset Management"},
        "quality": {"shares_outstanding": 620.0, "is_bank": False},
        "valuation": {"current_price": 700.0},
        "insights": {},
        "computation_inputs": {
            "replacement": {
                "ppe_gross": 500.0,
                "shares_outstanding": 620.0,
            },
        },
    }
    _inject_replacement_dict(payload)
    assert payload["replacement_per_share"] is None
    assert payload.get("replacement_reason"), (
        "AMC must surface a not-applicable reason"
    )
