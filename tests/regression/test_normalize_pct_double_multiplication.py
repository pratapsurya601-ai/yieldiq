"""Regression test: ``_normalize_pct`` must not double-multiply percent values.

Reference: PR #126 — ``fix/normalize-pct-bound-correction``.

Bug history
-----------
``backend/services/analysis/utils.py::_normalize_pct`` originally used
the heuristic window ``-5 < v < 5`` to decide whether the input was a
yfinance-shaped decimal (e.g. ``0.235`` for 23.5%) and therefore needed
multiplication by 100. That window swallowed *legitimate* percent inputs
in the [1, 5) band — for instance GRASIM's ROCE of ~3.5% was being
read from XBRL as ``3.5`` (already percent), the heuristic decided it
was a decimal, multiplied by 100, and produced ``350`` (i.e. 350%).

The fix narrowed the window to ``-1 < v < 1`` because yfinance's API
contract bounds ROE/ROCE/ROA decimals to ``[-1, 1]`` — so any input
with absolute value >= 1 is already in percent form and must NOT be
multiplied again.

This test pins that contract.
"""

from __future__ import annotations

import importlib
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]


import re


def _load():
    """Extract the ``_normalize_pct`` function source from
    ``backend/services/analysis/utils.py`` and exec it in an isolated
    namespace.

    Why this dance: the host module imports pandas / pydantic /
    screener at top level — none of which are installed in the
    lightweight CI test runner that runs the regression suite (``pip
    install requests pytest`` per the regression workflow). The
    function itself is pure Python, no third-party deps, so we slice
    it out of the source file and exec it standalone. This still
    catches real regressions: any edit to ``_normalize_pct`` in the
    source file is reflected in the test, byte-identical.
    """
    src = ROOT / "backend" / "services" / "analysis" / "utils.py"
    if not src.exists():  # pragma: no cover
        pytest.skip(f"source not found: {src}")
    text = src.read_text(encoding="utf-8")
    # Match `def _normalize_pct(...) ... <next top-level def>` — the
    # body ends at the next line that starts with `def ` at column 0.
    m = re.search(
        r"^def _normalize_pct\b.*?(?=^def |\Z)",
        text,
        flags=re.DOTALL | re.MULTILINE,
    )
    if not m:  # pragma: no cover
        pytest.skip("could not slice _normalize_pct from utils.py")
    ns: dict = {}
    try:
        exec(m.group(0), ns)
    except Exception as exc:  # pragma: no cover
        pytest.skip(f"_normalize_pct failed to exec standalone: {exc}")
    return ns["_normalize_pct"]


def test_percent_value_in_double_multiplication_band_is_not_remultiplied():
    """ROE = 2.35 (already percent) must round-trip to 2.35.

    Pre-fix this returned 235.0 because 2.35 fell inside the old
    (-5, 5) heuristic window. Post-fix the window is (-1, 1) so 2.35
    is recognised as already-percent and passed through.
    """
    fn = _load()
    out = fn(2.35)
    assert out == 2.35, (
        f"_normalize_pct(2.35) returned {out!r}; expected 2.35. "
        "If you are seeing 235.0, the heuristic window has regressed "
        "to the old (-5, 5) form — see PR #126."
    )


def test_decimal_value_below_one_is_correctly_multiplied():
    """ROE = 0.0235 (yfinance decimal) must round-trip to 2.35."""
    fn = _load()
    assert fn(0.0235) == 2.35


@pytest.mark.parametrize(
    "value,expected",
    [
        # Values below the new (-1, 1) window — treated as decimal,
        # multiplied by 100.
        (0.99, 99.0),
        # Boundary: at |v| == 1 we treat as already-percent (no
        # multiply) per the strict ``-1 < v < 1`` form.
        (1.0, 1.0),
        # Above 1 — already percent.
        (1.01, 1.01),
        # Inside the OLD (-5, 5) buggy window but above the new (-1, 1)
        # window — these are the regression-critical values.
        (4.99, 4.99),
        (5.0, 5.0),
        # Negative mirror of the regression-critical band.
        (-2.35, -2.35),
        (-0.0235, -2.35),
    ],
)
def test_boundary_values_around_window(value, expected):
    fn = _load()
    out = fn(value)
    assert out == pytest.approx(expected, abs=1e-9), (
        f"_normalize_pct({value!r}) returned {out!r}; expected {expected!r}"
    )


def test_zero_and_none_pass_through():
    fn = _load()
    assert fn(0) == 0.0
    assert fn(0.0) == 0.0
    assert fn(None) is None


def test_non_numeric_returns_none():
    fn = _load()
    assert fn("not a number") is None
