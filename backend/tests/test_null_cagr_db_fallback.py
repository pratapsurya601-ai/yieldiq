# backend/tests/test_null_cagr_db_fallback.py
#
# Regression guard for the null-CAGR data_limited fix (2026-06-13).
#
# THE BUG: the hot analysis path builds `income_df` from whichever
# source served the ticker. The local-DB assembler caps annual rows at
# LIMIT 5 and the yfinance collector frequently returns only a TTM /
# 1-2yr income statement for thin-coverage mid-caps. When that leaves
# BOTH revenue_cagr_3y and revenue_cagr_5y None, the null-CAGR gate
# (service.py FIX 1) forces verdict=data_limited even for names that
# have >=3 years of genuine annual revenue in the financials DB and a
# fully-formed, sound DCF (e.g. AARTIIND).
#
# THE FIX: backend/services/analysis/db._fetch_annual_revenue_series()
# loads a de-duped annual revenue series from v_financials_unified
# (which already collapses the cf_has_duplicate_fy / cf_is_corrupt
# cohort), and service.py uses it as an ADDITIVE fallback that can only
# FILL a None CAGR, never overwrite a value income_df already produced.
#
# These tests run without a live DB or yfinance: the helper is exercised
# against a fake session, and the service-level fallback logic is
# mirrored verbatim (same pattern as test_ratios_integration.py).
from __future__ import annotations

import pytest

from backend.services.ratios_service import compute_revenue_cagr as _rcagr


# ── 1. The helper's dedup + ordering contract ────────────────────────
class _FakeRow(dict):
    """mappings()-style row: supports .get()."""


class _FakeResult:
    def __init__(self, rows):
        self._rows = rows

    def mappings(self):
        return self

    def all(self):
        return self._rows


class _FakeSession:
    def __init__(self, rows):
        self._rows = rows
        self.closed = False

    def execute(self, *a, **k):
        return _FakeResult(self._rows)

    def close(self):
        self.closed = True


@pytest.fixture
def _patch_session(monkeypatch):
    """Return a factory that patches _get_pipeline_session to serve the
    supplied view rows."""
    from backend.services.analysis import db as _db

    def _install(rows):
        sess = _FakeSession(rows)
        monkeypatch.setattr(_db, "_get_pipeline_session", lambda: sess)
        return sess

    return _install


def test_helper_returns_chronological_revenue(_patch_session):
    from backend.services.analysis.db import _fetch_annual_revenue_series

    # View emits one row per FY (already deduped upstream); ORDER BY FY ASC.
    rows = [
        _FakeRow(fiscal_year=2022, revenue=5191.0),
        _FakeRow(fiscal_year=2023, revenue=6492.0),
        _FakeRow(fiscal_year=2024, revenue=6192.0),
        _FakeRow(fiscal_year=2025, revenue=7131.0),
        _FakeRow(fiscal_year=2026, revenue=8286.0),
    ]
    sess = _patch_session(rows)
    out = _fetch_annual_revenue_series("AARTIIND.NS")
    assert out == [5191.0, 6492.0, 6192.0, 7131.0, 8286.0]
    assert sess.closed is True  # session is always closed


def test_helper_collapses_any_duplicate_fy(_patch_session):
    """Defensive: even if the view ever emitted two rows for one FY,
    the helper keeps exactly one (the last-sorted) per fiscal year."""
    from backend.services.analysis.db import _fetch_annual_revenue_series

    rows = [
        _FakeRow(fiscal_year=2023, revenue=100.0),
        _FakeRow(fiscal_year=2023, revenue=110.0),  # dup FY
        _FakeRow(fiscal_year=2024, revenue=120.0),
        _FakeRow(fiscal_year=2025, revenue=130.0),
        _FakeRow(fiscal_year=2026, revenue=140.0),
    ]
    _patch_session(rows)
    out = _fetch_annual_revenue_series("DUP.NS")
    # 4 distinct FYs -> 4 values, the FY2023 dup collapsed to one.
    assert len(out) == 4
    assert out == [110.0, 120.0, 130.0, 140.0]


def test_helper_drops_null_and_nonpositive_and_returns_empty_when_none(
    _patch_session,
):
    from backend.services.analysis.db import _fetch_annual_revenue_series

    rows = [
        _FakeRow(fiscal_year=2024, revenue=None),
        _FakeRow(fiscal_year=2025, revenue=0.0),
        _FakeRow(fiscal_year=2026, revenue=-5.0),
    ]
    _patch_session(rows)
    assert _fetch_annual_revenue_series("THIN.NS") == []


def test_helper_returns_empty_when_session_unavailable(monkeypatch):
    from backend.services.analysis import db as _db

    monkeypatch.setattr(_db, "_get_pipeline_session", lambda: None)
    assert _db._fetch_annual_revenue_series("ANY.NS") == []


# ── 2. The service-level fallback logic ──────────────────────────────
# Verbatim replica of the CAGR-fallback block in
# backend/services/analysis/service.py (the lines guarded by
# `if _rev_cagr_3y is None or _rev_cagr_5y is None:`). Any drift here
# means this test no longer guards the real code path.
def _apply_db_cagr_fallback(rev_cagr_3y, rev_cagr_5y, db_series):
    if rev_cagr_3y is None or rev_cagr_5y is None:
        try:
            if len(db_series) >= 4 and rev_cagr_3y is None:
                _c3 = _rcagr(db_series, 3)
                if _c3 is not None:
                    rev_cagr_3y = _c3
            if len(db_series) >= 6 and rev_cagr_5y is None:
                _c5 = _rcagr(db_series, 5)
                if _c5 is not None:
                    rev_cagr_5y = _c5
        except Exception:
            pass
    return rev_cagr_3y, rev_cagr_5y


def _sanitize_cagr(v):
    """±80% clamp, identical to service.py."""
    if v is None:
        return None
    try:
        return None if abs(float(v)) > 0.80 else v
    except (TypeError, ValueError):
        return None


def _null_cagr_gate_would_trip(c3, c5):
    """service.py FIX 1: gate trips iff BOTH are None (for the
    non-financial / non-bellwether path)."""
    return c3 is None and c5 is None


def test_aartiind_short_income_df_db_fallback_fills_cagr_and_clears_gate():
    """AARTIIND-shaped: income_df too short to yield ANY CAGR (both
    None), but the DB has 9 de-duped annual rows -> 3y AND 5y fill ->
    the null-CAGR gate no longer trips."""
    # income_df produced nothing (the pre-fix state that tripped the gate)
    c3, c5 = None, None
    assert _null_cagr_gate_would_trip(c3, c5) is True  # pre-fix: gated

    # 9 distinct FYs of real AARTIIND revenue (Cr) from v_financials_unified
    db_series = [3699, 4858, 4186, 4506, 7000, 6619, 6372, 7131, 8286]
    c3, c5 = _apply_db_cagr_fallback(c3, c5, db_series)
    c3, c5 = _sanitize_cagr(c3), _sanitize_cagr(c5)

    assert c3 is not None
    assert c5 is not None
    assert c3 == pytest.approx(0.0778, abs=5e-3)
    assert c5 == pytest.approx(0.1296, abs=5e-3)
    assert _null_cagr_gate_would_trip(c3, c5) is False  # post-fix: cleared


def test_thin_nanocap_with_no_db_history_stays_gated():
    """AATMAJ / AKIKO control: no annual history in the view -> DB
    series empty -> CAGR stays None -> the gate STILL trips. The fix
    must not flip genuinely-thin nano-caps."""
    c3, c5 = None, None
    db_series: list[float] = []  # view returned []
    c3, c5 = _apply_db_cagr_fallback(c3, c5, db_series)
    c3, c5 = _sanitize_cagr(c3), _sanitize_cagr(c5)
    assert c3 is None and c5 is None
    assert _null_cagr_gate_would_trip(c3, c5) is True


def test_three_years_fills_only_3y_which_is_enough_to_clear_gate():
    """A name with exactly 4 annual rows (3y window) fills 3y only;
    5y stays None. One valid CAGR is enough to clear the BOTH-None
    gate."""
    c3, c5 = None, None
    db_series = [100.0, 112.0, 125.0, 140.0]  # 4 rows -> 3y only
    c3, c5 = _apply_db_cagr_fallback(c3, c5, db_series)
    c3, c5 = _sanitize_cagr(c3), _sanitize_cagr(c5)
    assert c3 is not None
    assert c5 is None
    assert _null_cagr_gate_would_trip(c3, c5) is False


def test_fallback_never_overwrites_existing_income_df_cagr():
    """ADDITIVE contract: when income_df already produced a 3y CAGR,
    the DB fallback must NOT touch it (only fills the None 5y)."""
    c3, c5 = 0.05, None  # income_df gave a 3y, no 5y
    db_series = [100.0, 110.0, 121.0, 133.1, 146.41, 161.05]  # 10% x6
    c3, c5 = _apply_db_cagr_fallback(c3, c5, db_series)
    c3, c5 = _sanitize_cagr(c3), _sanitize_cagr(c5)
    assert c3 == 0.05  # untouched
    assert c5 == pytest.approx(0.10, abs=5e-3)  # filled


def test_mixed_unit_artifact_is_clamped_and_stays_gated():
    """If the DB series is a mixed-unit / restructuring artifact, the
    ±80% clamp nulls the CAGR back out so the name STAYS gated rather
    than flipping on a bogus growth number."""
    c3, c5 = None, None
    # raw-INR vs Cr mixup: a >80% jump artifact
    db_series = [100.0, 100.0, 100.0, 5_000_000.0]
    c3, c5 = _apply_db_cagr_fallback(c3, c5, db_series)
    c3, c5 = _sanitize_cagr(c3), _sanitize_cagr(c5)
    assert c3 is None and c5 is None
    assert _null_cagr_gate_would_trip(c3, c5) is True
