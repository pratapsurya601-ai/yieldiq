"""Day-20 (2026-05-20): regression guards for the WACC-ceiling fix
(Day-16/Day-19 floors were no-ops) and the safety-net revenue
field (Day-18 logistics rescue couldn't fire because Story-DCF got
zero revenue from the rescue chain's _fin_sn dict).

Both bugs were caught by the impact_check_day14_19.py validation
post-force-warm: only 3/24 named tickers showed real movement;
13/24 still showed the same FV at cache_version=121 because the
engine-level changes were no-ops in practice.

Source-text grep is used so tests run without numpy/pandas.
"""
from __future__ import annotations
from pathlib import Path


_FORECASTER = Path(__file__).resolve().parents[2] / "models" / "forecaster.py"
_SERVICE = Path(__file__).resolve().parents[2] / "backend" / "services" / "analysis" / "service.py"


def test_hospital_chain_wacc_ceiling_present():
    """Day-20: the hospital sub-bucket gets a POST-clip WACC CEILING
    of 0.095, not just a pre-clip floor. The floor (Day-16) was a
    no-op because CAPM-derived hospital WACCs sit at 0.098-0.128
    — already above the 0.085 floor. The ceiling at 0.095 actually
    bites: it pulls APOLLOHOSP / NH (0.098) and AGARWALEYE (0.128)
    down to 0.095, lifting their TV via the wacc-g spread."""
    src = _FORECASTER.read_text(encoding="utf-8")
    assert "if _ticker_bare in _HOSPITAL_CHAIN_TICKERS and wacc > 0.095:" in src
    assert "wacc = 0.095" in src


def test_pharma_cdmo_wacc_ceiling_present():
    """Day-20: same ceiling pattern for CDMOs at 0.105 (between
    hospitals 0.095 and generic-pharma 0.105 floor below)."""
    src = _FORECASTER.read_text(encoding="utf-8")
    assert "elif _ticker_bare in _PHARMA_CDMO_TICKERS and wacc > 0.105:" in src
    assert "wacc = 0.105" in src


def test_wacc_ceiling_block_appears_after_main_clip():
    """The ceiling MUST run AFTER the np.clip(wacc, floor, 0.20)
    block — otherwise the clip would re-apply the 0.20 cap and the
    ceiling has no effect on the final value."""
    src = _FORECASTER.read_text(encoding="utf-8")
    clip_idx = src.find("e_w * re + d_w * rd * (1 - tax_rate),")
    ceiling_idx = src.find("if _ticker_bare in _HOSPITAL_CHAIN_TICKERS and wacc > 0.095:")
    assert clip_idx > 0 and ceiling_idx > clip_idx, (
        "WACC ceiling for hospital chains must appear AFTER the main "
        "np.clip() block (line ~1223). Currently the order is wrong."
    )


def test_safety_net_passes_revenue_to_story_dcf():
    """Day-20: the safety-net _fin_sn dict (service.py:2574) now
    includes "revenue" + "latest_revenue". Without these, the 3rd
    rescue rung (Story DCF) returns None at the rev0<=0 guard, so
    DELHIVERY / PAYTM / MEESHO / etc. cannot be rescued by story-
    DCF when DCF collapses."""
    src = _SERVICE.read_text(encoding="utf-8")
    # Confirm the new revenue assignment line is present
    assert '_revenue_raw = enriched.get("revenue") or enriched.get("latest_revenue")' in src, (
        "Day-20 revenue assignment line missing from safety-net block."
    )
    # Confirm both fields are passed into the _fin_sn dict
    assert '"revenue": _revenue_raw,' in src
    assert '"latest_revenue": _revenue_raw,' in src


def test_safety_net_revenue_assignment_inside_unreasonable_block():
    """The _revenue_raw assignment + _fin_sn dict must live INSIDE
    the `if _dcf_is_unreasonable(iv, price):` block, not above it —
    otherwise we'd compute revenue for every analysis (wasteful)
    and the locals could leak into other code paths.

    Heuristic: the _revenue_raw line should appear AFTER the
    is_unreasonable check but BEFORE the dict literal."""
    src = _SERVICE.read_text(encoding="utf-8")
    unreasonable_idx = src.find("if _dcf_is_unreasonable(iv, price):")
    revenue_idx = src.find('_revenue_raw = enriched.get("revenue")')
    dict_idx = src.find('"revenue": _revenue_raw,')
    assert unreasonable_idx > 0
    assert unreasonable_idx < revenue_idx < dict_idx, (
        "_revenue_raw must be assigned inside the is_unreasonable "
        "block, just before the _fin_sn dict literal."
    )
