# backend/tests/test_day74_daily_insight_rotation.py
"""Static checks for Day-74 Daily Insight rotation.

Audit 2026-05-20 flagged the Daily Insight slot as "same string for
weeks — still a screener hint". Day-74 converts it from a static
string to a 7-tip rotation indexed by day-of-year mod 7 (same pattern
as the Discover methodology spotlight). See
``frontend/src/components/home/v2/DailyInsightCard.tsx``.

This test runs in the backend pytest harness (we don't have a JS test
runner wired into CI yet — Tier-3 task #32 covers that) and parses
the .tsx source as text. It pins:

  * The tip array has exactly 7 entries (one per day of the week).
  * Each tip has both ``text`` and ``href`` fields.
  * No SEBI-banned vocabulary appears in any tip body or CTA.
  * The rotation helper uses day-of-year-mod-7 (matches the Discover
    page pattern at discover/page.tsx:pickTodayTip).
"""
from __future__ import annotations

import re
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
DAILY_INSIGHT_TSX = (
    REPO_ROOT
    / "frontend"
    / "src"
    / "components"
    / "home"
    / "v2"
    / "DailyInsightCard.tsx"
)

# SEBI Research Analyst Regulations 2014 + 2025 amendments restrict
# unregistered research from using directional / outcome-claiming
# language. YieldIQ is a SaaS analytical tool, not a registered RA,
# so the surface copy must stay neutral. This list is the same one
# enforced elsewhere in the codebase (see Day-65 dividend rewrite).
SEBI_BANNED_WORDS = [
    "buy",
    "sell",
    "hold",
    "strong buy",
    "strong sell",
    "accumulate",
    "recommend",
    "outperform",
    "underperform",
]


@pytest.fixture(scope="module")
def tsx_source() -> str:
    assert DAILY_INSIGHT_TSX.exists(), (
        f"DailyInsightCard.tsx not found at {DAILY_INSIGHT_TSX}"
    )
    return DAILY_INSIGHT_TSX.read_text(encoding="utf-8")


def _extract_tip_texts(src: str) -> list[str]:
    """Pull each ``text: "..."`` literal from the DAILY_TIPS array.

    Handles multi-line string literals (the tips use indented
    `text:\n    "..."` form for readability)."""
    # Match `text:` optional whitespace/newline, then a double-quoted
    # string that may contain escaped quotes. DOTALL so . matches \n.
    pattern = re.compile(r"text\s*:\s*\"((?:[^\"\\]|\\.)*)\"", re.DOTALL)
    return pattern.findall(src)


def _extract_cta_texts(src: str) -> list[str]:
    pattern = re.compile(r"cta\s*:\s*\"((?:[^\"\\]|\\.)*)\"", re.DOTALL)
    return pattern.findall(src)


def _extract_hrefs(src: str) -> list[str]:
    pattern = re.compile(r"href\s*:\s*\"([^\"]+)\"")
    return pattern.findall(src)


def test_daily_tips_array_has_seven_entries(tsx_source: str) -> None:
    tips = _extract_tip_texts(tsx_source)
    assert len(tips) == 7, (
        f"Daily Insight expects 7 tips (one per weekday), got {len(tips)}: "
        f"{[t[:40] for t in tips]}"
    )


def test_each_tip_has_href_and_cta(tsx_source: str) -> None:
    tips = _extract_tip_texts(tsx_source)
    hrefs = _extract_hrefs(tsx_source)
    ctas = _extract_cta_texts(tsx_source)
    assert len(hrefs) >= len(tips), (
        f"Found {len(tips)} tip texts but only {len(hrefs)} href fields"
    )
    assert len(ctas) == len(tips), (
        f"Found {len(tips)} tip texts but {len(ctas)} cta fields"
    )


def test_no_sebi_banned_vocabulary_in_tip_bodies(tsx_source: str) -> None:
    tips = _extract_tip_texts(tsx_source)
    ctas = _extract_cta_texts(tsx_source)
    surface_strings = tips + ctas
    assert surface_strings, "no tips/CTAs extracted — parser regression"

    for s in surface_strings:
        lower = s.lower()
        for banned in SEBI_BANNED_WORDS:
            # Use word-boundary matching so "household" doesn't trip
            # "hold" and "rebuy" doesn't trip "buy".
            if re.search(rf"\b{re.escape(banned)}\b", lower):
                pytest.fail(
                    f"SEBI-banned word '{banned}' found in Daily Insight tip: "
                    f"{s!r}"
                )


def test_rotation_uses_day_of_year_mod_7(tsx_source: str) -> None:
    """Rotation must be `dayOfYear % DAILY_TIPS.length` (or `% 7`),
    matching the Discover page methodology spotlight pattern. Drift
    here (e.g. switching to `% TIPS.length` where TIPS is the wrong
    array) is how rotations silently break."""
    # Look for `dayOfYear % DAILY_TIPS.length` or `dayOfYear % 7`.
    pattern = re.compile(r"dayOfYear\s*%\s*(DAILY_TIPS\.length|7)")
    assert pattern.search(tsx_source), (
        "Daily Insight rotation must use `dayOfYear % DAILY_TIPS.length` "
        "(or `% 7`). Confirm the pickTodayTip helper still matches the "
        "Discover page pickTodayTip pattern."
    )


def test_old_static_hint_string_removed(tsx_source: str) -> None:
    """Regression guard: the audit-flagged static string must not
    survive verbatim in the component."""
    bad = "Use the screener to find stocks with MoS > 20%"
    assert bad not in tsx_source, (
        "Old static Daily Insight string still present — Day-74 rotation "
        "did not replace it."
    )
