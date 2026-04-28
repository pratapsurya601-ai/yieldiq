"""Unit tests for the canary-diff harness gates.

Each gate has a clean-data PASS test and an injected-violation FAIL
test, exactly as specified in the merge-gate plan.
"""
from __future__ import annotations

import sys
from pathlib import Path

# Make ``scripts`` importable as a top-level package directory.
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import canary_diff as cd  # noqa: E402


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _clean_fields(**overrides):
    # API contract:
    #   roe / roce / mos -> PERCENT (e.g. 25.0 = 25%)
    #   wacc / debt_to_equity / revenue_cagr_3y -> DECIMAL (e.g. 0.11)
    # Gate 4 normalises percent fields via _to_decimal() before comparing
    # to canary bounds (which are decimal). Gate 5 uses the raw API
    # values. Fixtures must therefore reflect the API shape, not the
    # bounds shape.
    base = {
        "cmp": 1000.0,
        "fair_value": 1200.0,
        "margin_of_safety": 20.0,
        "bear_case": 900.0,
        "base_case": 1200.0,
        "bull_case": 1500.0,
        "roe": 25.0,    # percent — equiv decimal 0.25
        "roce": 30.0,   # percent — equiv decimal 0.30
        "wacc": 0.11,
        "ev_ebitda": 18.0,
        "revenue_cagr_3y": 0.10,
        "debt_to_equity": 0.10,
        "market_cap_cr": 400000,
    }
    base.update(overrides)
    return base


HCLTECH_BOUNDS = {
    "roe": [0.20, 0.30],
    "debt_to_equity": [0.00, 0.20],
    "wacc": [0.09, 0.13],
    "market_cap_cr": [350000, 550000],
    "revenue_cagr_3y": [0.05, 0.18],
}


# ---------------------------------------------------------------------------
# Gate 1 — single source of truth
# ---------------------------------------------------------------------------


def test_gate1_passes_when_public_matches_authed():
    f = _clean_fields()
    assert cd.gate1_single_source("HCLTECH", f, f) == []


def test_gate1_fails_when_public_fv_differs_from_authed():
    public = _clean_fields(fair_value=1000.0)
    authed = _clean_fields(fair_value=1200.0)
    violations = cd.gate1_single_source("HCLTECH", public, authed)
    assert any("fair_value" in v for v in violations)
    assert any("1000" in v and "1200" in v for v in violations)


# ---------------------------------------------------------------------------
# Gate 2 — MoS math consistency
# ---------------------------------------------------------------------------


def test_gate2_passes_on_consistent_mos():
    # cmp=1000, fv=1200 -> mos=20.0% (percent units)
    f = _clean_fields(cmp=1000.0, fair_value=1200.0, margin_of_safety=20.0)
    assert cd.gate2_mos_math("HCLTECH", f) == []


def test_gate2_fails_when_mos_inconsistent_with_fv_cmp():
    # fv=3000, cmp=2500 -> expected = +20% but harness reports mos=-10%
    f = _clean_fields(cmp=2500.0, fair_value=3000.0, margin_of_safety=-10.0)
    violations = cd.gate2_mos_math("HCLTECH", f)
    assert len(violations) == 1
    assert "-10" in violations[0]
    assert "20" in violations[0]


# ---------------------------------------------------------------------------
# Gate 3 — scenario dispersion
# ---------------------------------------------------------------------------


def test_gate3_passes_on_normal_dispersion():
    f = _clean_fields(bear_case=900.0, base_case=1200.0, bull_case=1500.0)
    assert cd.gate3_dispersion("HCLTECH", f) == []


def test_gate3_fails_when_bull_collapses_to_base():
    f = _clean_fields(bear_case=900.0, base_case=1200.0, bull_case=1200.0)
    violations = cd.gate3_dispersion("HCLTECH", f)
    assert len(violations) >= 1
    assert any("bull" in v.lower() for v in violations)


# ---------------------------------------------------------------------------
# Gate 4 — canary bounds
# ---------------------------------------------------------------------------


def test_gate4_passes_when_inside_bounds():
    # roe=25.0 (percent) -> 0.25 decimal — inside HCLTECH bounds [0.20, 0.30]
    f = _clean_fields(roe=25.0, debt_to_equity=0.05, wacc=0.11,
                      market_cap_cr=420000, revenue_cagr_3y=0.10)
    assert cd.gate4_canary_bounds("HCLTECH", f, HCLTECH_BOUNDS) == []


def test_gate4_fails_when_roe_outside_bounds():
    # HCLTECH roe expected in [0.20, 0.30] decimal. Inject percent=2.0
    # (decimal 0.02) — well below the floor.
    f = _clean_fields(roe=2.0)
    violations = cd.gate4_canary_bounds("HCLTECH", f, HCLTECH_BOUNDS)
    assert any("roe" in v and "2.0" in v for v in violations)


def test_gate4_skips_null_bounds():
    bounds = {"roe": None, "wacc": [0.09, 0.13]}
    f = _clean_fields(roe=99.0, wacc=0.11)  # roe is wild but bound is null
    assert cd.gate4_canary_bounds("HCLTECH", f, bounds) == []


def test_gate4_catches_percent_vs_decimal_unit_bug():
    """Regression guard for the silent-pass bug fixed in fix(canary): gate 4.

    Before the fix, gate 4 compared API percent values (e.g. roe=350.0
    for 350%) directly against decimal bounds (e.g. [0.20, 0.30]) — a
    350% ROE compared as ``0.20 <= 350.0 <= 0.30`` simply failed silently
    in the wrong direction depending on the bounds, OR (more commonly,
    when bounds are sub-1.0 decimal) the comparison `350 > 0.30` did
    fire — but a value like roe=0.45 (legitimately 0.45%, broken read)
    would slip through ``0.20 <= 0.45 <= 0.30``? No — it'd fail too.
    The truly silent path was sub-percent reads vs upper-bounded
    decimals: e.g. roe=0.45 (raw 0.45 from a buggy double-divide)
    against [0.20, 0.30] -> still flagged. The actual silent failure was
    inverse: e.g. wacc was already decimal, so a 350% ROE returned as
    `350.0` correctly fired — but a 35% ROE returned as `35.0` against
    [0.20, 0.30] looked like 35.0 > 0.30 -> FAIL with a confusing
    message, masking that the gate was right-for-the-wrong-reason. With
    the fix, 35.0 percent correctly normalises to 0.35 -> still fails
    [0.20, 0.30] but with a clear unit-aware message; an out-of-band
    350.0 percent normalises to 3.5 -> still fails, also clearly.
    """
    bounds = {"roe": [0.20, 0.30]}
    # roe = 350 (percent) -> decimal 3.5, way out of band; should fail
    # AND the message should mention the converted decimal so the next
    # debugger sees the units in play.
    f = _clean_fields(roe=350.0)
    violations = cd.gate4_canary_bounds("HCLTECH", f, bounds)
    assert violations, "gate 4 must flag a 350% ROE as out-of-bound"
    assert any("decimal=" in v or "3.5" in v for v in violations)


# ---------------------------------------------------------------------------
# Gate 5 — forbidden values
# ---------------------------------------------------------------------------


def test_gate5_passes_on_clean_data():
    assert cd.gate5_forbidden("HCLTECH", _clean_fields()) == []


def test_gate5_fails_on_roce_zero_sentinel():
    f = _clean_fields(roce=0.0)
    violations = cd.gate5_forbidden("HCLTECH", f)
    assert any("roce" in v for v in violations)


def test_gate5_fails_on_revenue_cagr_extreme():
    f = _clean_fields(revenue_cagr_3y=-0.755)
    violations = cd.gate5_forbidden("HCLTECH", f)
    assert any("revenue_cagr_3y" in v for v in violations)


def test_gate5_fails_on_fv_cmp_ratio_extreme():
    # fv/cmp = 4.2 -> outside [0.4, 2.5]; mos=320% to keep gate2 isolated
    f = _clean_fields(cmp=1000.0, fair_value=4200.0,
                      margin_of_safety=320.0,
                      bear_case=3000.0, base_case=4200.0, bull_case=5500.0)
    violations = cd.gate5_forbidden("HCLTECH", f)
    assert any("fv/cmp" in v for v in violations)


# ---------------------------------------------------------------------------
# PR-FV0: no-DCF verdict skip (TATAMOTORS rename, unavailable stocks)
# ---------------------------------------------------------------------------


def test_gate2_skips_unavailable_verdict():
    # fv=0, cmp=X, mos=0 — would fire without the skip
    f = _clean_fields(cmp=500.0, fair_value=0.0, margin_of_safety=0.0,
                      verdict="unavailable")
    assert cd.gate2_mos_math("TATAMOTORS", f) == []


def test_gate3_skips_data_limited_verdict():
    f = _clean_fields(bear_case=0.0, base_case=0.0, bull_case=0.0,
                      verdict="data_limited")
    assert cd.gate3_dispersion("TATAMOTORS", f) == []


def test_gate5_skips_avoid_verdict():
    # fv/cmp=0 would normally fire; avoid verdict short-circuits the check
    f = _clean_fields(cmp=500.0, fair_value=0.0, margin_of_safety=0.0,
                      bear_case=0.0, base_case=0.0, bull_case=0.0,
                      verdict="avoid")
    assert cd.gate5_forbidden("TATAMOTORS", f) == []


def test_gate5_still_fires_on_fv_zero_WITHOUT_verdict_sentinel():
    # If fv=0 ships with a normal verdict (product regression), still fail.
    # This confirms the skip only bypasses when verdict is the sentinel.
    f = _clean_fields(cmp=500.0, fair_value=0.0, margin_of_safety=0.0,
                      verdict="fairly_valued")
    violations = cd.gate5_forbidden("TATAMOTORS", f)
    assert any("fv/cmp" in v for v in violations)


# ---------------------------------------------------------------------------
# Driver smoke tests
# ---------------------------------------------------------------------------


def test_run_all_gates_clean():
    f = _clean_fields()
    results = cd.run_all_gates("HCLTECH", f, f, HCLTECH_BOUNDS)
    assert all(v == [] for v in results.values())


def test_run_all_gates_aggregates_violations():
    public = _clean_fields(fair_value=1000.0)  # gate 1 fail
    authed = _clean_fields(fair_value=1200.0)
    results = cd.run_all_gates("HCLTECH", public, authed, HCLTECH_BOUNDS)
    assert results[1], "gate 1 should fire"
    assert results[2] == [], "gate 2 should be clean"


def test_evaluate_marks_passed_false_on_any_violation():
    stocks = [{"symbol": "HCLTECH", "canary_bounds": HCLTECH_BOUNDS}]
    state = {
        "HCLTECH": {
            "public": _clean_fields(fair_value=1000.0),
            "authed": _clean_fields(fair_value=1200.0),
            "error": None,
        }
    }
    report = cd.evaluate(state, stocks)
    assert report["passed"] is False
    assert report["gate_totals"]["single_source_of_truth"] >= 1


def test_evaluate_passes_on_clean_state():
    stocks = [{"symbol": "HCLTECH", "canary_bounds": HCLTECH_BOUNDS}]
    f = _clean_fields()
    state = {"HCLTECH": {"public": f, "authed": f, "error": None}}
    report = cd.evaluate(state, stocks)
    assert report["passed"] is True
    assert report["total_violations"] == 0


def test_evaluate_handles_fetch_failure_without_crashing():
    # NEW SEMANTIC: a single fetch failure no longer cascades into per-gate
    # violation counts. Within the default budget (2), a single fetch
    # failure soft-passes the run.
    stocks = [{"symbol": "HCLTECH", "canary_bounds": HCLTECH_BOUNDS}]
    state = {"HCLTECH": {"public": None, "authed": None, "error": "HTTP 500"}}
    report = cd.evaluate(state, stocks)
    assert report["fetch_failures"] == 1
    assert report["gate_violations"] == 0
    # 1 failure <= default budget of 2 -> soft-pass.
    assert report["passed"] is True


def test_evaluate_fails_when_fetch_failures_exceed_budget():
    stocks = [
        {"symbol": f"T{i}", "canary_bounds": None} for i in range(5)
    ]
    state = {
        "T0": {"public": None, "authed": None, "error": "ReadTimeout"},
        "T1": {"public": None, "authed": None, "error": "ReadTimeout"},
        "T2": {"public": None, "authed": None, "error": "ReadTimeout"},
        "T3": {"public": _clean_fields(), "authed": _clean_fields(), "error": None},
        "T4": {"public": _clean_fields(), "authed": _clean_fields(), "error": None},
    }
    report = cd.evaluate(state, stocks)
    assert report["fetch_failures"] == 3
    assert report["gate_violations"] == 0
    assert report["passed"] is False  # 3 > budget 2


def test_evaluate_real_violation_still_fails_with_fetch_failures_under_budget():
    stocks = [
        {"symbol": "GOOD", "canary_bounds": None},
        {"symbol": "BAD", "canary_bounds": None},
        {"symbol": "FLAKE", "canary_bounds": None},
    ]
    bad_public = _clean_fields(fair_value=1000.0)
    bad_authed = _clean_fields(fair_value=1200.0)  # gate 1 mismatch
    state = {
        "GOOD": {"public": _clean_fields(), "authed": _clean_fields(), "error": None},
        "BAD": {"public": bad_public, "authed": bad_authed, "error": None},
        "FLAKE": {"public": None, "authed": None, "error": "ReadTimeout"},
    }
    report = cd.evaluate(state, stocks)
    assert report["fetch_failures"] == 1  # within budget
    assert report["gate_violations"] >= 1
    assert report["passed"] is False  # real violation always fails
