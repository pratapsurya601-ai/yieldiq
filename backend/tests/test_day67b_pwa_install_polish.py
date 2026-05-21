"""Day-67b (2026-05-21): PWA install banner polish.

Audit P3: 'PWA install prompt is intrusive --- overlaps portfolio
table left column. Sticks at bottom-left for the whole session.'
Same audit also flagged hardcoded bg-white as part of the theme-
consistency gap.

Two components were affected --- InstallPrompt.tsx (desktop +
mobile) and PWAInstallBanner.tsx (mobile-only, gated on views).
Both repainted with design tokens + the desktop variant moved
from bottom-left to bottom-right so it stops overlapping the
portfolio holdings table.
"""
from __future__ import annotations
from pathlib import Path


_INSTALL_PROMPT = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "components" / "InstallPrompt.tsx"
)
_PWA_BANNER = (
    Path(__file__).resolve().parents[2]
    / "frontend" / "src" / "components" / "PWAInstallBanner.tsx"
)


# ── InstallPrompt: desktop repositioning + tokens ──────────


def test_install_prompt_moved_to_bottom_right_on_desktop():
    src = _INSTALL_PROMPT.read_text(encoding="utf-8")
    # Was: sm:right-auto sm:left-4 (left-anchored on desktop)
    # Now: sm:left-auto sm:right-4 (right-anchored on desktop)
    assert "sm:left-auto sm:right-4" in src
    # Old left-anchored variant must be gone
    assert "sm:right-auto sm:left-4" not in src


def test_install_prompt_uses_design_tokens():
    src = _INSTALL_PROMPT.read_text(encoding="utf-8")
    # bg-white / text-gray replaced
    assert "bg-bg dark:bg-surface" in src
    assert "text-ink" in src
    assert "text-caption" in src
    assert "border-border" in src


def test_install_prompt_has_explicit_x_close():
    """Audit complaint: 'doesn't dismiss easily'. Add an explicit
    × close button at top-right alongside the existing 'Not now'.
    The aria-label "Dismiss install prompt" is the SSOT marker;
    the visible glyph is just the multiplication sign character."""
    src = _INSTALL_PROMPT.read_text(encoding="utf-8")
    assert "Dismiss install prompt" in src
    # The × character appears somewhere in the file (cheap proximity
    # check — exact glyph rendering is theme-detail)
    assert "×" in src


# ── PWAInstallBanner: tokens only ───────────────────────────


def test_pwa_banner_uses_design_tokens():
    src = _PWA_BANNER.read_text(encoding="utf-8")
    assert "bg-bg dark:bg-surface" in src
    assert "text-ink" in src
    assert "text-caption" in src
    # Hardcoded greys removed
    assert "text-gray-900" not in src
    assert "text-gray-500" not in src
    assert "bg-white border border-gray-200" not in src
