"""Tests for the Layer-C verdict-gate wiring in
``backend/services/analysis/service.py``.

Background: PR #376 shipped ``_apply_confidence_verdict_gate`` but the
call site in service.py was lost during the squash-merge of PR #340
(see agent a933's note on PR #376). Without the wiring, Layer C
scoring computes three pillar scores per ticker but the verdict gate
never fires — so broken-FV tickers (e.g. INDIACEM with FV=0.77 at
CMP=405) still ship as "Notably Undervalued/Overvalued" instead of
"Under Review".

These tests pin the wiring:

* The import + call exists in service.py at the documented call site
  (right before ``return AnalysisResponse(...)``).
* End-to-end gate behaviour via the *exact same* call shape used by
  the wiring (verdict, dq, mc, vs, issues, fair_value=, current_price=,
  valuation_model=) for the three required scenarios:
  - INDIACEM-shape FV ratio extreme + low confidence  -> under_review
  - extreme ratio + high confidence                   -> unchanged
  - rate_base engine + extreme ratio                  -> unchanged
"""

from __future__ import annotations

import ast
import inspect
from pathlib import Path

import backend.services.analysis.service as analysis_service
from backend.services.confidence_service import _apply_confidence_verdict_gate


# ───────────────────────────────────────────────────────────────────
# Wiring presence — fails loudly if the call site is removed/renamed
# ───────────────────────────────────────────────────────────────────
def test_wiring_imports_gate_in_service_module() -> None:
    """The service module must import (locally or top-level) the gate
    function by its real name. We accept either the underscored or the
    public-alias spelling."""
    src = Path(inspect.getsourcefile(analysis_service)).read_text(
        encoding="utf-8"
    )
    assert (
        "_apply_confidence_verdict_gate" in src
        or "apply_confidence_verdict_gate" in src
    ), "verdict gate not imported in analysis/service.py"


def test_wiring_call_site_present_before_response_construction() -> None:
    """The gate must be invoked before the ``return AnalysisResponse``
    that ships the verdict, otherwise the override never takes
    effect."""
    src = Path(inspect.getsourcefile(analysis_service)).read_text(
        encoding="utf-8"
    )
    gate_idx = src.rfind("_apply_confidence_verdict_gate")
    assert gate_idx != -1, "gate function never referenced in service.py"
    # The wiring must sit before the final AnalysisResponse return that
    # uses ``verdict=verdict``. We assert at least one such return
    # follows the gate invocation.
    tail = src[gate_idx:]
    assert "AnalysisResponse(" in tail, (
        "verdict gate must be invoked before the AnalysisResponse "
        "construction that consumes ``verdict``"
    )
    assert "verdict=verdict" in tail, (
        "expected ``verdict=verdict`` in AnalysisResponse after the gate"
    )


def test_wiring_passes_required_kwargs() -> None:
    """Spot-check that the wiring passes the four kwargs that govern
    gate behaviour: fair_value, current_price, valuation_model, and
    the three pillar scores. A regression that drops any of these
    would silently disable the override."""
    src = Path(inspect.getsourcefile(analysis_service)).read_text(
        encoding="utf-8"
    )
    # Find the AST call to the gate.
    tree = ast.parse(src)
    found = False
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = getattr(func, "id", None) or getattr(func, "attr", None)
        if name not in ("_apply_confidence_verdict_gate",
                        "apply_confidence_verdict_gate",
                        "_vg_apply"):
            continue
        kwarg_names = {kw.arg for kw in node.keywords if kw.arg}
        # Required kwargs per gate signature.
        for required in ("fair_value", "current_price", "valuation_model"):
            assert required in kwarg_names, (
                f"verdict-gate call missing kwarg ``{required}``; "
                f"got {sorted(kwarg_names)}"
            )
        found = True
    assert found, "no call to verdict gate found in service.py AST"


# ───────────────────────────────────────────────────────────────────
# Behavioural — the wiring uses the gate exactly like these calls,
# so these pin end-to-end semantics for the three required scenarios.
# ───────────────────────────────────────────────────────────────────
def test_wiring_scenario_indiacem_extreme_ratio_low_conf() -> None:
    """FV=0.77, CMP=405, model_conf=50 (the exact shape from the brief
    acceptance criterion). Gate must force ``under_review``."""
    verdict, issues = _apply_confidence_verdict_gate(
        verdict="notably_undervalued",
        data_quality=60,
        model_confidence=50,
        valuation_stability=70,
        data_issues=[],
        fair_value=0.77,
        current_price=405.0,
        valuation_model="dcf",
    )
    assert verdict == "under_review"
    assert any("FV/price ratio" in i for i in issues)


def test_wiring_scenario_high_confidence_extreme_ratio_unchanged() -> None:
    """High confidence on all three pillars: trust the engine, don't
    override even when the ratio is extreme."""
    verdict, _ = _apply_confidence_verdict_gate(
        verdict="notably_undervalued",
        data_quality=85,
        model_confidence=90,
        valuation_stability=85,
        data_issues=[],
        fair_value=0.77,
        current_price=405.0,
        valuation_model="dcf",
    )
    assert verdict == "notably_undervalued"


def test_wiring_scenario_rate_base_carveout_extreme_ratio_unchanged() -> None:
    """Regulated-utility engine (rate_base) is carved out of the
    extreme-ratio override. The intensity cap may still rewrite the
    verdict (mc=50 < 70 triggers cap to fairly_valued), but it must
    NOT be ``under_review``."""
    verdict, issues = _apply_confidence_verdict_gate(
        verdict="notably_undervalued",
        data_quality=60,
        model_confidence=50,
        valuation_stability=70,
        data_issues=[],
        fair_value=0.77,
        current_price=405.0,
        valuation_model="rate_base",
    )
    assert verdict != "under_review"
    # No extreme-ratio "Manual review required" caveat for carve-outs.
    assert not any(
        "FV/price ratio" in i and "Manual review" in i for i in issues
    )
