"""Pure-function tests for backend/services/peer_cap_service.py.

DB-free: we monkeypatch _query_median_pe so the tests don't need a
live MarketMetrics/Stocks fixture. Every test here exercises the
policy decisions, not the SQL.
"""
from __future__ import annotations

import pytest

from backend.services import peer_cap_service as pcs
from backend.services.peer_cap_service import (
    PEER_CAP_MULTIPLIER,
    MIN_PEERS,
    PeerScope,
    apply_peer_cap,
)


@pytest.fixture(autouse=True)
def _clear_cache():
    """Ensure the in-memory median cache doesn't leak across tests."""
    pcs._median_cache.clear()
    yield
    pcs._median_cache.clear()


def _stub_scope(monkeypatch, scope: str, label: str, peer_count: int, median_pe):
    """Replace _query_median_pe with a fixed PeerScope."""
    def _fake(exclude_ticker, scope_kind, lbl, db):
        if scope_kind == scope and lbl == label:
            return PeerScope(scope_kind, lbl, peer_count, median_pe)
        return PeerScope(scope_kind, lbl, 0, None)
    monkeypatch.setattr(pcs, "_query_median_pe", _fake)


def test_clamp_fires_on_outlier(monkeypatch):
    """EMAMILTD-style: DCF 800, peer median P/E 30, EPS 10 → peer FV 300,
    cap = 450, DCF clamped to 450."""
    _stub_scope(monkeypatch, "industry", "Personal Care", 8, 30.0)
    r = apply_peer_cap(
        ticker="EMAMILTD", dcf_fv=800.0, eps_ttm=10.0,
        industry="Personal Care", sector="Consumer Staples",
        db=object(),
    )
    assert r.source == "peer_capped"
    assert r.capped_fv == pytest.approx(30.0 * 10.0 * PEER_CAP_MULTIPLIER)
    assert r.details["fired"] is True
    assert r.details["raw_dcf_fv"] == 800.0


def test_clamp_does_not_fire_within_envelope(monkeypatch):
    """DCF 400, peer median P/E 30, EPS 10 → cap 450, DCF stays 400."""
    _stub_scope(monkeypatch, "industry", "Personal Care", 8, 30.0)
    r = apply_peer_cap(
        ticker="HUL", dcf_fv=400.0, eps_ttm=10.0,
        industry="Personal Care", sector="Consumer Staples",
        db=object(),
    )
    assert r.source == "dcf"
    assert r.capped_fv == 400.0
    assert r.details["fired"] is False


def test_down_only_never_raises_dcf(monkeypatch):
    """DCF below peer envelope must never be lifted up — clamp is
    one-directional. (Trivially follows from min(dcf, cap), but pin
    it as a regression so future refactors don't introduce a max.)"""
    _stub_scope(monkeypatch, "industry", "Banks", 10, 25.0)
    r = apply_peer_cap(
        ticker="HDFCBANK", dcf_fv=100.0, eps_ttm=80.0,
        industry="Banks", sector="Financial Services",
        db=object(),
    )
    # Cap would be 25*80*1.5 = 3000; DCF 100 stays.
    assert r.capped_fv == 100.0
    assert r.source == "dcf"


def test_falls_back_to_sector_when_industry_sparse(monkeypatch):
    """Industry has only 2 peers (< MIN_PEERS) → fall back to sector."""
    def _fake(exclude_ticker, scope_kind, lbl, db):
        if scope_kind == "industry":
            return PeerScope("industry", lbl, 2, 30.0)  # too few peers
        return PeerScope("sector", lbl, 12, 25.0)
    monkeypatch.setattr(pcs, "_query_median_pe", _fake)

    r = apply_peer_cap(
        ticker="ORPHAN", dcf_fv=1000.0, eps_ttm=10.0,
        industry="Niche Industry", sector="Consumer Staples",
        db=object(),
    )
    assert r.source == "peer_capped"
    assert r.details["scope"] == "sector"
    assert r.capped_fv == pytest.approx(25.0 * 10.0 * PEER_CAP_MULTIPLIER)


def test_no_cap_when_both_industry_and_sector_sparse(monkeypatch):
    """Neither scope hits MIN_PEERS → pass DCF through, mark source."""
    def _fake(exclude_ticker, scope_kind, lbl, db):
        return PeerScope(scope_kind, lbl, 1, None)
    monkeypatch.setattr(pcs, "_query_median_pe", _fake)

    r = apply_peer_cap(
        ticker="MICROCAP", dcf_fv=500.0, eps_ttm=10.0,
        industry="Tiny Industry", sector="Tiny Sector",
        db=object(),
    )
    assert r.source == "dcf_no_peer_data"
    assert r.capped_fv == 500.0


def test_negative_eps_skips_cap(monkeypatch):
    """Loss-makers have no P/E baseline; pass DCF through with the
    'no peer data' tag so the frontend can disclose. EV/EBITDA branch
    (when added) is what handles this case."""
    _stub_scope(monkeypatch, "industry", "Pharma", 10, 35.0)
    r = apply_peer_cap(
        ticker="LOSSCO", dcf_fv=500.0, eps_ttm=-2.0,
        industry="Pharma", sector="Healthcare",
        db=object(),
    )
    assert r.source == "dcf_no_peer_data"
    assert r.capped_fv == 500.0
    assert r.details.get("reason") == "non_positive_eps"


def test_zero_dcf_passes_through():
    """Defensive: 0 DCF (data-limited path) shouldn't be clamped to
    something positive — pass through and tag as plain dcf."""
    r = apply_peer_cap(
        ticker="ZEROCO", dcf_fv=0.0, eps_ttm=10.0,
        industry="Anything", sector="Anything",
        db=object(),
    )
    assert r.capped_fv == 0.0
    assert r.source == "dcf"


def test_missing_db_returns_no_peer_data():
    """No DB session → can't compute peers. Don't crash; tag as no-peer."""
    r = apply_peer_cap(
        ticker="X", dcf_fv=500.0, eps_ttm=10.0,
        industry="X", sector="X", db=None,
    )
    assert r.source == "dcf_no_peer_data"
    assert r.capped_fv == 500.0


def test_min_peers_threshold_is_strict(monkeypatch):
    """Exactly MIN_PEERS = pass; one less = fall through."""
    def _fake_n(n):
        def inner(exclude_ticker, scope_kind, lbl, db):
            if scope_kind == "industry":
                return PeerScope("industry", lbl, n, 30.0 if n >= MIN_PEERS else None)
            return PeerScope("sector", lbl, 0, None)
        return inner

    monkeypatch.setattr(pcs, "_query_median_pe", _fake_n(MIN_PEERS))
    r = apply_peer_cap("T", 1000.0, 10.0, "I", "S", object())
    assert r.source == "peer_capped"

    pcs._median_cache.clear()
    monkeypatch.setattr(pcs, "_query_median_pe", _fake_n(MIN_PEERS - 1))
    r = apply_peer_cap("T", 1000.0, 10.0, "I", "S", object())
    assert r.source == "dcf_no_peer_data"
