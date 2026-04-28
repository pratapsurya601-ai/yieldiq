"""Regression test: degenerate scenario triplets must be flagged.

Reference: ``docs/grasim_investigation_2026-04-28.md`` and PR #125
(``docs/grasim-investigation``). The same investigation also drove
the canary scenario_dispersion gate (gate 3 in ``scripts/canary_diff.py``).

Bug history
-----------
GRASIM produced a DCF scenario triplet of bear=base=589, bull=1783.
That is a *degenerate* shape: bull-vs-base spread is real (~3x), but
base-vs-bear spread is ZERO. The downstream UI rendered "fair value
band: 589 — 1783" and the user-visible MoS was computed off the base
case — but with no downside scenario, the band is meaningless.

The canary harness's gate 3 (``scenario_dispersion``) must reject any
stock where bull > base > bear with at least 5% spread on each side.
A bear==base triplet is the canonical violation we shipped GRASIM
with, so it is the canonical regression case.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _load_gate3():
    try:
        import canary_diff  # noqa: WPS433
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"scripts.canary_diff unavailable: {exc}")
    return canary_diff.gate3_dispersion


def _grasim_pattern(**overrides):
    """The exact scenario shape we shipped GRASIM with."""
    base = {
        "cmp": 1500.0,
        "fair_value": 589.0,
        "margin_of_safety": -60.7,
        "bear_case": 589.0,
        "base_case": 589.0,
        "bull_case": 1783.0,
    }
    base.update(overrides)
    return base


def test_grasim_bear_equals_base_is_flagged_by_gate3():
    """The canonical GRASIM pattern: bear == base, bull >> base.

    Gate 3 must reject because the bull > base > bear strict-ordering
    requirement is violated (bull > base == bear, not bull > base > bear).
    """
    gate3 = _load_gate3()
    violations = gate3("GRASIM", _grasim_pattern())
    assert violations, (
        "Gate 3 must flag bear==base triplet. The GRASIM scenario "
        "(bear=base=589, bull=1783) is the canonical degenerate case "
        "and must NOT pass the dispersion gate. See PR #125 / "
        "docs/grasim_investigation_2026-04-28.md."
    )


def test_gate3_flags_under_threshold_dispersion():
    """A 1% spread on either side is below the 5% dispersion floor."""
    gate3 = _load_gate3()
    fields = _grasim_pattern(bear_case=580.0, base_case=589.0, bull_case=595.0)
    violations = gate3("SYNTHETIC", fields)
    assert violations, (
        "Gate 3 must flag scenario triplets where either spread is "
        "<= 5%. Got no violations for bear=580/base=589/bull=595."
    )


def test_gate3_passes_healthy_dispersion():
    """Bull = base + 25%, bear = base - 25%, base > 0 — clean pass."""
    gate3 = _load_gate3()
    fields = {
        "cmp": 1000.0,
        "fair_value": 1000.0,
        "margin_of_safety": 0.0,
        "bear_case": 750.0,
        "base_case": 1000.0,
        "bull_case": 1250.0,
    }
    assert gate3("HEALTHY", fields) == []


def test_gate3_flags_inverted_order():
    """bull < base inverts the strict order requirement."""
    gate3 = _load_gate3()
    fields = _grasim_pattern(bear_case=400.0, base_case=600.0, bull_case=550.0)
    violations = gate3("INVERTED", fields)
    assert violations, "Gate 3 must flag bull < base."
