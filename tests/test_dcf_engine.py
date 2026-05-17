"""Unit tests for screener.dcf_engine helpers.

Step B (2026-05-17): the buffett_mos_pct helper was added alongside the
existing upside_pct (aliased margin_of_safety) so that the wire format
can carry both quantities. These tests pin the formula contract +
edge-case behaviour so a future refactor can't silently change either.

Run from repo root: ``pytest tests/test_dcf_engine.py -q``
"""
from __future__ import annotations

import math

import pytest

from screener.dcf_engine import (
    buffett_mos_pct,
    margin_of_safety,
    upside_pct,
)


# ── upside_pct / margin_of_safety alias ────────────────────────────────


def test_upside_pct_huhtamaki_fixture():
    """HUHTAMAKI canonical example from the Step B PR body."""
    # upside is returned as a FRACTION (callers ×100 for display)
    got = upside_pct(357.35, 179.36)
    assert got == pytest.approx(0.9924, abs=1e-4)


def test_margin_of_safety_alias_is_upside_pct():
    """Backward-compat alias must point at the same function."""
    assert margin_of_safety is upside_pct


def test_upside_pct_zero_price_returns_zero():
    """Defined as 0 when price is non-positive (avoids divide-by-zero)."""
    assert upside_pct(100.0, 0.0) == 0.0
    assert upside_pct(100.0, -5.0) == 0.0


# ── buffett_mos_pct ─────────────────────────────────────────────────────


def test_buffett_mos_huhtamaki_fixture():
    """HUHTAMAKI: FV=357.35, CP=179.36 → +49.8% (the PR body number)."""
    got = buffett_mos_pct(357.35, 179.36)
    assert got is not None
    assert got == pytest.approx(49.81, abs=0.05)


def test_buffett_mos_fv_equals_cp():
    """FV == CP → exactly 0 (no discount, no premium)."""
    assert buffett_mos_pct(100.0, 100.0) == 0.0


def test_buffett_mos_fv_less_than_cp_is_negative():
    """Stock priced above FV → negative MoS (correct: no margin)."""
    got = buffett_mos_pct(80.0, 100.0)
    assert got is not None
    assert got < 0
    assert got == pytest.approx(-25.0, abs=1e-6)


def test_buffett_mos_zero_fv_returns_none():
    """FV<=0 → None (Buffett MoS undefined when there's no fair value)."""
    assert buffett_mos_pct(0.0, 100.0) is None
    assert buffett_mos_pct(-10.0, 100.0) is None


def test_buffett_mos_non_numeric_returns_none():
    """Defensive: garbage input → None, not an exception."""
    assert buffett_mos_pct(None, 100.0) is None  # type: ignore[arg-type]
    assert buffett_mos_pct("oops", 100.0) is None  # type: ignore[arg-type]


def test_buffett_mos_differs_from_upside_when_undervalued():
    """The two metrics MUST diverge when CP < FV (the whole point of Step B).

    Identity: if upside = (FV-CP)/CP, then buffett = upside/(1+upside).
    """
    fv, cp = 200.0, 100.0
    u = upside_pct(fv, cp) * 100  # +100%
    b = buffett_mos_pct(fv, cp)
    assert u == pytest.approx(100.0)
    assert b == pytest.approx(50.0)  # 100 / (1+1) → 50
    assert not math.isclose(u, b)


@pytest.mark.parametrize(
    "fv,cp,want_buffett",
    [
        (357.35, 179.36, 49.81),  # HUHTAMAKI fixture
        (100.0, 100.0, 0.0),       # parity
        (200.0, 100.0, 50.0),      # deep value
        (1000.0, 1.0, 99.9),       # extreme upside
        (100.0, 200.0, -100.0),    # 2× overvalued
    ],
)
def test_buffett_mos_parametric(fv, cp, want_buffett):
    got = buffett_mos_pct(fv, cp)
    assert got is not None
    assert got == pytest.approx(want_buffett, abs=0.05)
