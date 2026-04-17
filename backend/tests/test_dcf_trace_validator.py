# backend/tests/test_dcf_trace_validator.py
# Unit tests for validate_dcf_trace — the deterministic red-flag checks
# that run against the DCF_TRACES ring-buffer entries.
from __future__ import annotations

from backend.services.validators import validate_dcf_trace


def _base_trace(**overrides):
    """Build a synthetic 'healthy' trace; override keys to simulate issues."""
    t = {
        "fcf_base": 1_000.0,
        "fcfN": 1_500.0,
        "impl_g": 0.10,
        "terminal_fcf_norm": 1_600.0,
        "terminal_value": 25_000.0,
        "pv_tv": 12_000.0,
        "tv_pct_ev": 0.65,
        "enterprise_value": 18_000.0,
        "total_debt": 500.0,
        "total_cash": 1_000.0,
        "equity_value": 18_500.0,
        "shares": 100.0,
        "raw_iv": 185.0,
        "price": 150.0,
        "iv_ratio": 1.23,
        "wacc": 0.12,
        "g": 0.04,
        "capped": False,
        "projected_fcfs": [1_100, 1_200, 1_300, 1_400, 1_500],
    }
    t.update(overrides)
    return t


def test_healthy_trace_produces_no_issues():
    issues, sev = validate_dcf_trace("HEALTHYCO", _base_trace())
    assert issues == []
    assert sev == "ok"


def test_iv_ratio_4_flags_warning_and_capped_info():
    # Mirrors HCLTECH: iv_ratio=4.23 capped=True
    trace = _base_trace(iv_ratio=4.23, capped=True)
    issues, sev = validate_dcf_trace("HCLTECH", trace)
    assert len(issues) == 2
    assert any("4.2x price" in i for i in issues)
    assert any("capped" in i for i in issues)
    assert sev == "warning"  # capped is info, iv_ratio>3 is warning


def test_tv_pct_ev_096_flags_critical():
    trace = _base_trace(tv_pct_ev=0.96)
    issues, sev = validate_dcf_trace("FRAGILECO", trace)
    assert len(issues) == 1
    assert "96%" in issues[0]
    assert sev == "critical"


def test_wacc_g_spread_too_narrow_flags_critical():
    # wacc=0.08, g=0.065 → spread = 0.015 < 0.03
    trace = _base_trace(wacc=0.08, g=0.065)
    issues, sev = validate_dcf_trace("EXPLODECO", trace)
    assert len(issues) == 1
    assert "WACC-g spread" in issues[0]
    assert "1.50%" in issues[0]
    assert sev == "critical"


def test_fcf_base_non_positive_is_critical():
    trace = _base_trace(fcf_base=-100.0)
    issues, sev = validate_dcf_trace("BURNCO", trace)
    assert any("non-positive" in i for i in issues)
    assert sev == "critical"


def test_non_dict_trace_is_safe():
    issues, sev = validate_dcf_trace("X", None)  # type: ignore[arg-type]
    assert issues == []
    assert sev == "ok"
