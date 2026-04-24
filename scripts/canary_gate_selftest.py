"""Canary gate self-test — the harness that verifies the harness.

Runs the canary-diff gate logic against a FIXTURE set of known-good and
known-bad response shapes (NO network). Asserts that the decisions the
gate makes on each fixture match the expected outcome.

Why this exists
---------------
``canary_diff.py`` is the YieldIQ merge gate. If the harness itself has
a bug, CI either:
  (a) lets a regression through (harness under-fires), or
  (b) blocks clean PRs (harness over-fires — the RELIANCE 0.050 boundary
      flake that triggered this whole effort).

Neither mode of failure is acceptable for a merge gate. This selftest
runs on every PR touching ``scripts/canary_*`` files; if it fails the
harness cannot be trusted and the merge gate must not run.

How it works
------------
Each fixture is a ``(symbol, public_fields, authed_fields, bounds,
expected_decisions)`` tuple. ``expected_decisions`` is a dict
``{gate_number: bool}`` where True means "this gate must fire on this
fixture" and False means "this gate must NOT fire".

Run with:
    python scripts/canary_gate_selftest.py
Exits 0 on success, 1 on any mismatch.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import canary_diff as cd  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture builder — same shape as the real API response after
# extract_fields() pulls canonical keys out.
# ---------------------------------------------------------------------------


def _fields(**overrides):
    """Clean, gate-passing field set. Override keys to inject a violation."""
    base = {
        "cmp": 1000.0,
        "fair_value": 1200.0,
        "margin_of_safety": 20.0,  # percent units
        "bear_case": 900.0,
        "base_case": 1200.0,
        "bull_case": 1500.0,
        "roe": 0.25,
        "roce": 0.30,
        "wacc": 0.11,
        "ev_ebitda": 18.0,
        "revenue_cagr_3y": 0.10,
        "debt_to_equity": 0.10,
        "market_cap_cr": 400000,
    }
    base.update(overrides)
    return base


DEFAULT_BOUNDS = {
    "roe": [0.15, 0.35],
    "wacc": [0.08, 0.14],
    "revenue_cagr_3y": [0.0, 0.25],
}


# ---------------------------------------------------------------------------
# Fixture set
#
# Each entry: (name, public, authed, bounds, expected_fire_map)
# expected_fire_map keys are gate numbers 1..5, values True/False.
# ---------------------------------------------------------------------------

FIXTURES: list[tuple] = [
    # ---- known-good ------------------------------------------------------
    (
        "clean_pass_all_gates",
        _fields(),
        _fields(),
        DEFAULT_BOUNDS,
        {1: False, 2: False, 3: False, 4: False, 5: False},
    ),
    # ---- Gate 1: SoT divergence ----------------------------------------
    (
        "gate1_fv_mismatch_public_vs_authed",
        _fields(fair_value=1000.0),
        _fields(fair_value=1200.0),
        DEFAULT_BOUNDS,
        {1: True, 2: False, 3: False, 4: False, 5: False},
    ),
    # ---- Gate 2: MoS math ----------------------------------------------
    (
        "gate2_mos_inconsistent_with_fv_cmp",
        _fields(cmp=2500.0, fair_value=3000.0, margin_of_safety=-10.0,
                bear_case=2200.0, base_case=3000.0, bull_case=3800.0),
        _fields(cmp=2500.0, fair_value=3000.0, margin_of_safety=-10.0,
                bear_case=2200.0, base_case=3000.0, bull_case=3800.0),
        None,
        {1: False, 2: True, 3: False, 4: False, 5: False},
    ),
    # ---- Gate 3: RELIANCE boundary (the one that flaked) ---------------
    # bull = base * 1.05 exactly — lands at the 0.05 floor. After the
    # 2026-04-25 clamp-widen fix, real outputs land at 1.075 base or
    # better so this fixture documents the regression case: if the
    # clamp ever gets walked back to 1.05, this will fire.
    (
        "gate3_bull_spread_exactly_at_floor_fires",
        _fields(bear_case=950.0, base_case=1000.0, bull_case=1050.0),
        _fields(bear_case=950.0, base_case=1000.0, bull_case=1050.0),
        None,
        {1: False, 2: False, 3: True, 4: False, 5: False},
    ),
    (
        "gate3_bull_spread_just_above_floor_passes",
        _fields(cmp=1000.0, fair_value=1000.0, margin_of_safety=0.0,
                bear_case=925.0, base_case=1000.0, bull_case=1075.0),
        _fields(cmp=1000.0, fair_value=1000.0, margin_of_safety=0.0,
                bear_case=925.0, base_case=1000.0, bull_case=1075.0),
        None,
        {1: False, 2: False, 3: False, 4: False, 5: False},
    ),
    # ---- Gate 3: inverted ordering -------------------------------------
    (
        "gate3_bull_below_base_fires",
        _fields(bear_case=900.0, base_case=1200.0, bull_case=1100.0),
        _fields(bear_case=900.0, base_case=1200.0, bull_case=1100.0),
        None,
        {1: False, 2: False, 3: True, 4: False, 5: False},
    ),
    # ---- Gate 4: bound violation ---------------------------------------
    (
        "gate4_roe_outside_bounds",
        _fields(roe=0.05),
        _fields(roe=0.05),
        DEFAULT_BOUNDS,
        {1: False, 2: False, 3: False, 4: True, 5: False},
    ),
    # ---- Gate 5: forbidden sentinels -----------------------------------
    (
        "gate5_roce_zero_sentinel",
        _fields(roce=0.0),
        _fields(roce=0.0),
        None,
        {1: False, 2: False, 3: False, 4: False, 5: True},
    ),
    (
        "gate5_fv_cmp_ratio_extreme",
        _fields(cmp=1000.0, fair_value=4200.0, margin_of_safety=320.0,
                bear_case=3000.0, base_case=4200.0, bull_case=5500.0),
        _fields(cmp=1000.0, fair_value=4200.0, margin_of_safety=320.0,
                bear_case=3000.0, base_case=4200.0, bull_case=5500.0),
        None,
        {1: False, 2: False, 3: False, 4: False, 5: True},
    ),
    # ---- no-DCF verdict must short-circuit gates 2/3/5 -----------------
    (
        "data_limited_verdict_skips_numeric_gates",
        _fields(cmp=500.0, fair_value=0.0, margin_of_safety=0.0,
                bear_case=0.0, base_case=0.0, bull_case=0.0,
                verdict="data_limited"),
        _fields(cmp=500.0, fair_value=0.0, margin_of_safety=0.0,
                bear_case=0.0, base_case=0.0, bull_case=0.0,
                verdict="data_limited"),
        None,
        {1: False, 2: False, 3: False, 4: False, 5: False},
    ),
    (
        "unavailable_verdict_skips_numeric_gates",
        _fields(cmp=500.0, fair_value=0.0, margin_of_safety=0.0,
                bear_case=0.0, base_case=0.0, bull_case=0.0,
                verdict="unavailable"),
        _fields(cmp=500.0, fair_value=0.0, margin_of_safety=0.0,
                bear_case=0.0, base_case=0.0, bull_case=0.0,
                verdict="unavailable"),
        None,
        {1: False, 2: False, 3: False, 4: False, 5: False},
    ),
    # ---- fv=0 with NORMAL verdict must STILL fire (regression guard) ---
    (
        "fv_zero_without_sentinel_verdict_still_fails",
        _fields(cmp=500.0, fair_value=0.0, margin_of_safety=0.0,
                bear_case=0.0, base_case=0.0, bull_case=0.0,
                verdict="fairly_valued"),
        _fields(cmp=500.0, fair_value=0.0, margin_of_safety=0.0,
                bear_case=0.0, base_case=0.0, bull_case=0.0,
                verdict="fairly_valued"),
        None,
        # Expected fires:
        #   gate 2: mos=0 vs expected (0-500)/500*100 = -100
        #   gate 3: bull=base=bear=0, order broken
        #   gate 5: fv/cmp = 0 outside [0.35, 2.7]
        {1: False, 2: True, 3: True, 4: False, 5: True},
    ),
]


# ---------------------------------------------------------------------------
# Fetch-failure driver test — uses cd.evaluate() directly with a mocked
# state dict to confirm that fetch_failures do NOT inflate gate_totals
# and that the soft-pass / hard-fail budget works as advertised.
# ---------------------------------------------------------------------------


def _check_fetch_failure_semantics() -> list[str]:
    errors: list[str] = []
    stocks = [
        {"symbol": f"T{i}", "canary_bounds": None} for i in range(5)
    ]
    # 3 stocks fetch-failed, 2 clean. Over default budget of 2.
    clean = _fields()
    state = {
        "T0": {"public": None, "authed": None, "error": "ReadTimeout"},
        "T1": {"public": None, "authed": None, "error": "ReadTimeout"},
        "T2": {"public": None, "authed": None, "error": "ReadTimeout"},
        "T3": {"public": clean, "authed": clean, "error": None},
        "T4": {"public": clean, "authed": clean, "error": None},
    }
    rpt = cd.evaluate(state, stocks)
    if rpt["fetch_failures"] != 3:
        errors.append(f"fetch_failures expected 3 got {rpt['fetch_failures']}")
    if rpt["gate_violations"] != 0:
        errors.append(
            f"gate_violations must NOT include fetch failures, "
            f"got {rpt['gate_violations']} (legacy cascade bug)"
        )
    if rpt["passed"]:
        errors.append("3 fetch failures > budget 2 must fail the job")

    # 2 stocks fetch-failed (== budget). Should soft-pass.
    state2 = {
        "T0": {"public": None, "authed": None, "error": "ReadTimeout"},
        "T1": {"public": None, "authed": None, "error": "ReadTimeout"},
        "T2": {"public": clean, "authed": clean, "error": None},
        "T3": {"public": clean, "authed": clean, "error": None},
        "T4": {"public": clean, "authed": clean, "error": None},
    }
    rpt2 = cd.evaluate(state2, stocks)
    if not rpt2["passed"]:
        errors.append(
            f"2 fetch failures == budget must soft-pass, got "
            f"passed={rpt2['passed']} gate_violations={rpt2['gate_violations']}"
        )

    # Real gate violation always fails, regardless of fetch failures.
    bad = _fields(roce=0.0)  # gate 5 sentinel
    state3 = {
        "T0": {"public": clean, "authed": clean, "error": None},
        "T1": {"public": clean, "authed": clean, "error": None},
        "T2": {"public": clean, "authed": clean, "error": None},
        "T3": {"public": clean, "authed": clean, "error": None},
        "T4": {"public": bad, "authed": bad, "error": None},
    }
    rpt3 = cd.evaluate(state3, stocks)
    if rpt3["passed"]:
        errors.append("real gate violation must always fail the job")

    return errors


# ---------------------------------------------------------------------------
# Runner
# ---------------------------------------------------------------------------


def _run_fixture(name, public, authed, bounds, expected):
    results = cd.run_all_gates(name, public, authed, bounds)
    errors: list[str] = []
    for gate_n, should_fire in expected.items():
        fired = bool(results.get(gate_n))
        if fired != should_fire:
            errors.append(
                f"  gate {gate_n}: expected fire={should_fire} got "
                f"fire={fired} detail={results.get(gate_n)}"
            )
    return errors


def main() -> int:
    total_errors = 0
    print(f"Running {len(FIXTURES)} canary gate selftest fixtures...")
    for fx in FIXTURES:
        name, public, authed, bounds, expected = fx
        errs = _run_fixture(name, public, authed, bounds, expected)
        if errs:
            total_errors += len(errs)
            print(f"FAIL {name}")
            for e in errs:
                print(e)
        else:
            print(f"OK   {name}")

    print()
    print("Running fetch-failure semantics checks...")
    ff_errs = _check_fetch_failure_semantics()
    if ff_errs:
        total_errors += len(ff_errs)
        print("FAIL fetch_failure_semantics")
        for e in ff_errs:
            print(f"  {e}")
    else:
        print("OK   fetch_failure_semantics")

    print()
    if total_errors:
        print(f"SELFTEST FAILED: {total_errors} error(s).")
        print(
            "The canary harness itself has a bug — do NOT trust its "
            "gate decisions until this is fixed."
        )
        return 1
    print("SELFTEST PASSED.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
