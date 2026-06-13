"""B1 DCF scale-fix — regression pins.

Root cause (2026-06-13): USD-reporter Financials rows are converted
USD→INR at INGEST (data/collector._detect_financial_currency × 83.5)
but keep currency='USD'. The read-path _convert_row_to_inr then
multiplied a SECOND time because its idempotency guard compared raw
revenue against 1e10 — a threshold valid only if the table stored
ABSOLUTE rupees. The `financials` table stores ₹ CRORE, so the guard
(off by ~7 orders of magnitude) never fired and every already-converted
USD reporter got an 83.5× FCF leak. PERSISTENT's DCF produced
pv_fcfs ≈ ₹9.66 TRILLION on a ₹0.79T company; the per-share IV cap
(5× price) masked it and the ticker silently degraded to data_limited.

Two guards pinned here:

  Part 1 — _convert_row_to_inr now suppresses the second multiply via a
           market-cap anchor (revenue×83.5 cannot exceed 2× market cap)
           with a crore-magnitude fallback (>5,000 cr). It still applies
           ×83.5 to GENUINELY-USD rows (INFY-shape), so the fix is
           surgical, not a blanket disable.

  Part 2 — DCFEngine rejects the DCF outright (iv=0, suspicious=True,
           dcf_scale_rejected=True) when sum_pv_fcfs > EV_SANITY_MULT ×
           market cap, instead of laundering garbage through the 5×
           price cap.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

import pytest

from screener.dcf_engine import DCFEngine, EV_SANITY_MULT


# ──────────────────────────────────────────────────────────────────
# Part 1 — read-path double-convert guard
# ──────────────────────────────────────────────────────────────────

def _row(currency, revenue, fcf, pat=None):
    return SimpleNamespace(
        currency=currency, revenue=revenue, free_cash_flow=fcf,
        pat=pat if pat is not None else fcf,
    )


def test_persistent_shape_already_inr_not_double_converted(monkeypatch):
    """PERSISTENT-shape: ccy=USD but rev/fcf already in ₹ crore
    (rev=14748 cr, fcf=1558.5 cr, mcap=78717 cr). The mcap anchor must
    suppress the ×83.5 second multiply → fcf stays ~1558, NOT ~130138."""
    import backend.services.analysis.db as dbmod
    monkeypatch.setattr(dbmod, "_market_cap_cr", lambda t: 78717.0)

    fcf, rev, pat = dbmod._convert_row_to_inr(
        "PERSISTENT", _row("USD", revenue=14748.449, fcf=1558.549),
    )
    assert fcf == pytest.approx(1558.549, rel=1e-6), (
        f"already-INR USD-tagged row must NOT be ×83.5'd (got {fcf})"
    )
    assert rev == pytest.approx(14748.449, rel=1e-6)


def test_genuine_usd_row_still_converted(monkeypatch):
    """INFY-shape: ccy=USD and values genuinely USD-magnitude
    (rev=2015.8, fcf=373.3) on a ₹484,820 cr company. Converting gives
    a sane rev/mcap (~0.35), so the ×83.5 MUST be applied."""
    import backend.services.analysis.db as dbmod
    monkeypatch.setattr(dbmod, "_market_cap_cr", lambda t: 484820.0)

    fcf, rev, pat = dbmod._convert_row_to_inr(
        "INFY", _row("USD", revenue=2015.8, fcf=373.3),
    )
    assert fcf == pytest.approx(373.3 * 83.5, rel=1e-6), (
        f"genuine-USD row must be ×83.5'd (got {fcf})"
    )


def test_inr_row_untouched(monkeypatch):
    """A plain INR row is never multiplied (mult=1.0)."""
    import backend.services.analysis.db as dbmod
    monkeypatch.setattr(dbmod, "_market_cap_cr", lambda t: 795581.0)

    fcf, rev, pat = dbmod._convert_row_to_inr(
        "TCS", _row("INR", revenue=267021.0, fcf=47948.0),
    )
    assert fcf == pytest.approx(47948.0, rel=1e-6)
    assert rev == pytest.approx(267021.0, rel=1e-6)


def test_crore_magnitude_fallback_when_mcap_missing(monkeypatch):
    """When market cap is unavailable, the crore-magnitude fallback
    (>5,000 cr) still catches an already-INR USD-tagged row."""
    import backend.services.analysis.db as dbmod
    monkeypatch.setattr(dbmod, "_market_cap_cr", lambda t: None)

    fcf, rev, pat = dbmod._convert_row_to_inr(
        "PERSISTENT", _row("USD", revenue=14748.449, fcf=1558.549),
    )
    assert fcf == pytest.approx(1558.549, rel=1e-6)


# ──────────────────────────────────────────────────────────────────
# Part 2 — DCFEngine EV/market-cap sanity clamp
# ──────────────────────────────────────────────────────────────────

def _proj(fcf0, years=10, g=0.08):
    out, f = [], fcf0
    for _ in range(years):
        f *= (1 + g)
        out.append(f)
    return out


def test_clamp_rejects_inflated_dcf():
    """An 83.5×-inflated FCF stream (PERSISTENT-buggy shape) must be
    rejected outright, NOT laundered through the 5×-price IV cap."""
    mcap = 78717e7  # ₹78,717 cr in raw rupees
    proj = _proj(130139e7)  # buggy ₹130,139 cr FCF base
    tnorm = sum(proj[-3:]) / 3
    eng = DCFEngine(discount_rate=0.11, terminal_growth=0.04, ticker="LEAK")
    res = eng.intrinsic_value_per_share(
        projected_fcfs=proj, terminal_fcf_norm=tnorm,
        total_debt=0, total_cash=0, shares_outstanding=156231044.0,
        current_price=4811.0, ticker="LEAK", market_cap=mcap,
    )
    assert res.get("dcf_scale_rejected") is True
    assert res["intrinsic_value_per_share"] == 0.0
    assert res["suspicious"] is True
    assert any("rejected" in w.lower() for w in res["warnings"])


def test_clamp_leaves_healthy_dcf_alone():
    """A sane FCF stream (PERSISTENT-fixed shape, ₹1,558 cr base) must
    NOT be rejected — the clamp only fires on garbage."""
    mcap = 78717e7
    proj = _proj(1558.5e7)  # fixed ₹1,558.5 cr FCF base
    tnorm = sum(proj[-3:]) / 3
    eng = DCFEngine(discount_rate=0.11, terminal_growth=0.04, ticker="OK")
    res = eng.intrinsic_value_per_share(
        projected_fcfs=proj, terminal_fcf_norm=tnorm,
        total_debt=0, total_cash=0, shares_outstanding=156231044.0,
        current_price=4811.0, ticker="OK", market_cap=mcap,
    )
    assert res.get("dcf_scale_rejected") in (None, False)
    assert res["intrinsic_value_per_share"] > 0


def test_clamp_noop_when_no_market_cap_reference():
    """When neither market_cap nor price×shares yields a positive
    reference, the clamp must not fire (no false-positive on missing
    data)."""
    proj = _proj(130139e7)
    tnorm = sum(proj[-3:]) / 3
    eng = DCFEngine(discount_rate=0.11, terminal_growth=0.04, ticker="NOMCAP")
    res = eng.intrinsic_value_per_share(
        projected_fcfs=proj, terminal_fcf_norm=tnorm,
        total_debt=0, total_cash=0, shares_outstanding=156231044.0,
        current_price=0.0, ticker="NOMCAP", market_cap=None,
    )
    assert res.get("dcf_scale_rejected") in (None, False)


def test_ev_sanity_mult_is_documented_value():
    assert EV_SANITY_MULT == 10.0
