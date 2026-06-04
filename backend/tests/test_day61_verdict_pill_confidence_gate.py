"""Day-61 (2026-05-21): verdict-pill confidence gate.

Audit P2: 'A 45%-confidence Reliance was rendering with a confident
green Below Fair Value pill alongside its own 45% confidence number
on the same screen.' Highest impact-per-LOC fix per the audit.

Rule
----
If model confidence < 50% AND we haven't already routed to
data_limited (stricter gate), downgrade the rendered pill to
'low_confidence' (neutral slate). The underlying MoS / FV numbers
stay visible elsewhere so serious users can still read the leaning.

Source-text regression guards because the fix lives in frontend
TS components (no Python runtime to assert against). Each guard
verifies the fix is wired in at a specific layer.
"""
from __future__ import annotations
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "src"
_TYPES = _ROOT / "types" / "api.ts"
_CONSTS = _ROOT / "lib" / "constants.ts"
_CHIP = _ROOT / "components" / "analysis" / "VerdictChip.tsx"
# PR-3 (acquisition four-hero retire, 2026-06-04): AnalysisHero.tsx is
# DELETED — it was the dead-code else-branch fallback in AnalysisBody
# (prismResolved is non-null on every code path that ships). The
# low-confidence gate behaviour is now guarded inside <EditorialHero>
# (test_day91_verdict_gate_tighten) and <HonestHero> (which derives
# its "Under Review" label from signals.verdictGated, populated by
# the same shouldGateVerdict() helper). The two hero-scoped assertions
# below are retired; the type / constants / chip wire-contract
# assertions remain.


# ── Type union extended ─────────────────────────────────────


def test_verdict_type_includes_low_confidence():
    src = _TYPES.read_text(encoding="utf-8")
    assert '"low_confidence"' in src
    # The Verdict union is the single source of truth across the app;
    # drift would silently break exhaustive Record<Verdict, ...> maps.
    assert "Day-61" in src


# ── Constants: colors + dark classes + label ────────────────


def test_verdict_colors_has_low_confidence_neutral_slate():
    src = _CONSTS.read_text(encoding="utf-8")
    # Slate hue --- explicitly neutral, never green/amber
    assert "low_confidence:" in src
    assert "bg-slate-100" in src
    assert "text-slate-700" in src
    assert "border-slate-300" in src


def test_verdict_dark_classes_includes_low_confidence():
    """Tailwind purge requires static dark: classes; runtime
    interpolation would be stripped from the production CSS."""
    src = _CONSTS.read_text(encoding="utf-8")
    assert "low_confidence: \"dark:bg-slate-800 dark:text-slate-300 dark:border-slate-700\"" in src


def test_verdict_chip_renders_low_confidence_label():
    src = _CHIP.read_text(encoding="utf-8")
    assert "low_confidence:" in src
    assert '"Low Confidence"' in src


# ── Hero gate logic ─────────────────────────────────────────
# Retired in PR-3 (acquisition four-hero retire, 2026-06-04). See the
# `_HERO` removal comment above. EditorialHero gate coverage lives in
# test_day91_verdict_gate_tighten; HonestHero consumes the same
# shouldGateVerdict() helper via useHeroSignals().
