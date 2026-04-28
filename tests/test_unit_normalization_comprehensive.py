"""Comprehensive coverage for every unit-detection helper in the codebase.

Why this file exists
====================
On 2026-04-26 we shipped ``fix/normalize-pct-bound-correction`` (PR #126),
which corrected the heuristic window in
``backend.services.analysis.utils._normalize_pct`` from ``(-5, 5)`` to
``(-1, 1)``. The previous window silently double-multiplied any percent
value with ``|v| < 5`` — corrupting ROE/ROCE/ROA for ~100 low-margin
stocks (e.g. GRASIM ROE 2.35% → 235%). The bug was invisible for two
weeks because no test pinned the boundary.

This module pins **every** unit-detection helper across the repo so a
future "tweak this threshold" PR fails CI before it can ship a silent
data-corruption regression.

Helpers covered
---------------
* ``backend.services.analysis.utils._normalize_pct`` (production
  ROE/ROCE/ROA path, used in fundamentals enrichment).
* ``backend.services.analytical_notes._normalize_pct`` (rule-engine
  helper for analytical notes; uses a different threshold of 1.5).
* ``data.collector._normalize_pct_to_decimal`` (yfinance/Finnhub
  dividend-yield three-way disambiguation).
* ``backend.services.units`` — the new centralised canonicaliser.
"""

from __future__ import annotations

import math

import pytest

from backend.services import units as U
from backend.services.analysis.utils import _normalize_pct as analysis_norm_pct
from backend.services.analytical_notes import _normalize_pct as notes_norm_pct


# ════════════════════════════════════════════════════════════════════
# 1. analysis/utils._normalize_pct  — the helper that hosted the bug
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "raw, expected",
    [
        # ─── decimal inputs from yfinance (|v| < 1) — multiplied ×100
        (0.0235, 2.35),       # GRASIM ROE (regression case)
        (0.235, 23.5),        # typical large-cap ROE
        (0.001, 0.1),         # tiny but non-zero
        (-0.05, -5.0),        # negative ROE (loss-making)
        (0.999, 99.9),        # just inside decimal regime
        # ─── percent inputs from Aiven XBRL (|v| >= 1) — passthrough
        (1.0, 1.0),           # boundary, treated as percent (>= 1.0)
        (1.01, 1.01),         # just over the boundary
        (2.35, 2.35),         # the regression value as percent
        (5.0, 5.0),           # used to be at the OLD boundary
        (4.99, 4.99),         # used to be JUST inside the OLD boundary
        (5.01, 5.01),         # used to be JUST outside the OLD boundary
        (23.5, 23.5),         # textbook ROE in percent
        (100.0, 100.0),       # 100% ROE
        (-23.5, -23.5),       # negative percent
        # ─── zero and None
        (0, 0.0),
        (0.0, 0.0),
        (None, None),
    ],
)
def test_analysis_normalize_pct(raw, expected):
    out = analysis_norm_pct(raw)
    if expected is None:
        assert out is None
    else:
        assert out == pytest.approx(expected, abs=1e-6)


def test_analysis_normalize_pct_rejects_junk():
    assert analysis_norm_pct("not-a-number") is None
    assert analysis_norm_pct(object()) is None


# ════════════════════════════════════════════════════════════════════
# 2. analytical_notes._normalize_pct  — uses a 1.5 threshold instead
# ════════════════════════════════════════════════════════════════════


@pytest.mark.parametrize(
    "raw, expected",
    [
        (0.23, 23.0),         # decimal → percent
        (1.49, 149.0),        # under 1.5 → still treated as decimal
        (1.5, 1.5),           # at threshold → already percent
        (23.0, 23.0),         # passthrough
        (None, None),
        (float("nan"), None),
    ],
)
def test_notes_normalize_pct(raw, expected):
    out = notes_norm_pct(raw)
    if expected is None:
        assert out is None
    else:
        assert out == pytest.approx(expected, abs=1e-6)


# ════════════════════════════════════════════════════════════════════
# 3. data.collector._normalize_pct_to_decimal  — three-way div yield
# ════════════════════════════════════════════════════════════════════


def _import_collector_norm():
    """Import lazily — collector pulls in heavy deps (pandas, yfinance)."""
    from data.collector import _normalize_pct_to_decimal  # type: ignore
    return _normalize_pct_to_decimal


@pytest.mark.parametrize(
    "raw, expected",
    [
        # already-decimal: |v| < 0.20 → passthrough
        (0.0097, 0.0097),
        (0.05, 0.05),
        (0.20, 0.20),         # boundary, treated as percent-decimal-form
        # percent-in-decimal: 0.20 < v <= 1.0 → divide by 100
        (0.97, 0.0097),
        (1.0, 0.01),
        # percent: v > 1 → divide by 100
        (2.5, 0.025),
        (97.0, 0.97),
        # negatives + zero are clamped to zero
        (-1.0, 0.0),
        (0.0, 0.0),
    ],
)
def test_collector_normalize_pct_to_decimal(raw, expected):
    pytest.importorskip("pandas")
    pytest.importorskip("numpy")
    f = _import_collector_norm()
    assert f(raw) == pytest.approx(expected, abs=1e-9)


# ════════════════════════════════════════════════════════════════════
# 4. backend.services.units  — central canonicaliser (new module)
# ════════════════════════════════════════════════════════════════════


# ─── to_percent
@pytest.mark.parametrize(
    "raw, hint, expected",
    [
        (0.0235, None, 2.35),
        (0.0235, "decimal", 2.35),
        (2.35, None, 2.35),
        (2.35, "percent", 2.35),
        (2.35, "decimal", 235.0),     # explicit hint overrides heuristic
        (0.5, "percent", 0.5),         # explicit hint overrides heuristic
        (0, None, 0.0),
        (None, None, None),
        (float("nan"), None, None),
        (float("inf"), None, None),
        (float("-inf"), None, None),
        ("garbage", None, None),
    ],
)
def test_units_to_percent(raw, hint, expected):
    out = U.to_percent(raw, hint=hint)
    if expected is None:
        assert out is None
    else:
        assert out == pytest.approx(expected, abs=1e-6)


# ─── to_decimal
@pytest.mark.parametrize(
    "raw, hint, expected",
    [
        (0.235, None, 0.235),
        (23.5, None, 0.235),
        (23.5, "percent", 0.235),
        (0.235, "decimal", 0.235),
        (23.5, "decimal", 23.5),       # explicit hint trusted
        (0, None, 0.0),
        (None, None, None),
    ],
)
def test_units_to_decimal(raw, hint, expected):
    out = U.to_decimal(raw, hint=hint)
    if expected is None:
        assert out is None
    else:
        assert out == pytest.approx(expected, abs=1e-9)


# ─── to_inr_crore
@pytest.mark.parametrize(
    "raw, hint, expected",
    [
        (1500.0, None, 1500.0),                     # already crore
        (1500.0, "crore", 1500.0),
        (1.5e10, None, 1500.0),                     # raw INR detected
        (1.5e10, "raw_inr", 1500.0),
        (1500.0, "raw_inr", 1500.0 / U.ONE_CRORE),  # explicit hint trusted
        (150_000.0, "lakh", 1500.0),                # 1.5 lakh crore
        (None, None, None),
        (float("nan"), None, None),
    ],
)
def test_units_to_inr_crore(raw, hint, expected):
    out = U.to_inr_crore(raw, hint=hint)
    if expected is None:
        assert out is None
    else:
        assert out == pytest.approx(expected, rel=1e-6)


# ─── invalid hints raise
def test_units_invalid_hint_raises():
    with pytest.raises(ValueError):
        U.to_percent(1.0, hint="bogus")
    with pytest.raises(ValueError):
        U.to_decimal(1.0, hint="bogus")
    with pytest.raises(ValueError):
        U.to_inr_crore(1.0, hint="bogus")


# ─── boundary warnings (caplog-based)
def test_units_boundary_warns(caplog):
    """Values within ±0.05 of the decimal/percent boundary log WARNING."""
    with caplog.at_level("WARNING", logger="backend.services.units"):
        U.to_percent(0.99, name="roe")
        U.to_percent(1.0, name="roe")
        U.to_percent(1.01, name="roe")
    msgs = [r.getMessage() for r in caplog.records]
    assert any("boundary" in m for m in msgs), msgs


def test_units_no_warning_when_clearly_decimal(caplog):
    with caplog.at_level("WARNING", logger="backend.services.units"):
        U.to_percent(0.235)
    msgs = [r.getMessage() for r in caplog.records]
    assert not any("boundary" in m for m in msgs)


# ─── assert_percent / assert_decimal
def test_assert_percent_warns_on_decimalish(caplog):
    with caplog.at_level("WARNING", logger="backend.services.units"):
        U.assert_percent(0.05, name="roe_pct")
    assert any("looks like a decimal" in r.getMessage() for r in caplog.records)


def test_assert_decimal_warns_on_percentish(caplog):
    with caplog.at_level("WARNING", logger="backend.services.units"):
        U.assert_decimal(23.5, name="roe_dec")
    assert any("looks like a percent" in r.getMessage() for r in caplog.records)


def test_asserts_silent_on_zero_and_none(caplog):
    with caplog.at_level("WARNING", logger="backend.services.units"):
        U.assert_percent(0)
        U.assert_percent(None)
        U.assert_decimal(0.0)
        U.assert_decimal(None)
    assert not caplog.records


# ─── double-normalisation sentinel
def test_double_normalisation_sentinel():
    obj: dict = {"roe": 23.5}
    assert not U.is_normalised(obj, "roe")
    U.mark_normalised(obj, "roe")
    assert U.is_normalised(obj, "roe")
    assert not U.is_normalised(obj, "roce")
    # repeated marks are idempotent
    U.mark_normalised(obj, "roe")
    assert U.is_normalised(obj, "roe")


def test_sentinel_handles_non_dict():
    U.mark_normalised(None, "roe")  # no-op, no exception
    assert not U.is_normalised(None, "roe")
    assert not U.is_normalised([], "roe")


# ─── mixed-unit dict (one field decimal, one percent)
def test_mixed_unit_dict_handled_per_field():
    """Real enrichment dicts mix conventions — assert each field is
    routed through the canonicaliser independently."""
    enriched = {
        "roe": 0.235,   # decimal (yfinance)
        "roce": 18.5,   # percent (Aiven XBRL)
        "de_ratio": 0.45,  # plain ratio, no unit
    }
    assert U.to_percent(enriched["roe"]) == pytest.approx(23.5)
    assert U.to_percent(enriched["roce"]) == pytest.approx(18.5)
    # de_ratio should NOT be normalised through to_percent — it is a
    # ratio, not a percent. We just confirm to_percent does not corrupt
    # it if mistakenly called (it would treat 0.45 as decimal → 45.0,
    # which is exactly why hint= is mandatory at call sites that know
    # better).
    assert U.to_percent(enriched["de_ratio"], hint="percent") == pytest.approx(0.45)


# ─── parity: heuristic path matches the legacy helper
@pytest.mark.parametrize(
    "raw",
    [0.0235, 0.235, 2.35, 23.5, 5.0, 4.99, 1.0, 0.999, -0.05, -23.5, 0, None],
)
def test_units_to_percent_parity_with_legacy(raw):
    """Heuristic-mode ``to_percent`` must match
    ``backend.services.analysis.utils._normalize_pct`` exactly so the
    central module is a drop-in for existing callers."""
    legacy = analysis_norm_pct(raw)
    new = U.to_percent(raw)
    if legacy is None:
        assert new is None
    else:
        assert new == pytest.approx(legacy, abs=1e-6), (raw, legacy, new)
