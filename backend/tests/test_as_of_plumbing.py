# backend/tests/test_as_of_plumbing.py
"""Task #197 — feat/as-of-plumbing.

The freshness chip on the analysis surface should read the actual
live_quotes.as_of (5-15m fresh) instead of the analysis-recompute time
(often hours stale). These tests pin the structural pieces of that
contract so a future refactor doesn't silently drop the field.
"""
from __future__ import annotations

from backend.models.responses import (
    AnalysisResponse,
    CompanyInfo,
    HoldingResponse,
    InsightCards,
    QualityOutput,
    ScreenerStock,
    SectorOverviewItem,
    ValuationOutput,
    WatchlistItemResponse,
)


def test_valuation_output_carries_as_of():
    """ValuationOutput must accept an `as_of` ISO-8601 string and round-trip
    it through model_dump() so downstream JSON serializers preserve it."""
    iso = "2026-05-24T09:15:00+05:30"
    vo = ValuationOutput(
        fair_value=100.0,
        current_price=80.0,
        margin_of_safety=25.0,
        verdict="undervalued",
        as_of=iso,
    )
    assert vo.as_of == iso
    dumped = vo.model_dump()
    assert dumped["as_of"] == iso


def test_valuation_output_as_of_defaults_to_none_for_legacy_payloads():
    """Old cached payloads (pre-Task #197) don't carry `as_of` — the
    response model must default to None so they don't 500."""
    vo = ValuationOutput(
        fair_value=100.0,
        current_price=80.0,
        margin_of_safety=25.0,
        verdict="undervalued",
    )
    assert vo.as_of is None


def test_analysis_response_top_level_as_of():
    """AnalysisResponse mirrors valuation.as_of at the top level so the
    AnalysisHero can read freshness without unwrapping `valuation`."""
    iso = "2026-05-24T09:15:00+05:30"
    resp = AnalysisResponse(
        ticker="INFY.NS",
        company=CompanyInfo(ticker="INFY.NS", company_name="Infosys"),
        valuation=ValuationOutput(
            fair_value=1500.0,
            current_price=1400.0,
            margin_of_safety=7.0,
            verdict="undervalued",
            as_of=iso,
        ),
        quality=QualityOutput(),
        insights=InsightCards(),
        as_of=iso,
    )
    assert resp.as_of == iso
    assert resp.valuation.as_of == iso


def test_other_response_models_accept_as_of():
    """ScreenerStock / HoldingResponse / WatchlistItemResponse /
    SectorOverviewItem all gained the optional `as_of` field for the
    same plumbing reason. Smoke test that none of the constructors
    reject it and the round-trip preserves the value."""
    iso = "2026-05-24T09:15:00+05:30"
    rows = [
        ScreenerStock(ticker="X", as_of=iso),
        HoldingResponse(ticker="X", as_of=iso),
        WatchlistItemResponse(ticker="X", as_of=iso),
        SectorOverviewItem(name="IT", as_of=iso),
    ]
    for r in rows:
        assert r.as_of == iso
        assert r.model_dump()["as_of"] == iso
