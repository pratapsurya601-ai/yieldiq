# backend/tests/test_auto_oem_cycle_service.py
# ═════════════════════════════════════════════════════════════════════
# Tests for the standalone auto-OEM mid-cycle valuation service.
#
# Coverage targets:
#   • Mid-cycle geometric-mean math (volume / revenue / EBITDA).
#   • MARUTI-shape sanity bracket (₹6k–₹12k FV).
#   • TATAMOTORS-shape cyclical (wide peak/trough band, CV+PV blend).
#   • EICHERMOT-shape premium 2W (high multiple, low net debt).
#   • Cycle-position adjustments (trough discount, peak premium).
#   • Multiple-applicability gate (8 known OEMs, 1 non-OEM).
#   • Defensive: zero shares, negative equity, peak<=0, mid_margin=0,
#     extreme multiple, extreme peak/trough ratio.
#   • to_dict shape — both available and unavailable result paths.
# ═════════════════════════════════════════════════════════════════════
from __future__ import annotations

import math

import pytest

from backend.services.auto_oem_cycle_service import (
    AUTO_OEM_TICKERS,
    SEGMENT_MULTIPLES,
    AutoOEMInputs,
    AutoOEMResult,
    compute_auto_oem_fv,
    compute_mid_cycle_normalization,
    is_auto_oem_applicable,
    to_dict,
)


# ── Fixture-style shape builders ────────────────────────────────────
def _maruti_shape(**overrides) -> AutoOEMInputs:
    """MARUTI-like 4W OEM at ~mid-cycle."""
    base = dict(
        current_year_volume_units=1_700_000,
        peak_year_volume_units=2_000_000,
        trough_year_volume_units=1_400_000,
        realization_per_unit_inr=800_000,
        operating_margin_current_pct=11.0,
        operating_margin_mid_cycle_pct=10.5,
        ev_ebitda_multiple_mid_cycle=14.0,
        net_debt_inr_cr=-50_000.0,  # net cash position
        shares_outstanding=302_000_000.0,
        segment="pv_4w",
        cycle_position="mid_cycle",
    )
    base.update(overrides)
    return AutoOEMInputs(**base)


def _tatamotors_shape(**overrides) -> AutoOEMInputs:
    """TATAMOTORS-like: cyclical CV+PV blend with wider peak/trough."""
    base = dict(
        current_year_volume_units=900_000,
        peak_year_volume_units=1_100_000,
        trough_year_volume_units=550_000,
        realization_per_unit_inr=1_500_000,  # blended (CV heavier)
        operating_margin_current_pct=8.0,
        operating_margin_mid_cycle_pct=7.5,
        ev_ebitda_multiple_mid_cycle=11.0,   # blended 4W/CV
        net_debt_inr_cr=45_000.0,
        shares_outstanding=3_700_000_000.0,
        segment="pv_4w",
        cycle_position="late_cycle",
    )
    base.update(overrides)
    return AutoOEMInputs(**base)


def _eichermot_shape(**overrides) -> AutoOEMInputs:
    """EICHERMOT-like premium 2W (Royal Enfield), high multiple."""
    base = dict(
        current_year_volume_units=950_000,
        peak_year_volume_units=1_050_000,
        trough_year_volume_units=600_000,
        realization_per_unit_inr=180_000,
        operating_margin_current_pct=26.0,
        operating_margin_mid_cycle_pct=24.0,
        ev_ebitda_multiple_mid_cycle=25.0,
        net_debt_inr_cr=-9_000.0,
        shares_outstanding=274_000_000.0,
        segment="luxury_2w",
        cycle_position="mid_cycle",
    )
    base.update(overrides)
    return AutoOEMInputs(**base)


# ── Applicability gate ──────────────────────────────────────────────
class TestApplicability:
    def test_maruti_is_pv_4w(self):
        ok, label = is_auto_oem_applicable("MARUTI")
        assert ok is True
        assert label == "pv_4w"

    def test_tatamotors_is_pv_4w(self):
        ok, label = is_auto_oem_applicable("TATAMOTORS")
        assert ok is True
        assert label == "pv_4w"

    def test_mahindra_with_ampersand(self):
        ok, label = is_auto_oem_applicable("M&M")
        assert ok is True
        assert label == "pv_4w"

    def test_bajaj_auto_pv_2w(self):
        ok, label = is_auto_oem_applicable("BAJAJ-AUTO")
        assert ok is True
        assert label == "pv_2w"

    def test_heromotoco_pv_2w(self):
        ok, label = is_auto_oem_applicable("HEROMOTOCO")
        assert ok is True
        assert label == "pv_2w"

    def test_tvsmotor_pv_2w(self):
        ok, label = is_auto_oem_applicable("TVSMOTOR")
        assert ok is True
        assert label == "pv_2w"

    def test_eichermot_luxury_2w(self):
        ok, label = is_auto_oem_applicable("EICHERMOT")
        assert ok is True
        assert label == "luxury_2w"

    def test_ashokley_cv(self):
        ok, label = is_auto_oem_applicable("ASHOKLEY")
        assert ok is True
        assert label == "cv"

    def test_ns_suffix_stripped(self):
        ok, _ = is_auto_oem_applicable("MARUTI.NS")
        assert ok is True

    def test_bo_suffix_stripped(self):
        ok, _ = is_auto_oem_applicable("MARUTI.BO")
        assert ok is True

    def test_lowercase_normalized(self):
        ok, _ = is_auto_oem_applicable("maruti")
        assert ok is True

    def test_reliance_not_an_oem(self):
        ok, reason = is_auto_oem_applicable("RELIANCE")
        assert ok is False
        assert reason == "ticker_not_in_auto_oem_universe"

    def test_mahscooter_not_in_universe(self):
        """MAHSCOOTER is a holdco-style cash box, not a volume OEM."""
        ok, _ = is_auto_oem_applicable("MAHSCOOTER")
        assert ok is False

    def test_empty_ticker_rejected(self):
        ok, reason = is_auto_oem_applicable("")
        assert ok is False
        assert reason == "missing_ticker"

    def test_none_ticker_rejected(self):
        ok, reason = is_auto_oem_applicable(None)
        assert ok is False
        assert reason == "missing_ticker"

    def test_sector_argument_advisory_only(self):
        """`sector` is accepted but does not override membership test."""
        ok, _ = is_auto_oem_applicable("RELIANCE", sector="Auto")
        assert ok is False  # gate is by ticker, not sector

    def test_all_eight_known_oems_classified(self):
        assert len(AUTO_OEM_TICKERS) == 8
        for t, seg in AUTO_OEM_TICKERS.items():
            ok, label = is_auto_oem_applicable(t)
            assert ok is True, f"{t} should be applicable"
            assert label == seg

    def test_segment_multiples_table_covers_all_segments(self):
        segments_used = set(AUTO_OEM_TICKERS.values())
        for seg in segments_used:
            assert seg in SEGMENT_MULTIPLES, f"missing multiple for {seg}"


# ── Mid-cycle normalisation math ────────────────────────────────────
class TestMidCycleNormalization:
    def test_geometric_mean_volume(self):
        i = _maruti_shape()
        out = compute_mid_cycle_normalization(i)
        expected = math.sqrt(2_000_000 * 1_400_000)
        assert out["mid_cycle_volume"] == pytest.approx(expected, rel=1e-4)

    def test_revenue_in_inr_cr(self):
        i = _maruti_shape()
        out = compute_mid_cycle_normalization(i)
        # mid_vol × realization / 1e7 = revenue in INR cr
        expected = math.sqrt(2_000_000 * 1_400_000) * 800_000 / 1e7
        assert out["mid_cycle_revenue_inr_cr"] == pytest.approx(expected, rel=1e-3)

    def test_ebitda_from_mid_margin_not_current(self):
        """Mid-cycle EBITDA must use mid-cycle margin, NOT current."""
        i = _maruti_shape(
            operating_margin_current_pct=18.0,   # peak margin
            operating_margin_mid_cycle_pct=10.5,
        )
        out = compute_mid_cycle_normalization(i)
        expected_revenue = math.sqrt(2_000_000 * 1_400_000) * 800_000 / 1e7
        expected_ebitda = expected_revenue * 0.105
        assert out["mid_cycle_ebitda_inr_cr"] == pytest.approx(
            expected_ebitda, rel=1e-3
        )

    def test_zero_peak_returns_zeros(self):
        i = _maruti_shape(peak_year_volume_units=0)
        out = compute_mid_cycle_normalization(i)
        assert out["mid_cycle_volume"] == 0
        assert out["mid_cycle_revenue_inr_cr"] == 0
        assert out["mid_cycle_ebitda_inr_cr"] == 0

    def test_zero_trough_returns_zeros(self):
        i = _maruti_shape(trough_year_volume_units=0)
        out = compute_mid_cycle_normalization(i)
        assert out["mid_cycle_volume"] == 0

    def test_negative_peak_clamped_to_zero(self):
        i = _maruti_shape(peak_year_volume_units=-100)
        out = compute_mid_cycle_normalization(i)
        assert out["mid_cycle_volume"] == 0


# ── MARUTI-shape full bracket ───────────────────────────────────────
class TestMarutiShape:
    def test_fv_per_share_in_defensible_band(self):
        r = compute_auto_oem_fv(_maruti_shape())
        # MARUTI mid-cycle FV expected ~₹8k (current price ~₹12k).
        # Allow ±50% bracket — point is "lands in a defensible
        # range" not "matches a single point estimate".
        assert r.fair_value_per_share is not None
        assert 4_000 < r.fair_value_per_share < 15_000

    def test_label_is_mid_neutral_when_no_cycle_taper(self):
        r = compute_auto_oem_fv(_maruti_shape(cycle_position="mid_cycle"))
        assert r.cycle_adjustment_label == "mid_neutral"

    def test_components_carry_all_intermediate_steps(self):
        r = compute_auto_oem_fv(_maruti_shape())
        c = r.components
        for k in (
            "mid_cycle_volume",
            "mid_cycle_revenue_inr_cr",
            "mid_cycle_ebitda_inr_cr",
            "enterprise_value_inr_cr",
            "equity_value_inr_cr",
            "equity_value_after_taper_inr_cr",
            "ev_ebitda_multiple",
            "net_debt_inr_cr",
            "cycle_position",
            "cycle_taper",
            "segment",
        ):
            assert k in c, f"missing component {k}"

    def test_net_cash_lifts_equity_above_ev(self):
        r = compute_auto_oem_fv(_maruti_shape(net_debt_inr_cr=-50_000.0))
        assert (
            r.components["equity_value_inr_cr"]
            > r.components["enterprise_value_inr_cr"]
        )

    def test_no_warnings_on_clean_inputs(self):
        r = compute_auto_oem_fv(_maruti_shape())
        assert r.sanity_warnings == []

    def test_method_string_stable(self):
        r = compute_auto_oem_fv(_maruti_shape())
        assert r.method == "auto_oem_mid_cycle_normalization"


# ── TATAMOTORS-shape: cyclical with wide band ──────────────────────
class TestTataMotorsShape:
    def test_fv_per_share_computed(self):
        r = compute_auto_oem_fv(_tatamotors_shape())
        assert r.fair_value_per_share is not None
        assert r.fair_value_per_share > 0

    def test_late_cycle_premium_label(self):
        r = compute_auto_oem_fv(_tatamotors_shape(cycle_position="late_cycle"))
        assert r.cycle_adjustment_label == "peak_premium"

    def test_wide_peak_trough_band_flagged(self):
        """Peak ~2× trough is within tolerance (ratio 2.0 < 3.0)."""
        r = compute_auto_oem_fv(_tatamotors_shape())
        assert "peak_trough_ratio_above_threshold" not in r.sanity_warnings

    def test_extreme_peak_trough_ratio_flagged(self):
        i = _tatamotors_shape(
            peak_year_volume_units=2_000_000,
            trough_year_volume_units=400_000,  # ratio 5×
        )
        r = compute_auto_oem_fv(i)
        assert "peak_trough_ratio_above_threshold" in r.sanity_warnings

    def test_net_debt_subtracts_from_ev(self):
        r = compute_auto_oem_fv(_tatamotors_shape(net_debt_inr_cr=45_000.0))
        assert (
            r.components["equity_value_inr_cr"]
            < r.components["enterprise_value_inr_cr"]
        )

    def test_late_cycle_taper_raises_equity(self):
        late = compute_auto_oem_fv(
            _tatamotors_shape(cycle_position="late_cycle")
        )
        mid = compute_auto_oem_fv(_tatamotors_shape(cycle_position="mid_cycle"))
        assert (
            late.components["equity_value_after_taper_inr_cr"]
            > mid.components["equity_value_after_taper_inr_cr"]
        )


# ── EICHERMOT-shape: premium 2W ─────────────────────────────────────
class TestEicherShape:
    def test_fv_per_share_computed(self):
        r = compute_auto_oem_fv(_eichermot_shape())
        assert r.fair_value_per_share is not None
        assert r.fair_value_per_share > 0

    def test_high_margin_does_not_trigger_warning(self):
        """24% mid-margin vs 26% current — 2pp gap is within tolerance."""
        r = compute_auto_oem_fv(_eichermot_shape())
        assert (
            "current_vs_mid_margin_gap_above_threshold"
            not in r.sanity_warnings
        )

    def test_premium_multiple_25x_not_flagged_as_outlier(self):
        r = compute_auto_oem_fv(_eichermot_shape())
        assert (
            "ev_ebitda_multiple_out_of_defensible_band"
            not in r.sanity_warnings
        )

    def test_segment_recorded_as_luxury_2w(self):
        r = compute_auto_oem_fv(_eichermot_shape())
        assert r.components["segment"] == "luxury_2w"

    def test_net_cash_lifts_fv(self):
        net_cash = compute_auto_oem_fv(_eichermot_shape(net_debt_inr_cr=-9_000))
        with_debt = compute_auto_oem_fv(_eichermot_shape(net_debt_inr_cr=+9_000))
        assert net_cash.fair_value_per_share > with_debt.fair_value_per_share


# ── Cycle position adjustments ──────────────────────────────────────
class TestCyclePositionAdjustment:
    def test_trough_yields_trough_discount_label(self):
        r = compute_auto_oem_fv(_maruti_shape(cycle_position="trough"))
        assert r.cycle_adjustment_label == "trough_discount"

    def test_early_recovery_yields_trough_discount_label(self):
        r = compute_auto_oem_fv(_maruti_shape(cycle_position="early_recovery"))
        assert r.cycle_adjustment_label == "trough_discount"

    def test_mid_cycle_yields_mid_neutral_label(self):
        r = compute_auto_oem_fv(_maruti_shape(cycle_position="mid_cycle"))
        assert r.cycle_adjustment_label == "mid_neutral"

    def test_late_cycle_yields_peak_premium_label(self):
        r = compute_auto_oem_fv(_maruti_shape(cycle_position="late_cycle"))
        assert r.cycle_adjustment_label == "peak_premium"

    def test_peak_yields_peak_premium_label(self):
        r = compute_auto_oem_fv(_maruti_shape(cycle_position="peak"))
        assert r.cycle_adjustment_label == "peak_premium"

    def test_trough_lowers_fv_vs_mid(self):
        mid = compute_auto_oem_fv(_maruti_shape(cycle_position="mid_cycle"))
        trough = compute_auto_oem_fv(_maruti_shape(cycle_position="trough"))
        assert trough.fair_value_per_share < mid.fair_value_per_share

    def test_peak_raises_fv_vs_mid(self):
        mid = compute_auto_oem_fv(_maruti_shape(cycle_position="mid_cycle"))
        peak = compute_auto_oem_fv(_maruti_shape(cycle_position="peak"))
        assert peak.fair_value_per_share > mid.fair_value_per_share

    def test_trough_taper_magnitude_15pct(self):
        mid = compute_auto_oem_fv(_maruti_shape(cycle_position="mid_cycle"))
        trough = compute_auto_oem_fv(_maruti_shape(cycle_position="trough"))
        ratio = trough.fair_value_per_share / mid.fair_value_per_share
        assert ratio == pytest.approx(0.85, abs=0.01)

    def test_peak_taper_magnitude_15pct(self):
        mid = compute_auto_oem_fv(_maruti_shape(cycle_position="mid_cycle"))
        peak = compute_auto_oem_fv(_maruti_shape(cycle_position="peak"))
        ratio = peak.fair_value_per_share / mid.fair_value_per_share
        assert ratio == pytest.approx(1.15, abs=0.01)


# ── Defensive / edge cases ──────────────────────────────────────────
class TestDefensiveBehavior:
    def test_zero_shares_returns_none_fv(self):
        r = compute_auto_oem_fv(_maruti_shape(shares_outstanding=0.0))
        assert r.fair_value_per_share is None
        assert "non_positive_shares_outstanding" in r.sanity_warnings

    def test_negative_shares_returns_none_fv(self):
        r = compute_auto_oem_fv(_maruti_shape(shares_outstanding=-1.0))
        assert r.fair_value_per_share is None

    def test_huge_net_debt_drives_equity_negative(self):
        r = compute_auto_oem_fv(_maruti_shape(net_debt_inr_cr=10_000_000.0))
        assert r.fair_value_per_share is None
        assert "non_positive_equity_after_net_debt" in r.sanity_warnings

    def test_zero_peak_volume_flagged(self):
        r = compute_auto_oem_fv(_maruti_shape(peak_year_volume_units=0))
        assert "non_positive_peak_or_trough_volume" in r.sanity_warnings

    def test_zero_trough_volume_flagged(self):
        r = compute_auto_oem_fv(_maruti_shape(trough_year_volume_units=0))
        assert "non_positive_peak_or_trough_volume" in r.sanity_warnings

    def test_zero_realization_flagged(self):
        r = compute_auto_oem_fv(_maruti_shape(realization_per_unit_inr=0))
        assert "non_positive_realization_per_unit" in r.sanity_warnings

    def test_extreme_margin_gap_flagged(self):
        r = compute_auto_oem_fv(
            _maruti_shape(
                operating_margin_current_pct=25.0,
                operating_margin_mid_cycle_pct=10.0,
            )
        )
        assert (
            "current_vs_mid_margin_gap_above_threshold" in r.sanity_warnings
        )

    def test_low_multiple_flagged_as_outlier(self):
        r = compute_auto_oem_fv(_maruti_shape(ev_ebitda_multiple_mid_cycle=3.0))
        assert (
            "ev_ebitda_multiple_out_of_defensible_band" in r.sanity_warnings
        )

    def test_high_multiple_flagged_as_outlier(self):
        r = compute_auto_oem_fv(_maruti_shape(ev_ebitda_multiple_mid_cycle=40.0))
        assert (
            "ev_ebitda_multiple_out_of_defensible_band" in r.sanity_warnings
        )

    def test_current_above_peak_band_flagged(self):
        r = compute_auto_oem_fv(
            _maruti_shape(
                current_year_volume_units=3_000_000,  # > peak × 1.3
                peak_year_volume_units=2_000_000,
            )
        )
        assert "current_volume_above_peak_band" in r.sanity_warnings

    def test_current_below_trough_band_flagged(self):
        r = compute_auto_oem_fv(
            _maruti_shape(
                current_year_volume_units=500_000,   # < trough × 0.7
                trough_year_volume_units=1_400_000,
            )
        )
        assert "current_volume_below_trough_band" in r.sanity_warnings


# ── to_dict serialisation ───────────────────────────────────────────
class TestToDict:
    def test_success_shape(self):
        r = compute_auto_oem_fv(_maruti_shape())
        d = to_dict(r)
        assert d["available"] is True
        assert d["method"] == "auto_oem_mid_cycle_normalization"
        assert d["fair_value_per_share"] == r.fair_value_per_share
        assert d["mid_cycle_volume"] == r.mid_cycle_volume
        assert isinstance(d["components"], dict)
        assert isinstance(d["sanity_warnings"], list)

    def test_unavailable_when_shares_zero(self):
        r = compute_auto_oem_fv(_maruti_shape(shares_outstanding=0))
        d = to_dict(r)
        assert d["available"] is False
        assert d["fair_value_per_share"] is None

    def test_none_result_yields_unavailable_dict(self):
        d = to_dict(None)
        assert d["available"] is False
        assert d["method"] == "auto_oem_mid_cycle_normalization"
        assert d["reason"] == "no_result"

    def test_components_dict_is_copy_not_reference(self):
        r = compute_auto_oem_fv(_maruti_shape())
        d = to_dict(r)
        d["components"]["mid_cycle_volume"] = -999
        assert r.components["mid_cycle_volume"] != -999

    def test_warnings_list_is_copy_not_reference(self):
        r = compute_auto_oem_fv(_maruti_shape(shares_outstanding=0))
        d = to_dict(r)
        d["sanity_warnings"].append("tampered")
        assert "tampered" not in r.sanity_warnings


# ── Cross-cutting invariants ────────────────────────────────────────
class TestInvariants:
    def test_result_is_dataclass_instance(self):
        r = compute_auto_oem_fv(_maruti_shape())
        assert isinstance(r, AutoOEMResult)

    def test_ev_equals_ebitda_times_multiple(self):
        r = compute_auto_oem_fv(_maruti_shape())
        c = r.components
        assert c["enterprise_value_inr_cr"] == pytest.approx(
            c["mid_cycle_ebitda_inr_cr"] * c["ev_ebitda_multiple"],
            rel=1e-3,
        )

    def test_equity_equals_ev_minus_net_debt(self):
        r = compute_auto_oem_fv(_maruti_shape())
        c = r.components
        assert c["equity_value_inr_cr"] == pytest.approx(
            c["enterprise_value_inr_cr"] - c["net_debt_inr_cr"],
            rel=1e-3,
        )

    def test_taper_zero_at_mid_cycle(self):
        r = compute_auto_oem_fv(_maruti_shape(cycle_position="mid_cycle"))
        assert r.components["cycle_taper"] == 0.0
        assert (
            r.components["equity_value_after_taper_inr_cr"]
            == r.components["equity_value_inr_cr"]
        )

    def test_per_share_units_correct(self):
        """equity_cr × 1e7 / shares should round-trip back to FV/share."""
        r = compute_auto_oem_fv(_maruti_shape())
        c = r.components
        expected = round(
            c["equity_value_after_taper_inr_cr"] * 1e7 / c["shares_outstanding"],
            2,
        )
        assert r.fair_value_per_share == expected
