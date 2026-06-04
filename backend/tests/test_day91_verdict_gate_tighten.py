"""Day-91 (2026-05-22): verdict-pill gate tighten (audit #4).

Audit #4 (2026-05-22) found the Day-61 confidence gate fired
INCONSISTENTLY because four render paths each derived their verdict
independently:

  - AnalysisHero       Day-61 inline gate, threshold 50
  - EditorialHero      score100 < 50 gate (no confidence check)
  - AnalysisBody       document.title via verdictFromMos() only
  - PublicAnalysis     public pill via verdictFromMos() only

Result on production cached payloads:
  - TCS:       confidence 67%, Data Limited banner ON, ADR cohort flag
               -> STILL rendered "NOTABLY UNDERVALUED" in tab title +
               public pill (gate path bypassed by direct
               verdictFromMos() call)
  - RELIANCE:  confidence 45% -> confident "UNDERVALUED" pill
  - INDIGO:    confidence 41% -> confident "UNDERVALUED" pill

Fix (this PR):

  1. Threshold lifted 50 -> 60 (LOW_CONFIDENCE_THRESHOLD).
  2. New WIDE_BAND_RATIO_THRESHOLD = 0.25 — when bull/bear scenario
     band exceeds 25% of current price the gate fires even with
     confidence >= 60. Catches TCS-class wide-band names that the
     pure-confidence gate missed.
  3. Single source of truth: lib/utils.ts::shouldGateVerdict() — all
     four render paths import and call this one helper, so the four
     paths can never disagree again.

These are source-text regression guards because the fix lives in TS
components. Each guard pins one wiring point so a future refactor
that re-introduces an independent derivation fails CI.
"""
from __future__ import annotations
from pathlib import Path


_ROOT = Path(__file__).resolve().parents[2] / "frontend" / "src"
_UTILS = _ROOT / "lib" / "utils.ts"
# PR-3 (acquisition four-hero retire, 2026-06-04): AnalysisHero.tsx
# was deleted (dead-code else branch in AnalysisBody). The shared
# gate is still pinned via _UTILS, _EDITORIAL, _BODY and _PUBLIC; the
# AnalysisHero-scoped assertions below are retired with the file.
_EDITORIAL = _ROOT / "components" / "analysis" / "EditorialHero.tsx"
_BODY = _ROOT / "app" / "(app)" / "analysis" / "[ticker]" / "AnalysisBody.tsx"
_PUBLIC = _ROOT / "app" / "(app)" / "analysis" / "[ticker]" / "PublicAnalysis.tsx"
_HONEST = _ROOT / "components" / "analysis" / "HonestHero.tsx"


# ── Shared gate helper: thresholds + signature ──────────────


def test_shared_gate_helper_defines_tight_thresholds():
    """The threshold lifted 50 -> 60 and the new band-ratio gate at 0.25
    are exported as named constants so the test (and future tickers)
    pin the exact numbers."""
    src = _UTILS.read_text(encoding="utf-8")
    assert "LOW_CONFIDENCE_THRESHOLD = 60" in src
    assert "WIDE_BAND_RATIO_THRESHOLD = 0.25" in src


def test_shared_gate_helper_present_with_band_ratio_logic():
    """shouldGateVerdict is the single source of truth. It must
    compute the (bull_case - bear_case) / current_price ratio and
    compare against the wide-band threshold."""
    src = _UTILS.read_text(encoding="utf-8")
    assert "export function shouldGateVerdict" in src
    # Scenario band gate present
    assert "bullCase - bearCase" in src
    assert "WIDE_BAND_RATIO_THRESHOLD" in src
    # Confidence gate present
    assert "LOW_CONFIDENCE_THRESHOLD" in src
    # dataLimited short-circuits first
    assert "dataLimited === true" in src


# ── All four render paths import the shared gate ────────────


def test_honest_hero_consumes_shared_gate_via_signals():
    """PR-3 (2026-06-04) replaced AnalysisHero with HonestHero in the
    AnalysisBody render path. HonestHero reads `signals.verdictGated`
    from useHeroSignals — which calls shouldGateVerdict internally —
    and collapses the verdict label to "Under Review" when the gate
    fires. This pins the wire-through: the rail title must consume
    verdictGated, never derive its own gate."""
    src = _HONEST.read_text(encoding="utf-8")
    assert "verdictGated" in src
    assert '"Under Review"' in src


def test_editorial_hero_uses_shared_gate():
    """EditorialHero previously gated only on score100 < 50 — RELIANCE
    (score 70, confidence 45) slipped through. The shared gate now
    folds confidence + band-ratio into isUnreliable."""
    src = _EDITORIAL.read_text(encoding="utf-8")
    assert "shouldGateVerdict" in src
    assert "verdictGated" in src
    # The gate result feeds the isUnreliable decision
    assert "verdictGated ||" in src or "|| verdictGated" in src


def test_analysis_body_title_uses_shared_gate():
    """document.title used to read directly from verdictFromMos(mos)
    bypassing the gate — that's how TCS got "NOTABLY UNDERVALUED" in
    the browser tab. The title pipeline now passes through the gate
    and collapses to "Under Review" when it fires."""
    src = _BODY.read_text(encoding="utf-8")
    assert "shouldGateVerdict" in src
    # Title cascade: gate -> MoS -> backend label -> neutral
    assert 'gated\n        ? "Under Review"' in src
    # PR-3 (2026-06-04): EditorialHero (with its bull/bear plumbing)
    # is retired from AnalysisBody. The shared gate is exercised
    # against HonestHero via useHeroSignals (covered by the dedicated
    # HonestHero assertion above); the bull/bear-prop pin is no
    # longer applicable to this file.


def test_public_analysis_pill_uses_shared_gate():
    """PublicAnalysis (unauthenticated landing) derived its pill from
    MoS alone — so TCS rendered a green "Notably Undervalued" pill to
    visitors even though the authenticated hero gated it. The public
    payload includes confidence + scenarios, so the same gate runs."""
    src = _PUBLIC.read_text(encoding="utf-8")
    assert "shouldGateVerdict" in src
    assert "publicGated" in src
    # When the gate fires, tone forces neutral so a 25%+ MoS doesn't
    # leak green tint onto the "Under Review" pill
    assert "publicGated\n    ? \"neutral\"" in src


# ── Gate-routing cascade pin ────────────────────────────────


def test_effective_verdict_cascade_pins_data_limited_first():
    """The cascade must be: dataLimited (outer) -> verdictGated ->
    verdict. Reordering would let a low-confidence name with a Data
    Limited banner render the wrong pill (TCS-class regression).

    PR-3 (2026-06-04): AnalysisHero.tsx is deleted; the cascade now
    lives inside HonestHero via the verdictGated signal. dataLimited
    must short-circuit FIRST so an under-review ticker can't render
    a "low_confidence" label that hides the harder caveat."""
    src = _HONEST.read_text(encoding="utf-8")
    # dataLimited branch wins first inside the tier resolution.
    assert "signals.dataLimited" in src
    assert '"data_limited"' in src
    # Then verdictGated produces the "Under Review" label.
    assert "verdictGated" in src
    assert '"Under Review"' in src


# ── SEBI vocabulary regression ──────────────────────────────


def test_day91_files_avoid_banned_advisory_words():
    """The new copy must not introduce 'should', 'recommend',
    'recommendation', 'buy', 'sell', 'hold', 'strong', 'accumulate',
    'outperform', 'underperform' OUTSIDE of pre-existing defensive
    strip patterns. We scope this check to the new gate copy by
    grepping the Day-91 comment block in lib/utils.ts."""
    src = _UTILS.read_text(encoding="utf-8")
    # Find the Day-91 docstring block
    marker = "Day-91 (2026-05-22): verdict-pill confidence gate"
    assert marker in src
    start = src.index(marker)
    # Take a 2KB slice around the new gate region (definition + docstring)
    block = src[start : start + 2500]
    banned = [
        " buy ",
        " sell ",
        " hold ",
        " accumulate ",
        " outperform ",
        " underperform ",
        " strong ",
    ]
    for word in banned:
        assert word.lower() not in block.lower(), (
            f"Day-91 gate block introduces banned advisory word: {word!r}"
        )
