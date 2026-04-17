# backend/tests/test_validators_module.py
# Unit tests for the dict-based validator module at backend/validators/.
# The response-object validator in backend/services/validators.py is
# covered separately by test_dcf_trace_validator.py.
from __future__ import annotations

import math

import pytest

from backend.validators import (
    BOUNDS,
    CANARY_STOCKS,
    check_consistency,
    run_canary,
    validate_field,
    validate_record,
    validate_stock,
)


# ── BOUNDS / validate_field ──────────────────────────────────


def test_wacc_broken_percent_form_fails():
    """HCLTECH-class bug: WACC returned as 12.0 (percent) instead of 0.12."""
    ok, err = validate_field("wacc", 12.0)
    assert ok is False
    assert err is not None and "wacc=12" in err


def test_wacc_correct_decimal_form_passes():
    ok, err = validate_field("wacc", 0.105)
    assert ok is True
    assert err is None


def test_wacc_negative_fails():
    ok, err = validate_field("wacc", -0.05)
    assert ok is False
    assert err is not None


def test_roe_percent_convention_23_passes():
    ok, err = validate_field("roe", 23.0)
    assert ok is True


def test_roe_out_of_range_negative_fails():
    ok, err = validate_field("roe", -150.0)
    assert ok is False


def test_roce_percent_22_passes():
    ok, err = validate_field("roce", 22.5)
    assert ok is True


def test_mos_percent_range():
    assert validate_field("margin_of_safety", -50.0)[0] is True
    assert validate_field("margin_of_safety", 150.0)[0] is True
    # +600% would break even the widest sane range
    assert validate_field("margin_of_safety", 600.0)[0] is False


def test_nan_fails():
    ok, err = validate_field("wacc", float("nan"))
    assert ok is False
    assert err is not None and "NaN" in err


def test_none_value_is_skipped():
    ok, err = validate_field("wacc", None)
    assert ok is True
    assert err is None


def test_non_numeric_fails():
    ok, err = validate_field("wacc", "0.12")
    # str converts via float() -> passes. We only fail on non-convertible.
    assert ok is True
    ok2, _ = validate_field("wacc", "high")
    assert ok2 is False


def test_unknown_field_is_skipped():
    ok, err = validate_field("some_unknown_field", 9999)
    assert ok is True


# ── New-ratio bounds (Step 8) ────────────────────────────────


def test_current_ratio_bounds():
    assert validate_field("current_ratio", 2.1)[0] is True
    assert validate_field("current_ratio", 25.0)[0] is False


def test_asset_turnover_bounds():
    assert validate_field("asset_turnover", 0.85)[0] is True
    assert validate_field("asset_turnover", 12.0)[0] is False


def test_revenue_cagr_is_decimal():
    # 12.4% growth = 0.124 decimal
    assert validate_field("revenue_cagr_3y", 0.124)[0] is True
    # 200% growth wouldn't pass
    assert validate_field("revenue_cagr_3y", 2.0)[0] is False


def test_debt_ebitda_bounds():
    assert validate_field("debt_ebitda", 0.4)[0] is True
    assert validate_field("debt_ebitda", -10)[0] is False


def test_interest_coverage_bounds():
    assert validate_field("interest_coverage", 28.0)[0] is True
    assert validate_field("interest_coverage", 5000.0)[0] is False


# ── Consistency rules ────────────────────────────────────────


def test_wide_moat_low_roce_is_flagged():
    errs = check_consistency({"moat": "Wide", "roce": 8.0})
    assert any("Wide moat" in e and "ROCE" in e for e in errs)


def test_wide_moat_strong_roce_passes():
    errs = check_consistency({"moat": "Wide", "roce": 25.0})
    assert not any("Wide moat" in e for e in errs)


def test_mos_inconsistent_with_fv_cmp():
    # FV 1200 / CMP 1000 -> MoS should be +20%, not -5%
    errs = check_consistency({
        "fair_value": 1200.0,
        "current_price": 1000.0,
        "margin_of_safety": -5.0,
    })
    assert any("MoS" in e and "inconsistent" in e for e in errs)


def test_mos_consistent_with_fv_cmp_passes():
    errs = check_consistency({
        "fair_value": 1200.0,
        "current_price": 1000.0,
        "margin_of_safety": 20.0,
    })
    assert not any("inconsistent" in e for e in errs)


def test_piotroski_high_with_high_de_flagged():
    errs = check_consistency({
        "piotroski_score": 8,
        "de_ratio": 3.5,
    })
    assert any("F-Score" in e and "D/E" in e for e in errs)


def test_fv_cmp_ratio_5x_fails():
    errs = check_consistency({
        "fair_value": 10000.0,
        "current_price": 1000.0,
    })
    assert any("FV/CMP ratio" in e for e in errs)


def test_wacc_below_rf_floor_flagged():
    errs = check_consistency({"wacc": 0.02})
    assert any("WACC" in e and "risk-free" in e for e in errs)


# ── validate_stock composite ─────────────────────────────────


def test_valid_record_passes():
    record = {
        "symbol": "HCLTECH",
        "fair_value": 1173.0,
        "current_price": 1442.0,
        "margin_of_safety": -18.7,
        "wacc": 0.12,
        "terminal_growth": 0.025,
        "roe": 24.96,
        "de_ratio": 0.1,
        "piotroski_score": 7,
        "yieldiq_score": 49,
        "market_cap": 3_902_362_652_093.0,
        "moat": "Narrow",
    }
    ok, errors = validate_stock(record)
    assert ok is True, f"expected valid, got errors: {errors}"


def test_broken_wacc_record_fails_critical():
    record = {
        "symbol": "HCLTECH",
        "wacc": 12.0,  # percent in a decimal slot
        "roe": 0.2,    # already looks suspicious (would render as 0.2%)
        "fair_value": 6067.0,
        "current_price": 1442.0,
        "margin_of_safety": 268.0,
        "yieldiq_score": 49,
    }
    ok, errors = validate_stock(record)
    assert ok is False
    assert any("wacc" in e for e in errors)


def test_non_dict_returns_error():
    ok, errors = validate_stock("not a dict")  # type: ignore[arg-type]
    assert ok is False
    assert errors


# ── Canary ───────────────────────────────────────────────────


def test_canary_hcl_clean_values_pass():
    db = {
        "HCLTECH": {
            "roe": 24.96,
            "de_ratio": 0.1,
            "wacc": 0.12,
            "market_cap_cr": 400_000,
        },
    }
    # Canary validates only listed symbols from CANARY_STOCKS; missing others
    # are reported, so we check that HCLTECH itself has no violations.
    violations = run_canary(db)
    hcl = [v for v in violations if v.startswith("HCLTECH.")]
    assert hcl == []


def test_canary_hcl_broken_roe_fails():
    db = {
        "HCLTECH": {
            "roe": 0.2,    # the diagnostic-reported broken value
            "de_ratio": 0.1,
            "wacc": 0.12,
            "market_cap_cr": 400_000,
        },
    }
    violations = run_canary(db)
    hcl = [v for v in violations if v.startswith("HCLTECH.roe")]
    assert len(hcl) == 1
    assert "outside canary range" in hcl[0]


def test_canary_missing_symbol_reported():
    violations = run_canary({})
    # All 20 stocks missing
    missing = [v for v in violations if "missing" in v]
    assert len(missing) == len(CANARY_STOCKS)


def test_canary_accepts_ns_suffix():
    db = {
        "TCS.NS": {
            "roe": 45.0,
            "de_ratio": 0.05,
            "wacc": 0.11,
            "market_cap_cr": 1_100_000,
        },
    }
    violations = run_canary(db)
    tcs = [v for v in violations if v.startswith("TCS.")]
    assert tcs == []


def test_canary_derives_mcap_cr_from_raw_inr():
    db = {
        "RELIANCE": {
            "roe": 9.0,
            "de_ratio": 0.4,
            "wacc": 0.11,
            "market_cap": 1_700_000 * 1e7,  # raw INR for ~17L Cr
        },
    }
    violations = run_canary(db)
    ril = [v for v in violations if v.startswith("RELIANCE.")]
    assert ril == []


# ── BOUNDS sanity ────────────────────────────────────────────


def test_every_bound_is_well_formed():
    for field, (lo, hi, sev) in BOUNDS.items():
        assert lo < hi, f"{field}: lo={lo} >= hi={hi}"
        assert sev in ("critical", "warning"), f"{field}: invalid severity {sev}"


if __name__ == "__main__":
    raise SystemExit(pytest.main([__file__, "-v"]))
