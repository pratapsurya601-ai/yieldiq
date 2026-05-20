"""Day-38 (2026-05-20): visual-regression baseline.

Locks in every data-testid hook added during Week-2 (Days 28-37).
Catches accidental removal — the most common cause of silent visual
regression — without requiring a Playwright/Chrome MCP install.

This is the LIGHTWEIGHT half of the visual-regression strategy:
  - Day-38a (this test):  source-text inventory of test hooks
  - Day-38b (follow-up):  Playwright pixel-diff harness for CI

The hooks here are the contract between the UI and any future
visual / e2e test suite. If any one disappears, future Playwright
selectors break — fire BEFORE that happens.
"""
from __future__ import annotations
from pathlib import Path


_F = Path(__file__).resolve().parents[2] / "frontend" / "src"


# (testid string, file path relative to frontend/src/, day-shipped)
EXPECTED_TESTIDS: list[tuple[str, str, str]] = [
    # Day-28: loading skeletons
    ("public-analysis-loading-skeleton",
     "app/(app)/analysis/[ticker]/PublicAnalysis.tsx", "28"),
    ("portfolio-panel-loading-skeleton",
     "components/home/v2/PortfolioPanel.tsx", "28"),
    ("screener-loading-skeleton",
     "app/(app)/screener/page.tsx", "28"),

    # Day-29: error states
    ("panel-fallback-",
     "app/(app)/home/page.tsx", "29"),
    ("screener-error-banner",
     "app/(app)/screener/page.tsx", "29"),
    ("login-submit-button",
     "app/auth/login/page.tsx", "29"),

    # Day-32: WatchlistButton
    ("watchlist-button",
     "components/watchlist/WatchlistButton.tsx", "32"),

    # Day-37: search no-results CTA
    ("search-no-results",
     "app/(app)/search/page.tsx", "37"),

    # Day-40: JSON-LD structured data
    ("jsonld-financialproduct",
     "app/(app)/analysis/[ticker]/JsonLd.tsx", "40"),
    ("jsonld-breadcrumb",
     "app/(app)/analysis/[ticker]/JsonLd.tsx", "40"),
]


def test_every_week2_testid_still_present():
    """One assertion per Week-2 testid. Failure message names the
    Day-XX PR that added it so the regression is immediately
    diagnosable."""
    failures: list[str] = []
    for testid, rel_path, day in EXPECTED_TESTIDS:
        path = _F / rel_path
        if not path.exists():
            failures.append(
                f"Day-{day}: file missing — {rel_path}"
            )
            continue
        src = path.read_text(encoding="utf-8")
        # Match `data-testid="<testid>"` or with backtick template
        # (panel-fallback uses a backtick template like
        # `panel-fallback-${label}`)
        needle_a = f'data-testid="{testid}"'
        needle_b = f"data-testid={{`{testid}"
        if needle_a not in src and needle_b not in src:
            failures.append(
                f"Day-{day}: data-testid='{testid}' missing from "
                f"{rel_path}. Look up PR #4xx that added it before "
                f"removing — likely Day-{day} regression."
            )
    assert not failures, "\n  ".join([""] + failures)


def test_visual_regression_strategy_documented():
    """A docs/design/ note must explain the Day-38 strategy + the
    follow-up Playwright path. Catches doc-drift if anyone changes
    the harness without updating the rationale."""
    doc = (
        Path(__file__).resolve().parents[2]
        / "docs" / "design" / "visual-regression-strategy.md"
    )
    assert doc.exists(), (
        "docs/design/visual-regression-strategy.md must document the "
        "Day-38 testid-inventory approach + the Day-38b Playwright "
        "pixel-diff follow-up."
    )
    text = doc.read_text(encoding="utf-8")
    # Required headings / phrases to confirm the doc actually
    # explains the approach (not a stub)
    assert "Day-38" in text
    assert "data-testid" in text
    assert "Playwright" in text or "Chrome MCP" in text


def test_testid_hooks_inventory_at_least_8():
    """Sanity floor — Week-2 shipped >=8 testid hooks. If this drops
    below 8, the inventory above is incomplete."""
    assert len(EXPECTED_TESTIDS) >= 8, (
        f"Inventory has {len(EXPECTED_TESTIDS)} testids — Week-2 "
        "shipped at least 8. Has one been removed from the list "
        "without removing the source?"
    )
