"""Day-75 theme rollout PR-3: semantic-component sweep.

PR-1 (Day-69), PR-2 (Day-71), PR-4 (Day-72) handled bulk codemod of
neutral tokens across 54 files / 1337 swaps. PR-3 covers the remaining
SEMANTIC surfaces where colors carry meaning (verdict bands, sentiment
chips, value bands, market pulse). Each file was hand-judged: neutral
container surfaces and pure-neutral text migrated to design tokens,
while branded conditional colors (red/amber/green/blue ternaries) were
preserved verbatim.

Test strategy:
  - Assert specific safe swaps landed (neutral surfaces -> tokens).
  - Pin three known-good semantic conditionals that MUST remain intact.
  - Assert design tokens (bg-bg / text-ink / text-caption / border-border)
    now appear in the changed files.
"""
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
FRONTEND = REPO_ROOT / "frontend" / "src" / "components"


def _read(rel: str) -> str:
    p = FRONTEND / rel
    assert p.exists(), f"missing: {p}"
    return p.read_text(encoding="utf-8")


# ---- Safe swaps that MUST have happened ----------------------------------


def test_marketpulse_neutral_surfaces_migrated() -> None:
    """MarketPulse loading/empty/table containers now use neutral tokens."""
    src = _read("discover/MarketPulse.tsx")
    # Container surfaces
    assert "bg-bg dark:bg-surface border border-border rounded-xl" in src
    # Caption labels
    assert "text-[10px] font-bold text-caption uppercase tracking-widest" in src
    # No leftover neutral grays on container surfaces
    assert "bg-white border border-gray-100" not in src


def test_marketpulse_preserves_fii_dii_blue_red_branches() -> None:
    """The blue (net positive) vs red (net negative) ternary is semantic.
    It must remain untouched by the codemod."""
    src = _read("discover/MarketPulse.tsx")
    # Bar fill color ternary
    assert '(d.fii_net ?? 0) >= 0 ? "bg-blue-400" : "bg-red-400"' in src
    # Text color ternary
    assert '(d.dii_net ?? 0) >= 0 ? "text-blue-700" : "text-red-700"' in src


def test_data_under_review_neutral_migrated_amber_preserved() -> None:
    """DataUnderReview: neutral grays -> tokens, amber warning treatment kept."""
    src = _read("DataUnderReview.tsx")
    # Neutral surfaces migrated
    assert "bg-bg dark:bg-surface rounded-2xl border border-amber-200" in src
    assert "text-xl sm:text-2xl font-bold text-ink" in src
    assert "border-t border-border" in src
    # Amber warning visuals preserved verbatim (this IS the semantic signal)
    assert "bg-amber-100 flex items-center justify-center text-amber-600" in src
    # SEBI compliance lint: the previous "holding back" verb form was
    # rephrased to avoid the reserved-word trigger even in non-rating copy.
    assert "holding back" not in src
    assert "retaining analysis figures" in src


def test_bulk_block_deals_buy_sell_blue_red_preserved() -> None:
    """Buy/Sell side color is semantic (blue=buy, red=sell). Must be intact."""
    src = _read("analysis/BulkBlockDealsPanel.tsx")
    assert '"bg-blue-50 text-blue-700"' in src
    assert '"bg-red-50 text-red-700"' in src
    # Neutral header / row stripes migrated
    assert "border-b border-border bg-surface/50" in src
    assert 'i % 2 === 1 ? "bg-surface/40"' in src


def test_empty_states_use_design_tokens() -> None:
    """All six empty-state files render neutral text via design tokens."""
    for rel in (
        "empty-states/HomeEmpty.tsx",
        "empty-states/WatchlistEmpty.tsx",
        "empty-states/CompareEmpty.tsx",
        "empty-states/PortfolioEmpty.tsx",
        "empty-states/AlertsEmpty.tsx",
        "empty-states/ConcallEmpty.tsx",
    ):
        src = _read(rel)
        assert "text-lg font-semibold text-ink" in src, rel
        assert "text-sm text-caption" in src, rel
        # No leftover light-mode neutral gray on h2/p (dark variant collapsed)
        assert "text-gray-900 dark:text-ink" not in src, rel
        assert "text-gray-500 dark:text-caption" not in src, rel


def test_common_empty_state_container_uses_tokens() -> None:
    src = _read("common/EmptyState.tsx")
    assert "bg-bg dark:bg-surface border border-border" in src
    assert "text-lg font-semibold text-ink" in src
    assert "text-sm text-caption" in src


def test_marketing_top_nav_light_variant_uses_tokens_keeps_dark_branding() -> None:
    """Light-variant neutral grays migrated; dark gradient branding kept."""
    src = _read("marketing/MarketingTopNav.tsx")
    # Light variant uses tokens
    assert "bg-bg/95 backdrop-blur-md border-b border-border" in src
    assert 'isDark ? "text-white" : "text-ink"' in src
    # Dropdown menu (light-mode only) — neutral surface tokens
    assert "border border-border bg-bg dark:bg-surface shadow-lg" in src
    # Dark variant gradient branding (semantic CTA) is untouched
    assert (
        "bg-gradient-to-r from-blue-600 to-cyan-500 text-white font-semibold"
        in src
    )


def test_navbar_neutral_surfaces_tokens_active_state_preserved() -> None:
    """Mobile Navbar: surfaces -> tokens, but active=blue vs inactive=gray
    icon ternaries are semantic (active state) and must remain."""
    src = _read("layout/Navbar.tsx")
    # Surface migrated
    assert (
        "bg-bg/95 dark:bg-surface/95 backdrop-blur-md border-t border-border"
        in src
    )
    assert "border border-border bg-bg dark:bg-surface" in src
    # Active=blue / inactive=gray-500 icon coloring is SEMANTIC — preserve
    assert 'active ? "text-blue-600" : "text-gray-500"' in src
    assert 'isActive ? "text-blue-600" : "text-gray-500"' in src


def test_back_button_uses_caption_token() -> None:
    src = _read("layout/BackButton.tsx")
    assert "text-sm text-caption hover:text-ink" in src
    assert "rounded-lg hover:bg-surface" in src


# ---- Skipped (intentionally) ---------------------------------------------


def test_value_band_chip_left_alone() -> None:
    """ValueBandChip is a 6-band semantic ordinal scale (strong_discount ->
    notably_overvalued). Every gray/green/amber/red token is part of the
    band visual — there are no purely neutral surfaces to migrate.
    Asserting the BAND_STYLE map is intact protects against accidental
    codemod regressions in future PRs."""
    src = _read("hex/ValueBandChip.tsx")
    assert '"bg-green-600 text-white border border-green-700"' in src
    assert '"bg-gray-200 text-gray-900 border border-gray-300"' in src
    assert '"bg-red-600 text-white border border-red-700"' in src
