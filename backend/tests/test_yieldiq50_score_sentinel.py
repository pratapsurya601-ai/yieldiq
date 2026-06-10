# backend/tests/test_yieldiq50_score_sentinel.py
# ═══════════════════════════════════════════════════════════════
# Regression lock-ins for the 2026-06-11 YIQ50 score-uniformity bug
# (PR `fix/discover-yiq50-score-uniformity`).
#
# Pre-fix the Discover leaderboard surfaced three banks all at
# identical "50/100" despite vastly different MoS readings:
#   #1 KOTAKBANK  +44.8%  50/100
#   #2 BANDHANBNK +37.2%  50/100
#   #3 BANKINDIA  +34.6%  50/100
#
# Two compounding root causes:
#   1. The DB-fallback `synth_score = min(95, max(50, int(50 + mos*0.5)))`
#      floored at 50, so any score-less row showed at least 50/100. The
#      synth was meant as "score not persisted yet, render a proxy" but
#      the floor was deceptive — three rows with different MoS could
#      land on the same floor when their bare-ticker analysis_cache
#      rows were missing.
#   2. The cache-override path overwrote `score` with `live_score = q.get(
#      "yieldiq_score")` even when live_score was 0 (the QualityOutput
#      int default for a partial / not-yet-computed payload). A 0 is
#      worse than a synth — the row then renders "0/100" in legacy
#      builds and clips back to 50 here via the gate.
#
# PR #883 added the `fair_value_history.yieldiq_score` column so the
# real score is now persistable. This PR consumes that column in the
# YIQ50 builder, swaps the synth for a non-floored proxy, and gates
# the cache override on `live_score > 0`. Rows that still have neither
# a persisted nor a cached score are marked `score_estimated=True` so
# the frontend renders "—" rather than a deceptive baseline.
#
# These tests exercise the *contract* (model fields + override gating)
# without touching Neon / DuckDB. The full SQL path is exercised in
# the existing test_yieldiq50_db_fallback_ticker_form.py + the canary
# nightly suite.
# ═══════════════════════════════════════════════════════════════

from __future__ import annotations

from backend.models.responses import ScreenerStock


def test_screener_stock_has_score_estimated_flag():
    """The new field must exist with a False default for back-compat
    with payloads that don't set it (legacy CSV / cache override).
    """
    s = ScreenerStock(ticker="X")
    assert hasattr(s, "score_estimated"), (
        "ScreenerStock must carry a `score_estimated` sentinel so the "
        "frontend can distinguish a real YieldIQ score from a synth "
        "MoS-proxy. Without it the rail re-acquires the 50/100 bug."
    )
    assert s.score_estimated is False


def test_screener_stock_score_estimated_serialises():
    """Pydantic must surface the flag through model_dump so the field
    actually reaches the wire. Easy to break by typing it Optional
    without a default."""
    s = ScreenerStock(ticker="X", score=72, score_estimated=True)
    dumped = s.model_dump()
    assert dumped["score_estimated"] is True
    assert dumped["score"] == 72


def test_synth_score_varies_with_mos_no_floor():
    """The post-fix synth formula is `min(95, max(0, int(40 + mos*0.8)))`.
    Three rows with the same SQL fallback path but different MoS must
    NOT all land on 50 — that was the user-visible bug.

    The 50-floor (pre-fix `max(50, ...)`) is intentionally removed.
    Rows whose synth falls below 50 are then dropped by the existing
    `_ok_for_top50` gate (score >= 50), so the rail still shows only
    score>=50 rows but the synth differentiates between mid-MoS picks.
    """
    def _synth(mos: float) -> int:
        return min(95, max(0, int(40 + mos * 0.8)))

    # KOTAKBANK / BANDHANBNK / BANKINDIA MoS values from the bug
    # report. Pre-fix all three synth'd to 50; post-fix they spread.
    assert _synth(44.8) == 75  # KOTAKBANK
    assert _synth(37.2) == 69  # BANDHANBNK
    assert _synth(34.6) == 67  # BANKINDIA

    # All three are distinct → user no longer sees three identical
    # 50/100 readings stacked on the rail.
    assert len({_synth(44.8), _synth(37.2), _synth(34.6)}) == 3


def test_synth_score_low_mos_below_floor_dropped():
    """A row with MoS just barely positive (e.g. 1.0%) synths to ~40,
    which is below the `_ok_for_top50` >= 50 gate — i.e. it never
    reaches the rail. The previous 50-floor would have shown it as
    50/100. This is the desired honest behaviour.
    """
    def _synth(mos: float) -> int:
        return min(95, max(0, int(40 + mos * 0.8)))

    assert _synth(1.0) == 40  # below the 50 gate → dropped
    assert _synth(12.0) == 49  # still below the 50 gate
    assert _synth(13.0) == 50  # exactly on the gate → kept


def test_synth_score_high_mos_capped_at_95():
    """Sanity: the upper bound stays at 95 so a wildly-undervalued
    DCF blow-up doesn't push the synth past 95/100, which would
    misrepresent a synth proxy as an A+ grade."""
    def _synth(mos: float) -> int:
        return min(95, max(0, int(40 + mos * 0.8)))

    # SQL filter caps mos at 50, so this is the realistic ceiling.
    assert _synth(50.0) == 80
    # Defence-in-depth: even if SQL relaxes, synth stays bounded.
    assert _synth(100.0) == 95
    assert _synth(500.0) == 95


def test_cache_override_zero_score_treated_as_missing():
    """The cache-override path must NOT overwrite a real persisted
    score with a 0-sentinel from a partial QualityOutput payload.
    This is the second compounding cause of the 50/100 bug — banks
    with cached payloads carrying yieldiq_score=0 (int default,
    never computed) had their real DB-persisted score clobbered.

    Pattern matches the production code's guard:
        if _live_score_int <= 0:
            continue
    """
    # Simulate the guard logic directly (test_yieldiq50_filters.py
    # style — re-derive the predicate so we lock the contract here
    # without spinning up FastAPI/Neon).
    def _override_should_fire(live_score) -> bool:
        if live_score is None:
            return False
        try:
            v = int(live_score)
        except (TypeError, ValueError):
            return False
        return v > 0

    assert _override_should_fire(72) is True
    assert _override_should_fire(50) is True  # legitimate C+ score
    assert _override_should_fire(0) is False  # int default sentinel
    assert _override_should_fire(None) is False
    assert _override_should_fire("not a number") is False


def test_score_estimated_default_back_compat():
    """A ScreenerStock built from a legacy payload (no score_estimated
    field set) must default to False so the frontend renders the real
    score. The flag is opt-in for the synth path — never opt-out for
    the override path.
    """
    legacy = ScreenerStock(ticker="LEGACY.NS", score=80, margin_of_safety=20.0)
    assert legacy.score_estimated is False, (
        "Default must be False so legacy callers (warm-cache loader, "
        "CSV loader, cache-override path) don't accidentally flag "
        "their real scores as estimated."
    )
