"""Day-81 (2026-05-22): Discover UX redesign — Option A.

Originally scoped as Day-31 (deferred from Week-2 of the audit sprint),
the Discover page after Day-68 still rendered as a vertical stack of
six rails where the highest-intent conversion surface
(ScreenerPresetsWithCounts) sat at the bottom, behind YIQ50, earnings,
methodology, sector leaders, and MarketPulse.

This redesign (Option A — hero + above-the-fold restructure) reorders
the page so reading order matches user intent:

  1. Top Pick                     (anchor)
  2. Daily Insight                (always-fresh educational tile)
  3. Screener Presets             (conversion surface — above the fold)
  4. YIQ 50 / Top-5 MoS gainers   (deeper exploration rails)
  5. Earnings + Sector Leaders    (calendar / browse)
  6. MarketPulse                  (macro context, demoted to bottom)

No backend changes. No new endpoints. No CACHE_VERSION bump. Source-text
regressions on frontend/src/app/(app)/discover/page.tsx — these fail
loudly if someone reverts the ordering or strips the design tokens.
"""
from __future__ import annotations
from pathlib import Path


_DISCOVER = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "app" / "(app)" / "discover" / "page.tsx"
)


def _src() -> str:
    assert _DISCOVER.exists(), f"Discover page not found at {_DISCOVER}"
    return _DISCOVER.read_text(encoding="utf-8")


# ── Slot markers exist ────────────────────────────────────────


def test_day81_slot_markers_present():
    """Three semantic slot markers must exist so the reading order is
    auditable from source without parsing the JSX tree."""
    src = _src()
    for slot in ("daily-insight", "screener-presets", "market-pulse"):
        assert f'data-day81-slot="{slot}"' in src, (
            f"Missing Day-81 slot marker: {slot}"
        )


# ── Reading order: presets must be above-the-fold ─────────────


def test_screener_presets_appear_before_yiq50():
    """The activation surface (Screener Presets grid) must render
    BEFORE the YIQ 50 rail in source order — that is the whole point
    of the Day-81 redesign."""
    src = _src()
    presets_idx = src.find('data-day81-slot="screener-presets"')
    yiq50_idx = src.find("{/* YieldIQ 50 */}")
    assert presets_idx != -1, "screener-presets slot not found"
    assert yiq50_idx != -1, "YieldIQ 50 section comment not found"
    assert presets_idx < yiq50_idx, (
        "Screener Presets must precede YieldIQ 50 in JSX source order "
        f"(presets at {presets_idx}, YIQ50 at {yiq50_idx})."
    )


def test_daily_insight_appears_before_screener_presets():
    """Daily Insight is the educational anchor that sits between the
    Top Pick and the Screener Presets — it must render second."""
    src = _src()
    insight_idx = src.find('data-day81-slot="daily-insight"')
    presets_idx = src.find('data-day81-slot="screener-presets"')
    assert insight_idx != -1 and presets_idx != -1
    assert insight_idx < presets_idx, (
        "Daily Insight must precede Screener Presets in source order."
    )


def test_top_pick_anchors_the_page():
    """TopPickCard is the hero anchor and must come before every
    Day-81 slot."""
    src = _src()
    top_pick_idx = src.find("<TopPickCard")
    insight_idx = src.find('data-day81-slot="daily-insight"')
    presets_idx = src.find('data-day81-slot="screener-presets"')
    assert top_pick_idx != -1, "TopPickCard JSX not found"
    assert top_pick_idx < insight_idx < presets_idx, (
        "Reading order is Top Pick -> Daily Insight -> Screener Presets."
    )


def test_market_pulse_demoted_to_bottom():
    """MarketPulse is macro context and the least time-sensitive surface
    for the per-stock workflow — it must render AFTER the screener
    presets."""
    src = _src()
    pulse_idx = src.find('data-day81-slot="market-pulse"')
    presets_idx = src.find('data-day81-slot="screener-presets"')
    assert pulse_idx != -1, "market-pulse slot not found"
    assert pulse_idx > presets_idx, (
        "MarketPulse must come after Screener Presets in source order."
    )


# ── Design tokens (Day-69/71/72/75 theme work) ────────────────


def test_design_tokens_present_in_new_sections():
    """The redesigned sections must use the canonical design tokens
    (bg-bg, dark:bg-surface, text-ink, text-caption, border-border)
    rather than hardcoded Tailwind grays — otherwise dark mode breaks."""
    src = _src()
    # Slice from the first Day-81 slot to the end so we only assert on
    # the redesigned region.
    region_start = src.find('data-day81-slot="daily-insight"')
    region = src[region_start:]
    for token in (
        "bg-bg",
        "dark:bg-surface",
        "text-ink",
        "text-caption",
        "border-border",
    ):
        assert token in region, (
            f"Design token '{token}' missing from Day-81 redesigned region."
        )


# ── No duplicate methodology / presets sections ───────────────


def test_screener_presets_rendered_exactly_once():
    """The old layout rendered ScreenerPresetsWithCounts at the bottom;
    the redesign moves it up. Both copies must not coexist."""
    src = _src()
    count = src.count("<ScreenerPresetsWithCounts />")
    assert count == 1, (
        f"<ScreenerPresetsWithCounts /> rendered {count} times — must be exactly 1."
    )


def test_no_duplicate_methodology_spotlight_section():
    """Day-68 had a 'Methodology spotlight' uppercase header. Day-81
    renames the same tile to 'Daily Insight' and moves it up. The
    legacy header must not also be present."""
    src = _src()
    # Only check the JSX body (after `return (`), so historical
    # references inside file-header comments don't trip the guard.
    jsx_start = src.find("return (")
    assert jsx_start != -1, "return ( not found"
    jsx = src[jsx_start:]
    assert "Methodology spotlight" not in jsx, (
        "Legacy 'Methodology spotlight' JSX header still present — Day-81 "
        "renamed it to 'Daily Insight'."
    )
    assert "Daily Insight" in jsx, "Daily Insight header missing in JSX."


# ── SEBI vocabulary guard ─────────────────────────────────────


def test_no_sebi_forbidden_words_in_day81_additions():
    """The vocabulary lint forbids buy/sell/hold/strong/accumulate/etc.
    Spot-check the Day-81 redesigned region for the most common
    offenders. (Project-wide lint runs separately in CI.)"""
    src = _src()
    region_start = src.find("Day-81")
    region = src[region_start:].lower()
    # Whole-word-ish guard: check each forbidden term as a substring
    # surrounded by non-letter chars. This catches accidental copy.
    import re
    for word in ("buy", "sell", "hold", "accumulate", "recommend", "outperform"):
        # Skip "hold" inside "household" etc. by requiring word boundary.
        if re.search(rf"\b{word}\b", region):
            raise AssertionError(
                f"Forbidden SEBI vocabulary '{word}' found in Day-81 region."
            )
