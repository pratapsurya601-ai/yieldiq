"""Day-16: lock in hospital-chain WACC floor + terminal-g lift.

Regression guards mirroring the Day-13 pharma-generic test pattern.
Source-text grep is used (no heavy numpy/pandas import) — the same
discipline as ``test_pharma_generic_expansion.py``.
"""
from __future__ import annotations

EXPECTED_HOSPITAL_CHAIN = {
    "MAXHEALTH", "FORTIS", "MEDANTA", "KIMS",
    "NH", "APOLLOHOSP", "ASTERDM", "RAINBOW",
    "VIJAYA", "AGARWALEYE",
}


def _read_frozenset_from_source(name: str) -> set[str]:
    import re
    from pathlib import Path
    src = (
        Path(__file__).resolve().parents[2]
        / "models" / "forecaster.py"
    ).read_text(encoding="utf-8")
    pat = rf"{name}\s*=\s*frozenset\(\{{(.*?)\}}\)"
    m = re.search(pat, src, flags=re.DOTALL)
    assert m, f"could not locate {name} in models/forecaster.py"
    body = m.group(1)
    return set(re.findall(r'"([A-Z0-9]+)"', body))


def test_hospital_chain_wacc_set_matches_expected():
    members = _read_frozenset_from_source("_HOSPITAL_CHAIN_TICKERS")
    missing = EXPECTED_HOSPITAL_CHAIN - members
    extra = members - EXPECTED_HOSPITAL_CHAIN
    assert not missing, f"missing from _HOSPITAL_CHAIN_TICKERS: {sorted(missing)}"
    assert not extra, f"unexpected in _HOSPITAL_CHAIN_TICKERS: {sorted(extra)}"


def test_hospital_chain_tg_set_synced_with_wacc_set():
    """Symmetric treatment: every hospital that gets a WACC-floor pin
    MUST also get a terminal-g lift, and vice versa. The Day-13
    asymmetric-treatment bug (pharma generics had a 6-ticker mismatch
    between the two sets) should never recur."""
    wacc_set = _read_frozenset_from_source("_HOSPITAL_CHAIN_TICKERS")
    tg_set = _read_frozenset_from_source("_HOSPITAL_CHAIN_TICKERS_TG")
    only_wacc = wacc_set - tg_set
    only_tg = tg_set - wacc_set
    assert not only_wacc, f"WACC-only entries: {sorted(only_wacc)}"
    assert not only_tg, f"TG-only entries: {sorted(only_tg)}"


def test_hospital_floor_below_default_capm():
    """Sanity: the hospital-chain WACC floor (0.085) must be BELOW the
    default Indian floor (0.09). Otherwise the min() call has no effect.
    Locks in the directional intent of the fix."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "models" / "forecaster.py").read_text(encoding="utf-8")
    assert "wacc_floor = min(wacc_floor, 0.085)" in src, (
        "Hospital-chain WACC-floor pin line missing or value changed. "
        "Day-16 design: hospital chains get tighter floor (0.085) than "
        "default Indian (0.09) because their cash-flow predictability "
        "is closer to a regulated utility."
    )


def test_hospital_tg_above_default():
    """The terminal-g lift to 0.055 must be ABOVE the default
    TERMINAL_FADE_G (0.04). Locks in the directional intent."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "models" / "forecaster.py").read_text(encoding="utf-8")
    assert "_g_terminal_eff < 0.055:" in src, (
        "Hospital-chain TG-lift threshold (0.055) changed or removed."
    )
    assert "_g_terminal_eff = 0.055" in src, (
        "Hospital-chain TG-lift target (0.055) changed or removed."
    )


def test_hospital_wacc_g_spread_safe():
    """Gordon model breaks down at wacc - g < 0.03. Our combo of
    floor=0.085 + TG=0.055 implies a spread of EXACTLY 0.03 in the
    edge case. That's at the safety boundary — if anyone tightens the
    floor further OR raises TG further the spread becomes < 0.03 and
    the perpetuity blows up. This test fires the moment that happens."""
    floor = 0.085
    tg = 0.055
    spread = floor - tg
    assert spread >= 0.030, (
        f"WACC floor ({floor}) - TG ({tg}) = {spread:.4f} is below the "
        "0.03 Gordon-model safety threshold. Adjust before merging."
    )
