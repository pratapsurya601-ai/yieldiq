# backend/tests/test_earnings_impact_ma_suppression.py
# ═══════════════════════════════════════════════════════════════
# ROOT CAUSE #8 — quarterly surprise expectation must be suppressed
# when an M&A event distorts the YoY baseline.
#
# These tests exercise the FastAPI endpoint
# `GET /api/v1/analysis/{ticker}/earnings-impact` because the
# suppression logic lives in the router, not the pure heuristic
# service. We monkeypatch:
#   * `quarterly_results_service.get_quarterly_results` for the
#     row set (so no Postgres dependency),
#   * `ma_event_detector.detect_ma_event` for the M&A payload,
#   * the analysis-service resolver so sector / implied_growth are
#     deterministic.
#
# Scope:
#   * HDFCBANK fixture (HDFC merger detected, latest quarter inside
#     the 8-quarter window) → response carries
#     `ma_distortion_flag=True`, a non-empty `suppression_copy`, and
#     `impact.surprise_pct` / `impact.fv_delta_range` are nulled out.
#   * TCS fixture (no M&A) → response has
#     `ma_distortion_flag=False`, `ma_event=None`, and the legacy
#     numeric surprise comes through untouched.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import os
import sys
from datetime import date

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(os.path.dirname(_HERE))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.routers import earnings_impact as ei_router


def _make_app(monkeypatch) -> TestClient:
    """Spin a lightweight FastAPI app exposing just the earnings-impact
    router so the test doesn't have to mount the full application graph.

    Monkeypatches `_resolve_sector_and_growth` to return a deterministic
    pair (the helper hits AnalysisService which would otherwise try to
    cold-compute a real ticker).
    """
    app = FastAPI()
    app.include_router(ei_router.router)
    monkeypatch.setattr(
        ei_router, "_resolve_sector_and_growth",
        lambda ticker: ("Bank", 0.10),
    )
    return TestClient(app)


def _hdfcbank_rows() -> list[dict]:
    """Synthetic HDFCBANK quarterly rows straddling the merger.

    The latest period_end (Mar 2024) sits 3 quarters past the
    2023-07-01 merger; the YoY baseline (Mar 2023) sits BEFORE the
    merger, so the surprise math would compare an inflated 87k Cr
    post-merger quarter against a pre-merger 41k Cr quarter —
    structurally meaningless.
    """
    return [
        {
            "period_end": date(2024, 3, 31),
            "revenue_cr": 87_183.0,
            "net_profit_cr": 16_512.0,
        },
        {
            "period_end": date(2023, 12, 31),
            "revenue_cr": 76_124.0,
            "net_profit_cr": 16_372.0,
        },
        {
            "period_end": date(2023, 9, 30),
            "revenue_cr": 71_628.0,
            "net_profit_cr": 15_976.0,
        },
        {
            "period_end": date(2023, 6, 30),
            "revenue_cr": 48_587.0,
            "net_profit_cr": 12_403.0,
        },
        {
            "period_end": date(2023, 3, 31),
            "revenue_cr": 41_000.0,
            "net_profit_cr": 12_047.0,
        },
    ]


def _tcs_rows() -> list[dict]:
    """Synthetic TCS quarterly rows — well-behaved, no M&A."""
    return [
        {
            "period_end": date(2024, 3, 31),
            "revenue_cr": 62_613.0,
            "net_profit_cr": 12_434.0,
        },
        {
            "period_end": date(2023, 12, 31),
            "revenue_cr": 60_583.0,
            "net_profit_cr": 11_058.0,
        },
        {
            "period_end": date(2023, 9, 30),
            "revenue_cr": 59_692.0,
            "net_profit_cr": 11_342.0,
        },
        {
            "period_end": date(2023, 6, 30),
            "revenue_cr": 59_381.0,
            "net_profit_cr": 11_120.0,
        },
        {
            "period_end": date(2023, 3, 31),
            "revenue_cr": 59_162.0,
            "net_profit_cr": 11_392.0,
        },
    ]


def _hdfc_ma_event() -> dict:
    return {
        "event_date": "2023-07-01",
        "event_type": "REVERSE_MERGER",
        "magnitude_pct": 100.0,
        "multiplier": 2.0,
        "normalization_window_quarters": 8,
        "quarters_since_event": 3,
        "description": (
            "Reverse merger — HDFC Ltd parent absorbed into HDFC Bank; "
            "effective date 2023-07-01."
        ),
        "source_url": "https://www.sebi.gov.in/sebiweb/home/HomeAction.do",
        "source_doc": "RBI/SEBI joint approval — HDFC Ltd into HDFC Bank reverse merger",
        "is_within_normalization_window": True,
    }


# ── HDFCBANK suppression — surprise number stripped ─────────────
def test_hdfcbank_ma_distortion_suppresses_surprise(monkeypatch):
    client = _make_app(monkeypatch)
    monkeypatch.setattr(
        ei_router, "get_quarterly_results",
        lambda ticker, n_quarters=5, consolidated=True: _hdfcbank_rows(),
    )
    monkeypatch.setattr(
        ei_router, "detect_ma_event",
        lambda ticker, **kw: _hdfc_ma_event(),
    )

    r = client.get("/api/v1/analysis/HDFCBANK/earnings-impact")
    assert r.status_code == 200
    body = r.json()

    assert body["ma_distortion_flag"] is True
    assert body["ma_event"] is not None
    assert body["ma_event"]["event_date"] == "2023-07-01"
    assert isinstance(body["suppression_copy"], str)
    assert "Baseline distorted" in body["suppression_copy"]

    impact = body["impact"]
    assert impact is not None
    # Latest quarter still flows through so the frontend can render
    # context, but the misleading numbers are gone.
    assert impact["latest_quarter"]["revenue_cr"] == pytest.approx(87_183.0)
    assert impact["surprise_pct"] is None
    assert impact["fv_delta_estimate"] is None
    assert impact["fv_delta_range"] is None
    assert impact["ma_distortion_flag"] is True


# ── TCS — no suppression, legacy numeric path ───────────────────
def test_tcs_no_ma_event_legacy_surprise(monkeypatch):
    client = _make_app(monkeypatch)
    monkeypatch.setattr(
        ei_router, "get_quarterly_results",
        lambda ticker, n_quarters=5, consolidated=True: _tcs_rows(),
    )
    monkeypatch.setattr(
        ei_router, "detect_ma_event",
        lambda ticker, **kw: None,
    )

    r = client.get("/api/v1/analysis/TCS/earnings-impact")
    assert r.status_code == 200
    body = r.json()

    assert body["ma_distortion_flag"] is False
    assert body["ma_event"] is None
    assert body["suppression_copy"] is None

    impact = body["impact"]
    assert impact is not None
    # Heuristic produced a real numeric surprise + range.
    assert isinstance(impact["surprise_pct"], float)
    assert isinstance(impact["fv_delta_estimate"], float)
    assert impact["fv_delta_range"] is not None
    assert "low" in impact["fv_delta_range"]
    assert "high" in impact["fv_delta_range"]
