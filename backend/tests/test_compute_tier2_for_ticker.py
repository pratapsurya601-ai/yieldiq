"""Tests for the standalone Tier 2 wiring helper
``backend.services.analysis.service.compute_tier2_for_ticker``.

This is the helper consumed by the Tier 2 vs custom-engine head-to-head
reconciliation harness (``scripts/tier2_head_to_head.py``). It must:

  * Return a dict with ``fair_value`` / ``confidence_score`` / ``bucket``
    for tickers that have a real cohort (MANKIND, TCS).
  * Return ``None`` for skip-sectors (banking, NBFC, regulated utility,
    REIT, ETF, holdco) per Tier 2 design doc §2.4.
  * Return ``None`` for unknown tickers (collector returns nothing).
  * Return ``None`` when the DB / collector is unreachable — never
    raise, so the harness can keep marching across the universe.

The helper composes existing primitives (``StockDataCollector``,
``compute_metrics``, ``_resolve_sector``,
``_build_tier2_peers_from_sector_relative``,
``compute_tier2_fair_value``); the tests mock those primitives at the
``backend.services.analysis.service`` namespace so we exercise the
helper's orchestration logic without hitting the network or DB.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.services.analysis import service as svc


# ── Fixture builders ───────────────────────────────────────────────


def _pharma_premium_peers() -> list[dict]:
    """SUN / CIPLA / DRREDDY / DIVISLAB / LUPIN — Premium pharma cohort
    (mirrors the fixture in test_tier2_cohort.py)."""
    return [
        {"ticker": "SUNPHARMA", "pe": 38.0, "ev_ebitda": 24.0,
         "roce": 26.0, "piotroski": 7, "market_cap_cr": 380000.0},
        {"ticker": "CIPLA", "pe": 30.0, "ev_ebitda": 20.0,
         "roce": 27.0, "piotroski": 8, "market_cap_cr": 110000.0},
        {"ticker": "DRREDDY", "pe": 22.0, "ev_ebitda": 16.0,
         "roce": 30.0, "piotroski": 8, "market_cap_cr": 100000.0},
        {"ticker": "DIVISLAB", "pe": 28.0, "ev_ebitda": 20.0,
         "roce": 28.0, "piotroski": 7, "market_cap_cr": 150000.0},
        {"ticker": "LUPIN", "pe": 26.0, "ev_ebitda": 16.0,
         "roce": 25.5, "piotroski": 7, "market_cap_cr": 75000.0},
    ]


def _it_premium_peers() -> list[dict]:
    """INFY / WIPRO / HCLTECH / TECHM / LTIM — large-cap IT cohort.

    All ROCE > 25, Piotroski >= 7, mcap >= ₹50k Cr.
    """
    return [
        {"ticker": "INFY", "pe": 26.0, "ev_ebitda": 18.0,
         "roce": 35.0, "piotroski": 8, "market_cap_cr": 660000.0},
        {"ticker": "WIPRO", "pe": 22.0, "ev_ebitda": 15.0,
         "roce": 26.0, "piotroski": 7, "market_cap_cr": 260000.0},
        {"ticker": "HCLTECH", "pe": 25.0, "ev_ebitda": 17.0,
         "roce": 28.0, "piotroski": 8, "market_cap_cr": 410000.0},
        {"ticker": "TECHM", "pe": 28.0, "ev_ebitda": 16.0,
         "roce": 26.0, "piotroski": 7, "market_cap_cr": 130000.0},
        {"ticker": "LTIM", "pe": 30.0, "ev_ebitda": 20.0,
         "roce": 30.0, "piotroski": 7, "market_cap_cr": 170000.0},
    ]


def _mankind_raw() -> dict:
    """Minimal raw/enriched payload — what compute_metrics would produce
    for MANKIND at price ≈ ₹2,400 / EPS ≈ ₹76 / ROCE 27 / Piotroski 8.
    """
    return {
        "sector": "Pharma",
        "price": 2400.0,
        "diluted_eps": 76.0,
        "trailingEps": 76.0,
        "shares": 4.005e8,
        "roce_pct": 27.0,
        "ebitda": 3500.0,
        "book_value_per_share": 380.0,
        "total_debt": 1_000 * 1e7,
        "total_cash": 5_000 * 1e7,
    }


def _tcs_raw() -> dict:
    return {
        "sector": "IT",
        "price": 3800.0,
        "diluted_eps": 125.0,
        "trailingEps": 125.0,
        "shares": 3.66e9,
        "roce_pct": 60.0,
        "ebitda": 70_000.0,
        "book_value_per_share": 250.0,
        "total_debt": 0.0,
        "total_cash": 30_000 * 1e7,
    }


def _hdfcbank_raw() -> dict:
    return {
        "sector": "Banking",
        "price": 1700.0,
        "diluted_eps": 80.0,
        "shares": 7.59e9,
        "roce_pct": 18.0,
        "book_value_per_share": 580.0,
    }


# ── Helper for installing a full mock stack ───────────────────────────


def _install_mocks(
    raw: dict | None,
    peers: list[dict],
    *,
    piotroski: int | dict | None = 8,
    sector: str | None = None,
):
    """Patch every external dependency the helper consumes. Returns a
    list of patcher context managers caller should ``enter``.
    """
    class _FakeCollector:
        def __init__(self, *_args, **_kwargs):
            pass

        def get_all(self):
            return raw

    patches = [
        patch.object(svc, "StockDataCollector", _FakeCollector),
        patch.object(svc, "compute_metrics", lambda r: dict(r or {})),
        patch.object(
            svc, "_build_tier2_peers_from_sector_relative",
            lambda _t: list(peers),
        ),
        patch.object(
            svc, "compute_piotroski_fscore", lambda _e: piotroski,
        ),
    ]
    if sector is not None:
        patches.append(
            patch.object(
                svc, "_resolve_sector",
                lambda _rs, _ct: sector,
            )
        )
    return patches


# ── Tests ─────────────────────────────────────────────────────────────


def test_mankind_returns_fv_in_band():
    """MANKIND with realistic Premium pharma peers — FV should land in
    the [₹1,900, ₹2,500] band the harness expects."""
    patches = _install_mocks(
        _mankind_raw(), _pharma_premium_peers(),
        piotroski=8, sector="Pharma",
    )
    for p in patches:
        p.start()
    try:
        out = svc.compute_tier2_for_ticker("MANKIND")
    finally:
        for p in patches:
            p.stop()

    assert out is not None, "Tier 2 must produce a result for MANKIND"
    fv = out["fair_value"]
    assert 1900 <= fv <= 2500, (
        f"MANKIND Tier 2 FV ₹{fv} outside [₹1,900, ₹2,500]. "
        f"bucket={out.get('bucket')}, meta={out.get('_meta')}"
    )
    assert out["bucket"] == "premium"
    assert isinstance(out["confidence_score"], int)
    assert 40 <= out["confidence_score"] <= 75


def test_tcs_tier1_membership_does_not_gate_helper():
    """TCS is a Tier 1 large-cap, but Tier 2 is a sector-cohort
    fallback comparison — the helper must still return a real FV so
    the head-to-head harness can compare engines on Tier 1 names too.
    """
    patches = _install_mocks(
        _tcs_raw(), _it_premium_peers(),
        piotroski=9, sector="IT",
    )
    for p in patches:
        p.start()
    try:
        out = svc.compute_tier2_for_ticker("TCS")
    finally:
        for p in patches:
            p.stop()

    assert out is not None, "Tier 2 helper must not gate on Tier 1 membership"
    assert out["fair_value"] > 0
    assert out["bucket"] in {"premium", "core", "tail"}


def test_banking_skip_sector_returns_none():
    """HDFCBANK routes to the dedicated bank engine; Tier 2 must skip
    it (banking is in TIER2_SKIP_SECTORS per design doc)."""
    patches = _install_mocks(
        _hdfcbank_raw(), peers=[],
        piotroski=7, sector="Banking",
    )
    for p in patches:
        p.start()
    try:
        out = svc.compute_tier2_for_ticker("HDFCBANK")
    finally:
        for p in patches:
            p.stop()

    assert out is None, (
        "Banking is a Tier 2 skip-sector — helper must return None "
        "so the harness records data_limited and routes via the bank "
        "engine instead."
    )


def test_unknown_ticker_returns_none():
    """Collector returns an empty payload for an unknown ticker — the
    helper must degrade to None rather than raising."""
    patches = _install_mocks(
        raw=None, peers=[],
        piotroski=None, sector=None,
    )
    for p in patches:
        p.start()
    try:
        out = svc.compute_tier2_for_ticker("DOES_NOT_EXIST")
    finally:
        for p in patches:
            p.stop()

    assert out is None


def test_db_unreachable_returns_none_without_raising():
    """If the collector raises (network down, DB unreachable, ...),
    the helper must swallow the exception and return None — the
    harness depends on this to keep marching across the universe."""
    class _BoomCollector:
        def __init__(self, *_a, **_kw):
            pass

        def get_all(self):
            raise RuntimeError("DB unreachable")

    with patch.object(svc, "StockDataCollector", _BoomCollector):
        # Must not raise.
        out = svc.compute_tier2_for_ticker("MANKIND")
    assert out is None


def test_empty_ticker_returns_none():
    """Defensive: empty ticker short-circuits."""
    assert svc.compute_tier2_for_ticker("") is None
    assert svc.compute_tier2_for_ticker(None) is None  # type: ignore[arg-type]
