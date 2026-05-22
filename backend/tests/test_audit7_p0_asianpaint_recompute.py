"""Audit#7 P0: ASIANPAINT summary recompute wedged on cache_miss_recompute_failed.

Background
----------
PR #503 (Audit#6) added the bear-side overvalued bypass in
``backend/services/confidence_service.py::_apply_confidence_verdict_gate``.
For mos_pct <= BEAR_NOTABLY_OVERVALUED_MOS (-40%) the bypass returned
the string ``"notably_overvalued"``. ``ValuationOutput.verdict`` in
``backend/models/responses.py`` is a ``Literal["undervalued",
"fairly_valued", "overvalued", "avoid", "data_limited", "unavailable"]``
which does NOT include ``"notably_overvalued"``.

When the engine assembled a ValuationOutput for ASIANPAINT.NS
(mos=-47.8%, model_confidence ~55) pydantic raised ValidationError.
The public stock-summary endpoint
(``backend/routers/public.py``) caught the exception in the cache-miss
recompute fallback branch and returned the opaque ``under_review``
payload with ``reason: "cache_miss_recompute_failed"``. Every
subsequent fetch hit the same branch and re-served the placeholder.

SUNPHARMA (mos=-33%), MARUTI (-31%), SBIN (-31%) escaped the bug
because their MoS is ABOVE the -40% threshold so the bypass returned
plain ``"overvalued"`` (a valid literal) and recomputed cleanly.
ASIANPAINT, with the deepest negative MoS in the audit universe, was
the only ticker that crossed into the unmodeled branch.

Fix
---
Clamp the bypass surface label to ``"overvalued"`` (the only valid
literal in the overvalued band) and log the intensity hint
(``"notably_overvalued"`` when mos_pct <= -40) in the issues array
for analytics. Frontend pill rendering is unaffected because it
derives the visible label from ``mos_pct`` via
``frontend/src/lib/utils.ts::verdictFromMos`` on the client side.

Defensive: an unreachable literal would now fall through to
``fairly_valued`` with a CLEAR ``verdict_gate_inconsistent`` issue
string instead of raising and producing the opaque
``cache_miss_recompute_failed`` placeholder.
"""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.models.responses import ValuationOutput
from backend.services.confidence_service import _apply_confidence_verdict_gate


# ── Helper ─────────────────────────────────────────────────────────
def _gate(
    verdict: str,
    mos_pct: float,
    model_confidence: int,
    *,
    data_quality: int = 65,
    valuation_stability: int = 65,
) -> tuple[str, list[str]]:
    price = 100.0
    fair_value = price * (1.0 + mos_pct / 100.0)
    return _apply_confidence_verdict_gate(
        verdict,
        data_quality,
        model_confidence,
        valuation_stability,
        [],
        fair_value=fair_value,
        current_price=price,
        valuation_model="dcf",
    )


# ── Regression: bypass output must be a valid ValuationOutput literal
def test_bypass_output_validates_against_valuation_output_literal() -> None:
    """The bypass output must round-trip through
    ``ValuationOutput.verdict`` for EVERY mos_pct in the bear-side
    band. This is the test that would have caught Audit#7 P0 at
    PR-#503 review time.

    The pre-fix implementation returned ``"notably_overvalued"`` for
    mos_pct <= -40, which is not in the Literal[…], so the
    ValidationError below would have surfaced.
    """
    for mos_pct in (-25.5, -33.0, -41.0, -47.8, -60.0, -90.0):
        result, _ = _gate("overvalued", mos_pct=mos_pct, model_confidence=55)
        # Some inputs route through Layer 1 (extreme ratio) to
        # under_review — that is a valid literal too. The only
        # required invariant is "pydantic accepts the surfaced
        # string".
        if result == "under_review":
            # under_review is the engine's wedge state, surfaced via
            # the public endpoint's quarantine wrapper, not via
            # ValuationOutput.verdict. Skip the literal check.
            continue
        # Pydantic will raise ValidationError if `result` is not a
        # valid Literal member. This is the load-bearing assertion.
        try:
            ValuationOutput(
                fair_value=100.0 * (1.0 + mos_pct / 100.0),
                current_price=100.0,
                margin_of_safety=mos_pct,
                verdict=result,  # type: ignore[arg-type]
            )
        except ValidationError as e:
            pytest.fail(
                f"Bypass returned '{result}' for mos_pct={mos_pct} "
                f"which fails ValuationOutput.verdict validation: {e}"
            )


# ── ASIANPAINT-shape input must surface a clean overvalued ───────
def test_asianpaint_shape_returns_valid_overvalued() -> None:
    """The exact input shape that wedged ASIANPAINT in prod.

    mos_pct = -47.8 (live as of 2026-05-22)
    model_confidence = 55 (audit-confirmed range)
    data_quality / valuation_stability ~ 60-70 (typical large-cap)

    Pre-fix: bypass -> "notably_overvalued" -> ValidationError ->
    cache_miss_recompute_failed.
    Post-fix: bypass -> "overvalued" with intensity_hint logged.
    """
    verdict, issues = _gate("overvalued", mos_pct=-47.8, model_confidence=55)
    assert verdict == "overvalued"
    # The intensity must be recoverable from the issues log for
    # analytics consumers that want the deeper signal.
    assert any(
        "intensity_hint='notably_overvalued'" in s for s in issues
    ), f"intensity_hint missing from issues: {issues}"


# ── Defensive fall-through ──────────────────────────────────────
def test_bypass_never_returns_unmodeled_literal() -> None:
    """Fuzz the bear-side band. The bypass MUST NEVER return a string
    that is not one of:
      - undervalued, fairly_valued, overvalued, avoid,
        data_limited, unavailable, under_review

    under_review is included because the gate can route through
    Layer 1 / Layer 2 even when the bypass is in scope; the public
    endpoint handles under_review via the quarantine wrapper.
    """
    allowed = {
        "undervalued",
        "fairly_valued",
        "overvalued",
        "avoid",
        "data_limited",
        "unavailable",
        "under_review",
    }
    for mos_pct in range(-95, -24):  # -95 .. -25 inclusive
        for conf in (40, 50, 60, 69):  # all confidences that hit Layer 3
            verdict, _ = _gate(
                "overvalued", mos_pct=float(mos_pct), model_confidence=conf
            )
            assert verdict in allowed, (
                f"bypass returned '{verdict}' for mos_pct={mos_pct} "
                f"mc={conf} — would crash ValuationOutput pydantic "
                "validation and wedge recompute (Audit#7 P0 root "
                "cause). All bypass outputs MUST be modeled literals."
            )


# ── Issues log preserves the intensity signal ──────────────────
def test_intensity_hint_logged_for_deep_bear_reads() -> None:
    """When mos_pct crosses BEAR_NOTABLY_OVERVALUED_MOS (-40), the
    issues array must carry ``intensity_hint='notably_overvalued'``
    so downstream analytics / og-data / push copy can recover the
    deeper signal even though the surfaced verdict is the clamped
    ``"overvalued"``."""
    _, issues = _gate("overvalued", mos_pct=-50.0, model_confidence=55)
    assert any("intensity_hint='notably_overvalued'" in s for s in issues)

    _, issues_shallow = _gate("overvalued", mos_pct=-30.0, model_confidence=55)
    assert any("intensity_hint='overvalued'" in s for s in issues_shallow)
