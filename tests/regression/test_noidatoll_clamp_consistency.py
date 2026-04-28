"""Regression test: headline FV / MoS must equal base-case FV when scenarios
are clamped, not the pre-clamp flat-field value.

Reference: PR #108 — NOIDATOLL clamp inconsistency.

Bug history
-----------
NOIDATOLL was rendering with a public-page MoS of +200% while the
underlying base case showed only ~+95%. The cause: the analysis
service computed scenarios twice — once as flat fields
(``fair_value`` / ``margin_of_safety``), once as ``ScenariosOutput``
which then ran through ``_enforce_scenario_order`` to clamp to the
contract that ``bull > base > bear``.

The flat field was sourced from the *pre-clamp* compute, so when the
clamp kicked in (bear/base/bull ordering correction or the symmetric
+/-100% MoS cap from PR #d6255d1), the headline number disagreed
with the scenario card directly under it. NOIDATOLL's headline read
+200% while the base case the user saw was +95%.

The fix: the headline ``fair_value`` / ``margin_of_safety`` must be
taken from the *post-clamp* base case — i.e. the same source the
public scenario card draws from. They must be byte-identical, modulo
float rounding.

This regression test pins the invariant against synthetic payloads
shaped like the analysis-service output.
"""

from __future__ import annotations

import math
import pytest


def _mos_from(fv: float, cmp_: float) -> float:
    """Mirror the API contract: MoS in percent, formula (fv-cmp)/cmp*100."""
    return (fv - cmp_) / cmp_ * 100.0


def _check_clamp_consistency(payload: dict) -> list[str]:
    """Pure invariant checker — same shape ``analysis_service`` emits.

    Returns a list of violations; empty means consistent.
    """
    out: list[str] = []
    fv = payload.get("fair_value")
    cmp_ = payload.get("cmp")
    mos = payload.get("margin_of_safety")
    base = (payload.get("scenarios") or {}).get("base_case")
    if base is None:
        # Some sentinel paths emit no scenarios; gate-callers handle.
        return []
    if fv is None or cmp_ is None or mos is None:
        out.append("missing required headline field")
        return out
    # Headline FV must equal base-case FV within 0.01 (rupee).
    if abs(fv - base) > 0.01:
        out.append(f"fair_value={fv} != base_case={base}")
    # Headline MoS must equal (base - cmp)/cmp * 100 within 0.05 pp.
    expected_mos = _mos_from(base, cmp_)
    if abs(mos - expected_mos) > 0.05:
        out.append(
            f"margin_of_safety={mos:.2f}% but base-derived "
            f"={expected_mos:.2f}%"
        )
    return out


def _noidatoll_pre_fix_payload():
    """The actual pre-fix shape: cmp=100, base case +95% but headline +200%.

    Pre-clamp the flat field claimed fv=300 / mos=+200 while scenarios
    came out base=195 (a clean +95% MoS). The disagreement is the bug.
    """
    return {
        "cmp": 100.0,
        "fair_value": 300.0,        # pre-clamp flat field
        "margin_of_safety": 200.0,  # pre-clamp flat field
        "scenarios": {
            "bear_case": 120.0,
            "base_case": 195.0,     # post-clamp base, divergent
            "bull_case": 260.0,
        },
    }


def _noidatoll_post_fix_payload():
    """The shape the fix produces: headline === base-case."""
    return {
        "cmp": 100.0,
        "fair_value": 195.0,
        "margin_of_safety": 95.0,
        "scenarios": {
            "bear_case": 120.0,
            "base_case": 195.0,
            "bull_case": 260.0,
        },
    }


def test_clamp_inconsistency_is_caught():
    """The pre-fix NOIDATOLL payload must trip the invariant checker."""
    violations = _check_clamp_consistency(_noidatoll_pre_fix_payload())
    assert violations, (
        "NOIDATOLL pre-fix payload (headline +200% / base +95%) must "
        "be flagged. If this passes, the clamp-consistency invariant "
        "is broken — see PR #108."
    )
    # The specific failure should mention fair_value mismatch.
    assert any("fair_value" in v for v in violations)


def test_post_fix_payload_passes():
    """When headline === base-case, no violations."""
    assert _check_clamp_consistency(_noidatoll_post_fix_payload()) == []


def test_clamp_consistency_tolerates_float_rounding():
    """sub-rupee differences (e.g. round-trip through float arithmetic)
    must not trip the invariant."""
    payload = {
        "cmp": 100.0,
        "fair_value": 195.0001,
        "margin_of_safety": 95.0001,
        "scenarios": {
            "bear_case": 120.0,
            "base_case": 195.0,
            "bull_case": 260.0,
        },
    }
    assert _check_clamp_consistency(payload) == []


@pytest.mark.parametrize(
    "fv,base,should_violate",
    [
        (195.0, 195.0, False),
        (200.0, 195.0, True),
        (195.0, 200.0, True),
        # Negative-MoS regime (overvalued stock) — still must agree.
        (80.0, 80.0, False),
        (90.0, 80.0, True),
    ],
)
def test_headline_must_track_base_case(fv, base, should_violate):
    payload = {
        "cmp": 100.0,
        "fair_value": fv,
        "margin_of_safety": _mos_from(fv, 100.0),
        "scenarios": {
            "bear_case": base * 0.7,
            "base_case": base,
            "bull_case": base * 1.3,
        },
    }
    violations = _check_clamp_consistency(payload)
    assert bool(violations) == should_violate
