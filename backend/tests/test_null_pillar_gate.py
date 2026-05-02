"""P0 null-pillar gate tests.

Regression guard for the worst credibility bug found by the
2026-05-02 external audit: stocks with no pillar data (e.g.
/prism/HEALTHCARE — a sector slug, not a ticker; /prism/SHAQUAK —
junk; /prism/TRL) silently defaulted to verdict "Fair value
region" and composite "5.0/10", which directly contradicts the
methodology page promise of an "Under Review" verdict for
insufficient data.

Three hardcoded "Fair value region" / "fair" defaults were
removed in:
  - backend/services/prism_service.py: _verdict_from_mos,
    _baseline_payload (was line 502).
  - backend/services/prism_narration_service.py: _groq_narration
    fallback (was line 123) and _templated_narration outro
    (was line 276).

These tests lock in the new contract:
  * >=3 null pillars -> verdict_band == "data_limited",
    verdict_label == "Under Review", composite == None.
  * 0-2 null pillars -> existing MoS-based verdict applies.
  * `_baseline_payload` (the catch-all error response) returns
    "Under Review" not "Fair value region".
"""
from __future__ import annotations

from backend.services import prism_service


def _axis(score, *, data_limited=False):
    """Mimic the shape `hex_service._axis` produces."""
    return {"score": score, "data_limited": data_limited, "why": ""}


def _hex(scores):
    """Build a hex_payload with six pillars from a score list.

    Items may be a number (real score), None (missing score), or a
    dict (full override). Length must be 6.
    """
    keys = ("pulse", "quality", "moat", "safety", "growth", "value")
    assert len(scores) == 6
    axes = {}
    for k, s in zip(keys, scores):
        if isinstance(s, dict):
            axes[k] = s
        elif s is None:
            axes[k] = _axis(None)
        else:
            axes[k] = _axis(float(s))
    return {"axes": axes, "overall": 5.0}


# (1) The gate trips at exactly 3 null pillars
def test_gate_trips_when_three_pillars_null():
    """3 null pillars -> "Under Review" regardless of MoS."""
    hx = _hex([7.0, 8.0, 6.5, None, None, None])
    band, label, composite, reason = prism_service.assign_verdict(hx, mos_pct=25.0)
    assert band == "data_limited"
    assert label == "Under Review"
    assert composite is None
    assert reason and "Insufficient data" in reason


def test_gate_trips_when_all_six_pillars_null():
    """All-null hex (the SHAQUAK / HEALTHCARE case) -> Under Review."""
    hx = _hex([None] * 6)
    band, label, composite, _ = prism_service.assign_verdict(hx, mos_pct=None)
    assert band == "data_limited"
    assert label == "Under Review"
    assert composite is None


def test_gate_trips_when_axes_missing_entirely():
    """No `axes` key at all (compute fully failed) -> Under Review."""
    band, label, composite, _ = prism_service.assign_verdict({}, mos_pct=10.0)
    assert band == "data_limited"
    assert label == "Under Review"
    assert composite is None


def test_gate_trips_when_hex_payload_none():
    """Defensive: None hex_payload counts as 6 nulls."""
    band, label, composite, _ = prism_service.assign_verdict(None, mos_pct=10.0)
    assert band == "data_limited"
    assert label == "Under Review"
    assert composite is None


def test_gate_counts_data_limited_neutral_axes_as_null():
    """`hex_service._neutral_axis` returns score=5.0, data_limited=True.

    These are placeholder fills, not real signal -- the gate must
    treat them as null even though `score` is non-None.
    """
    placeholder = _axis(5.0, data_limited=True)
    hx = _hex([7.0, 8.0, 6.5, placeholder, placeholder, placeholder])
    band, label, _, _ = prism_service.assign_verdict(hx, mos_pct=25.0)
    assert band == "data_limited"
    assert label == "Under Review"


# (2) Existing logic still applies at 0-2 nulls
def test_zero_nulls_uses_mos_verdict_undervalued():
    hx = _hex([7.0, 8.0, 6.5, 7.5, 7.0, 6.0])
    band, label, _, reason = prism_service.assign_verdict(hx, mos_pct=25.0)
    # +25% MoS sits in the "undervalued" / "Below fair value region" band
    assert band == "undervalued"
    assert label == "Below fair value region"
    assert reason is None


def test_zero_nulls_uses_mos_verdict_fair():
    hx = _hex([7.0, 8.0, 6.5, 7.5, 7.0, 6.0])
    band, label, _, _ = prism_service.assign_verdict(hx, mos_pct=0.0)
    assert band == "fair"
    assert label == "Fair value region"


def test_two_nulls_does_not_trip_gate():
    hx = _hex([7.0, 8.0, 6.5, 7.5, None, None])
    band, label, _, _ = prism_service.assign_verdict(hx, mos_pct=25.0)
    assert band == "undervalued"
    assert label != "Under Review"


# (3) Baseline payload no-data response
def test_baseline_payload_returns_under_review_not_fair_value():
    """_baseline_payload is the catch-all error response; previously
    it shipped verdict_label="Fair value region" which directly
    caused the audit findings on /prism/HEALTHCARE etc.
    """
    payload = prism_service._baseline_payload(
        ticker="HEALTHCARE", compute_ms=12.3
    )
    assert payload["verdict_band"] == "data_limited"
    assert payload["verdict_label"] == "Under Review"
    assert payload.get("composite_score") is None
    # The string "Fair value region" must not appear anywhere in
    # the no-data response.
    assert "Fair value region" not in str(payload)


# (4) _verdict_from_mos no longer falls back to "fair"
def test_verdict_from_mos_none_returns_under_review():
    band, label = prism_service._verdict_from_mos(None)
    assert band == "data_limited"
    assert label == "Under Review"


def test_verdict_from_mos_nan_returns_under_review():
    band, label = prism_service._verdict_from_mos(float("nan"))
    assert band == "data_limited"
    assert label == "Under Review"
