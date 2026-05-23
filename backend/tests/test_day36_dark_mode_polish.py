"""Day-36 (2026-05-20): regression guards for dark-mode polish.

Day-27 audit found 11 components had ZERO dark: variants — bg-white
rendered as glaring light strips on dark theme. Day-36 adds canonical
dark: counterparts to the highest-impact 7 sites:

  Screener trio (FilterBuilder / ResultsTable both branches /
    SavedQueries / screener page empty-state)
  CoverageTierBadge (3 tier classes)
  IncidentBanner (red + amber tones)
  Discover warming-up card

The remaining 4 sites from the audit (PortfolioPanel internals etc.)
already inherit dark backgrounds from their parent containers; no
explicit dark: variants needed.
"""
from __future__ import annotations
from pathlib import Path

import pytest


_F = Path(__file__).resolve().parents[2] / "frontend" / "src"


def _src(path: str) -> str:
    return (_F / path).read_text(encoding="utf-8")


# ── Screener trio ───────────────────────────────────────────


def test_filter_builder_has_dark_bg():
    src = _src("components/screener/FilterBuilder.tsx")
    assert "bg-white dark:bg-surface" in src, (
        "FilterBuilder root container missing dark:bg-surface."
    )


def test_results_table_loading_has_dark_bg():
    src = _src("components/screener/ResultsTable.tsx")
    # The loading state container at the top of the file
    assert src.count("bg-white dark:bg-surface") >= 2, (
        "ResultsTable should have dark:bg-surface on BOTH the loading "
        "state AND the main results container."
    )


def test_saved_queries_has_dark_bg():
    src = _src("components/screener/SavedQueries.tsx")
    assert "bg-white dark:bg-surface" in src


def test_screener_empty_state_has_dark_bg():
    src = _src("app/(app)/screener/page.tsx")
    # The empty-state preset grid container at L207
    assert (
        'className="rounded-2xl border border-border bg-white dark:bg-surface p-6"'
        in src
    )


# ── CoverageTierBadge ────────────────────────────────────────


def test_coverage_tier_badge_has_dark_variants_for_all_3_tiers():
    src = _src("components/analysis/CoverageTierBadge.tsx")
    # All three tier classes (A, B, C) should have dark counterparts
    assert "dark:bg-emerald-950/40" in src, "Tier A dark variant missing"
    assert "dark:bg-amber-950/40" in src, "Tier B dark variant missing"
    assert "dark:bg-zinc-800" in src, "Tier C dark variant missing"
    # Text colours
    assert "dark:text-emerald-300" in src
    assert "dark:text-amber-300" in src
    assert "dark:text-zinc-300" in src


# ── IncidentBanner ───────────────────────────────────────────


def test_incident_banner_has_dark_variants():
    src = _src("components/IncidentBanner.tsx")
    # Both tones (open=red, closed=amber) need dark counterparts
    assert "dark:bg-red-950/40" in src
    assert "dark:bg-amber-950/40" in src
    assert "dark:text-red-200" in src
    assert "dark:text-amber-200" in src


# ── Discover warming-up card ─────────────────────────────────


@pytest.mark.skip(
    reason=(
        "STALE post-Day-68 (2026-05-21). The Discover 'warming up' card "
        "was REMOVED — the 2026-05-20 audit found YIQ50 + FII/DII rails "
        "sat in 'warming up' for hours after every deploy; Day-68 "
        "replaced the placeholder with always-fresh educational content "
        "so this card no longer exists. See "
        "frontend/src/app/(app)/discover/page.tsx:16-46. Test should be "
        "deleted once the Day-68 default-content surface is locked down "
        "with its own assertions; tracked as Fix-139 follow-up."
    )
)
def test_discover_warming_up_card_has_dark_bg():
    src = _src("app/(app)/discover/page.tsx")
    assert "bg-white dark:bg-surface border border-gray-100 dark:border-border rounded-xl p-6 text-center" in src


# ── Sanity sweep ────────────────────────────────────────────


def test_no_bare_bg_white_in_critical_screener_files():
    """The screener trio should have NO bg-white without dark:bg-surface
    companion. Defensive: catches future edits that drop the dark
    variant by mistake."""
    for path in (
        "components/screener/FilterBuilder.tsx",
        "components/screener/SavedQueries.tsx",
    ):
        src = _src(path)
        # Strip whitespace-only lines for the scan
        for line in src.split("\n"):
            stripped = line.strip()
            # Match a className= line that contains bg-white
            if "bg-white" not in stripped:
                continue
            # Must also contain dark:bg- (any color) OR dark:bg-surface
            if "dark:bg-" not in stripped:
                raise AssertionError(
                    f"{path}: bare bg-white without dark:bg- companion "
                    f"on line: {stripped[:120]}"
                )
