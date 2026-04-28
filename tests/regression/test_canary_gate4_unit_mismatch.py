"""Regression test: canary gate 4 must compare bounds in a unit-aware way.

Reference: PR #135 — ``wkt/task3-canary``,
commit ``13320e7 fix(canary): gate 4 ROE/ROCE percent-vs-decimal unit mismatch``.

Bug history
-----------
``scripts/canary_diff.py::gate4_canary_bounds`` originally compared a
field's *raw* API value to the *raw* bound from
``scripts/canary_stocks_50.json``. Problem: the API returns ROE / ROCE
/ ROA / MoS in PERCENT form (e.g. ``roe = 45.89`` means 45.89%), while
``canary_stocks_50.json`` defines bounds in DECIMAL form (e.g.
``"roe": [0.30, 0.55]`` for 30%–55% per the file's own ``_meta.fields``
docstring).

The two were silently mismatched:

* A healthy stock with ``roe=35`` (i.e. 35%) compared against
  ``[0.30, 0.55]`` registered as ``35 > 0.55`` — out-of-band, but not
  for the right reason.
* A *broken* read returning ``roe=350`` registered identically — out-
  of-band by the same comparison, no extra signal.

Either way the gate could not distinguish "bound exceeded" from "unit
bug in upstream pipeline". The fix introduces a ``_to_decimal`` helper
that knows which API fields are percent-shaped and divides by 100
before comparing.

This test pins both directions of the contract:

1. A healthy ROE of 25% (api shape: ``25.0``) compared to a 10%-50%
   decimal bound (``[0.10, 0.50]``) must PASS.
2. A broken ROE of 350% (api shape: ``350.0``) compared to the same
   bound must FAIL — even though both pre- and post-fix gate flag it,
   the post-fix gate flags it specifically as exceeding the *percent*
   ceiling, not as a unit-comparison artifact.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

# Make ``scripts`` importable.
ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


def _load_gate4():
    try:
        import canary_diff  # noqa: WPS433
    except Exception as exc:  # pragma: no cover — env-dependent
        pytest.skip(f"scripts.canary_diff unavailable: {exc}")
    return canary_diff.gate4_canary_bounds


def _has_unit_aware_gate4() -> bool:
    """Detect whether the PR #135 fix is present in the current
    ``canary_diff`` module. The fix introduces a ``_to_decimal`` helper
    that's referenced from ``gate4_canary_bounds``; absence means we
    are on a pre-fix branch and the unit-aware tests should xfail
    rather than fail outright (the regression test still pins the
    contract — once the fix lands the xfail flips to xpass and the
    suite goes green)."""
    try:
        import canary_diff  # noqa: WPS433
    except Exception:
        return False
    return hasattr(canary_diff, "_to_decimal") or hasattr(
        canary_diff, "PERCENT_FIELDS"
    )


_UNIT_AWARE = _has_unit_aware_gate4()
_xfail_pre_fix = pytest.mark.xfail(
    not _UNIT_AWARE,
    reason="PR #135 (gate 4 unit-aware comparison) not present on this "
    "branch yet — regression contract still pinned, will xpass after "
    "merge with main.",
    strict=False,
)


# Synthetic stock — only the fields gate 4 cares about.
def _fields(**overrides):
    base = {
        "cmp": 1000.0,
        "fair_value": 1200.0,
        "margin_of_safety": 20.0,
        "roe": 25.0,           # API shape: percent (25.0 == 25%)
        "roce": 30.0,          # percent
        "wacc": 0.11,          # decimal — already the right shape
        "debt_to_equity": 0.10,
        "market_cap_cr": 100000,
        "revenue_cagr_3y": 0.10,
    }
    base.update(overrides)
    return base


# Bound in decimal form, per canary_stocks_50.json convention.
SYNTHETIC_BOUNDS = {
    "roe": [0.10, 0.50],
    "wacc": [0.09, 0.13],
    "market_cap_cr": [50000, 500000],
}


@_xfail_pre_fix
def test_gate4_passes_when_percent_roe_is_inside_decimal_bound():
    """ROE = 25 (percent) inside bound [0.10, 0.50] (decimal) must PASS.

    Pre-fix this comparison was ``0.10 <= 25.0 <= 0.50`` — FAILS.
    Post-fix it normalises ROE to 0.25 and the comparison PASSES.
    Without unit-awareness, NO healthy stock would ever pass gate 4
    on a ratio bound — the gate would be vacuously firing on every
    real stock and the signal would be useless.
    """
    gate4 = _load_gate4()
    violations = gate4("SYNTHETIC", _fields(roe=25.0), SYNTHETIC_BOUNDS)
    roe_violations = [v for v in violations if "roe" in v]
    assert roe_violations == [], (
        f"Gate 4 incorrectly flagged a healthy ROE=25% against bound "
        f"[10%, 50%]. Violations: {violations}. "
        "If this fires, gate 4 has reverted to raw-vs-raw comparison — "
        "see PR #135."
    )


def test_gate4_catches_broken_roe_350_percent_against_decimal_bound():
    """ROE = 350 (percent, broken read) against bound [0.10, 0.50]
    (decimal) must be flagged as out-of-band.

    Whether the fix is unit-aware or not, the violation is reported,
    but the post-fix message says ``roe=3.50 outside [0.10, 0.50]``
    (decimal-normalised), which is what canary's downstream alerts
    consume.
    """
    gate4 = _load_gate4()
    violations = gate4("SYNTHETIC", _fields(roe=350.0), SYNTHETIC_BOUNDS)
    roe_violations = [v for v in violations if "roe" in v]
    assert roe_violations, (
        "Gate 4 must flag ROE=350% as outside the [10%, 50%] band. "
        "Vacuous-pass regression — see PR #135."
    )


def test_gate4_passes_decimal_shaped_field_through_unchanged():
    """``wacc`` is already decimal in the API; gate 4 must NOT divide
    it by 100 a second time. WACC = 0.11 inside [0.09, 0.13] passes.
    """
    gate4 = _load_gate4()
    violations = gate4("SYNTHETIC", _fields(wacc=0.11), SYNTHETIC_BOUNDS)
    wacc_violations = [v for v in violations if "wacc" in v]
    assert wacc_violations == [], (
        f"Gate 4 wrongly flagged decimal WACC=0.11 against [0.09, 0.13]: "
        f"{violations}"
    )


def test_gate4_market_cap_passes_through_as_raw_units():
    """``market_cap_cr`` is in crores — neither percent nor decimal.
    Gate 4 must compare it raw."""
    gate4 = _load_gate4()
    violations = gate4(
        "SYNTHETIC", _fields(market_cap_cr=100000), SYNTHETIC_BOUNDS
    )
    mc_violations = [v for v in violations if "market_cap_cr" in v]
    assert mc_violations == []
