"""Day-30 (2026-05-20): regression guards for 4 mobile-breakpoint
fixes from the Day-27 audit. AnalysisHero:401 (2-col by design at
375px) was intentionally skipped.

Source-text grep over .tsx files.
"""
from __future__ import annotations
from pathlib import Path


_F = Path(__file__).resolve().parents[2] / "frontend" / "src"
_CONCALL = _F / "app" / "(app)" / "concall" / "page.tsx"
_ANALYSIS_BODY = _F / "app" / "(app)" / "analysis" / "[ticker]" / "AnalysisBody.tsx"
_PORTFOLIO = _F / "app" / "(app)" / "portfolio" / "page.tsx"
_RESULTS_TABLE = _F / "components" / "screener" / "ResultsTable.tsx"


def test_concall_uses_mobile_first_grid():
    """Day-27 audit HIGH: concall:135 was `grid-cols-2` with no `sm:`
    fallback — squashed inputs to ~150px on 375px phones."""
    src = _CONCALL.read_text(encoding="utf-8")
    assert "grid grid-cols-1 sm:grid-cols-2 gap-3 mb-4" in src
    # Old version eliminated
    bad = src.count('"grid grid-cols-2 gap-3 mb-4"')
    assert bad == 0, (
        f"Old 'grid grid-cols-2' (no sm: fallback) still present "
        f"{bad}× — Day-30 should have replaced all of them."
    )


def test_analysis_body_scenario_grid_mobile_first():
    """Day-27 audit HIGH: AnalysisBody:688 scenario block was
    grid-cols-3 — squashed Bear/Base/Bull to ~100px on phones."""
    src = _ANALYSIS_BODY.read_text(encoding="utf-8")
    assert "grid grid-cols-1 sm:grid-cols-3 gap-3" in src
    # Verify the specific Scenario Analysis block (avoid false-positive
    # from other grid-cols-3 instances)
    sa_idx = src.find("Scenario Analysis")
    assert sa_idx > 0
    next_block = src[sa_idx:sa_idx + 400]
    assert "grid-cols-1 sm:grid-cols-3" in next_block, (
        "Scenario Analysis grid not using mobile-first breakpoint."
    )


def test_portfolio_summary_grid_mobile_first():
    """Day-27 audit HIGH: portfolio:246 holdings summary was
    grid-cols-3 — squashed Invested / Current Value / P&L."""
    src = _PORTFOLIO.read_text(encoding="utf-8")
    assert "grid grid-cols-1 sm:grid-cols-3 gap-3 mt-4 pt-4 border-t border-white/20 text-xs" in src


def test_results_table_min_width_forces_horizontal_scroll():
    """Day-27 audit MED: ResultsTable had overflow-x-auto wrapper but
    the inner table collapsed to viewport width — needed min-w-[800px]
    to force horizontal scroll on mobile."""
    src = _RESULTS_TABLE.read_text(encoding="utf-8")
    assert 'className="w-full min-w-[800px] text-sm"' in src, (
        "ResultsTable inner <table> missing min-w-[800px]. Without it, "
        "the overflow-x-auto wrapper has nothing to scroll on mobile."
    )


def test_no_hardcoded_grid_cols_3_without_breakpoint_in_main_pages():
    """Sanity sweep: none of the 3 main pages we edited should still
    contain `grid-cols-3` className WITHOUT a `sm:` / `md:` companion.
    Permits prose mentions inside comments."""
    for path in (_CONCALL, _ANALYSIS_BODY, _PORTFOLIO):
        src = path.read_text(encoding="utf-8")
        for line in src.split("\n"):
            # Only inspect lines that LOOK like JSX className strings
            if "className=" not in line and 'class="' not in line:
                continue
            if "grid-cols-3" not in line:
                continue
            if "sm:grid-cols-3" in line or "md:grid-cols-3" in line or "lg:grid-cols-3" in line:
                continue
            assert False, (
                f"{path.name}: bare grid-cols-3 without responsive "
                f"prefix on className line: {line.strip()[:120]}"
            )
