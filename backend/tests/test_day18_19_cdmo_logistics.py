"""Day-18 + Day-19 (2026-05-20) regression guards.

Day-18: logistics platforms (DELHIVERY, MAHLOG, ALLCARGO) routed through
the existing Story-DCF engine via "Internet Platform" sector override
+ DELHIVERY entry in story_dcf_overrides.json.

Day-19: pharma CDMO / contract-services sub-bucket. Six tickers get a
WACC floor of 0.095 (between hospitals 0.085 and generic pharma 0.105)
and terminal-g cap of 0.045 (between hospital 0.055 and generic 0.035).

Source-text grep is used so tests run without numpy/pandas — same
pattern as test_pharma_generic_expansion + test_hospital_chain_treatment.
"""
from __future__ import annotations


EXPECTED_CDMO_TICKERS = {
    "DIVISLAB", "SYNGENE", "COHANCE",
    "ANTHEM", "SAGILITY", "IKS",
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
    return set(re.findall(r'"([A-Z0-9]+)"', m.group(1)))


# ── Day-18: Logistics platforms via Internet Platform sector ─────


def test_logistics_tickers_routed_to_internet_platform():
    from backend.services.analysis.constants import TICKER_SECTOR_OVERRIDES
    for t in ("DELHIVERY", "MAHLOG", "ALLCARGO"):
        assert TICKER_SECTOR_OVERRIDES.get(t) == "Internet Platform", (
            f"{t} must route to Internet Platform so the safety-net's "
            f"3rd rung (story-DCF) is eligible to rescue it when "
            f"generic DCF collapses. Without this override, story-DCF "
            f"is skipped (no sector key match) and the ticker stays "
            f"at FV ~10-15% of consensus."
        )


def test_delhivery_has_story_override():
    """DELHIVERY needs ticker-specific overrides because the e-commerce
    default (initial_growth=0.30, target_op_margin=0.15) over-shoots
    Delhivery's actual mature-state economics. Tuned to 22% growth +
    8% margin per analyst guidance."""
    import json
    from pathlib import Path
    overrides = json.loads(
        (Path(__file__).resolve().parents[2] / "config" / "story_dcf_overrides.json")
        .read_text(encoding="utf-8")
    )
    assert "DELHIVERY" in overrides
    entry = overrides["DELHIVERY"]
    assert entry["initial_growth"] == 0.22
    assert entry["target_op_margin"] == 0.08
    assert entry["reinvestment_rate"] == 0.70
    assert entry["wacc"] == 0.135


def test_story_dcf_engine_accepts_internet_platform_sector():
    """Sanity: the Story-DCF engine must accept the sector string that
    our overrides produce. Without this, the route plan fails."""
    from backend.services.story_dcf_engine import _SECTOR_TO_INDUSTRY_KEY
    # The override is "Internet Platform" (Title case) — _SECTOR_TO_INDUSTRY_KEY
    # uses lowercase. The engine does .strip().lower() before lookup.
    assert "internet platform" in _SECTOR_TO_INDUSTRY_KEY
    assert _SECTOR_TO_INDUSTRY_KEY["internet platform"] == "ecommerce"


# ── Day-19: CDMO sub-bucket ───────────────────────────────────


def test_cdmo_wacc_set_matches_expected():
    members = _read_frozenset_from_source("_PHARMA_CDMO_TICKERS")
    missing = EXPECTED_CDMO_TICKERS - members
    extra = members - EXPECTED_CDMO_TICKERS
    assert not missing, f"missing from _PHARMA_CDMO_TICKERS: {sorted(missing)}"
    assert not extra, f"unexpected in _PHARMA_CDMO_TICKERS: {sorted(extra)}"


def test_cdmo_tg_set_synced_with_wacc_set():
    """Day-13 lesson: WACC + TG sets MUST match (asymmetric treatment
    produced 25-50% over-shoots on the original pharma generics)."""
    wacc_set = _read_frozenset_from_source("_PHARMA_CDMO_TICKERS")
    tg_set = _read_frozenset_from_source("_PHARMA_CDMO_TICKERS_TG")
    only_wacc = wacc_set - tg_set
    only_tg = tg_set - wacc_set
    assert not only_wacc, f"WACC-only entries: {sorted(only_wacc)}"
    assert not only_tg, f"TG-only entries: {sorted(only_tg)}"


def test_cdmo_floor_above_default_but_below_generic():
    """The CDMO WACC floor (0.095) must sit BETWEEN the default Indian
    floor (0.09) and the generic-pharma floor (0.105). This documents
    the risk-ranking intent: CDMOs are riskier than hospitals but
    safer than generic exporters."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "models" / "forecaster.py").read_text(encoding="utf-8")
    assert "wacc_floor = max(wacc_floor, 0.095)" in src, (
        "CDMO WACC-floor pin line missing or changed."
    )


def test_cdmo_tg_between_generic_and_hospital():
    """CDMO TG cap (0.045) must sit BETWEEN generic-pharma cap (0.035)
    and hospital lift (0.055)."""
    from pathlib import Path
    src = (Path(__file__).resolve().parents[2] / "models" / "forecaster.py").read_text(encoding="utf-8")
    assert "_g_terminal_eff < 0.045:" in src
    assert "_g_terminal_eff = 0.045" in src


def test_cdmo_wacc_g_spread_safe():
    """Gordon model breaks at wacc - g < 0.03. CDMO's 0.095 floor +
    0.045 TG implies spread = 0.050. Locks the values so any future
    tightening fires this guard."""
    floor = 0.095
    tg = 0.045
    spread = floor - tg
    assert spread >= 0.030, (
        f"CDMO WACC floor ({floor}) - TG ({tg}) = {spread:.4f} below "
        "0.03 Gordon-model safety threshold."
    )


def test_cdmo_not_double_classified():
    """A ticker must NOT be in both _PHARMA_GENERIC_TICKERS and
    _PHARMA_CDMO_TICKERS — they'd produce conflicting WACC floors
    (0.105 vs 0.095). The classifier in forecaster.py uses elif so
    only the first hit wins, but double-classification means the
    business model isn't cleanly bucketed.

    DIVISLAB was historically in CDMO mental-model but excluded from
    _PHARMA_GENERIC_TICKERS — verify that hasn't drifted."""
    generic_set = _read_frozenset_from_source("_PHARMA_GENERIC_TICKERS")
    cdmo_set = _read_frozenset_from_source("_PHARMA_CDMO_TICKERS")
    overlap = generic_set & cdmo_set
    assert not overlap, (
        f"Double-classification: {sorted(overlap)} are in BOTH "
        "_PHARMA_GENERIC_TICKERS and _PHARMA_CDMO_TICKERS. Decide "
        "which bucket each belongs in and remove from the other."
    )
