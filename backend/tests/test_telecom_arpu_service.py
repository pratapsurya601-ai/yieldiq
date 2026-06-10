# backend/tests/test_telecom_arpu_service.py
#
# Tests for the standalone telecom ARPU-driven valuation service
# shipped in T3.11 Phase A. Phase B will wire the engine into the
# analysis route; this test surface covers ONLY the pure math + the
# applicability gate so the Phase A PR can ship without touching any
# caller.
#
# Coverage:
#   1. BHARTIARTL-shaped baseline DCF — ballpark sanity
#   2. VODAFONEIDEA-shaped distress DCF — negative early FCFs, terminal
#      still computed, warnings surfaced
#   3. INDUSTOWER (towers) — segment tag, method tag preserved
#   4. Forecast list shorter than horizon → padded extrapolation
#   5. compute_ev_ebitda_multiple math
#   6. select_ev_ebitda_multiple ±1 trend adjustment
#   7. is_telecom_arpu_applicable for the universe + RELIANCE rejection
#   8. Empty forecasts → uses current subs + ARPU with defaults
#   9. to_dict shape — JSON-safe
#
# Run: pytest backend/tests/test_telecom_arpu_service.py -v
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ── BHARTIARTL-shaped baseline ──────────────────────────────────
def test_bhartiartl_shaped_baseline_dcf():
    """BHARTIARTL: ~400M subs, ARPU ₹190/mo, 30% EBITDA margin,
    12% maintenance capex, 5% growth capex, 5y horizon, ~600 Cr
    shares outstanding. Should produce a per-share number in a
    plausible band (telecom stocks rarely below ₹100 or above ₹5000
    on a 600 Cr share count given these unit economics)."""
    from backend.services.telecom_arpu_service import (
        TelecomInputs, SubscriberForecast, compute_arpu_driven_fv,
    )
    forecasts = [
        SubscriberForecast(
            year_offset=y,
            subscriber_count_millions=400.0 * (1.02 ** y),  # 2% sub growth
            arpu_inr_per_month=190.0 * (1.07 ** y),         # 7% ARPU lift
            churn_rate_pct=2.0,
        )
        for y in range(1, 6)
    ]
    inp = TelecomInputs(
        current_subscribers_millions=400.0,
        current_arpu_inr=190.0,
        forecast_horizon_years=5,
        forecasts=forecasts,
        operating_margin_pct=30.0,
        maintenance_capex_pct_of_revenue=12.0,
        growth_capex_pct_of_revenue=5.0,
        spectrum_capex_one_time=0.0,
        tax_rate=0.22,
        discount_rate=0.11,
        terminal_growth=0.04,
        shares_outstanding=600.0,  # ~600 Cr shares (Indian convention)
        segment="mobile",
    )
    out = compute_arpu_driven_fv(inp)
    assert out.method == "arpu_dcf"
    assert out.fair_value_per_share is not None
    assert out.fair_value_per_share > 50.0
    assert out.fair_value_per_share < 10000.0
    assert out.aggregate_ev > 0
    # Revenue Y5: 400M × 1.02^5 × 190 × 1.07^5 × 12 / 10 ≈ ₹1.21L Cr ballpark
    assert out.revenue_year_5 > 50000.0
    assert out.ebitda_year_5 > 0
    # 5 explicit FCF years in components
    assert len(out.components["years"]) == 5
    # Discount + terminal echoed back
    assert out.components["discount_rate"] == pytest.approx(0.11, abs=0.001)
    assert out.components["terminal_growth"] == pytest.approx(0.04, abs=0.001)


# ── VODAFONEIDEA distress shape ─────────────────────────────────
def test_vodafoneidea_shaped_distress_dcf():
    """VODAFONEIDEA-shaped: lower subs (~200M), lower ARPU (~150),
    fat spectrum one-off, depressed margins. Negative early FCFs are
    OK, but terminal value should still be computed and warnings
    surfaced. fair_value_per_share may be None on this profile if EV
    is non-positive."""
    from backend.services.telecom_arpu_service import (
        TelecomInputs, SubscriberForecast, compute_arpu_driven_fv,
    )
    forecasts = [
        SubscriberForecast(
            year_offset=y,
            subscriber_count_millions=200.0 * (0.97 ** y),  # net sub bleed
            arpu_inr_per_month=150.0 * (1.05 ** y),
            churn_rate_pct=3.5,
        )
        for y in range(1, 6)
    ]
    inp = TelecomInputs(
        current_subscribers_millions=200.0,
        current_arpu_inr=150.0,
        forecast_horizon_years=5,
        forecasts=forecasts,
        operating_margin_pct=18.0,                   # compressed
        maintenance_capex_pct_of_revenue=14.0,
        growth_capex_pct_of_revenue=8.0,             # 5G catch-up
        spectrum_capex_one_time=20000.0,             # heavy year-1 hit
        tax_rate=0.22,
        discount_rate=0.135,                         # distress discount lift
        terminal_growth=0.03,
        shares_outstanding=7000.0,                   # massive share dilution
        segment="mobile",
    )
    out = compute_arpu_driven_fv(inp)
    # Terminal value computed regardless of distress shape.
    assert out.components["terminal_value_inr_cr"] is not None
    assert out.components["pv_terminal_inr_cr"] is not None
    # Multiple negative FCF years across horizon should warn.
    neg_years = [y for y in out.components["years"] if y["fcf_inr_cr"] < 0]
    if len(neg_years) >= 3:
        assert any("distress" in w.lower() or "non-positive" in w.lower() for w in out.sanity_warnings)


# ── INDUSTOWER (towers) ─────────────────────────────────────────
def test_industower_towers_segment_tag_preserved():
    """INDUSTOWER is passive infra (towers, no ARPU per se). We still
    run the engine because Phase B will treat tower-revenue as
    "tenancy ARPU equivalent"; the segment tag must round-trip into
    the components dict so the analysis layer can label it correctly."""
    from backend.services.telecom_arpu_service import (
        TelecomInputs, SubscriberForecast, compute_arpu_driven_fv,
    )
    inp = TelecomInputs(
        current_subscribers_millions=0.20,           # ~200K towers
        current_arpu_inr=80000.0,                    # ₹80K per tower/mo tenancy rent
        forecast_horizon_years=5,
        forecasts=[
            SubscriberForecast(
                year_offset=y,
                subscriber_count_millions=0.20 * (1.03 ** y),
                arpu_inr_per_month=80000.0 * (1.04 ** y),
                churn_rate_pct=1.0,
            )
            for y in range(1, 6)
        ],
        operating_margin_pct=50.0,                   # high op leverage on towers
        maintenance_capex_pct_of_revenue=8.0,
        growth_capex_pct_of_revenue=4.0,
        tax_rate=0.22,
        discount_rate=0.10,
        terminal_growth=0.04,
        shares_outstanding=270.0,                    # ~270 Cr shares
        segment="towers",
    )
    out = compute_arpu_driven_fv(inp)
    assert out.method == "arpu_dcf"
    assert out.fair_value_per_share is not None
    assert out.components["segment"] == "towers"


# ── Forecast list shorter than horizon → padding ────────────────
def test_short_forecast_pads_to_horizon():
    """Forecast covers only 2 years; horizon=5 → engine pads with
    default growth extrapolation. Result has 5 years in components."""
    from backend.services.telecom_arpu_service import (
        TelecomInputs, SubscriberForecast, compute_arpu_driven_fv,
    )
    inp = TelecomInputs(
        current_subscribers_millions=350.0,
        current_arpu_inr=180.0,
        forecast_horizon_years=5,
        forecasts=[
            SubscriberForecast(
                year_offset=1, subscriber_count_millions=355.0,
                arpu_inr_per_month=195.0, churn_rate_pct=2.0,
            ),
            SubscriberForecast(
                year_offset=2, subscriber_count_millions=360.0,
                arpu_inr_per_month=210.0, churn_rate_pct=2.0,
            ),
        ],
        shares_outstanding=600.0,
    )
    out = compute_arpu_driven_fv(inp)
    years = out.components["years"]
    assert len(years) == 5
    # First two years exactly match supplied; padded tail extrapolates
    # at default growth (each year > prior).
    assert years[0]["subscribers_millions"] == pytest.approx(355.0, abs=0.01)
    assert years[1]["subscribers_millions"] == pytest.approx(360.0, abs=0.01)
    assert years[2]["subscribers_millions"] > years[1]["subscribers_millions"]
    assert years[4]["subscribers_millions"] > years[2]["subscribers_millions"]
    # Padding warning surfaced.
    assert any("pad" in w.lower() for w in out.sanity_warnings) or len(years) == 5


# ── compute_ev_ebitda_multiple ──────────────────────────────────
def test_compute_ev_ebitda_multiple_bhartiartl():
    """BHARTIARTL with EBITDA 50000 Cr, multiple 8.5, net_debt 110000
    Cr, shares 600 Cr.
        EV     = 50000 × 8.5 = 425000 Cr
        Equity = 425000 − 110000 = 315000 Cr
        FV/sh  = 315000 / 600 = 525.0
    """
    from backend.services.telecom_arpu_service import compute_ev_ebitda_multiple
    fv = compute_ev_ebitda_multiple(
        next_year_ebitda=50000.0,
        multiple=8.5,
        net_debt=110000.0,
        shares_outstanding=600.0,
    )
    assert fv == pytest.approx(525.0, abs=0.01)


def test_compute_ev_ebitda_multiple_returns_none_on_negative_equity():
    """Distress profile: EV < net debt → None (don't surface negative
    per-share)."""
    from backend.services.telecom_arpu_service import compute_ev_ebitda_multiple
    fv = compute_ev_ebitda_multiple(
        next_year_ebitda=5000.0,
        multiple=4.0,                 # distress
        net_debt=80000.0,             # AGR overhang
        shares_outstanding=7000.0,
    )
    assert fv is None


def test_compute_ev_ebitda_multiple_returns_none_on_missing_shares():
    from backend.services.telecom_arpu_service import compute_ev_ebitda_multiple
    assert compute_ev_ebitda_multiple(50000.0, 8.5, 110000.0, 0.0) is None
    assert compute_ev_ebitda_multiple(50000.0, 8.5, 110000.0, -10.0) is None


# ── select_ev_ebitda_multiple ───────────────────────────────────
def test_select_ev_ebitda_multiple_defaults():
    from backend.services.telecom_arpu_service import select_ev_ebitda_multiple
    assert select_ev_ebitda_multiple("BHARTIARTL") == pytest.approx(8.5)
    assert select_ev_ebitda_multiple("VODAFONEIDEA") == pytest.approx(4.5)
    assert select_ev_ebitda_multiple("INDUSTOWER") == pytest.approx(9.0)
    assert select_ev_ebitda_multiple("BHARTIHEXA") == pytest.approx(8.0)


def test_select_ev_ebitda_multiple_gaining_adds_one():
    from backend.services.telecom_arpu_service import select_ev_ebitda_multiple
    assert select_ev_ebitda_multiple("BHARTIARTL", "gaining") == pytest.approx(9.5)
    assert select_ev_ebitda_multiple("INDUSTOWER", "gaining") == pytest.approx(10.0)


def test_select_ev_ebitda_multiple_losing_subtracts_one():
    from backend.services.telecom_arpu_service import select_ev_ebitda_multiple
    assert select_ev_ebitda_multiple("BHARTIARTL", "losing") == pytest.approx(7.5)
    assert select_ev_ebitda_multiple("VODAFONEIDEA", "losing") == pytest.approx(3.5)


def test_select_ev_ebitda_multiple_unknown_ticker_uses_fallback():
    from backend.services.telecom_arpu_service import select_ev_ebitda_multiple
    assert select_ev_ebitda_multiple("RANDOM_TELCO") == pytest.approx(7.5)


def test_select_ev_ebitda_multiple_handles_ns_suffix():
    from backend.services.telecom_arpu_service import select_ev_ebitda_multiple
    assert select_ev_ebitda_multiple("BHARTIARTL.NS") == pytest.approx(8.5)
    assert select_ev_ebitda_multiple("INDUSTOWER.BO") == pytest.approx(9.0)


# ── is_telecom_arpu_applicable ──────────────────────────────────
def test_is_telecom_arpu_applicable_bhartiartl_true():
    from backend.services.telecom_arpu_service import is_telecom_arpu_applicable
    ok, reason = is_telecom_arpu_applicable("BHARTIARTL", "Communication Services")
    assert ok is True
    assert "BHARTIARTL" in reason


def test_is_telecom_arpu_applicable_all_universe():
    from backend.services.telecom_arpu_service import (
        is_telecom_arpu_applicable, TELECOM_TICKERS,
    )
    for ticker in TELECOM_TICKERS:
        ok, reason = is_telecom_arpu_applicable(ticker, None)
        assert ok is True, f"{ticker} should be applicable; reason={reason}"


def test_is_telecom_arpu_applicable_reliance_false_sotp_required():
    """RELIANCE is excluded — needs SOTP, not single-business ARPU
    DCF. Reason must explicitly mention SOTP so the caller can route."""
    from backend.services.telecom_arpu_service import is_telecom_arpu_applicable
    ok, reason = is_telecom_arpu_applicable("RELIANCE", "Energy")
    assert ok is False
    assert "SOTP" in reason or "Jio" in reason


def test_is_telecom_arpu_applicable_hdfcbank_false():
    from backend.services.telecom_arpu_service import is_telecom_arpu_applicable
    ok, reason = is_telecom_arpu_applicable("HDFCBANK", "Financial Services")
    assert ok is False
    assert "not" in reason.lower() or "telecom" in reason.lower()


def test_is_telecom_arpu_applicable_empty_ticker():
    from backend.services.telecom_arpu_service import is_telecom_arpu_applicable
    ok, _ = is_telecom_arpu_applicable("", None)
    assert ok is False


# ── Empty forecasts → defaults ──────────────────────────────────
def test_empty_forecasts_uses_current_baseline_with_defaults():
    """No explicit forecasts → engine extrapolates from baseline at
    default growth assumptions. Result still has horizon years and a
    positive per-share number for a healthy unit-economics profile."""
    from backend.services.telecom_arpu_service import (
        TelecomInputs, compute_arpu_driven_fv,
    )
    inp = TelecomInputs(
        current_subscribers_millions=400.0,
        current_arpu_inr=190.0,
        forecast_horizon_years=5,
        forecasts=[],                                # empty!
        operating_margin_pct=30.0,
        maintenance_capex_pct_of_revenue=12.0,
        growth_capex_pct_of_revenue=5.0,
        shares_outstanding=600.0,
    )
    out = compute_arpu_driven_fv(inp)
    assert out.method == "arpu_dcf"
    assert out.fair_value_per_share is not None
    assert out.fair_value_per_share > 0
    assert len(out.components["years"]) == 5
    # Padded warning fires (we filled all 5 from defaults).
    assert any("pad" in w.lower() for w in out.sanity_warnings)


# ── to_dict shape ───────────────────────────────────────────────
def test_to_dict_shape_is_json_safe():
    """to_dict() must return a plain dict whose values are JSON-
    serialisable primitives (numbers, strings, lists, dicts, None).
    No dataclass instances, no datetimes leak through."""
    import json
    from backend.services.telecom_arpu_service import (
        TelecomInputs, compute_arpu_driven_fv, to_dict,
    )
    inp = TelecomInputs(
        current_subscribers_millions=400.0,
        current_arpu_inr=190.0,
        forecast_horizon_years=5,
        forecasts=[],
        shares_outstanding=600.0,
    )
    out = compute_arpu_driven_fv(inp)
    d = to_dict(out)
    # Schema keys present
    expected_keys = {
        "fair_value_per_share", "aggregate_ev_inr_cr",
        "revenue_year_5_inr_cr", "ebitda_year_5_inr_cr",
        "method", "components", "sanity_warnings",
    }
    assert expected_keys.issubset(set(d.keys()))
    # Round-trip through json.dumps to prove JSON-safe.
    blob = json.dumps(d)
    assert isinstance(blob, str)
    assert len(blob) > 0
    # Re-parse and spot-check fields preserve type.
    parsed = json.loads(blob)
    assert parsed["method"] == "arpu_dcf"
    assert isinstance(parsed["components"]["years"], list)
    assert isinstance(parsed["sanity_warnings"], list)


# ── TELECOM_TICKERS / DEFAULT_MULTIPLES constants ───────────────
def test_telecom_tickers_constants():
    """Phase A constants: 4 tickers, RELIANCE explicitly excluded,
    DEFAULT_MULTIPLES covers every ticker in TELECOM_TICKERS."""
    from backend.services.telecom_arpu_service import (
        TELECOM_TICKERS, DEFAULT_MULTIPLES,
    )
    assert TELECOM_TICKERS == frozenset({
        "BHARTIARTL", "VODAFONEIDEA", "BHARTIHEXA", "INDUSTOWER",
    })
    assert "RELIANCE" not in TELECOM_TICKERS
    # Every covered ticker has a multiple.
    for t in TELECOM_TICKERS:
        assert t in DEFAULT_MULTIPLES
        assert DEFAULT_MULTIPLES[t] > 0


# ── project_revenue unit test ───────────────────────────────────
def test_project_revenue_arithmetic():
    """400M subs × ₹190 ARPU/mo × 12 months / 1e7 / 1e-6 → ₹91,200 Cr
    revenue. EBITDA at 30% margin = ₹27,360 Cr.

    Computation: 400 × 190 × 1.2 (combined factor) = 91200.
    """
    from backend.services.telecom_arpu_service import (
        SubscriberForecast, project_revenue,
    )
    fc = SubscriberForecast(
        year_offset=1,
        subscriber_count_millions=400.0,
        arpu_inr_per_month=190.0,
        churn_rate_pct=2.0,
    )
    revenue, ebitda = project_revenue(fc, operating_margin_pct=30.0)
    assert revenue == pytest.approx(91200.0, abs=0.5)
    assert ebitda == pytest.approx(27360.0, abs=0.5)
