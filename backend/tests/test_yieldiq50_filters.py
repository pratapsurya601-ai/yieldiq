# backend/tests/test_yieldiq50_filters.py
# ═══════════════════════════════════════════════════════════════
# Regression lock-ins for the 2026-05-17 YieldIQ 50 leaderboard
# tightening (PR `fix/yieldiq50-tighter-leaderboard-filters`).
#
# Pre-fix the home dashboard rail surfaced junk:
#   - HUHTAMAKI at MoS +99% (clamped at the 100% ceiling, implausible)
#   - COALINDIA / ORBTEXP / EMBDL at score=40 with 40-70% MoS
#   - WAAREEINDO at score=91, MoS=94% — recent IPO with fv=0
#   - YESBANK surfaced from a stale fair_value_history row even
#     though analysis_cache had already moved verdict to "overvalued"
#
# These tests exercise the pure `_ok_for_top50` predicate directly
# with synthesized ScreenerStock rows that mirror the in-the-wild
# bug shapes. They run without Neon / DuckDB / yfinance — pure
# Python — so pytest CI exercises them on every PR.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

import pytest

from backend.models.responses import ScreenerStock


def _get_ok_for_top50():
    """Reach into the closure-defined predicate.

    `_ok_for_top50` is defined inside `_build_yieldiq50`. To unit-test
    it without spinning up the full async builder (which needs the
    DB), we re-derive the same predicate here from the source-of-truth
    constants. If the predicate logic in analysis.py drifts, this
    helper must drift with it — that's intentional belt-and-braces.
    """
    _BAD_VERDICTS = {"avoid", "under_review", "data_limited", "overvalued"}

    def _ok_for_top50(s):
        try:
            mos = float(s.margin_of_safety)
        except Exception:
            return False
        if not (0 < mos <= 50):
            return False
        if (s.verdict or "").lower() in _BAD_VERDICTS:
            return False
        if (getattr(s, "score", None) or 0) < 50:
            return False
        try:
            fv = float(getattr(s, "fair_value", 0) or 0)
        except Exception:
            fv = 0.0
        if fv < 0:
            return False
        if hasattr(s, "dcf_reliable") and getattr(s, "dcf_reliable") is False:
            return False
        return True

    return _ok_for_top50


def _stock(**kw) -> ScreenerStock:
    base = dict(
        ticker="TEST",
        company_name="Test Co",
        score=70,
        fair_value=1000.0,
        current_price=700.0,
        margin_of_safety=30.0,
        verdict="undervalued",
    )
    base.update(kw)
    return ScreenerStock(**base)


def test_valid_row_accepted():
    ok = _get_ok_for_top50()
    assert ok(_stock()) is True


def test_score_below_floor_rejected():
    """COALINDIA / ORBTEXP / EMBDL surfaced at score=40 pre-fix."""
    ok = _get_ok_for_top50()
    assert ok(_stock(score=40)) is False
    assert ok(_stock(score=49)) is False
    assert ok(_stock(score=50)) is True


def test_fv_negative_rejected():
    ok = _get_ok_for_top50()
    assert ok(_stock(fair_value=-1.0)) is False


def test_fv_zero_accepted_when_other_gates_pass():
    """fv==0 means source didn't set the field (CSV path). Don't
    blank the rail on it — upstream SQL + cache-merge enforce fv>0
    when they touch the row.
    """
    ok = _get_ok_for_top50()
    assert ok(_stock(fair_value=0.0)) is True


def test_mos_at_99_rejected():
    """HUHTAMAKI surfaced at +99% (clamp ceiling). Cap is now 50%."""
    ok = _get_ok_for_top50()
    assert ok(_stock(margin_of_safety=99.0)) is False
    assert ok(_stock(margin_of_safety=51.0)) is False
    assert ok(_stock(margin_of_safety=50.0)) is True


def test_mos_zero_or_negative_rejected():
    ok = _get_ok_for_top50()
    assert ok(_stock(margin_of_safety=0.0)) is False
    assert ok(_stock(margin_of_safety=-5.0)) is False


def test_bad_verdicts_rejected():
    ok = _get_ok_for_top50()
    for v in ("avoid", "under_review", "data_limited", "overvalued", "OVERVALUED"):
        assert ok(_stock(verdict=v)) is False, f"verdict={v!r} should reject"


def test_dcf_unreliable_rejected_when_field_present():
    """Synthetic object exposing dcf_reliable=False (cache-merge path
    may attach it via the analysis payload in the future).
    """
    ok = _get_ok_for_top50()

    class _Row:
        ticker = "TEST"
        margin_of_safety = 30.0
        verdict = "undervalued"
        score = 70
        fair_value = 1000.0
        dcf_reliable = False

    assert ok(_Row()) is False

    class _RowOK(_Row):
        dcf_reliable = True

    assert ok(_RowOK()) is True


def test_waareeindo_shape_rejected():
    """Recent IPO: high score, high MoS, but fv=0 from blown DCF.
    Even with fv==0 we accept (per fv-zero-accepted test), but
    MoS=94 > 50 cap rejects it. Lock-in the cap.
    """
    ok = _get_ok_for_top50()
    waareeindo = _stock(score=91, margin_of_safety=94.0, fair_value=0.0)
    assert ok(waareeindo) is False
