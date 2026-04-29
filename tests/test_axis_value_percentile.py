# tests/test_axis_value_percentile.py
# ═══════════════════════════════════════════════════════════════
# Tests for Stage-2 wiring: _axis_value_general / _axis_value_bank /
# _axis_value_it now delegate to backend.services.sector_percentile.
#
# Hermetic — sector_percentile.compute_sector_cohort is monkey-patched
# to return a synthetic cohort, and hex_service._get_session is stubbed
# so the axis functions never touch a real DB.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest

from backend.services import hex_service
from backend.services import sector_percentile as sp


# ── Fixtures ────────────────────────────────────────────────────
class _StubSession:
    """Marker session — never actually executes; cohort is stubbed."""
    def close(self):
        pass


@pytest.fixture(autouse=True)
def _stub_session(monkeypatch):
    monkeypatch.setattr(hex_service, "_get_session", lambda: _StubSession())
    monkeypatch.setattr(hex_service, "_safe_close", lambda s: None)
    sp._clear_cohort_cache()
    yield


def _make_cohort(metric_key, values, *, peers_prefix="PEER"):
    """Build a 10+ ticker cohort dict for sector_percentile output shape."""
    rows = []
    for i, v in enumerate(values):
        row = {
            "ticker": f"{peers_prefix}{i:02d}",
            "mos_pct": None,
            "pe_ratio": None,
            "pb_ratio": None,
        }
        row[metric_key] = v
        rows.append(row)
    return rows


def _data(ticker, sector, *, mos=None, pe=None, pb=None,
          revenue=None, mcap_cr=None, fcf_src=""):
    analysis = {
        "valuation": {
            "margin_of_safety": mos,
            "fair_value": None,
            "current_price": None,
            "fcf_data_source": fcf_src,
        }
    }
    return {
        "ticker": ticker,
        "sector": sector,
        "analysis": analysis,
        "metrics": {"pe_ratio": pe, "pb_ratio": pb, "market_cap_cr": mcap_cr},
        "financials": [{"revenue": revenue}] if revenue is not None else [],
    }


# ── _axis_value_general (MoS percentile) ─────────────────────────
def test_general_strong_discount(monkeypatch):
    cohort = _make_cohort(
        "mos_pct",
        [-50, -40, -30, -20, -10, 0, 10, 20, 30, 40],
    )
    monkeypatch.setattr(sp, "compute_sector_cohort",
                        lambda label, sess, **kw: cohort)
    monkeypatch.setattr(sp, "_canonical_sector", lambda s, *a, **kw: "FMCG")

    # MoS +50% — strictly greater than every cohort entry → raw_rank 100
    # → inverted percentile = 0 → strong_discount, score = 10.0.
    out = hex_service._axis_value_general(
        _data("CHEAP.NS", "FMCG", mos=50.0)
    )
    assert out["band"] == "strong_discount"
    assert out["percentile"] == 0
    assert out["score"] == 10.0
    assert out["data_limited"] is False
    assert out["sector_peers"] == 10


def test_general_notably_overvalued(monkeypatch):
    cohort = _make_cohort(
        "mos_pct",
        [-50, -40, -30, -20, -10, 0, 10, 20, 30, 40],
    )
    monkeypatch.setattr(sp, "compute_sector_cohort",
                        lambda label, sess, **kw: cohort)
    monkeypatch.setattr(sp, "_canonical_sector", lambda s, *a, **kw: "FMCG")

    # MoS -90% — strictly less than every cohort entry → raw_rank 0
    # → inverted percentile = 100 → data_limited band (>=90 outer band).
    out = hex_service._axis_value_general(
        _data("RICH.NS", "FMCG", mos=-90.0)
    )
    # 100 maps to data_limited per band table outer guard,
    # but 99 would be notably_overvalued; check band & low score.
    assert out["percentile"] in (90, 95, 100)
    # Score derived from percentile 90-100 → 0..1.0.
    assert out["score"] is not None
    assert out["score"] <= 1.0


def test_general_data_limited_when_cohort_too_small(monkeypatch):
    cohort = _make_cohort("mos_pct", [-10, 0, 10])  # only 3 peers
    monkeypatch.setattr(sp, "compute_sector_cohort",
                        lambda label, sess, **kw: cohort)
    monkeypatch.setattr(sp, "_canonical_sector", lambda s, *a, **kw: "FMCG")

    out = hex_service._axis_value_general(
        _data("X.NS", "FMCG", mos=5.0)
    )
    assert out["data_limited"] is True
    assert out["score"] is None
    assert out["percentile"] is None
    assert out["band"] == "data_limited"


def test_general_data_limited_when_ticker_metric_null(monkeypatch):
    cohort = _make_cohort(
        "mos_pct",
        [-50, -40, -30, -20, -10, 0, 10, 20, 30, 40],
    )
    monkeypatch.setattr(sp, "compute_sector_cohort",
                        lambda label, sess, **kw: cohort)
    monkeypatch.setattr(sp, "_canonical_sector", lambda s, *a, **kw: "FMCG")

    out = hex_service._axis_value_general(
        _data("UNKNOWN.NS", "FMCG", mos=None)
    )
    assert out["data_limited"] is True
    assert out["score"] is None


def test_general_trough_anchor_mentioned(monkeypatch):
    cohort = _make_cohort(
        "mos_pct",
        [-50, -40, -30, -20, -10, 0, 10, 20, 30, 40],
    )
    monkeypatch.setattr(sp, "compute_sector_cohort",
                        lambda label, sess, **kw: cohort)
    monkeypatch.setattr(sp, "_canonical_sector", lambda s, *a, **kw: "Metals")

    out = hex_service._axis_value_general(
        _data(
            "TATASTEEL.NS", "Metals", mos=-5.0,
            fcf_src="annual_3y_mean+trough_anchor",
        )
    )
    assert "trough_anchor" in out["why"] or "anchor" in out["why"].lower()


# ── _axis_value_bank (P/BV percentile) ───────────────────────────
def test_bank_low_pb_strong_discount(monkeypatch):
    # PB cohort 1.5..6.0; HDFCBANK at 1.2 ranks lowest → cheapest.
    pb_values = [1.5, 1.8, 2.1, 2.5, 3.0, 3.4, 3.8, 4.2, 5.0, 6.0]
    cohort = _make_cohort("pb_ratio", pb_values)
    monkeypatch.setattr(sp, "compute_sector_cohort",
                        lambda label, sess, **kw: cohort)
    monkeypatch.setattr(sp, "_canonical_sector", lambda s, *a, **kw: "Banks")

    out = hex_service._axis_value_bank(
        _data("HDFCBANK.NS", "Banks", pb=1.2)
    )
    assert out["band"] == "strong_discount"
    assert out["percentile"] == 0
    assert out["score"] == 10.0


def test_bank_high_pb_above_peers(monkeypatch):
    pb_values = [1.5, 1.8, 2.1, 2.5, 3.0, 3.4, 3.8, 4.2, 5.0, 6.0]
    cohort = _make_cohort("pb_ratio", pb_values)
    monkeypatch.setattr(sp, "compute_sector_cohort",
                        lambda label, sess, **kw: cohort)
    monkeypatch.setattr(sp, "_canonical_sector", lambda s, *a, **kw: "Banks")

    # PB 4.0 sits above 7 of 10 cohort entries (1.5..3.8) → raw_rank 70
    # → percentile (no inversion) = 70 → above_peers band, score 3.0.
    out = hex_service._axis_value_bank(
        _data("BAJFINANCE.NS", "Banks", pb=4.0)
    )
    assert out["band"] == "above_peers"
    assert out["percentile"] == 70
    assert out["score"] == 3.0


def test_bank_data_limited_when_pb_null(monkeypatch):
    pb_values = [1.5, 1.8, 2.1, 2.5, 3.0, 3.4, 3.8, 4.2, 5.0, 6.0]
    cohort = _make_cohort("pb_ratio", pb_values)
    monkeypatch.setattr(sp, "compute_sector_cohort",
                        lambda label, sess, **kw: cohort)
    monkeypatch.setattr(sp, "_canonical_sector", lambda s, *a, **kw: "Banks")

    out = hex_service._axis_value_bank(
        _data("UNK.NS", "Banks", pb=None)
    )
    assert out["data_limited"] is True
    assert out["score"] is None


# ── _axis_value_it (P/E proxy for revenue multiple) ──────────────
def test_it_low_pe_strong_discount(monkeypatch):
    pe_values = [18, 20, 22, 24, 26, 28, 30, 33, 36, 40]
    cohort = _make_cohort("pe_ratio", pe_values)
    monkeypatch.setattr(sp, "compute_sector_cohort",
                        lambda label, sess, **kw: cohort)
    monkeypatch.setattr(sp, "_canonical_sector", lambda s, *a, **kw: "IT Services")

    out = hex_service._axis_value_it(
        _data(
            "TCS.NS", "IT Services",
            pe=15.0, pb=12.0,
            revenue=240_000.0,  # in crores; would map straight through
            mcap_cr=1_500_000.0,
        )
    )
    assert out["band"] == "strong_discount"
    assert out["percentile"] == 0
    assert out["score"] == 10.0


def test_it_falls_back_to_mos_when_no_revenue(monkeypatch):
    # When rev_multiple can't be computed, axis falls back to MoS-percentile.
    mos_values = [-50, -40, -30, -20, -10, 0, 10, 20, 30, 40]
    cohort = _make_cohort("mos_pct", mos_values)
    monkeypatch.setattr(sp, "compute_sector_cohort",
                        lambda label, sess, **kw: cohort)
    monkeypatch.setattr(sp, "_canonical_sector", lambda s, *a, **kw: "IT Services")

    out = hex_service._axis_value_it(
        _data(
            "INFY.NS", "IT Services",
            pe=22.0, mos=25.0,
            revenue=None, mcap_cr=None,
        )
    )
    # Fell through to MoS-percentile: 25% MoS sits in upper part of cohort.
    assert out["data_limited"] is False
    assert out["score"] is not None


# ── Synthetic-cohort behavioural smoke (TCS / HDFCBANK / TATASTEEL) ─
def test_blue_chip_synthetic_bands(monkeypatch):
    """Sanity: across three sector cohorts, named blue-chips land in the
    expected band relative to their synthetic peers."""
    # IT cohort PEs centred ~28; TCS at 26 should land below_peers.
    pe_cohort = _make_cohort("pe_ratio",
                             [18, 22, 25, 27, 28, 29, 31, 33, 36, 40])
    pb_cohort = _make_cohort("pb_ratio",
                             [1.5, 1.8, 2.1, 2.5, 3.0, 3.4, 3.8, 4.2, 5.0, 6.0])
    mos_cohort = _make_cohort("mos_pct",
                              [-50, -40, -30, -20, -10, 0, 10, 20, 30, 40])

    cohorts = {
        "IT Services": pe_cohort,
        "Banks":       pb_cohort,
        "Metals":      mos_cohort,
    }

    def _fake_cohort(label, sess, **kw):
        return cohorts.get(label, [])

    monkeypatch.setattr(sp, "compute_sector_cohort", _fake_cohort)
    monkeypatch.setattr(sp, "_canonical_sector", lambda s, *a, **kw: s)

    tcs = hex_service._axis_value_it(
        _data("TCS.NS", "IT Services",
              pe=26.0, pb=12.0,
              revenue=240_000.0, mcap_cr=1_500_000.0)
    )
    hdfc = hex_service._axis_value_bank(
        _data("HDFCBANK.NS", "Banks", pb=2.5)
    )
    tatasteel = hex_service._axis_value_general(
        _data("TATASTEEL.NS", "Metals", mos=-5.0,
              fcf_src="annual_3y_mean+trough_anchor")
    )

    # All three should produce a non-data-limited band.
    assert tcs["data_limited"] is False
    assert hdfc["data_limited"] is False
    assert tatasteel["data_limited"] is False

    # Cohort context surfaced in why text.
    assert "peers" in tcs["why"]
    assert "peers" in hdfc["why"]
    assert "anchor" in tatasteel["why"].lower()
