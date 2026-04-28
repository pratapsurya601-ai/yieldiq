# tests/test_peer_cap.py
# ═══════════════════════════════════════════════════════════════
# Tests for backend.services.peer_cap_service.compute_peer_cap.
#
# Mocks the four DB fetcher helpers so tests run hermetic — they
# do NOT exercise the real Aiven Postgres. Each test pins the
# (sector, industry) classification, the target's own current
# multiples + price, and the peer multiple distribution, then
# asserts the cap math.
#
# Cap math: peer_implied_fv = target_price × (peer_median / target_multiple).
# This is ratio-based on purpose — keeps unit conventions out of the
# loop (target_pe and peer_pe are dimensionless; multiplying by
# target_price gives rupees regardless of how shares_outstanding
# was recorded upstream).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.services import peer_cap_service as pcs


def _patch_fetchers(
    monkeypatch,
    classification,
    target_multiples,
    target_price,
    peers,
):
    """Patch the four fetchers + the session factory."""
    monkeypatch.setattr(pcs, "_get_session", lambda: object())
    monkeypatch.setattr(
        pcs, "_fetch_target_classification",
        lambda session, t: classification,
    )
    monkeypatch.setattr(
        pcs, "_fetch_target_multiples",
        lambda session, t: target_multiples,
    )
    monkeypatch.setattr(
        pcs, "_fetch_target_price",
        lambda session, t: target_price,
    )
    monkeypatch.setattr(
        pcs, "_fetch_peer_multiples",
        lambda session, t, sector, industry: peers,
    )


def test_cap_fires_when_dcf_far_above_peer_pe(monkeypatch):
    """Target is trading at 60× P/E vs. peer-median 21×.
    Peer-implied FV = price × (21 / 60) = 1000 × 0.35 = 350.
    Caller-side ceiling 1.5×350 = 525 < dcf_fv (3000) → cap fires."""
    _patch_fetchers(
        monkeypatch,
        {"sector": "Technology", "industry": "Information Technology Services"},
        {"pe_ratio": 60.0, "pb_ratio": 12.0, "ev_ebitda": 30.0, "market_cap_cr": 5000.0},
        1000.0,
        [
            {"pe_ratio": 18, "pb_ratio": 4, "ev_ebitda": 12, "market_cap_cr": 1000},
            {"pe_ratio": 20, "pb_ratio": 5, "ev_ebitda": 14, "market_cap_cr": 2000},
            {"pe_ratio": 22, "pb_ratio": 6, "ev_ebitda": 16, "market_cap_cr": 5000},
            {"pe_ratio": 24, "pb_ratio": 7, "ev_ebitda": 18, "market_cap_cr": 8000},
        ],
    )
    out = pcs.compute_peer_cap("FAKETECH")
    assert out is not None
    # median P/E = (20+22)/2 = 21 → P/E-implied = 1000 × 21/60 = 350
    # median EV/EBITDA = 15 → EV/EBITDA-implied = 1000 × 15/30 = 500
    # min = 350 (P/E wins)
    assert abs(out["peer_fv"] - 350.0) < 1e-6
    assert out["method"] == "min(pe,ev_ebitda)"
    assert out["n_peers"] == 4
    assert not out["is_bank"]
    assert 1.5 * out["peer_fv"] < 3000


def test_cap_does_not_fire_when_dcf_near_peer_pe(monkeypatch):
    """Target trading near peer-median multiples → 1.5× headroom
    swallows DCF FV; cap does NOT fire."""
    _patch_fetchers(
        monkeypatch,
        {"sector": "Technology", "industry": "Information Technology Services"},
        {"pe_ratio": 22.0, "pb_ratio": 5.5, "ev_ebitda": 14.0, "market_cap_cr": 5000.0},
        1000.0,
        [
            {"pe_ratio": 18, "pb_ratio": 4, "ev_ebitda": 12, "market_cap_cr": 1000},
            {"pe_ratio": 20, "pb_ratio": 5, "ev_ebitda": 14, "market_cap_cr": 2000},
            {"pe_ratio": 22, "pb_ratio": 6, "ev_ebitda": 16, "market_cap_cr": 5000},
            {"pe_ratio": 24, "pb_ratio": 7, "ev_ebitda": 18, "market_cap_cr": 8000},
        ],
    )
    out = pcs.compute_peer_cap("FAKETECH")
    assert out is not None
    # peer_implied_fv = 1000 × min(21/22, 15/14) = 1000 × min(0.954, 1.071)
    #                 = 954.5
    assert abs(out["peer_fv"] - (1000 * 21 / 22)) < 1e-3
    # ceiling = 1.5 × 954.5 ≈ 1431.8; if DCF FV is 1100 (below 1431) cap doesn't fire
    dcf_fv = 1100.0
    assert 1.5 * out["peer_fv"] >= dcf_fv


def test_no_peers_returns_none(monkeypatch):
    """Fewer than _MIN_PEERS liquid peers → return None (no cap)."""
    _patch_fetchers(
        monkeypatch,
        {"sector": "Real Estate", "industry": "Specialty REITs"},
        {"pe_ratio": 25.0, "pb_ratio": 3.0, "ev_ebitda": 15.0, "market_cap_cr": 2000.0},
        500.0,
        [
            {"pe_ratio": 15, "pb_ratio": 1.5, "ev_ebitda": 10, "market_cap_cr": 1000},
            {"pe_ratio": 20, "pb_ratio": 2.0, "ev_ebitda": 12, "market_cap_cr": 2000},
        ],
    )
    out = pcs.compute_peer_cap("FAKEREIT")
    assert out is None


def test_null_ebitda_falls_back_to_pe_only(monkeypatch):
    """Target has no EV/EBITDA multiple → method becomes pe_only."""
    _patch_fetchers(
        monkeypatch,
        {"sector": "Industrials", "industry": "Specialty Industrial"},
        {"pe_ratio": 60.0, "pb_ratio": 5.0, "ev_ebitda": None, "market_cap_cr": 3000.0},
        1500.0,
        [
            {"pe_ratio": 25, "pb_ratio": 3, "ev_ebitda": 15, "market_cap_cr": 1500},
            {"pe_ratio": 30, "pb_ratio": 4, "ev_ebitda": 18, "market_cap_cr": 3000},
            {"pe_ratio": 35, "pb_ratio": 5, "ev_ebitda": 20, "market_cap_cr": 5000},
        ],
    )
    out = pcs.compute_peer_cap("FAKEIND")
    assert out is not None
    # median P/E = 30 → P/E-implied = 1500 × 30/60 = 750
    assert abs(out["peer_fv"] - 750.0) < 1e-6
    assert out["method"] == "pe_only"


def test_bank_uses_pb_path(monkeypatch):
    """Financial Services sector → P/B-only cap; P/E and EV/EBITDA
    ignored even when populated."""
    _patch_fetchers(
        monkeypatch,
        {"sector": "Financial Services", "industry": "Banks - Regional"},
        {"pe_ratio": 14.0, "pb_ratio": 4.0, "ev_ebitda": None, "market_cap_cr": 80000.0},
        2000.0,
        [
            {"pe_ratio": 12, "pb_ratio": 1.5, "ev_ebitda": None, "market_cap_cr": 50000},
            {"pe_ratio": 14, "pb_ratio": 2.0, "ev_ebitda": None, "market_cap_cr": 80000},
            {"pe_ratio": 16, "pb_ratio": 2.5, "ev_ebitda": None, "market_cap_cr": 120000},
        ],
    )
    out = pcs.compute_peer_cap("FAKEBANK")
    assert out is not None
    assert out["method"] == "pb"
    assert out["is_bank"] is True
    # median P/B = 2.0 → P/B-implied = 2000 × 2.0/4.0 = 1000
    assert abs(out["peer_fv"] - 1000.0) < 1e-6


def test_unknown_ticker_returns_none(monkeypatch):
    """Ticker not present in `stocks` table → None."""
    _patch_fetchers(
        monkeypatch,
        None,
        {"pe_ratio": 20.0, "pb_ratio": 3.0, "ev_ebitda": 10.0, "market_cap_cr": 1000.0},
        500.0,
        [],
    )
    out = pcs.compute_peer_cap("NOSUCHTICKER")
    assert out is None


def test_db_unreachable_returns_none(monkeypatch):
    """Session factory returns None → graceful None."""
    monkeypatch.setattr(pcs, "_get_session", lambda: None)
    out = pcs.compute_peer_cap("ANYTICKER")
    assert out is None


def test_no_anchor_price_returns_none(monkeypatch):
    """Without a current price, ratio-based FV is undefined → None."""
    _patch_fetchers(
        monkeypatch,
        {"sector": "Technology", "industry": "Software"},
        {"pe_ratio": 30.0, "pb_ratio": 5.0, "ev_ebitda": 15.0, "market_cap_cr": 2000.0},
        None,  # no price anchor
        [
            {"pe_ratio": 25, "pb_ratio": 4, "ev_ebitda": 12, "market_cap_cr": 1000},
            {"pe_ratio": 30, "pb_ratio": 5, "ev_ebitda": 15, "market_cap_cr": 2000},
            {"pe_ratio": 35, "pb_ratio": 6, "ev_ebitda": 18, "market_cap_cr": 5000},
        ],
    )
    out = pcs.compute_peer_cap("FAKESOFT")
    assert out is None


def test_target_zero_pe_returns_none_for_non_bank(monkeypatch):
    """Target P/E and EV/EBITDA both null/zero → no candidates → None.
    Guards against a divide-by-zero on a loss-making target."""
    _patch_fetchers(
        monkeypatch,
        {"sector": "Technology", "industry": "Software"},
        {"pe_ratio": None, "pb_ratio": 5.0, "ev_ebitda": None, "market_cap_cr": 2000.0},
        500.0,
        [
            {"pe_ratio": 25, "pb_ratio": 5, "ev_ebitda": 15, "market_cap_cr": 1000},
            {"pe_ratio": 30, "pb_ratio": 6, "ev_ebitda": 18, "market_cap_cr": 2000},
            {"pe_ratio": 35, "pb_ratio": 7, "ev_ebitda": 20, "market_cap_cr": 5000},
        ],
    )
    out = pcs.compute_peer_cap("FAKESOFT")
    assert out is None


def test_ev_ebitda_more_conservative_wins(monkeypatch):
    """When EV/EBITDA-implied is below P/E-implied, the cap takes
    EV/EBITDA — the lower (more conservative) ceiling."""
    _patch_fetchers(
        monkeypatch,
        {"sector": "Consumer Defensive", "industry": "Household & Personal Products"},
        {"pe_ratio": 60.0, "pb_ratio": 10.0, "ev_ebitda": 40.0, "market_cap_cr": 8000.0},
        500.0,
        [
            {"pe_ratio": 50, "pb_ratio": 8, "ev_ebitda": 10, "market_cap_cr": 5000},
            {"pe_ratio": 55, "pb_ratio": 9, "ev_ebitda": 12, "market_cap_cr": 8000},
            {"pe_ratio": 60, "pb_ratio": 10, "ev_ebitda": 14, "market_cap_cr": 10000},
        ],
    )
    out = pcs.compute_peer_cap("FAKEFMCG")
    assert out is not None
    # median P/E = 55 → P/E-implied = 500 × 55/60 = 458.33
    # median EV/EBITDA = 12 → EV/EBITDA-implied = 500 × 12/40 = 150
    # min = 150 (EV/EBITDA wins)
    assert abs(out["peer_fv"] - 150.0) < 1e-6
    assert out["method"] == "min(pe,ev_ebitda)"
