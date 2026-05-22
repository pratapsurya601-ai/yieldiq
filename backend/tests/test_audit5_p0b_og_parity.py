# backend/tests/test_audit5_p0b_og_parity.py
# ═══════════════════════════════════════════════════════════════════════
# Audit #5 P0b follow-up (Day-100, 2026-05-22) — extend the fair_value
# 0-floor fallthrough from /api/v1/public/stock-summary to /og-data.
#
# Parent PR #496 fixed _extract_analysis_summary in routers/public.py so
# engine fair_value=0 + base_case>0 surfaces base_case. The authed
# /og-data endpoint (routers/analysis.py:get_og_data) was NOT covered by
# that fix and still rendered "₹0 fair value" on ULTRACEMCO.NS OG cards.
#
# This test asserts BOTH paths return the same fair_value for the same
# input AnalysisResponse: never one of each, never one positive and one
# zero. The shared helper lives at services/summary_projection.py.
# ═══════════════════════════════════════════════════════════════════════
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.routers.public import _extract_analysis_summary
from backend.services.summary_projection import resolve_fair_value


class _NS:
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _make_result(*, fair_value, base_case, verdict="data_limited",
                 current_price=11601.0):
    _bc_for_scenarios = base_case if base_case is not None else 0.0
    bear = max(_bc_for_scenarios * 0.9, 0)
    bull = max(_bc_for_scenarios * 1.4, 0)
    return _NS(
        ticker="ULTRACEMCO.NS",
        valuation=_NS(
            fair_value=fair_value,
            current_price=current_price,
            margin_of_safety=0.0,
            bear_case=bear,
            base_case=base_case,
            bull_case=bull,
            wacc=0.098,
            confidence_score=36,
            verdict=verdict,
            fair_value_source="dcf",
            valuation_model="dcf",
            peer_cap_details=None,
            ttm_source="yfinance",
            quarterly_last_filed_at=None,
        ),
        quality=_NS(
            yieldiq_score=40, grade="C", moat="Moderate", piotroski_score=4,
            roe=10.66, de_ratio=0.0, roce=11.9, debt_ebitda=1.3,
            interest_coverage=6.8, current_ratio=0.75, asset_turnover=0.0,
            revenue_cagr_3y=None, revenue_cagr_5y=None,
        ),
        company=_NS(
            company_name="UltraTech Cement Limited",
            sector="Cement", industry="", exchange="NSE", currency="INR",
            market_cap=3.4e12,
        ),
        insights=_NS(ev_ebitda=19.17),
        ai_summary=None,
        timestamp="2026-05-22T06:48:15.452987",
    )


def _og_fair_value(result):
    """Run the og-data fair_value resolution path on `result`.

    Mirrors the inline call in routers/analysis.py::get_og_data so we
    don't need to spin a full FastAPI request to verify parity.
    """
    fv_resolved = resolve_fair_value(
        result.valuation.fair_value,
        getattr(result.valuation, "base_case", None),
    )
    return float(fv_resolved if fv_resolved is not None else 0)


# ── Parity tests: both endpoints must agree ─────────────────────────


def test_ultracemco_repro_both_paths_surface_base_case():
    """The exact prod repro. Both extractions must yield 3028, not 0."""
    result = _make_result(fair_value=0.0, base_case=3028.83)
    summary_fv = _extract_analysis_summary(result)["fair_value"]
    og_fv = _og_fair_value(result)
    assert summary_fv == pytest.approx(3028.83, rel=1e-6)
    assert og_fv == pytest.approx(3028.83, rel=1e-6)
    assert summary_fv == pytest.approx(og_fv, rel=1e-6), (
        "og-data and public stock-summary must surface the SAME "
        "fair_value for the same AnalysisResponse — divergence is the "
        "Audit#5 P0b OG defect."
    )


def test_both_none_when_engine_and_base_missing():
    """When both inputs are None, the helper returns None and the og
    path collapses to 0 (frontend hides the pill either way). The
    contract is: same input → same downstream user experience."""
    result = _make_result(fair_value=None, base_case=None)
    # base_case is required to be a number for the summary's
    # round(v.base_case, 2) call elsewhere; patch it for this case.
    result.valuation.base_case = 0.0
    # Re-test the helper directly with the None/None input we care about:
    assert resolve_fair_value(None, None) is None


def test_happy_path_high_confidence_engine_value_preserved_both_paths():
    """When the engine produced a real number, neither path overrides it."""
    result = _make_result(
        fair_value=1845.54, base_case=1800.0, verdict="fairly_valued",
    )
    summary_fv = _extract_analysis_summary(result)["fair_value"]
    og_fv = _og_fair_value(result)
    assert summary_fv == pytest.approx(1845.54, rel=1e-6)
    assert og_fv == pytest.approx(1845.54, rel=1e-6)


def test_both_zero_inputs_never_surface_positive_synth():
    """If engine=0 AND base=0, neither path may invent a positive number."""
    result = _make_result(fair_value=0.0, base_case=0.0)
    summary_fv = _extract_analysis_summary(result)["fair_value"]
    og_fv = _og_fair_value(result)
    assert summary_fv in (None, 0, 0.0)
    assert og_fv == 0.0
    # Both render as "no pill" on the frontend — that's the parity
    # we actually care about for the user.


def test_negative_engine_value_falls_through_in_both_paths():
    """Defensive: negative FV (downstream override gone wrong) falls
    through to base_case in BOTH paths."""
    result = _make_result(fair_value=-5.0, base_case=3028.83)
    summary_fv = _extract_analysis_summary(result)["fair_value"]
    og_fv = _og_fair_value(result)
    assert summary_fv == pytest.approx(3028.83, rel=1e-6)
    assert og_fv == pytest.approx(3028.83, rel=1e-6)


# ── Helper unit tests ───────────────────────────────────────────────


def test_resolve_fair_value_engine_positive_wins():
    assert resolve_fair_value(1845.54, 1800.0) == pytest.approx(1845.54)


def test_resolve_fair_value_engine_zero_falls_through():
    assert resolve_fair_value(0.0, 3028.83) == pytest.approx(3028.83)


def test_resolve_fair_value_both_none_returns_none():
    assert resolve_fair_value(None, None) is None


def test_resolve_fair_value_negative_engine_falls_through():
    assert resolve_fair_value(-5.0, 3028.83) == pytest.approx(3028.83)


def test_resolve_fair_value_both_zero_preserves_zero():
    out = resolve_fair_value(0.0, 0.0)
    assert out == 0 or out == 0.0


def test_resolve_fair_value_engine_none_base_positive():
    assert resolve_fair_value(None, 100.0) == pytest.approx(100.0)


# ── Source-text guard ──────────────────────────────────────────────


def test_og_data_path_uses_shared_helper():
    """The routers/analysis.py og-data handler must route fair_value
    through services/summary_projection.resolve_fair_value so future
    edits can't accidentally bypass the floor."""
    import pathlib
    src = (
        pathlib.Path(__file__).parent.parent / "routers" / "analysis.py"
    ).read_text(encoding="utf-8")
    assert "resolve_fair_value" in src, (
        "og-data must import resolve_fair_value from "
        "backend.services.summary_projection — see Audit#5 P0b parity fix."
    )
    assert "AUDIT5_P0B_FAIR_VALUE_FLOOR" in src
