"""Day-24 (2026-05-20): regression guard for the per-step timings
instrumentation. The 10 Step N boundaries in
``_get_full_analysis_inner`` each get a ``_record_step()`` call so
the perf dashboard (Day-26) can answer "which step dominates the
2.7s cold p50?"

Source-text grep — no heavy imports needed.
"""
from __future__ import annotations
from pathlib import Path


_SERVICE = Path(__file__).resolve().parents[2] / "backend" / "services" / "analysis" / "service.py"
_RESPONSES = Path(__file__).resolve().parents[2] / "backend" / "models" / "responses.py"


EXPECTED_STEP_NAMES = [
    "step1_fetch",
    "step2_validate",
    "step3_metrics",
    "step4_company",
    "step5_wacc_forecast",
    "step6_valuation",
    "step7_quality",
    "step8_scenarios",
    "step9_insights",
    "step10_verdict",
]


def test_response_model_has_timings_ms_field():
    """AnalysisResponse must declare timings_ms (NOT _timings — leading
    underscore would be a Pydantic v2 PrivateAttr and excluded from
    JSON serialization)."""
    src = _RESPONSES.read_text(encoding="utf-8")
    assert "timings_ms: Optional[dict[str, int]] = None" in src, (
        "AnalysisResponse.timings_ms field missing or signature changed."
    )
    # Confirm leading-underscore version is NOT present (would be private)
    assert "_timings: Optional[dict[str, int]]" not in src, (
        "Field has leading underscore — Pydantic v2 treats this as "
        "PrivateAttr. Rename to timings_ms."
    )


def test_all_10_step_record_calls_present():
    """Each Step N boundary should record a delta via _record_step()."""
    src = _SERVICE.read_text(encoding="utf-8")
    missing = [s for s in EXPECTED_STEP_NAMES if f'_record_step("{s}")' not in src]
    assert not missing, (
        f"Missing _record_step calls for: {missing}. "
        "Every Step N boundary should record its delta."
    )


def test_record_step_helper_defined():
    """The _record_step nested helper must be defined inside
    _get_full_analysis_inner before Step 1 begins."""
    src = _SERVICE.read_text(encoding="utf-8")
    assert "def _record_step(name: str) -> None:" in src
    assert "_timings_steps: dict[str, int] = {}" in src
    assert "_t_inner_start = _time_t.perf_counter()" in src


def test_timings_threaded_into_response():
    """The AnalysisResponse(...) constructor at the end of
    _get_full_analysis_inner must pass the populated timings dict."""
    src = _SERVICE.read_text(encoding="utf-8")
    assert "timings_ms=_timings_steps if _timings_steps else None," in src


def test_total_inner_ms_recorded():
    """total_inner_ms is the wall-clock for the entire inner method.
    This is the headline metric Day-26 dashboard will plot."""
    src = _SERVICE.read_text(encoding="utf-8")
    assert '_timings_steps["total_inner_ms"] = int(' in src
    assert "(_time_t.perf_counter() - _t_inner_start) * 1000" in src


def test_record_step_happens_before_step_n_blocks():
    """Sanity: the _record_step for stepN must IMMEDIATELY PRECEDE
    the Step N+1 boundary comment. This locks in that the timing
    records what was JUST completed, not what's about to run."""
    src = _SERVICE.read_text(encoding="utf-8")
    # Pair each _record_step with the next Step header
    pairs = [
        ("step1_fetch",        "# ── Step 2: Validate"),
        ("step2_validate",     "# ── Step 3: Compute metrics"),
        ("step3_metrics",      "# ── Step 4: Build company info"),
        ("step4_company",      "# ── Step 5: WACC + Forecast"),
        ("step5_wacc_forecast","# ── Step 6: Valuation"),
        ("step6_valuation",    "# ── Step 7: Quality"),
        ("step7_quality",      "# ── Step 8: Scenarios"),
        ("step8_scenarios",    "# ── Step 9: Insights"),
        ("step9_insights",     "# ── Step 10: Verdict"),
    ]
    for step_name, next_header in pairs:
        record_idx = src.find(f'_record_step("{step_name}")')
        header_idx = src.find(next_header, record_idx)
        assert record_idx > 0 and header_idx > 0, f"{step_name}: anchors not found"
        # The header should be the very next significant content (within ~200 chars)
        gap = src[record_idx:header_idx]
        assert header_idx - record_idx < 200, (
            f"{step_name}: large gap ({header_idx - record_idx} chars) before "
            f"the next Step header. The record should be tight to the boundary."
        )
