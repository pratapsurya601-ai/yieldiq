"""Day-68 (2026-05-21): Discover page default content fix.

The 2026-05-20 audit found the Discover page rendered an empty
"YieldIQ 50 is warming up" card for new visitors — a 6-week-old
placeholder that killed first-impression activation.

Fix (frontend-only, no CACHE_VERSION bump): when YIQ50 is cold, the
empty card is REPLACED by real default content:

  1. Top 5 MoS gainers — pulled from /api/v1/screener/run?min_mos=15
     and sorted by margin_of_safety desc client-side (since the
     screener's native sort is by PE).
  2. Earnings reporters today — pulled from
     /api/v1/public/earnings-calendar?days=1 (the same endpoint that
     powers the home "Earnings this week" strip).
  3. Methodology spotlight — a 7-entry client-side tip array that
     rotates by day-of-year so the section is always fresh.

These tests are source-text regressions on
frontend/src/app/(app)/discover/page.tsx. They will fail loudly if
someone reintroduces the "warming up" placeholder or removes a
default-content section.
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


# ── Placeholder copy is gone ──────────────────────────────────


def test_yiq50_warming_up_placeholder_is_replaced():
    """The user-visible 'YieldIQ 50 is warming up' headline must be
    gone — replaced by the Top 5 MoS gainers default-content card.
    Comment references in code header are OK; the rendered string is not."""
    src = _src()
    # The exact rendered placeholder copy must not appear in any JSX node.
    assert "YieldIQ 50 is warming up</p>" not in src, (
        "The 'YieldIQ 50 is warming up' placeholder card is still rendered."
    )


def test_old_warming_up_helper_copy_is_gone():
    src = _src()
    # The helper line under the placeholder ("Daily shortlist refreshes
    # overnight — check back tomorrow morning.") was the second tell-tale
    # phrase of the old empty card.
    assert "check back tomorrow morning" not in src, (
        "Legacy 'check back tomorrow morning' copy still present — "
        "the warming-up empty card was not fully replaced."
    )


# ── New section markers are present ───────────────────────────


def test_top_mos_gainers_section_present():
    src = _src()
    assert "Top 5 MoS gainers" in src


def test_earnings_reporters_section_present():
    src = _src()
    assert "Earnings reporters today" in src


def test_methodology_spotlight_section_present():
    src = _src()
    assert "Methodology spotlight" in src


# ── Wired to live data, not hard-coded ────────────────────────


def test_imports_runScreener_from_api():
    src = _src()
    assert 'from "@/lib/api"' in src, (
        "Discover page must import client functions from @/lib/api"
    )
    assert "runScreener" in src, (
        "Top 5 MoS gainers must call runScreener (live screener data)"
    )


def test_earnings_endpoint_wired():
    src = _src()
    # The earnings list calls the public earnings-calendar endpoint.
    assert "/api/v1/public/earnings-calendar" in src


def test_mos_gainers_sorted_desc():
    """Backend's screener default sort is by PE asc — the page must
    re-sort by margin_of_safety desc to honour the 'top MoS gainers'
    promise. Without this, the section would be misleading."""
    src = _src()
    assert "b.margin_of_safety - a.margin_of_safety" in src


def test_min_mos_filter_is_15():
    """min_mos=15 keeps borderline names out of the default content."""
    src = _src()
    assert "min_mos: 15" in src


# ── Methodology tip array sanity ──────────────────────────────


def test_methodology_tips_array_has_at_least_seven_entries():
    """Seven tips rotate daily — fewer entries means repeats within
    a single calendar week, which defeats the 'always fresh' promise.
    Count `title:` keys inside METHODOLOGY_TIPS (a robust proxy)."""
    src = _src()
    assert "METHODOLOGY_TIPS" in src
    # Slice the array literal so we don't accidentally count tip
    # references elsewhere in the file.
    # Anchor on the array opening bracket (skip the type annotation
    # `{ title: string; ... }[]` that precedes the literal).
    start = src.find("METHODOLOGY_TIPS")
    open_bracket = src.find("= [", start)
    assert open_bracket > start, "METHODOLOGY_TIPS array literal not found"
    end = src.find("\n]", open_bracket)
    assert end > open_bracket, "METHODOLOGY_TIPS array close not found"
    block = src[open_bracket:end]
    title_count = block.count("title:")
    assert title_count >= 7, (
        f"METHODOLOGY_TIPS has only {title_count} entries; need >= 7 "
        "for a 7-day rotation."
    )


def test_methodology_rotation_is_deterministic():
    """Rotation must be stable within a day (day-of-year mod 7) so
    a user refreshing twice doesn't see two different tips."""
    src = _src()
    assert "dayOfYear" in src
    assert "METHODOLOGY_TIPS.length" in src


# ── Design-token usage (Day-36 dark mode discipline) ──────────


def test_new_cards_use_design_tokens():
    """The new default-content cards must use bg-bg/bg-surface/text-ink/
    text-caption/border-border tokens (Day-36 dark-mode standard), not
    raw bg-white/text-gray-* like the legacy warming-up card did."""
    src = _src()
    # At least one occurrence of each token must appear after the
    # Day-68 comment marker (defensive: ensure the new code actually
    # uses tokens, not just that the file has tokens elsewhere).
    anchor = src.find("Day-68")
    assert anchor >= 0, "Day-68 marker comment missing"
    tail = src[anchor:]
    for tok in ("bg-bg", "text-ink", "text-caption", "border-border"):
        assert tok in tail, f"design token {tok!r} missing in Day-68 code"
