"""Phase C.3 — score_breakdown shape regression test.

Adds the field-additive ``quality.score_breakdown`` object to the
analysis response. Validates the typed model and the
service-side dict shape it ingests.

Reference: docs/diagnostics/phase-c-score-formula-2026-05-25.md.
"""
from __future__ import annotations


def test_score_breakdown_typed_model_round_trips():
    """Construct a ScoreBreakdown end-to-end and confirm it serializes."""
    from backend.models.responses import (
        ScoreBreakdown, ScoreComponent, ScoreModifier,
    )
    sb = ScoreBreakdown(
        components=[
            ScoreComponent(
                name="Business Quality (50pts)", weight_max=50,
                points=44, source="piotroski+moat",
            ),
            ScoreComponent(
                name="Growth (20pts)", weight_max=20,
                points=15, source="revenue_growth",
            ),
            ScoreComponent(
                name="Valuation (20pts)", weight_max=20,
                points=20, source="mos_pct",
            ),
            ScoreComponent(
                name="Sentiment (10pts)", weight_max=10,
                points=7, source="analyst_upside",
            ),
        ],
        modifiers=[
            ScoreModifier(
                name="MoS-dominance cap",
                delta=-26,
                reason="|MoS|=43% — composite capped at 50.",
            ),
        ],
        base_score=86,
        final_score=50,
        note="Score is floored, not rounded.",
    )
    j = sb.model_dump()
    assert j["base_score"] == 86
    assert j["final_score"] == 50
    assert len(j["components"]) == 4
    assert j["modifiers"][0]["delta"] == -26
    assert sum(c["points"] for c in j["components"]) == 86


def test_quality_output_accepts_score_breakdown():
    """QualityOutput must accept score_breakdown as an optional field
    so legacy payloads (None) and Phase C.3 payloads both validate."""
    from backend.models.responses import QualityOutput, ScoreBreakdown

    # Legacy / cached payload: no breakdown.
    legacy = QualityOutput(yieldiq_score=65, grade="B+")
    assert legacy.score_breakdown is None

    # New payload with breakdown.
    fresh = QualityOutput(
        yieldiq_score=78, grade="A",
        score_breakdown=ScoreBreakdown(
            components=[], modifiers=[],
            base_score=78, final_score=78,
        ),
    )
    assert fresh.score_breakdown is not None
    assert fresh.score_breakdown.final_score == 78


def test_breakdown_dict_shape_matches_service_emit():
    """The dict the service builds (no Pydantic) must round-trip
    through ScoreBreakdown(**) without validation errors."""
    from backend.models.responses import ScoreBreakdown
    # This mirrors what `_score_breakdown` is set to in service.py.
    service_dict = {
        "components": [
            {"name": "Business Quality (50pts)", "weight_max": 50,
             "points": 44, "source": "piotroski+moat"},
            {"name": "Growth (20pts)", "weight_max": 20,
             "points": 15, "source": "revenue_growth"},
            {"name": "Valuation (20pts)", "weight_max": 20,
             "points": 12, "source": "mos_pct"},
            {"name": "Sentiment (10pts)", "weight_max": 10,
             "points": 7, "source": "analyst_upside"},
        ],
        "modifiers": [],
        "base_score": 78,
        "final_score": 78,
        "note": "Score is floored, not rounded.",
    }
    sb = ScoreBreakdown(**service_dict)
    assert sb.final_score == 78
    assert sb.base_score == 78
    assert len(sb.components) == 4
