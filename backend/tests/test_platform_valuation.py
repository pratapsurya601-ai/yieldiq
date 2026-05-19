"""Tests for backend.services.platform_valuation_service."""
from __future__ import annotations

from backend.services.platform_valuation_service import (
    compute_platform_fair_value,
    _norm_sector,
)


def _fin(rev=10_000e7, shares=6e8, price=900, growth=0.20):
    """Sample financials: ₹10,000 Cr TTM revenue, 60 Cr shares, ₹900 CMP."""
    return {
        "revenue": rev,
        "shares": shares,
        "current_price": price,
        "revenue_cagr_3y": growth,
    }


def _peers(ps_values, growths=None):
    """Build a peer-list with given P/S values."""
    if growths is None:
        growths = [0.20] * len(ps_values)
    return [
        {"ticker": f"P{i}", "ps": ps, "revenue_cagr_3y": g}
        for i, (ps, g) in enumerate(zip(ps_values, growths))
    ]


# ── _norm_sector ──────────────────────────────────────────────


def test_norm_sector_accepts_human_strings():
    assert _norm_sector("Internet Platform") == "internet_platform"
    assert _norm_sector("internet platform") == "internet_platform"
    assert _norm_sector("internet_platform") == "internet_platform"
    assert _norm_sector("E-commerce") == "internet_platform"
    assert _norm_sector("Fintech") == "fintech_broker"
    assert _norm_sector("Stock Exchanges") == "fintech_broker"
    assert _norm_sector("Capital Markets") == "fintech_broker"


def test_norm_sector_rejects_unknown():
    assert _norm_sector("Cement") is None
    assert _norm_sector("") is None
    assert _norm_sector(None) is None


# ── compute_platform_fair_value — happy path ──────────────────


def test_paytm_shape_computes_ps_fv():
    """PAYTM-shape: ₹10,000 Cr TTM revenue, ~60 Cr shares, CMP ₹1000.
    Peer median P/S of 8 (similar to PAYTM peers like POLICYBZR/NYKAA).
    Expected FV ≈ 8 × (10000e7 / 60e8) = ₹1333.
    """
    result = compute_platform_fair_value(
        ticker="PAYTM.NS",
        sector="Internet Platform",
        financials=_fin(rev=10_000e7, shares=60e7, price=1000, growth=0.20),
        peers=_peers([6, 7, 8, 9, 10]),  # peer median 8
    )
    assert result is not None
    assert result["method"] == "ps_peer_median"
    # 8 × (10000/60) = 1333
    assert 1100 <= result["fair_value"] <= 1500
    assert result["verdict"] in ("undervalued", "fairly_valued")
    assert result["_meta"]["peer_ps_median"] == 8.0
    assert result["_meta"]["n_peers"] == 5


def test_growth_adjustment_amplifies_when_target_outgrows_peers():
    """Target growth 40% vs peer median 20% → adj 2.0, clamped to 1.6."""
    result = compute_platform_fair_value(
        ticker="ZOMATO.NS",
        sector="Internet Platform",
        financials=_fin(growth=0.40),
        peers=_peers([5, 5, 5, 5], growths=[0.20, 0.20, 0.20, 0.20]),
    )
    assert result is not None
    assert result["_meta"]["growth_adj"] == 1.6  # clamped


def test_growth_adjustment_floors_when_target_undergrows():
    """Target growth 5% vs peer median 30% → adj 0.17, clamped to 0.6."""
    result = compute_platform_fair_value(
        ticker="POLICYBZR.NS",
        sector="Internet Platform",
        financials=_fin(growth=0.05),
        peers=_peers([5, 5, 5, 5], growths=[0.30, 0.30, 0.30, 0.30]),
    )
    assert result is not None
    assert result["_meta"]["growth_adj"] == 0.6  # clamped


# ── compute_platform_fair_value — refuse-to-fire cases ────────


def test_non_platform_sector_returns_none():
    """Sector "Pharma" not recognised → None."""
    result = compute_platform_fair_value(
        ticker="SUNPHARMA.NS",
        sector="Pharma",
        financials=_fin(),
        peers=_peers([5, 6, 7]),
    )
    assert result is None


def test_insufficient_peers_returns_none():
    """< 3 peers with valid P/S → None."""
    result = compute_platform_fair_value(
        ticker="PAYTM.NS",
        sector="Internet Platform",
        financials=_fin(),
        peers=_peers([5, 6]),  # only 2 peers
    )
    assert result is None


def test_missing_revenue_returns_none():
    """No revenue → can't compute P/S → None."""
    result = compute_platform_fair_value(
        ticker="PAYTM.NS",
        sector="Internet Platform",
        financials={"shares": 60e7, "current_price": 1000},
        peers=_peers([5, 6, 7, 8]),
    )
    assert result is None


def test_target_excluded_from_peer_set():
    """Target itself is in peers list → must be filtered out."""
    peers_with_self = [
        {"ticker": "PAYTM", "ps": 99},   # absurd value; if not excluded, skews median
        {"ticker": "P1", "ps": 6},
        {"ticker": "P2", "ps": 7},
        {"ticker": "P3", "ps": 8},
    ]
    result = compute_platform_fair_value(
        ticker="PAYTM.NS",
        sector="Internet Platform",
        financials=_fin(),
        peers=peers_with_self,
    )
    assert result is not None
    # Median should be 7 (of 6, 7, 8) — not include the 99
    assert result["_meta"]["peer_ps_median"] == 7.0


def test_peer_ps_out_of_band_filtered():
    """Peer with P/S 100 (above MAX_PEER_PS=40) is data noise → filtered."""
    result = compute_platform_fair_value(
        ticker="ZOMATO.NS",
        sector="Internet Platform",
        financials=_fin(),
        peers=_peers([5, 6, 7, 100, 200]),
    )
    assert result is not None
    # Only 5, 6, 7 should remain → median 6
    assert result["_meta"]["peer_ps_median"] == 6.0
    assert result["_meta"]["n_peers"] == 3


# ── Confidence cap ────────────────────────────────────────────


def test_confidence_capped_at_65():
    """Even with 20 peers, confidence shouldn't exceed 65 (P/S is
    inherently noisier than P/E)."""
    result = compute_platform_fair_value(
        ticker="PAYTM.NS",
        sector="Internet Platform",
        financials=_fin(),
        peers=_peers([6] * 20),
    )
    assert result is not None
    assert result["confidence_score"] <= 65


def test_market_cap_revenue_derives_ps_when_explicit_ps_missing():
    """Peer with mcap+revenue_cr but no explicit ps → derive P/S."""
    peers = [
        {"ticker": "P1", "market_cap_cr": 5000, "revenue_cr": 1000},  # ps=5
        {"ticker": "P2", "market_cap_cr": 6000, "revenue_cr": 1000},  # ps=6
        {"ticker": "P3", "market_cap_cr": 7000, "revenue_cr": 1000},  # ps=7
    ]
    result = compute_platform_fair_value(
        ticker="PAYTM.NS",
        sector="Internet Platform",
        financials=_fin(),
        peers=peers,
    )
    assert result is not None
    assert result["_meta"]["peer_ps_median"] == 6.0
