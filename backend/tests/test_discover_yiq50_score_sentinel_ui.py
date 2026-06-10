"""Discover YIQ50 score-sentinel UI fix (2026-06-11).

Pre-fix the Discover page rendered "50/100" for three banks (KOTAKBANK,
BANDHANBNK, BANKINDIA) whose backend score was the synth-floor sentinel
rather than a real persisted YieldIQ score. Fix (PR
fix/discover-yiq50-score-uniformity):

  1. Backend SQL now reads fv.yieldiq_score (PR #883 column) and uses
     it when NOT NULL. When NULL, the row is marked `score_estimated=True`
     and the synth proxy no longer floors at 50.
  2. Frontend `discover/page.tsx` renders "—" (mdash) for rows where
     `s.score_estimated === true`, with a "Pending" tooltip. This stops
     the user-visible "three banks all 50/100" anomaly.

These tests are source-text regressions on
frontend/src/app/(app)/discover/page.tsx + the TS types. They fail
loudly if someone removes the sentinel-aware rendering branch.
"""
from __future__ import annotations
from pathlib import Path


_REPO_ROOT = Path(__file__).resolve().parents[2]
_DISCOVER = _REPO_ROOT / "frontend" / "src" / "app" / "(app)" / "discover" / "page.tsx"
_API_TYPES = _REPO_ROOT / "frontend" / "src" / "types" / "api.ts"


def _discover_src() -> str:
    assert _DISCOVER.exists(), f"Discover page not found at {_DISCOVER}"
    return _DISCOVER.read_text(encoding="utf-8")


def _api_types_src() -> str:
    assert _API_TYPES.exists(), f"API types not found at {_API_TYPES}"
    return _API_TYPES.read_text(encoding="utf-8")


# ── Type contract ─────────────────────────────────────────────


def test_screener_stock_type_carries_score_estimated_field():
    """The TS interface must declare `score_estimated?: boolean` so
    consumers can branch on it without TS complaining about the prop.
    If this field drops, the discover-page guards silently degrade to
    "always show numeric score" → the 50/100 bug re-surfaces.
    """
    src = _api_types_src()
    # Must appear in the ScreenerStock interface block.
    iface_start = src.find("export interface ScreenerStock {")
    assert iface_start >= 0, "ScreenerStock interface block missing."
    iface_end = src.find("}", iface_start)
    iface_body = src[iface_start:iface_end]
    assert "score_estimated" in iface_body, (
        "ScreenerStock.score_estimated dropped from TS contract — "
        "frontend guards will silently degrade and the 50/100 bug "
        "will re-surface on Discover."
    )


# ── Discover page renders the sentinel guard ─────────────────


def test_discover_renders_mdash_when_score_estimated():
    """The top-3 card grid must check `s.score_estimated` before
    rendering the score. The check goes from `{s.score}<...>/100<...>`
    to a ternary that emits `&mdash;` for estimated rows.
    """
    src = _discover_src()
    # The sentinel-aware ternary must be present in the top-3 grid.
    assert "s.score_estimated" in src, (
        "Discover page no longer reads s.score_estimated — every "
        "row will render its numeric score, including synth-50 "
        "floor sentinels. This is the exact bug the PR closed."
    )
    # mdash entity must appear at least once (the placeholder char).
    assert "&mdash;" in src, (
        "Sentinel rows must render as an mdash (—) so users can tell "
        "the score is pending rather than reading it as a real 50/100."
    )


def test_discover_pending_tooltip_present_for_sentinel():
    """The user-facing hint must accompany the mdash so the reader
    understands why it shows up. Without it the rail looks broken."""
    src = _discover_src()
    # Either "Pending" or "pending" must show up near the mdash in a
    # title attribute. Both casings allowed so cosmetic copy edits
    # don't break this test.
    assert "Pending" in src or "pending" in src, (
        "Sentinel-row tooltip missing the 'Pending' hint."
    )


def test_discover_table_score_column_honours_sentinel():
    """The expanded table view (paid-tier surface) must use the
    same sentinel-aware rendering as the top-3 grid. Otherwise the
    bug remains visible on paid plans.
    """
    src = _discover_src()
    # We expect at least two distinct `score_estimated` checks — one
    # for the top-3 grid and one for the table body. Use simple
    # substring count as the structural assertion.
    occurrences = src.count("score_estimated")
    assert occurrences >= 2, (
        f"Expected ≥2 score_estimated checks (top-3 grid + table); "
        f"found {occurrences}. Both surfaces must honour the sentinel."
    )


# ── Defence: legacy bare-score render must NOT be the SOLE path ──


def test_discover_does_not_render_bare_score_without_guard():
    """Make sure no JSX node renders `{s.score}<span>/100` without
    being wrapped in a sentinel check. We tolerate the legacy
    bare-render INSIDE a ternary's false-branch (where score_estimated
    is checked first), but not on its own.

    This is a structural check: count the bare `{s.score}` JSX
    occurrences and require they all sit inside ternary branches whose
    condition references `score_estimated`. A simple proxy: every
    `{s.score}` should be within ~200 chars of a `score_estimated`
    reference.
    """
    src = _discover_src()
    # Find every literal occurrence of `{s.score}` (the JSX form).
    positions = []
    start = 0
    needle = "{s.score}"
    while True:
        i = src.find(needle, start)
        if i < 0:
            break
        positions.append(i)
        start = i + 1

    assert positions, (
        "No `{s.score}` JSX render found in discover page. Either the "
        "leaderboard was removed or this test is testing the wrong file."
    )

    for pos in positions:
        # Look backward for the nearest score_estimated check. The
        # ternary's true-branch (mdash + Pending hint + closing
        # `</span>`) sits between the `?` condition and the `: (`
        # false-branch where the bare render lives. Empirically the
        # full ternary block runs ~600-700 chars; allow 800 for slack.
        window_start = max(0, pos - 800)
        window = src[window_start:pos + 50]
        assert "score_estimated" in window, (
            f"Bare `{{s.score}}` render at char {pos} is not within a "
            f"score_estimated guard. The 50/100 sentinel will leak into "
            f"the UI when this branch is reached for a row whose backend "
            f"flagged score_estimated=True."
        )
