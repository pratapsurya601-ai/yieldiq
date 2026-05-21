"""Day-87 (2026-05-22): frontend wiring for Day-76's reverse-DCF
backend additions.

Day-76 (PR #466) added three new fields to
`/api/v1/public/reverse-dcf/{ticker}`:

  1. `applicable: false` + `reason` + `category: bank_like` —
     returned for banks / NBFCs / insurers instead of attempting an
     FCF-DCF inversion.
  2. `growth_off_scale` + `growth_pegged_high` + `growth_pegged_low` —
     fired when the bisector terminates at the search boundary
     without converging interior.
  3. A bound-qualified `current_market_implied_summary` (">=" / "<=")
     when off-scale.

Before Day-87 the frontend panel (`ReverseDcfPanel.tsx`) returned
null on any payload missing `implied_growth_pct`, which hid banks
entirely with no explanation. It also rendered the off-scale
implied-growth number as if it were a precise point estimate.

This module is a SOURCE-TEXT guard over the panel — it pins:

  * The `applicable === false` branch renders an explanatory card
    instead of returning null, with the design-token classes the
    spec calls for.
  * The off-scale branch surfaces the >= / <= bound prefix and an
    amber caveat note.
  * `ReverseDcfPayload` declares the six new optional fields so the
    TypeScript compiler can narrow against them.
  * SEBI vocabulary is not reintroduced and `<strong>` is not used
    (the codebase-wide ban from Day-72).
"""
from __future__ import annotations

from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PANEL_TSX = (
    REPO_ROOT
    / "frontend"
    / "src"
    / "components"
    / "analysis"
    / "ReverseDcfPanel.tsx"
)


def _panel_src() -> str:
    assert PANEL_TSX.exists(), f"{PANEL_TSX} must exist"
    return PANEL_TSX.read_text(encoding="utf-8")


# ─── Type-interface extension ───────────────────────────────────


def test_payload_interface_declares_new_optional_fields():
    """`ReverseDcfPayload` must declare every Day-76 field as optional
    so the bank-skip payload and the off-scale flags can be narrowed
    against in TS."""
    src = _panel_src()
    for field in (
        "applicable?: boolean",
        "reason?: string",
        "category?: string",
        "growth_off_scale?: boolean",
        "growth_pegged_high?: boolean",
        "growth_pegged_low?: boolean",
    ):
        assert field in src, (
            f"ReverseDcfPayload must declare `{field}` so the Day-76 "
            "backend shape is representable in TypeScript."
        )


# ─── Bank-skip rendering ────────────────────────────────────────


def test_fetch_accepts_bank_skip_payload():
    """fetchReverseDcf must NOT drop a payload just because it lacks
    `implied_growth_pct` — when `applicable === false` it has to pass
    through so the component can render the explanatory card."""
    src = _panel_src()
    assert "data.applicable === false" in src, (
        "fetchReverseDcf must short-circuit on applicable === false "
        "and return the payload instead of treating it as malformed."
    )


def test_bank_skip_card_renders_with_design_tokens():
    """When `applicable === false` the component must render a small
    explanatory card using the design tokens
    (bg-bg dark:bg-surface text-ink text-caption border-border)."""
    src = _panel_src()
    assert "data.applicable === false" in src
    assert "Not applicable for banks" in src
    assert "ROE / RoA / NIM" in src
    assert "Quality panel" in src
    # Design-token classes the spec calls for.
    assert "bg-bg dark:bg-surface" in src
    assert "border-border" in src
    assert "text-caption" in src
    assert "text-ink" in src


# ─── Off-scale rendering ────────────────────────────────────────


def test_off_scale_headline_uses_bound_prefix():
    """When `growth_off_scale` is true the headline implied-growth
    number must be prefixed with a >= / <= bound symbol — never
    rendered as if it were a precise point estimate."""
    src = _panel_src()
    # The Unicode bound symbols, not the ASCII >= / <= (those live
    # in the backend summary which we render verbatim).
    assert "≥" in src
    assert "≤" in src
    assert "peggedHigh" in src
    assert "peggedLow" in src
    assert "growth_off_scale" in src


def test_off_scale_caveat_note_present():
    """An amber-tinted caveat note must explain *why* the number is
    off-scale (trough-margin vs balance-sheet event distortion).
    The caveat strings are the spec-mandated phrasing."""
    src = _panel_src()
    assert "trough-margin distortion" in src
    assert "balance-sheet event distortion" in src
    # The amber tint must be present so the note is visually
    # distinguishable from the standard body copy.
    assert "amber" in src


# ─── Vocabulary / markup guards ─────────────────────────────────


def test_no_sebi_banned_vocabulary_in_panel():
    """SEBI-banned advisory verbs must stay out of the panel copy.
    `should` is allowed only in TypeScript identifiers / JSDoc where
    no rendered string contains it — we keep the guard strict here
    since the panel has no such legitimate usage."""
    src = _panel_src()
    banned = (
        "buy",
        "sell",
        " hold ",
        " hold.",
        "accumulate",
        "recommend",
        "outperform",
        "underperform",
    )
    lowered = src.lower()
    for word in banned:
        assert word not in lowered, (
            f"SEBI-banned token `{word.strip()}` must not appear in "
            "ReverseDcfPanel.tsx — use SEBI-safe phrasing instead."
        )


def test_no_raw_strong_html_tag():
    """Day-72 banned `<strong>` site-wide in favour of
    `<span className=\"font-bold\">`. Guard the panel against
    regressing on that."""
    src = _panel_src()
    assert "<strong>" not in src
    assert "</strong>" not in src
