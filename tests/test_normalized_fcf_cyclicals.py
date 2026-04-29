# tests/test_normalized_fcf_cyclicals.py
# ═══════════════════════════════════════════════════════════════
# Tests for the cyclical-FCF normalization path:
#
#   1. is_cyclical() classification (ticker + sector)
#   2. _query_normalized_fcf averages 3 annual rows
#   3. _query_normalized_fcf returns None when <2 years available
#   4. _query_normalized_fcf does NOT mutate non-cyclical TTM path
#      (covered indirectly — non-cyclical service.py path skips
#      _query_normalized_fcf entirely; we assert the predicate)
#   5. The normalized FCF for a TATASTEEL-shaped fixture (one deeply
#      negative cycle-bottom year) produces a positive smoothed
#      input — i.e. DCF will not collapse to zero downstream.
#
# All tests are hermetic: monkeypatch `_get_pipeline_session` and
# the `Financials` ORM model so no Aiven connection is required.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import os
import sys
from types import SimpleNamespace

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ─────────────────────────────────────────────────────────────
# Fakes
# ─────────────────────────────────────────────────────────────

class _FakeQuery:
    """Stand-in for the SQLAlchemy chained query object."""

    def __init__(self, rows):
        self._rows = rows

    def filter(self, *_a, **_kw):
        return self

    def order_by(self, *_a, **_kw):
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def all(self):
        return list(self._rows)

    def first(self):
        return self._rows[0] if self._rows else None


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.closed = False

    def query(self, _model):
        return _FakeQuery(list(self._rows))

    def close(self):
        self.closed = True


def _make_row(period_end: str, fcf, revenue=1_000_000_000, pat=200_000_000,
              currency="INR"):
    """Build a row that quacks like a Financials ORM instance."""
    return SimpleNamespace(
        period_end=period_end,
        free_cash_flow=fcf,
        revenue=revenue,
        pat=pat,
        currency=currency,
    )


def _patch_session(monkeypatch, db, rows):
    """Wire the fake session and a sentinel `Financials` model.

    The implementation imports `data_pipeline.models.Financials`
    inside the function — we provide a dummy module so the import
    succeeds. The `_FakeQuery` returns the fixture rows regardless
    of what the caller passes to `.filter(...)`.
    """
    import types

    fake_models = types.ModuleType("data_pipeline.models")
    fake_models.Financials = SimpleNamespace(
        ticker=None, period_type=None, period_end=None,
        free_cash_flow=None,
    )
    monkeypatch.setitem(sys.modules, "data_pipeline.models", fake_models)

    monkeypatch.setattr(
        db, "_get_pipeline_session", lambda: _FakeSession(rows),
    )


# ─────────────────────────────────────────────────────────────
# 1. is_cyclical predicate
# ─────────────────────────────────────────────────────────────

def test_is_cyclical_recognises_steel_ticker():
    from backend.services.analysis.constants import is_cyclical
    assert is_cyclical("TATASTEEL.NS") is True
    assert is_cyclical("JSWSTEEL.NS") is True
    assert is_cyclical("RELIANCE.NS") is True
    assert is_cyclical("ONGC") is True
    assert is_cyclical("COALINDIA.NS") is True
    assert is_cyclical("HINDALCO.NS") is True
    assert is_cyclical("VEDL.NS") is True


def test_is_cyclical_rejects_compounders():
    from backend.services.analysis.constants import is_cyclical
    assert is_cyclical("HDFCBANK.NS") is False
    assert is_cyclical("TCS.NS") is False
    assert is_cyclical("HINDUNILVR.NS") is False
    assert is_cyclical("ASIANPAINT.NS") is False


def test_is_cyclical_falls_through_to_sector_match():
    from backend.services.analysis.constants import is_cyclical
    # Unknown ticker, but resolved sector is plainly cyclical.
    assert is_cyclical("FOO.NS", sector="Metals & Mining") is True
    assert is_cyclical("BAR.NS", sector="Oil & Gas") is True
    # Non-cyclical sector
    assert is_cyclical("FOO.NS", sector="IT") is False


# ─────────────────────────────────────────────────────────────
# 2. _query_normalized_fcf averages 3 annual rows
# ─────────────────────────────────────────────────────────────

def test_normalized_fcf_averages_three_years(monkeypatch):
    from backend.services.analysis import db

    rows = [
        _make_row("2025-03-31", fcf=8_000_000_000),   # mid-cycle
        _make_row("2024-03-31", fcf=-3_000_000_000),  # cycle bottom
        _make_row("2023-03-31", fcf=10_000_000_000),  # cycle top
    ]
    _patch_session(monkeypatch, db, rows)

    out = db._query_normalized_fcf("TATASTEEL.NS", years=3)
    assert out is not None
    assert out["source"] == "normalized_3y"
    assert out["years_used"] == 3
    # Mean of the three: (8 - 3 + 10) / 3 = 5
    assert abs(out["fcf"] - 5_000_000_000) < 1.0
    # Even with a deeply negative cycle-bottom year, the smoothed
    # input is comfortably positive — DCF will not collapse to ~0.
    assert out["fcf"] > 0


def test_normalized_fcf_skips_null_years(monkeypatch):
    from backend.services.analysis import db

    rows = [
        _make_row("2025-03-31", fcf=6_000_000_000),
        _make_row("2024-03-31", fcf=None),  # missing — must be skipped
        _make_row("2023-03-31", fcf=4_000_000_000),
    ]
    _patch_session(monkeypatch, db, rows)

    out = db._query_normalized_fcf("ONGC.NS", years=3)
    assert out is not None
    assert out["years_used"] == 2
    # Average of the two non-null years.
    assert abs(out["fcf"] - 5_000_000_000) < 1.0
    assert out["source"] == "normalized_2y"


# ─────────────────────────────────────────────────────────────
# 3. Falls back to None (caller → TTM) when <2 years
# ─────────────────────────────────────────────────────────────

def test_normalized_fcf_returns_none_when_one_row(monkeypatch):
    from backend.services.analysis import db

    rows = [_make_row("2025-03-31", fcf=6_000_000_000)]
    _patch_session(monkeypatch, db, rows)

    assert db._query_normalized_fcf("JSWSTEEL.NS", years=3) is None


def test_normalized_fcf_returns_none_when_all_null(monkeypatch):
    from backend.services.analysis import db

    rows = [
        _make_row("2025-03-31", fcf=None),
        _make_row("2024-03-31", fcf=None),
        _make_row("2023-03-31", fcf=None),
    ]
    _patch_session(monkeypatch, db, rows)

    assert db._query_normalized_fcf("HINDALCO.NS", years=3) is None


def test_normalized_fcf_returns_none_when_db_unavailable(monkeypatch):
    from backend.services.analysis import db
    monkeypatch.setattr(db, "_get_pipeline_session", lambda: None)
    assert db._query_normalized_fcf("RELIANCE.NS", years=3) is None


# ─────────────────────────────────────────────────────────────
# 4. Non-cyclical predicate guards the TTM path
# ─────────────────────────────────────────────────────────────

def test_non_cyclical_predicate_does_not_trigger_normalization():
    """The service.py wiring only calls _query_normalized_fcf when
    is_cyclical() is True. Asserting the predicate here is the
    minimal hermetic check that non-cyclicals retain TTM behavior."""
    from backend.services.analysis.constants import is_cyclical
    for t in ("TCS.NS", "HDFCBANK.NS", "HINDUNILVR.NS", "ASIANPAINT.NS",
              "INFY.NS", "ITC.NS"):
        assert is_cyclical(t) is False, f"{t} should not be cyclical"


# ─────────────────────────────────────────────────────────────
# 5. TATASTEEL-shaped fixture: smoothed FCF stays sane
# ─────────────────────────────────────────────────────────────

def test_tatasteel_shaped_fixture_avoids_zero_collapse(monkeypatch):
    """Given a cycle-bottom TTM print of ~-₹500cr but historical
    annual FCF of (-₹50cr, ₹15,000cr, ₹22,000cr), the normalized
    input is ₹12,317cr — orders of magnitude away from zero. This
    is the regression that motivated the change (validators.py
    logged TATASTEEL fair_value_ratio=0.0485)."""
    from backend.services.analysis import db

    rows = [
        _make_row("2025-03-31", fcf=-50_00_00_000),       # -50 cr
        _make_row("2024-03-31", fcf=15_000_00_00_000),    # 15,000 cr
        _make_row("2023-03-31", fcf=22_000_00_00_000),    # 22,000 cr
    ]
    _patch_session(monkeypatch, db, rows)

    out = db._query_normalized_fcf("TATASTEEL.NS", years=3)
    assert out is not None
    assert out["fcf"] > 1_000_00_00_000  # well above ₹1,000 cr — DCF safe
    assert out["years_used"] == 3
