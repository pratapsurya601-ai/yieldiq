"""Day-34 (2026-05-20): regression guards for the verdict-chip
consolidation. 3 components (concall, PeerComparisonCard,
ConvictionRing) previously duplicated VERDICT_COLORS-style class
strings / hex literals inline. Now they all import from
lib/constants.ts.

Source-text grep — same pattern as Days 28-33.
"""
from __future__ import annotations
from pathlib import Path


_F = Path(__file__).resolve().parents[2] / "frontend" / "src"
_CONSTANTS = _F / "lib" / "constants.ts"
_CONCALL = _F / "app" / "(app)" / "concall" / "page.tsx"
_PEER_CARD = _F / "components" / "analysis" / "PeerComparisonCard.tsx"
_CONVICTION = _F / "components" / "analysis" / "ConvictionRing.tsx"
_VERDICT_CHIP = _F / "components" / "analysis" / "VerdictChip.tsx"


# ── New helpers in constants.ts ────────────────────────────


def test_constants_exports_verdict_classes_helper():
    src = _CONSTANTS.read_text(encoding="utf-8")
    assert "export function verdictClassesWithDark(" in src, (
        "verdictClassesWithDark() helper missing from lib/constants.ts. "
        "This is the canonical entry point for verdict chip styling."
    )


def test_constants_exports_mos_and_sentiment_helpers():
    src = _CONSTANTS.read_text(encoding="utf-8")
    assert "export function mosToneClass(" in src
    assert "export function sentimentToneClass(" in src


def test_verdict_dark_classes_are_static_strings():
    """Tailwind purge depends on STATIC class strings. The dark-mode
    counterpart map MUST contain literal `dark:bg-blue-950/40` etc.
    rather than `dark:bg-${family}-950/40` interpolation."""
    src = _CONSTANTS.read_text(encoding="utf-8")
    # Static literals must be present so Tailwind's purge step sees them
    for cls in (
        "dark:bg-blue-950/40",
        "dark:bg-amber-950/40",
        "dark:bg-red-950/40",
        "dark:text-blue-300",
        "dark:text-amber-300",
        "dark:text-red-300",
    ):
        assert cls in src, (
            f"Static class '{cls}' missing — required for Tailwind purge "
            "to include it in production CSS."
        )
    # And the dangerous dynamic form must NOT be there
    assert "dark:bg-${family}" not in src, (
        "Dynamic class interpolation present — Tailwind purge would "
        "strip these from the production build."
    )


# ── Component dedup ────────────────────────────────────────


def test_concall_uses_sentiment_helper():
    src = _CONCALL.read_text(encoding="utf-8")
    assert 'from "@/lib/constants"' in src
    assert "sentimentToneClass" in src
    # Old hardcoded palette removed
    assert 'if (s === "positive") return "bg-green-50' not in src, (
        "Old inline palette in concall sentimentColor() still present."
    )


def test_peer_comparison_uses_canonical_helper():
    src = _PEER_CARD.read_text(encoding="utf-8")
    assert 'import { verdictClassesWithDark } from "@/lib/constants"' in src
    # The local 8-line palette body should be gone — only a 1-line
    # delegate function remains
    assert (
        'if (k === "undervalued") return "bg-green-50 text-green-700'
        not in src
    ), (
        "PeerComparisonCard still carries the old green-50 inline palette. "
        "Should now delegate to verdictClassesWithDark()."
    )


def test_conviction_ring_uses_verdict_colors_hex():
    src = _CONVICTION.read_text(encoding="utf-8")
    assert "import { SCORE_COLOR, SCORE_GRADE, VERDICT_COLORS }" in src
    assert "VERDICT_COLORS.undervalued.hex" in src
    assert "VERDICT_COLORS.overvalued.hex" in src
    assert "VERDICT_COLORS.avoid.hex" in src
    # Old hardcoded "#185FA5" should not appear in the confidenceColor
    # line specifically. (Other parts of the file may still use other
    # hex literals for the score gradient — leave those alone.)
    # Find the confidenceColor assignment
    idx = src.find("confidenceColor")
    snippet = src[idx:idx + 400] if idx > 0 else ""
    assert "#185FA5" not in snippet, (
        "ConvictionRing confidenceColor still uses hardcoded #185FA5 hex. "
        "Should reference VERDICT_COLORS.undervalued.hex."
    )


def test_verdict_chip_still_uses_canonical_source():
    """Regression guard: VerdictChip (the canonical chip component)
    must continue importing VERDICT_COLORS — if anyone changes it to
    a different palette, this fires."""
    src = _VERDICT_CHIP.read_text(encoding="utf-8")
    assert 'import { VERDICT_COLORS } from "@/lib/constants"' in src
    assert "VERDICT_COLORS[verdict]" in src
