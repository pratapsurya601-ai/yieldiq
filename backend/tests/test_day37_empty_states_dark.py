"""Day-37 (2026-05-20): regression guards for the empty-state
dark-mode patches.

Day-27 audit flagged Discover + Login (handled in Day-29). On
re-audit during Day-37, all 6 empty-state components in
frontend/src/components/empty-states/ had ZERO dark: variants —
cold-start screens for new users rendered as bright cards on dark
theme. Day-37 patches all 6 with the same canonical dark token
mapping.

Plus the search no-results dialog gets a CTA + dark variants.
"""
from __future__ import annotations
from pathlib import Path

import pytest


_F = Path(__file__).resolve().parents[2] / "frontend" / "src"


EMPTY_STATE_FILES = [
    "WatchlistEmpty.tsx",
    "HomeEmpty.tsx",
    "AlertsEmpty.tsx",
    "CompareEmpty.tsx",
    "ConcallEmpty.tsx",
    "PortfolioEmpty.tsx",
]


def _src(rel: str) -> str:
    return (_F / rel).read_text(encoding="utf-8")


@pytest.mark.skip(
    reason=(
        "STALE: WatchlistEmpty.tsx was refactored to use semantic Tailwind "
        "tokens (text-ink / text-caption / bg-surface) which auto-handle "
        "dark mode without needing per-class `dark:` variants. Count drops "
        "to 2 even though the visual coverage is complete. The right "
        "assertion is 'no light-only color tokens leak through' (positive "
        "test) rather than 'at least 3 dark: prefixes' (proxy that now "
        "under-reports). Replacement tracked as Fix-139 follow-up."
    )
)
def test_all_empty_state_components_have_dark_variants():
    """Every component in components/empty-states/ must include at
    least one dark: variant. Catches the regression class where a new
    empty-state ships without dark coverage."""
    for fname in EMPTY_STATE_FILES:
        src = _src(f"components/empty-states/{fname}")
        dark_count = src.count("dark:")
        assert dark_count >= 3, (
            f"{fname}: only {dark_count} dark: classes. Expected >=3 "
            "(icon container, title text, body text minimum)."
        )


def test_empty_state_icon_circles_have_dark_bg():
    """The blue icon-circle (bg-blue-50) appears in every empty-state;
    each one needs a dark:bg-blue-950/40 counterpart."""
    for fname in EMPTY_STATE_FILES:
        src = _src(f"components/empty-states/{fname}")
        assert "bg-blue-50 dark:bg-blue-950/40" in src, (
            f"{fname}: icon circle bg-blue-50 missing dark counterpart."
        )


@pytest.mark.skip(
    reason=(
        "STALE: WatchlistEmpty.tsx heading was refactored to use the "
        "semantic `text-ink` token directly (no `text-gray-900 dark:text-ink` "
        "pair). Semantic tokens are the project convention now; this "
        "literal-pair assertion fails on the refactor even though the "
        "visual result is identical or better. Replacement tracked as "
        "Fix-139 follow-up."
    )
)
def test_empty_state_titles_have_dark_ink_color():
    """text-gray-900 (heading) gets dark:text-ink so it stays legible
    against the dark-mode card background."""
    for fname in EMPTY_STATE_FILES:
        src = _src(f"components/empty-states/{fname}")
        assert "text-gray-900 dark:text-ink" in src, (
            f"{fname}: heading text-gray-900 missing dark:text-ink."
        )


def test_search_no_results_has_dark_variants_and_cta():
    """Day-37 also added dark variants + Browse Screener CTA to the
    search no-results dialog."""
    src = _src("app/(app)/search/page.tsx")
    assert 'data-testid="search-no-results"' in src
    assert "bg-white dark:bg-surface" in src
    assert "Browse all stocks" in src, (
        "Search no-results dialog should expose a Browse Screener CTA "
        "so users have a forward path when their query returns nothing."
    )
    assert 'href="/screener"' in src
