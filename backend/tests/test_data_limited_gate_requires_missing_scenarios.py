"""Day-? (2026-05-24): data_limited verdict gate tighten.

The 2026-05-24 FV/MoS audit found LT.NS shipping verdict='data_limited'
despite a complete valuation:

    fair_value=2211.55, current_price=3926.6, mos=-43.7%,
    bear_case=1210.4, base_case=2211.55, bull_case=3153.5,
    wacc=9.8%, confidence=33, roe=14.72%, de_ratio=1.15, roce=14.6%

Root cause: the confidence-only gate in
``backend/services/analysis/service.py`` (the elif branch keyed on
``_conf_score < 35 and abs(mos_pct) > 40``) triggered data_limited
without checking whether the engine had actually produced a valid
valuation. data_limited should mean "we literally can't compute" —
not "we computed but confidence is modest". Low confidence on its
own is surfaced via the frontend's ``shouldGateVerdict`` helper
(Day-91) which renders the "Under Review" pill + caution chip
without erasing the underlying numbers.

Fix: require BOTH (a) low confidence AND (b) at least one scenario
missing (iv<=0 OR bear<=0 OR bull<=0). This is a source-text
regression guard because exercising the full ``service.py`` pipeline
in a unit test requires the entire enrichment stack — the canary-diff
harness is the integration-level check.
"""
from __future__ import annotations
from pathlib import Path


_SERVICE = (
    Path(__file__).resolve().parents[2]
    / "backend" / "services" / "analysis" / "service.py"
)


def _read_service_src() -> str:
    return _SERVICE.read_text(encoding="utf-8")


def test_data_limited_confidence_gate_requires_missing_scenarios():
    """The two confidence-based data_limited branches must AND-in a
    scenarios-missing check. A complete valuation with low confidence
    should fall through to the normal MoS verdict tree, not get
    silently re-labelled data_limited."""
    src = _read_service_src()

    # Both gates (label-based and score-based) check iv + bear_iv + bull_iv.
    # Tolerate the exact `(... or 0) <= 0` form the fix uses.
    expected_fragment = "iv <= 0\n                or (bear_iv or 0) <= 0\n                or (bull_iv or 0) <= 0"
    occurrences = src.count(expected_fragment)
    assert occurrences >= 2, (
        f"Expected the scenarios-missing check in BOTH the label-based "
        f"(_confidence in (...)) and score-based (_conf_score < 35) "
        f"data_limited gates. Found {occurrences} occurrence(s) of the "
        f"sentinel fragment. If you refactored the check, update this "
        f"test to match — but DO NOT drop the requirement that "
        f"data_limited needs at least one missing scenario."
    )


def test_null_cagr_gate_does_not_zero_iv():
    """The null-CAGR gate must NOT set ``iv = 0`` / ``mos_pct = 0``.
    The verdict flag is the truthful signal; zeroing iv wrote FV=0
    into analysis_cache so any consumer reading the raw JSONB saw
    FV=0 even though the engine had computed a real value. HCLTECH.NS
    and ULTRACEMCO.NS were the canonical 2026-05-24 audit cases.
    """
    src = _read_service_src()

    # The gate is identified by its `_null_cagr_gate_tripped = True`
    # marker. The block must NOT contain `iv = 0` (which was the
    # destructive line removed in this fix).
    marker = "_null_cagr_gate_tripped = True"
    assert marker in src, "null_cagr_gate marker missing — refactored?"
    idx = src.index(marker)
    # Inspect a 400-char window after the marker — covers the whole
    # gate body. Make sure it doesn't re-introduce the zero-out.
    window = src[idx : idx + 400]
    assert "iv = 0" not in window, (
        "null_cagr_gate is zeroing iv again — this writes FV=0 into "
        "analysis_cache (see Bug 2 of the 2026-05-24 FV/MoS audit). "
        "The verdict='data_limited' flag is the signal; preserve iv "
        "so the cache row carries the canonical computed value."
    )
    assert "mos_pct = 0" not in window, (
        "null_cagr_gate is zeroing mos_pct again — same problem as "
        "the iv zero-out. The summary projection layer already gates "
        "display on verdict; preserve the raw MoS for the cache row."
    )
