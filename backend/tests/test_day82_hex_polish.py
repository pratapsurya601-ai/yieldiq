"""Day-82 (2026-05-22): Hex visualization polish — Option E (empty state).

Tier-3 #35: the Hex (and its newer Prism variant) is YieldIQ's signature
brand-defining visualization. The 2026-05-20 audit specifically called
out the Prism as "visually striking and genuinely differentiated" and
asked for continued investment.

This polish targets the *informativeness* of the empty / thin-data
state — the PARADEEP-class case where a ticker has fewer than 6 of the
6 pillar inputs available. Previously the Hex collapsed to a near-grey
hexagon with no copy explaining why; users could not distinguish "the
stock scores poorly" from "we don't have data for this stock yet".

The polish adds:

  * A coverage note above the legend: "Data coverage: N of 6 inputs
    available · Limited: <pillar names>". Rendered only when at least
    one axis is `data_limited`.

  * A small "Limited" tag inline on each axis chip that is data-limited,
    so the dim score reads as intentional.

  * A coverage suffix on the SVG aria-label / <title> so screen readers
    (and the visible browser tooltip on hover) say "— data limited:
    N of 6 inputs available" instead of just the overall score.

The polygon, gradients, vertex pills, and entry animation are
untouched — this is polish, not a redesign.

Source-text guards only — no Redis / no DB / no FastAPI bootstrap.
"""
from __future__ import annotations

from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2]
_HEX = _ROOT / "frontend" / "src" / "components" / "hex" / "Hex.tsx"
_HEX_LEGEND = _ROOT / "frontend" / "src" / "components" / "hex" / "HexLegend.tsx"


def _read(p: Path) -> str:
    assert p.exists(), f"required source file missing: {p}"
    return p.read_text(encoding="utf-8")


# ---------------------------------------------------------------------
# HexLegend: coverage note + per-axis Limited tag
# ---------------------------------------------------------------------


def test_hex_legend_emits_coverage_note_testid() -> None:
    """Coverage note must carry a stable data-testid so the frontend
    smoke test (and any future visual-regression baseline) can target
    it without selecting on copy that may evolve."""
    src = _read(_HEX_LEGEND)
    assert 'data-testid="hex-coverage-note"' in src, (
        "HexLegend must render a coverage note with the "
        "data-testid='hex-coverage-note' anchor."
    )


def test_hex_legend_coverage_copy_uses_inputs_available_phrasing() -> None:
    """Day-82 contract: copy reads 'N of 6 inputs available'. Locked so
    a future cleanup can't quietly soften it to 'partial data'."""
    src = _read(_HEX_LEGEND)
    assert "inputs available" in src
    assert "{coverage.available} of {coverage.total}" in src, (
        "Coverage line must show the exact available/total counts so a "
        "PARADEEP-class ticker reads as e.g. '3 of 6 inputs available'."
    )


def test_hex_legend_coverage_lists_missing_axis_names() -> None:
    """Listing the missing axes by name is the whole point — without
    them the note is no more informative than the old grey hexagon."""
    src = _read(_HEX_LEGEND)
    assert "missingLabels" in src, (
        "HexLegend must derive a human label for the limited axes."
    )
    assert '"Limited: "' in src or "Limited: " in src, (
        "Coverage note must prefix the missing-axis list with 'Limited:'."
    )


def test_hex_legend_renders_per_axis_limited_tag() -> None:
    """Each data-limited axis chip carries an inline 'Limited' tag so
    the dim score doesn't read as a render bug."""
    src = _read(_HEX_LEGEND)
    assert 'data-testid="hex-axis-limited-tag"' in src
    # JSX whitespace: locate the Limited tag block and assert the
    # literal copy "Limited" appears between its >...< text node.
    anchor = 'data-testid="hex-axis-limited-tag"'
    idx = src.find(anchor)
    assert idx > 0
    tail = src[idx: idx + 600]
    assert "Limited" in tail, (
        "Per-axis tag copy is 'Limited' (Title Case) — locked."
    )


def test_hex_legend_uses_design_tokens_not_hardcoded_colors() -> None:
    """Polish must use design tokens — no hardcoded hex / rgb in the
    new coverage UI."""
    src = _read(_HEX_LEGEND)
    # The coverage block must reference token vars.
    assert "var(--color-warning)" in src, (
        "Coverage note + Limited tag must drive their accent off "
        "--color-warning, not a hardcoded amber."
    )
    assert "var(--color-surface)" in src
    assert "var(--color-border)" in src


def test_hex_legend_avoids_sebi_banned_vocab() -> None:
    """No buy/sell/hold/strong/recommend leakage in the new coverage UI."""
    src = _read(_HEX_LEGEND)
    banned = (
        " buy ", " sell ", " hold ", "accumulate", "recommend",
        "outperform", "underperform", " should ",
    )
    lowered = src.lower()
    for word in banned:
        assert word not in lowered, (
            f"SEBI-banned vocabulary '{word.strip()}' leaked into HexLegend."
        )


# ---------------------------------------------------------------------
# Hex.tsx: SVG aria-label + <title> carry the coverage suffix
# ---------------------------------------------------------------------


def test_hex_svg_aria_label_includes_coverage_when_limited() -> None:
    """Screen readers should hear coverage, not just the overall score,
    when the hexagon collapses on a thin-data ticker."""
    src = _read(_HEX)
    assert "data limited:" in src, (
        "Hex.tsx must include a 'data limited:' phrase in the aria-label "
        "construction so screen readers explain the small polygon."
    )
    assert "inputs available" in src
    assert "aria-label={a11yLabel}" in src, (
        "Hex.tsx must wire the new a11yLabel string into the SVG "
        "aria-label attribute."
    )


def test_hex_svg_exposes_coverage_data_attributes() -> None:
    """Stable data- attributes let the visual-regression harness assert
    the limited-state polish without coupling to copy or testids."""
    src = _read(_HEX)
    assert "data-coverage-available={availableAxes}" in src
    assert "data-coverage-total={totalAxes}" in src
