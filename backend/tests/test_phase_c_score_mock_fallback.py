"""Phase C.2 PR 2 — Mock-fallback removal regression test.

Before this PR, ``backend/services/analysis/service.py:80-90`` wrapped
``from dashboard.utils.scoring import compute_yieldiq_score`` in a
``try/except Exception:`` that, on import failure, registered a 4-line
mock with DIFFERENT scoring weights (40/30/20/10 envelopes, no moat
awareness) under the same symbol name. The dashboard package ships
in the backend Docker image; any failure to import is a deploy bug
that must surface at boot.

This test pins the new behaviour: ``compute_yieldiq_score`` imported
through the backend service is the canonical function from
``dashboard.utils.scoring``, NOT the divergent mock.

Quirk reference: docs/diagnostics/phase-c-score-formula-2026-05-25.md §4 #3.
"""
from __future__ import annotations


def test_score_function_is_canonical_not_mock():
    """The symbol the backend imports must be the canonical 4-bucket
    scoring function from dashboard.utils.scoring, not a mock."""
    from backend.services.analysis import service as analysis_service
    from dashboard.utils import scoring as canonical

    # Same object — confirms no fallback shim was registered.
    assert analysis_service.compute_yieldiq_score is canonical.compute_yieldiq_score


def test_canonical_returns_4_components():
    """The canonical function returns a 4-component breakdown
    (Business Quality / Growth / Valuation / Sentiment). The mock
    returned only `score` + `grade` with NO components dict — if the
    mock were ever to fire, this assert would fail."""
    from backend.services.analysis.service import compute_yieldiq_score
    out = compute_yieldiq_score(
        mos_pct=10.0, piotroski=7, moat_grade="Wide",
        rev_growth=0.15, analyst_upside=12.0,
    )
    assert "components" in out
    assert set(out["components"].keys()) == {
        "Business Quality (50pts)",
        "Growth (20pts)",
        "Valuation (20pts)",
        "Sentiment (10pts)",
    }


def test_canonical_weights_match_documented():
    """A Wide-moat ticker with high piotroski must score > 60 — the
    mock awarded 0 for any moat grade, so a Wide-moat 9-piotroski
    ticker scored only ~50 there. Canonical: pio=25, moat=25, +
    growth + sentiment > 60."""
    from backend.services.analysis.service import compute_yieldiq_score
    out = compute_yieldiq_score(
        mos_pct=0, piotroski=9, moat_grade="Wide",
        rev_growth=0.15, analyst_upside=15.0,
    )
    # pio=25 + moat=25 + grw=15 (15% rev growth) + val=8 (mos>=0) + sent=7 (>=10 upside)
    # = 80 expected
    assert out["score"] >= 70, f"expected canonical >=70, got {out['score']}"
