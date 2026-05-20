"""Day-28 (2026-05-20): regression guard for the 3 loading-skeleton
fixes that close the Day-27 UX audit's HIGH/MED loading-state items.

Source-text grep over .tsx files — no node/vitest setup needed.
"""
from __future__ import annotations
from pathlib import Path


_FRONTEND = Path(__file__).resolve().parents[2] / "frontend" / "src"
_PUBLIC_ANALYSIS = _FRONTEND / "app" / "(app)" / "analysis" / "[ticker]" / "PublicAnalysis.tsx"
_PORTFOLIO_PANEL = _FRONTEND / "components" / "home" / "v2" / "PortfolioPanel.tsx"
_SCREENER_PAGE = _FRONTEND / "app" / "(app)" / "screener" / "page.tsx"


def test_public_analysis_skeleton_mirrors_final_layout():
    """Day-27 audit HIGH issue: skeleton didn't match final layout, caused
    ~300ms CLS burst. New skeleton has verdict-pill + 4-stat dl grid +
    breadcrumb + title placeholders all matching the final container."""
    src = _PUBLIC_ANALYSIS.read_text(encoding="utf-8")
    # Outer container matches final layout
    assert "max-w-6xl mx-auto px-4 sm:px-6 py-6 sm:py-8 space-y-8" in src, (
        "Loading-state outer container must match final layout exactly "
        "(same padding, max-width, spacing) to prevent CLS on real data."
    )
    # Verdict pill placeholder
    assert "h-7 w-32 bg-subtle rounded-full" in src, (
        "Verdict pill placeholder missing — final renders a rounded-full chip."
    )
    # 4-stat dl grid (mobile 2 cols, sm+ 4 cols)
    assert 'grid grid-cols-2 sm:grid-cols-4 gap-x-4 gap-y-3' in src, (
        "4-stat grid placeholder must match final dl breakpoints exactly."
    )
    # Test hook for future visual-regression
    assert 'data-testid="public-analysis-loading-skeleton"' in src


def test_portfolio_panel_skeleton_mirrors_table_layout():
    """Day-27 audit MED issue: PortfolioPanel skeleton was generic
    horizontal bars; didn't match the 6-column holdings table.
    New skeleton has header band + table with th row + 6 placeholder
    rows × 6 cells."""
    src = _PORTFOLIO_PANEL.read_text(encoding="utf-8")
    # Outer container matches final
    assert "bg-surface border border-border rounded-2xl overflow-hidden" in src
    # Table with th row + 6 td columns
    assert "<table className=\"w-full\">" in src, (
        "Skeleton must render an actual <table> (not just divs) so layout "
        "metrics match the final render."
    )
    # 6 column count matches the final Th declarations (ticker / price / today / FV / MoS / return)
    # Heuristic: count `key={i}` in the th-row placeholder
    skel_block = src[src.find("function Skeleton()"):src.find("export default function PortfolioPanel")]
    th_loop_count = skel_block.count("[0, 1, 2, 3, 4, 5]")
    assert th_loop_count >= 2, (
        "Skeleton should iterate 6 columns at least twice (th row + each "
        "tr row). Found %d loops — verify column count matches final table."
        % th_loop_count
    )
    # Test hook
    assert 'data-testid="portfolio-panel-loading-skeleton"' in src


def test_screener_suspense_fallback_renders_presets():
    """Day-27 audit MED issue: Suspense fallback was a generic spinner.
    Replaced with a static skeleton that eagerly references
    SCREENER_PRESETS so the first paint shows the screener identity
    (title + preset cards) instead of a blank spinner."""
    src = _SCREENER_PAGE.read_text(encoding="utf-8")
    # Old generic spinner gone
    assert "animate-spin rounded-full border-2 border-blue-600" not in src, (
        "Old generic Suspense spinner still present — should be replaced "
        "by ScreenerSkeleton."
    )
    # New skeleton component defined
    assert "function ScreenerSkeleton()" in src
    # Uses SCREENER_PRESETS (eager import already at top of file)
    assert "SCREENER_PRESETS.map" in src, (
        "Skeleton must eagerly iterate SCREENER_PRESETS so preset labels "
        "render during the Suspense bailout."
    )
    # Test hook
    assert 'data-testid="screener-loading-skeleton"' in src
    # Suspense wires to the new fallback
    assert "<Suspense fallback={<ScreenerSkeleton />}>" in src


def test_no_generic_loader_left_in_three_pages():
    """Sanity sweep: none of the 3 affected pages should still have a
    generic 'Loading…' string or animate-spin without context."""
    for path in (_PUBLIC_ANALYSIS, _PORTFOLIO_PANEL, _SCREENER_PAGE):
        src = path.read_text(encoding="utf-8")
        # Generic 'Loading…' text without surrounding structure
        assert "Loading…" not in src or "skeleton" in src.lower(), (
            f"{path.name}: 'Loading…' string present without a skeleton "
            "structure. Day-28 replaced these with layout-matching skeletons."
        )
