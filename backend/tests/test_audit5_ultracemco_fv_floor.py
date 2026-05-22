# backend/tests/test_audit5_ultracemco_fv_floor.py
# ═══════════════════════════════════════════════════════════════════════
# Audit #5 P0b (Day-100, 2026-05-22) — fair_value 0-floor leak.
#
# Repro: prod /api/v1/public/stock-summary/ULTRACEMCO.NS returned
#   {"fair_value": 0.0, "base_case": 3028.83, "verdict": "data_limited",
#    "confidence": 50, "fair_value_source": "dcf"}
# The SEO fair-value hero pill (frontend/src/app/(stocks)/stocks/[ticker]/
# fair-value/page.tsx:449) renders `fair_value` directly, so users saw
# "₹0 fair value" while the verdict gate showed data_limited.
#
# This is the same defect shape Audit #4 flagged for the utility bear case
# at Day-92, but the Day-92 fix only covered the bear/bull at the engine
# layer; the summary projection in backend/routers/public.py still
# forwarded engine fair_value verbatim.
#
# Fix: in `_extract_analysis_summary`, when fair_value collapses to 0 but
# a real scenario midpoint (base_case > 0) exists, fall through to
# base_case. When neither exists, emit None so the frontend pill is
# hidden (AnalysisHero branches on `fairValue > 0`).
# ═══════════════════════════════════════════════════════════════════════
from __future__ import annotations

import pathlib

import pytest

from backend.routers.public import _extract_analysis_summary


PUBLIC_PATH = (
    pathlib.Path(__file__).parent.parent / "routers" / "public.py"
)
MANIFEST_PATH = (
    pathlib.Path(__file__).parent.parent / "services" / "cache_invalidation_manifest.py"
)


# ── Test doubles ──────────────────────────────────────────────────────
#
# `_extract_analysis_summary` reaches for result.valuation.*,
# result.quality.*, result.company.*, plus a few top-level fields. We
# build the smallest possible duck-typed stand-in rather than spin the
# full AnalysisResponse model so the test stays isolated from any
# concurrent schema changes.


class _NS:
    """Tiny attribute namespace — accepts kwargs as attrs."""

    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _make_result(*, fair_value, base_case, bear_case=None, bull_case=None,
                 confidence=50, verdict="data_limited"):
    """Build a minimal AnalysisResponse-shaped object."""
    bear_case = bear_case if bear_case is not None else max(base_case * 0.9, 0)
    bull_case = bull_case if bull_case is not None else max(base_case * 1.4, 0)
    valuation = _NS(
        fair_value=fair_value,
        current_price=11601.0,
        margin_of_safety=0.0,
        bear_case=bear_case,
        base_case=base_case,
        bull_case=bull_case,
        wacc=0.098,
        confidence_score=confidence,
        verdict=verdict,
        fair_value_source="dcf",
        valuation_model="dcf",
        peer_cap_details=None,
    )
    quality = _NS(
        yieldiq_score=40,
        grade="C",
        moat="Moderate",
        piotroski_score=4,
        roe=10.66,
        de_ratio=0.0,
        roce=11.9,
        debt_ebitda=1.3,
        interest_coverage=6.8,
        current_ratio=0.75,
        asset_turnover=0.0,
        revenue_cagr_3y=None,
        revenue_cagr_5y=None,
    )
    company = _NS(
        company_name="UltraTech Cement Limited",
        sector="Cement",
        industry="",
        exchange="NSE",
        currency="INR",
        market_cap=3.4e12,
    )
    insights = _NS(ev_ebitda=19.17)
    return _NS(
        ticker="ULTRACEMCO.NS",
        valuation=valuation,
        quality=quality,
        company=company,
        insights=insights,
        ai_summary=None,
        timestamp="2026-05-22T06:48:15.452987",
    )


# ── Core behavioural tests ────────────────────────────────────────────


def test_ultracemco_zero_engine_fair_value_falls_through_to_base_case():
    """The bug repro: engine fair_value=0 but base_case=3028.83.

    The summary `fair_value` field must surface base_case rather than 0
    so the SEO hero pill stops rendering '₹0 fair value'.
    """
    result = _make_result(
        fair_value=0.0,
        base_case=3028.83,
        confidence=36,
        verdict="data_limited",
    )
    out = _extract_analysis_summary(result)
    assert out["fair_value"] is not None
    assert out["fair_value"] > 0, (
        "Engine 0 + real base_case must NOT surface as fair_value=0; "
        "audit-#5 P0b requires fall-through to base_case."
    )
    # base_case itself is preserved in its own field — separate concern.
    assert out["base_case"] == pytest.approx(3028.83, rel=1e-6)


def test_falls_through_to_base_case_value_specifically():
    """Stronger: the fallthrough must be exactly base_case, not a synth."""
    result = _make_result(fair_value=0.0, base_case=3028.83)
    out = _extract_analysis_summary(result)
    assert out["fair_value"] == pytest.approx(3028.83, rel=1e-6)


def test_happy_path_high_confidence_engine_value_preserved():
    """When the engine produced a real number, do not touch it.

    This prevents the fix from accidentally masking real engine output
    with a (potentially stale) base_case midpoint.
    """
    result = _make_result(
        fair_value=1845.54,
        base_case=1800.0,
        confidence=82,
        verdict="fairly_valued",
    )
    out = _extract_analysis_summary(result)
    assert out["fair_value"] == pytest.approx(1845.54, rel=1e-6)


def test_zero_engine_and_zero_base_emits_zero_not_none():
    """If the engine and the base scenario both genuinely produced 0,
    don't synthesise a number — the verdict gate is data_limited and
    that's the truthful signal."""
    result = _make_result(fair_value=0.0, base_case=0.0)
    out = _extract_analysis_summary(result)
    # Either 0 or None is acceptable here — both result in the frontend
    # hiding the pill. The contract is: never invent a positive number.
    assert (out["fair_value"] is None) or (out["fair_value"] == 0)


def test_negative_engine_value_falls_through_to_base_case():
    """Defensive: a downstream override that produces a negative
    fair_value should also trigger the fallthrough."""
    result = _make_result(fair_value=-5.0, base_case=3028.83)
    out = _extract_analysis_summary(result)
    assert out["fair_value"] is not None
    assert out["fair_value"] > 0


# ── Source-text guards ────────────────────────────────────────────────


def test_audit5_marker_present_in_public_router():
    """The fix block must be wired into public.py with an explicit
    marker so future audits can grep for the guard."""
    src = PUBLIC_PATH.read_text(encoding="utf-8")
    assert "AUDIT5_P0B_FAIR_VALUE_FLOOR" in src


def test_manifest_entry_present():
    """Day-94 manifest entry must record the engine-output change."""
    src = MANIFEST_PATH.read_text(encoding="utf-8")
    assert "v_audit5_p0b_fv_floor_2026_05_22" in src
    assert "ULTRACEMCO" in src
    assert "fair_value" in src
