"""Day-21 (2026-05-20): regression guard for the TG-lift propagation
fix (Bug B). The Day-16/Day-19 lift blocks inside
FCFForecaster.predict() were structurally orphaned — they mutated a
LOCAL _g_terminal_eff that never propagated to DCFEngine. Day-21 moves
the lift to service.py BEFORE DCFEngine construction.

Source-text grep keeps tests fast + no heavy imports.
"""
from __future__ import annotations
from pathlib import Path


_SERVICE = Path(__file__).resolve().parents[2] / "backend" / "services" / "analysis" / "service.py"


def test_hospital_tg_lift_block_in_service_py():
    """The TG-lift block must live in service.py BEFORE the
    DCFEngine construction, otherwise the terminal_g passed to
    DCFEngine(terminal_growth=...) is the un-lifted default."""
    src = _SERVICE.read_text(encoding="utf-8")
    assert "_HOSPITAL_CHAIN_TICKERS_INLINE" in src
    assert "if _bare_ticker_tg in _HOSPITAL_CHAIN_TICKERS_INLINE and terminal_g < 0.055:" in src
    assert "terminal_g = _tg_proposed" in src


def test_cdmo_tg_lift_block_in_service_py():
    """Same pattern for the CDMO sub-bucket."""
    src = _SERVICE.read_text(encoding="utf-8")
    assert "_PHARMA_CDMO_TICKERS_INLINE" in src
    assert "elif _bare_ticker_tg in _PHARMA_CDMO_TICKERS_INLINE and terminal_g < 0.045:" in src


def test_tg_lift_block_appears_before_dcfengine_construction():
    """Critical: the lift must run BEFORE the DCFEngine(...) call at
    ~L1896. Otherwise terminal_g is finalised to a stale value before
    the lift fires."""
    src = _SERVICE.read_text(encoding="utf-8")
    lift_idx = src.find("_HOSPITAL_CHAIN_TICKERS_INLINE")
    dcfengine_idx = src.find("dcf_engine = DCFEngine(")
    assert lift_idx > 0 and dcfengine_idx > 0
    assert lift_idx < dcfengine_idx, (
        "Hospital/CDMO TG lift must run BEFORE DCFEngine construction. "
        "If reversed, the lift has zero effect on TV computation."
    )


def test_tg_lift_preserves_wacc_safety_guard():
    """The wacc - 0.02 safety guard must be preserved — Gordon model
    blows up when wacc - g < 0.03. The lift is conditional on the
    new TG staying below this safety threshold."""
    src = _SERVICE.read_text(encoding="utf-8")
    assert "if _tg_proposed < wacc - 0.02:" in src, (
        "The wacc safety guard around the TG lift is missing or "
        "changed. Without it, TV can blow up when WACC drops to "
        "0.085 (hospital ceiling) and TG is 0.055 — spread = 0.03 "
        "exactly at Gordon breakdown threshold."
    )


def test_tg_lift_emits_data_issue_caveat():
    """The lift writes a [hospital-chain-tg-lifted] / [pharma-cdmo-tg-
    lifted] caveat to data_issues so the frontend / admin / debug
    UIs can see when the lift fired. This is the OBSERVABILITY fix
    that Bug B was originally meant to provide (the orphaned
    enriched flag mutation was unreachable)."""
    src = _SERVICE.read_text(encoding="utf-8")
    assert "[hospital-chain-tg-lifted]" in src
    assert "[pharma-cdmo-tg-lifted]" in src


def test_tg_lift_set_membership_matches_forecaster():
    """The inline sets in service.py MUST match the canonical sets
    in models/forecaster.py — otherwise the WACC ceiling and TG lift
    fire for DIFFERENT tickers, producing asymmetric Gordon spreads
    that violate the 0.030 minimum."""
    import re
    _FORECASTER = Path(__file__).resolve().parents[2] / "models" / "forecaster.py"
    fc_src = _FORECASTER.read_text(encoding="utf-8")
    svc_src = _SERVICE.read_text(encoding="utf-8")

    def _extract(src: str, name: str) -> set[str]:
        m = re.search(rf"{name}\s*=\s*frozenset\(\{{(.*?)\}}\)", src, flags=re.DOTALL)
        if not m:
            m = re.search(rf"{name}\s*=\s*\{{(.*?)\}}", src, flags=re.DOTALL)
        assert m, f"could not find {name}"
        return set(re.findall(r'"([A-Z0-9]+)"', m.group(1)))

    hospital_fc = _extract(fc_src, "_HOSPITAL_CHAIN_TICKERS")
    hospital_svc = _extract(svc_src, "_HOSPITAL_CHAIN_TICKERS_INLINE")
    assert hospital_fc == hospital_svc, (
        f"hospital ticker sets disagree:\n"
        f"  forecaster.py has {sorted(hospital_fc)}\n"
        f"  service.py inline has {sorted(hospital_svc)}\n"
        f"DRIFT = forecaster_only={hospital_fc - hospital_svc}, "
        f"service_only={hospital_svc - hospital_fc}"
    )

    cdmo_fc = _extract(fc_src, "_PHARMA_CDMO_TICKERS")
    cdmo_svc = _extract(svc_src, "_PHARMA_CDMO_TICKERS_INLINE")
    assert cdmo_fc == cdmo_svc, (
        f"CDMO ticker sets disagree:\n"
        f"  forecaster.py has {sorted(cdmo_fc)}\n"
        f"  service.py inline has {sorted(cdmo_svc)}\n"
    )
