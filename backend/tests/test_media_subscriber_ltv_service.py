# backend/tests/test_media_subscriber_ltv_service.py
# =====================================================================
# Tests for backend/services/media_subscriber_ltv_service.py
# (T3.14 Phase A).
#
# Coverage map (one test per concern, no shared fixtures so each test
# reads top-to-bottom):
#
#   compute_ltv
#     - canonical case: ARPU=300, churn=4%/mo, GM=55% -> LTV ~= 4125
#     - churn = 0 clamped to floor -> finite LTV
#     - huge churn clamped to ceiling -> very short lifetime
#     - non-positive ARPU -> 0.0
#     - non-finite GM -> 0.0
#
#   classify_ltv_cac_health
#     - >=3 -> "healthy", 2..3 -> "ok", <2 -> "stressed"
#     - non-positive / non-finite -> "unknown"
#
#   compute_media_fv
#     - ZEEL-shape (broadcaster, churn 5%, ARPU 80, 30M subs) ->
#       computable; lifetime=20mo, subscriber book in plausible band
#     - PVRINOX-shape (cinema, ARPU 400, churn 8%/mo) -> computable
#     - SAREGAMA-shape (music_rights, churn 2%/mo, SAC 0) ->
#       perpetuity-like LTV/CAC = inf, healthy
#     - NETFLIX-style OTT (ott_streaming, 5M subs, ARPU 200, churn 4%)
#       -> computable; segment multiple 3x applied
#     - paying_subscribers_mn = 0 -> method='unavailable'
#     - arpu_per_month_inr = 0 -> method='unavailable'
#     - unknown segment -> method='unavailable'
#     - cost_of_equity = 0 -> method='unavailable'
#     - shares_outstanding = 0 -> per-share FV is None, components
#       still populated
#     - clamped churn surfaces a sanity warning but still computes
#     - net_debt > 0 reduces equity_value
#     - SAC = 0 -> ltv_cac_ratio = inf, classified healthy
#
#   is_media_applicable
#     - explicit ticker match (ZEEL, .NS suffix) -> True
#     - explicit ticker match (SAREGAMA) -> True
#     - non-media ticker (HDFCBANK) -> False
#     - unknown ticker but sector contains 'media' -> True
#     - empty inputs -> False
#
#   to_dict
#     - returns plain-JSON shape, components is a plain dict
#     - inf ltv_cac_ratio serialises to None
# =====================================================================
from __future__ import annotations

import math

import pytest

from backend.services.media_subscriber_ltv_service import (
    MediaSubscriberInputs,
    MediaSubscriberResult,
    MEDIA_TICKERS,
    SEGMENT_LTV_MULTIPLES,
    classify_ltv_cac_health,
    compute_ltv,
    compute_media_fv,
    is_media_applicable,
    to_dict,
)


# ---------------------------------------------------------------------
# compute_ltv
# ---------------------------------------------------------------------
def test_compute_ltv_canonical_ott_case():
    """ARPU 300, monthly churn 4% (=0.04), GM 55%:
       lifetime = 1 / 0.04 = 25 months
       LTV = 300 * 0.55 * 25 = 4125 INR
    """
    ltv = compute_ltv(
        arpu_monthly=300.0,
        churn_monthly=0.04,
        gross_margin_pct=55.0,
    )
    assert ltv == pytest.approx(4125.0, abs=1e-6)


def test_compute_ltv_churn_zero_clamps_to_floor():
    """A 0%/mo churn would imply infinite lifetime. We clamp to the
    MIN_MONTHLY_CHURN_PCT floor (0.5%/mo => 200-month lifetime).
    """
    ltv = compute_ltv(
        arpu_monthly=100.0,
        churn_monthly=0.0,
        gross_margin_pct=50.0,
    )
    # 100 * 0.50 * (100/0.5) = 100 * 0.5 * 200 = 10_000
    assert ltv == pytest.approx(10_000.0, abs=1e-6)
    assert math.isfinite(ltv)


def test_compute_ltv_huge_churn_clamps_to_ceiling():
    """200%/mo churn is nonsense; clamp ceiling is 50%/mo
       => 2-month avg lifetime.
    """
    ltv = compute_ltv(
        arpu_monthly=500.0,
        churn_monthly=2.0,            # 200%/mo
        gross_margin_pct=60.0,
    )
    # 500 * 0.60 * (100/50) = 500 * 0.6 * 2 = 600
    assert ltv == pytest.approx(600.0, abs=1e-6)


def test_compute_ltv_non_positive_arpu_returns_zero():
    assert compute_ltv(arpu_monthly=0.0, churn_monthly=0.04, gross_margin_pct=55.0) == 0.0
    assert compute_ltv(arpu_monthly=-100.0, churn_monthly=0.04, gross_margin_pct=55.0) == 0.0


def test_compute_ltv_non_finite_gm_returns_zero():
    assert compute_ltv(arpu_monthly=300.0, churn_monthly=0.04, gross_margin_pct=float("nan")) == 0.0


# ---------------------------------------------------------------------
# classify_ltv_cac_health
# ---------------------------------------------------------------------
def test_classify_ltv_cac_health_tiers():
    assert classify_ltv_cac_health(5.0) == "healthy"
    assert classify_ltv_cac_health(3.0) == "healthy"
    assert classify_ltv_cac_health(2.5) == "ok"
    assert classify_ltv_cac_health(2.0) == "ok"
    assert classify_ltv_cac_health(1.5) == "stressed"
    assert classify_ltv_cac_health(0.5) == "stressed"


def test_classify_ltv_cac_health_defensive_inputs():
    assert classify_ltv_cac_health(0.0) == "unknown"
    assert classify_ltv_cac_health(-1.0) == "unknown"
    assert classify_ltv_cac_health(float("nan")) == "unknown"
    # inf is finite=False under math.isfinite, treated as unknown.
    assert classify_ltv_cac_health(float("inf")) == "unknown"


# ---------------------------------------------------------------------
# compute_media_fv — ZEEL-shape broadcaster
# ---------------------------------------------------------------------
def test_zeel_shape_broadcaster_computable():
    """ZEEL-shape: 30M paying subscribers (ZEE5 + linear bundle), ARPU
    INR 80/mo, churn 5%/mo, GM 55%, SAC INR 600, ad revenue 4500 Cr,
    shares ~96 Cr, low net debt.

    Expected:
      lifetime = 100/5 = 20 months
      LTV = 80 * 0.55 * 20 = 880 INR/sub
      ltv_cac = 880 / 600 = 1.467 -> "stressed"
      subscriber_book = 30e6 * 880 / 1e7 = 2640 Cr
      subscriber_contribution = 2640 * 1.5 = 3960 Cr
    """
    inp = MediaSubscriberInputs(
        paying_subscribers_mn=30.0,
        arpu_per_month_inr=80.0,
        monthly_churn_rate_pct=5.0,
        gross_margin_pct=55.0,
        subscriber_acquisition_cost_inr=600.0,
        advertising_revenue_inr_cr=4500.0,
        other_revenue_inr_cr=200.0,
        cost_of_equity=0.13,
        net_debt_inr_cr=-500.0,        # net cash position
        shares_outstanding=96e7,        # ~96 Cr shares
        segment="broadcaster",
    )
    res = compute_media_fv(inp)

    assert res.method == "media_subscriber_ltv"
    assert res.avg_subscriber_lifetime_months == pytest.approx(20.0, abs=1e-9)
    assert res.customer_lifetime_value_inr == pytest.approx(880.0, abs=1e-6)
    assert res.subscriber_book_value_inr_cr == pytest.approx(2640.0, abs=1e-3)
    assert res.ltv_cac_ratio == pytest.approx(880.0 / 600.0, abs=1e-6)
    assert res.components["ltv_cac_health"] == "stressed"
    assert res.components["segment_ltv_multiple"] == 1.5
    assert res.components["subscriber_contribution_inr_cr"] == pytest.approx(3960.0, abs=1e-3)
    # Should surface the stressed-unit-economics warning.
    assert any("ltv_cac_ratio" in w for w in res.sanity_warnings)
    # Per-share FV should be a positive finite number.
    assert res.fair_value_per_share is not None
    assert math.isfinite(res.fair_value_per_share)
    assert res.fair_value_per_share > 0


# ---------------------------------------------------------------------
# compute_media_fv — PVRINOX-shape cinema exhibitor
# ---------------------------------------------------------------------
def test_pvrinox_shape_cinema_computable():
    """PVRINOX-shape: ~150M annual admissions -> ~12.5M "subscribers"
    (treating monthly active visitors as the subscriber proxy), ARPU
    INR 400 per visit, churn 8%/mo (occasion-driven, not contractual),
    GM 35% on F&B+ticket margin, SAC INR 50.
    """
    inp = MediaSubscriberInputs(
        paying_subscribers_mn=12.5,
        arpu_per_month_inr=400.0,
        monthly_churn_rate_pct=8.0,
        gross_margin_pct=35.0,
        subscriber_acquisition_cost_inr=50.0,
        advertising_revenue_inr_cr=350.0,
        other_revenue_inr_cr=600.0,
        cost_of_equity=0.13,
        net_debt_inr_cr=1200.0,
        shares_outstanding=10e7,        # ~10 Cr shares
        segment="cinema_exhibition",
    )
    res = compute_media_fv(inp)

    assert res.method == "media_subscriber_ltv"
    # lifetime = 100/8 = 12.5 months
    assert res.avg_subscriber_lifetime_months == pytest.approx(12.5, abs=1e-9)
    # LTV = 400 * 0.35 * 12.5 = 1750
    assert res.customer_lifetime_value_inr == pytest.approx(1750.0, abs=1e-6)
    # ltv_cac = 1750 / 50 = 35 -> "healthy"
    assert res.ltv_cac_ratio == pytest.approx(35.0, abs=1e-6)
    assert res.components["ltv_cac_health"] == "healthy"
    assert res.components["segment_ltv_multiple"] == 2.5
    # Per-share FV should be finite and positive.
    assert res.fair_value_per_share is not None
    assert res.fair_value_per_share > 0


# ---------------------------------------------------------------------
# compute_media_fv — SAREGAMA-shape music catalogue
# ---------------------------------------------------------------------
def test_saregama_shape_music_rights_perpetuity():
    """SAREGAMA-shape: music catalogue + Carvaan device base.
    Model the licensee count as "subscribers" with very low churn (2%
    /mo, since once a streaming platform licenses the catalogue they
    rarely drop it) and SAC=0 (no per-subscriber acquisition cost on a
    catalogue royalty stream).
    """
    inp = MediaSubscriberInputs(
        paying_subscribers_mn=2.5,
        arpu_per_month_inr=250.0,
        monthly_churn_rate_pct=2.0,
        gross_margin_pct=70.0,
        subscriber_acquisition_cost_inr=0.0,    # no acquisition cost
        advertising_revenue_inr_cr=0.0,
        other_revenue_inr_cr=300.0,             # IP licensing
        cost_of_equity=0.12,
        net_debt_inr_cr=-400.0,                 # net cash
        shares_outstanding=20e7,
        segment="music_rights",
    )
    res = compute_media_fv(inp)

    assert res.method == "media_subscriber_ltv"
    # lifetime = 100/2 = 50 months
    assert res.avg_subscriber_lifetime_months == pytest.approx(50.0, abs=1e-9)
    # LTV = 250 * 0.70 * 50 = 8750
    assert res.customer_lifetime_value_inr == pytest.approx(8750.0, abs=1e-6)
    # SAC=0 -> ltv_cac is inf
    assert math.isinf(res.ltv_cac_ratio)
    # ltv_cac_health is "unknown" for inf per the classifier convention
    assert res.components["ltv_cac_health"] == "unknown"
    assert res.components["segment_ltv_multiple"] == 5.0
    # Per-share FV finite + positive
    assert res.fair_value_per_share is not None
    assert math.isfinite(res.fair_value_per_share)
    assert res.fair_value_per_share > 0


# ---------------------------------------------------------------------
# compute_media_fv — OTT-streaming sanity case
# ---------------------------------------------------------------------
def test_ott_streaming_segment_multiple_applied():
    """OTT-streaming gets the 3.0x segment multiple — verifies the
    SEGMENT_LTV_MULTIPLES dispatch is wired through the components.
    """
    inp = MediaSubscriberInputs(
        paying_subscribers_mn=5.0,
        arpu_per_month_inr=200.0,
        monthly_churn_rate_pct=4.0,
        gross_margin_pct=50.0,
        subscriber_acquisition_cost_inr=400.0,
        advertising_revenue_inr_cr=300.0,
        other_revenue_inr_cr=0.0,
        cost_of_equity=0.13,
        net_debt_inr_cr=0.0,
        shares_outstanding=10e7,
        segment="ott_streaming",
    )
    res = compute_media_fv(inp)

    assert res.method == "media_subscriber_ltv"
    assert res.components["segment_ltv_multiple"] == 3.0
    # LTV = 200 * 0.50 * 25 = 2500; subscriber_book = 5e6 * 2500 / 1e7 = 1250 Cr
    assert res.subscriber_book_value_inr_cr == pytest.approx(1250.0, abs=1e-3)
    # contribution = 1250 * 3.0 = 3750 Cr
    assert res.components["subscriber_contribution_inr_cr"] == pytest.approx(3750.0, abs=1e-3)


# ---------------------------------------------------------------------
# compute_media_fv — defensive paths
# ---------------------------------------------------------------------
def test_zero_subscribers_returns_unavailable():
    inp = MediaSubscriberInputs(
        paying_subscribers_mn=0.0,
        arpu_per_month_inr=200.0,
    )
    res = compute_media_fv(inp)
    assert res.method == "unavailable"
    assert res.fair_value_per_share is None
    assert any("paying_subscribers_mn" in w for w in res.sanity_warnings)


def test_zero_arpu_returns_unavailable():
    inp = MediaSubscriberInputs(
        paying_subscribers_mn=5.0,
        arpu_per_month_inr=0.0,
    )
    res = compute_media_fv(inp)
    assert res.method == "unavailable"
    assert res.fair_value_per_share is None
    assert any("arpu_per_month_inr" in w for w in res.sanity_warnings)


def test_unknown_segment_returns_unavailable():
    inp = MediaSubscriberInputs(
        paying_subscribers_mn=5.0,
        arpu_per_month_inr=200.0,
        segment="podcast_rights",   # type: ignore[arg-type]
    )
    res = compute_media_fv(inp)
    assert res.method == "unavailable"
    assert res.fair_value_per_share is None
    assert any("segment" in w for w in res.sanity_warnings)


def test_zero_cost_of_equity_returns_unavailable():
    inp = MediaSubscriberInputs(
        paying_subscribers_mn=5.0,
        arpu_per_month_inr=200.0,
        cost_of_equity=0.0,
    )
    res = compute_media_fv(inp)
    assert res.method == "unavailable"
    assert any("cost_of_equity" in w for w in res.sanity_warnings)


def test_shares_outstanding_zero_returns_none_per_share_with_components():
    inp = MediaSubscriberInputs(
        paying_subscribers_mn=5.0,
        arpu_per_month_inr=200.0,
        monthly_churn_rate_pct=4.0,
        gross_margin_pct=50.0,
        shares_outstanding=0.0,
        segment="ott_streaming",
    )
    res = compute_media_fv(inp)
    assert res.method == "media_subscriber_ltv"
    assert res.fair_value_per_share is None
    # Components still computed
    assert "subscriber_book_inr_cr" in res.components
    assert res.subscriber_book_value_inr_cr > 0
    assert any("shares_outstanding" in w for w in res.sanity_warnings)


def test_churn_clamp_surfaces_warning_and_still_computes():
    inp = MediaSubscriberInputs(
        paying_subscribers_mn=5.0,
        arpu_per_month_inr=200.0,
        monthly_churn_rate_pct=0.1,    # below MIN_MONTHLY_CHURN_PCT (0.5)
        gross_margin_pct=50.0,
        shares_outstanding=10e7,
        segment="music_rights",
    )
    res = compute_media_fv(inp)
    assert res.method == "media_subscriber_ltv"
    # 0.1 clamped to 0.5 -> lifetime 200 months
    assert res.avg_subscriber_lifetime_months == pytest.approx(200.0, abs=1e-9)
    assert any("monthly_churn_rate_pct clamped" in w for w in res.sanity_warnings)


def test_net_debt_reduces_equity_value():
    """Run the same inputs twice with different net_debt; equity-value
    component must differ by exactly the net_debt delta.
    """
    base_args = dict(
        paying_subscribers_mn=5.0,
        arpu_per_month_inr=200.0,
        monthly_churn_rate_pct=4.0,
        gross_margin_pct=50.0,
        shares_outstanding=10e7,
        segment="ott_streaming",
    )
    r_nodebt = compute_media_fv(MediaSubscriberInputs(net_debt_inr_cr=0.0, **base_args))
    r_debt = compute_media_fv(MediaSubscriberInputs(net_debt_inr_cr=500.0, **base_args))
    delta = (
        r_nodebt.components["gross_equity_value_inr_cr"]
        - r_debt.components["gross_equity_value_inr_cr"]
    )
    assert delta == pytest.approx(500.0, abs=1e-3)


def test_sac_zero_gives_infinite_ltv_cac():
    inp = MediaSubscriberInputs(
        paying_subscribers_mn=2.0,
        arpu_per_month_inr=200.0,
        monthly_churn_rate_pct=3.0,
        gross_margin_pct=60.0,
        subscriber_acquisition_cost_inr=0.0,
        shares_outstanding=10e7,
        segment="music_rights",
    )
    res = compute_media_fv(inp)
    assert res.method == "media_subscriber_ltv"
    assert math.isinf(res.ltv_cac_ratio)


# ---------------------------------------------------------------------
# is_media_applicable
# ---------------------------------------------------------------------
def test_is_media_applicable_explicit_ticker_match_with_suffix():
    ok, reason = is_media_applicable("ZEEL.NS", sector=None)
    assert ok is True
    assert reason.startswith("in_media_ticker_map:")


def test_is_media_applicable_saregama():
    ok, reason = is_media_applicable("SAREGAMA", sector=None)
    assert ok is True
    assert "music_rights" in reason


def test_is_media_applicable_non_media_ticker():
    ok, reason = is_media_applicable("HDFCBANK", sector="Banking")
    assert ok is False
    assert reason == "not_a_media_ticker"


def test_is_media_applicable_sector_keyword_match():
    ok, reason = is_media_applicable("UNKNOWNNEWCO", sector="Media & Entertainment")
    assert ok is True
    assert reason.startswith("sector_keyword_match:")


def test_is_media_applicable_empty_inputs():
    ok, reason = is_media_applicable(None, None)
    assert ok is False
    assert reason == "not_a_media_ticker"
    ok2, _ = is_media_applicable("", "")
    assert ok2 is False


def test_media_tickers_all_have_known_segments():
    """Every entry in MEDIA_TICKERS must map to a SEGMENT_LTV_MULTIPLES
    key — keeps the two dicts in lock-step.
    """
    for ticker, seg in MEDIA_TICKERS.items():
        assert seg in SEGMENT_LTV_MULTIPLES, (
            f"{ticker} -> {seg} is not in SEGMENT_LTV_MULTIPLES"
        )


# ---------------------------------------------------------------------
# to_dict
# ---------------------------------------------------------------------
def test_to_dict_plain_json_shape():
    inp = MediaSubscriberInputs(
        paying_subscribers_mn=5.0,
        arpu_per_month_inr=200.0,
        monthly_churn_rate_pct=4.0,
        gross_margin_pct=50.0,
        subscriber_acquisition_cost_inr=400.0,
        shares_outstanding=10e7,
        segment="ott_streaming",
    )
    d = to_dict(compute_media_fv(inp))
    # No dataclass instances escaped.
    assert isinstance(d, dict)
    assert isinstance(d["components"], dict)
    assert isinstance(d["sanity_warnings"], list)
    # Core float fields preserved.
    assert d["method"] == "media_subscriber_ltv"
    assert d["customer_lifetime_value_inr"] == pytest.approx(2500.0, abs=1e-6)


def test_to_dict_inf_ltv_cac_serialises_to_none():
    """SAC=0 produces inf ltv_cac_ratio; JSON-safe serialisation must
    coerce that to None so downstream JSON encoders don't blow up.
    """
    inp = MediaSubscriberInputs(
        paying_subscribers_mn=2.0,
        arpu_per_month_inr=300.0,
        monthly_churn_rate_pct=3.0,
        gross_margin_pct=70.0,
        subscriber_acquisition_cost_inr=0.0,
        shares_outstanding=10e7,
        segment="music_rights",
    )
    d = to_dict(compute_media_fv(inp))
    assert d["ltv_cac_ratio"] is None


def test_to_dict_rejects_wrong_type():
    with pytest.raises(TypeError):
        to_dict({"method": "media_subscriber_ltv"})  # type: ignore[arg-type]
