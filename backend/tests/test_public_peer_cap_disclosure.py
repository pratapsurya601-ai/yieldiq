# backend/tests/test_public_peer_cap_disclosure.py
# ═══════════════════════════════════════════════════════════════
# Regression lock for feat/peer-cap-public-disclosure
# (follow-up to PR #136 / feat/peer-cap).
#
# PR #136 added `fair_value_source` and `peer_cap_details` to
# `ValuationOutput` and wired them into the authed
# `/api/v1/analysis/{ticker}` endpoint. The public
# `/api/v1/public/stock-summary/{ticker}` serializer was missed,
# so the SEO frontend couldn't render the "FV capped at 1.5×
# peer median" tooltip — the data simply wasn't on the wire.
#
# This test asserts that the public flat-summary helper
# `_extract_analysis_summary` mirrors the authed surface:
#   * always emits `fair_value_source` (default "dcf")
#   * emits `peer_cap_details` as a JSON-friendly dict when the
#     cap actually fired (verdict.fair_value_source ==
#     "peer_capped"), else null.
# ═══════════════════════════════════════════════════════════════
from types import SimpleNamespace

from backend.models.responses import (
    PeerCapDetails,
    ValuationOutput,
)
from backend.routers.public import _extract_analysis_summary


def _make_result(valuation: ValuationOutput) -> SimpleNamespace:
    """Build the minimal AnalysisResponse-shaped duck for the
    serializer. `_extract_analysis_summary` reads .valuation,
    .quality, .company, .insights, .ai_summary, .timestamp and
    .ticker — anything not relevant to peer-cap is stubbed."""
    return SimpleNamespace(
        ticker="AXISBANK.NS",
        timestamp="2026-04-27T10:00:00Z",
        ai_summary=None,
        valuation=valuation,
        quality=SimpleNamespace(
            yieldiq_score=72,
            grade="B",
            moat="narrow",
            piotroski_score=7,
            roe=15.4,
            de_ratio=0.0,
            roce=14.2,
            debt_ebitda=None,
            interest_coverage=None,
            current_ratio=None,
            asset_turnover=None,
            revenue_cagr_3y=None,
            revenue_cagr_5y=None,
        ),
        company=SimpleNamespace(
            company_name="Axis Bank Ltd",
            sector="Financial Services",
            industry="Banks",
            exchange="NSE",
            currency="INR",
            market_cap=3.5e12,
        ),
        insights=SimpleNamespace(ev_ebitda=None),
    )


def _baseline_valuation(**overrides) -> ValuationOutput:
    base = dict(
        fair_value=1450.0,
        current_price=1100.0,
        margin_of_safety=24.1,
        verdict="undervalued",
        bear_case=1100.0,
        base_case=1450.0,
        bull_case=1800.0,
        wacc=0.105,
        terminal_growth=0.04,
        fcf_growth_rate=0.08,
        confidence_score=70,
    )
    base.update(overrides)
    return ValuationOutput(**base)


def test_default_dcf_source_exposed_with_null_peer_cap_details():
    """For a vanilla DCF result (no cap), the public payload must
    still surface `fair_value_source="dcf"` and `peer_cap_details=None`
    so the frontend can branch on a single, always-present field
    instead of doing presence checks."""
    result = _make_result(_baseline_valuation())
    out = _extract_analysis_summary(result)
    assert out["fair_value_source"] == "dcf"
    assert out["peer_cap_details"] is None


def test_peer_capped_audit_trail_serialized():
    """When the cap fires (AXISBANK is one of the 5 stocks where
    peer-cap fires in production), the audit trail must reach the
    SEO frontend as a plain JSON-serializable dict — not the
    Pydantic instance, which doesn't survive `_cached_json`."""
    details = PeerCapDetails(
        uncapped_fv=2200.0,
        peer_fv=1000.0,
        ceiling_fv=1500.0,
        method="min(pe,ev_ebitda)",
        n_peers=6,
        median_pe=12.0,
        median_ev_ebitda=8.5,
        sector="Financial Services",
        industry="Banks",
    )
    val = _baseline_valuation(
        fair_value=1500.0,  # ceiling
        fair_value_source="peer_capped",
        peer_cap_details=details,
    )
    out = _extract_analysis_summary(_make_result(val))

    assert out["fair_value_source"] == "peer_capped"
    pcd = out["peer_cap_details"]
    assert isinstance(pcd, dict)
    assert pcd["uncapped_fv"] == 2200.0
    assert pcd["peer_fv"] == 1000.0
    assert pcd["ceiling_fv"] == 1500.0
    assert pcd["method"] == "min(pe,ev_ebitda)"
    assert pcd["n_peers"] == 6
    assert pcd["median_pe"] == 12.0
    assert pcd["median_ev_ebitda"] == 8.5
    assert pcd["sector"] == "Financial Services"
