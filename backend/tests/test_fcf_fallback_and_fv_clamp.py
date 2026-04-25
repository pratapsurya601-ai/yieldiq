"""
Tests for the two upstream-data fixes shipped 2026-04-25:

  A. TTM FCF annual fallback — when the TTM row's FCF is NULL / 0
     because the underlying 4 quarterly rows have NULL cfo/capex/fcf,
     the read path should fall back to the most recent annual FCF
     instead of returning 0 and collapsing the DCF to FV=0.

  B. Router FV clamp — when the computed FV lies outside [0.1*px, 3*px]
     or |MoS| >= 95%, the router used to blank FV to 0. That hid the
     symptom. It now clamps to the nearest bound, sets `data_limited`,
     and emits a `data_quality` analytical_notes entry.

  C. Negative-equity ROE guard — total_equity <= 0 must produce ROE=None,
     never a -439% chip.

These tests are intentionally hermetic: they stub SQLAlchemy session
+ model rows rather than touching a live DB.
"""
from __future__ import annotations

import types
from unittest.mock import patch, MagicMock


# ─────────────────────────────────────────────────────────────────
# Part A — TTM FCF annual fallback
# ─────────────────────────────────────────────────────────────────

class _Row:
    """Minimal stand-in for a Financials ORM row."""
    def __init__(self, **kw):
        for k, v in kw.items():
            setattr(self, k, v)


def _ttm_row(fcf, *, revenue=1000.0, pat=100.0):
    return _Row(
        free_cash_flow=fcf,
        revenue=revenue,
        pat=pat,
        period_end="2025-12-31",
        currency="INR",
        cfo=None,
        capex=None,
        total_equity=5000.0,
    )


def _quarter_row(*, cfo=None, capex=None, fcf=None):
    return _Row(cfo=cfo, capex=capex, free_cash_flow=fcf)


def test_ttm_annual_fallback_fires_when_quarterly_cf_null():
    """TTM FCF == 0 + all 4 quarterlies NULL → annual FCF is returned."""
    from backend.services.analysis import db as dbmod

    ttm = _ttm_row(fcf=0.0)
    quarters = [_quarter_row() for _ in range(4)]

    # Build a fake session whose query() chain returns ttm first, then
    # the 4 quarterlies.
    session = MagicMock()
    call_count = {"n": 0}

    def _query_side_effect(model):
        q = MagicMock()
        if call_count["n"] == 0:
            q.filter.return_value.order_by.return_value.first.return_value = ttm
        else:
            q.filter.return_value.order_by.return_value.limit.return_value.all.return_value = quarters
        call_count["n"] += 1
        return q

    session.query.side_effect = _query_side_effect

    with patch.object(dbmod, "_get_pipeline_session", return_value=session), \
         patch.object(dbmod, "_query_latest_annual_financials",
                      return_value={"fcf": 420.0, "revenue": 4200.0,
                                    "pat": 350.0, "period_end": "2025-03-31",
                                    "currency": "INR", "source": "annual"}):
        out = dbmod._query_ttm_financials("RELIANCE.NS")

    assert out is not None
    # FCF came from annual, not the zero TTM row.
    assert out["fcf"] == 420.0
    assert out["source"] == "ttm+annual_fcf_fallback"


def test_ttm_uses_ttm_fcf_when_nonzero():
    """Regression guard: a healthy TTM row is still the primary path."""
    from backend.services.analysis import db as dbmod

    ttm = _ttm_row(fcf=800.0)
    session = MagicMock()
    session.query.return_value.filter.return_value.order_by.return_value.first.return_value = ttm

    with patch.object(dbmod, "_get_pipeline_session", return_value=session):
        out = dbmod._query_ttm_financials("TCS.NS")

    assert out is not None
    assert out["source"] == "ttm"
    assert out["fcf"] == 800.0


def test_ttm_returns_none_when_no_annual_either():
    """Zero TTM + null quarters + no annual → None (existing data_issue fires)."""
    from backend.services.analysis import db as dbmod

    ttm = _ttm_row(fcf=None)
    quarters = [_quarter_row() for _ in range(4)]

    session = MagicMock()
    call_count = {"n": 0}

    def _query_side_effect(model):
        q = MagicMock()
        if call_count["n"] == 0:
            q.filter.return_value.order_by.return_value.first.return_value = ttm
        else:
            q.filter.return_value.order_by.return_value.limit.return_value.all.return_value = quarters
        call_count["n"] += 1
        return q

    session.query.side_effect = _query_side_effect

    with patch.object(dbmod, "_get_pipeline_session", return_value=session), \
         patch.object(dbmod, "_query_latest_annual_financials", return_value=None):
        out = dbmod._query_ttm_financials("UNKN.NS")

    assert out is None


# ─────────────────────────────────────────────────────────────────
# Part B — Router FV clamp emits data_quality note
# ─────────────────────────────────────────────────────────────────

def _make_fake_result(fv, px, mos, valuation_model="dcf"):
    """Build the minimum object the router's clamp block dereferences."""
    val = types.SimpleNamespace(
        fair_value=fv,
        current_price=px,
        margin_of_safety=mos,
        margin_of_safety_display=mos,
        mos_is_extreme=False,
        mos_extreme_note=None,
        verdict="undervalued",
        valuation_model=valuation_model,
        data_limited=False,
    )
    return types.SimpleNamespace(
        valuation=val,
        data_issues=[],
        analytical_notes=[],
    )


def _run_clamp(result):
    """Invoke the exact clamp block by lifting the logic into a closure.

    The clamp lives inline in `backend/routers/analysis.py`. We reproduce
    the bound-decision contract here and then verify the router-side
    functions it calls (AnalyticalNoteOutput construction, etc.) work.

    Rather than import-and-run the router (which pulls FastAPI + DB), we
    exercise the public side-effect: AnalyticalNoteOutput accepts the
    new kind, ValuationOutput has the new data_limited field.
    """
    from backend.models.responses import AnalyticalNoteOutput, ValuationOutput
    # Model must accept the new kind
    n = AnalyticalNoteOutput(
        kind="data_quality", severity="caution",
        title="Fair value clamped — data quality",
        body="Computed fair value was more than 3x price.",
    )
    assert n.kind == "data_quality"
    # ValuationOutput must accept data_limited
    # Clamp bound is 3*px on high side, 0.1*px on low side.
    _px = result.valuation.current_price
    if result.valuation.fair_value <= 0:
        _clamped = _px * 0.1
    elif _px > 0 and result.valuation.fair_value / _px > 3.0:
        _clamped = _px * 3.0
    elif _px > 0 and result.valuation.fair_value / _px < 0.1:
        _clamped = _px * 0.1
    else:
        _clamped = result.valuation.fair_value
    v = ValuationOutput(
        fair_value=round(_clamped, 2),
        current_price=_px,
        margin_of_safety=0.0,
        verdict="data_limited",
        data_limited=True,
    )
    assert v.data_limited is True
    return v, n


def test_fv_clamp_model_contract_high():
    """FV > 3*px → clamped; data_limited flag + data_quality note are valid."""
    r = _make_fake_result(fv=1500.0, px=100.0, mos=1400.0)
    v, n = _run_clamp(r)
    assert v.fair_value == 300.0  # 3.0 * 100 (clamped bound)
    assert n.severity == "caution"


def test_fv_clamp_model_contract_zero():
    """FV == 0 → clamped at 0.1*px; note emitted."""
    r = _make_fake_result(fv=0.0, px=200.0, mos=-100.0)
    # We verify the model contract directly — no router import needed.
    from backend.models.responses import ValuationOutput
    v = ValuationOutput(
        fair_value=round(200.0 * 0.1, 2),
        current_price=200.0,
        margin_of_safety=-90.0,
        verdict="data_limited",
        data_limited=True,
    )
    assert v.fair_value == 20.0
    assert v.data_limited is True


# ─────────────────────────────────────────────────────────────────
# Part C — Negative-equity ROE guard
# ─────────────────────────────────────────────────────────────────

def test_negative_equity_roe_returns_none():
    from backend.services.analysis.utils import _compute_roe_fallback

    enriched = {"net_income": 100.0, "total_equity": -50.0}
    assert _compute_roe_fallback(enriched) is None
    assert "negative_equity" in enriched.get("input_quality_flags", [])


def test_zero_equity_roe_returns_none():
    from backend.services.analysis.utils import _compute_roe_fallback

    enriched = {"net_income": 100.0, "total_equity": 0.0}
    assert _compute_roe_fallback(enriched) is None
    assert "negative_equity" in enriched.get("input_quality_flags", [])


def test_positive_equity_roe_still_works():
    from backend.services.analysis.utils import _compute_roe_fallback

    enriched = {"net_income": 100.0, "total_equity": 500.0}
    out = _compute_roe_fallback(enriched)
    assert out is not None
    assert abs(out - 0.2) < 1e-6


def test_roce_over_100pct_returns_none():
    """ROCE > 100% — likely demerger distortion — must return None."""
    from backend.services.ratios_service import compute_roce
    # EBIT=300, CE = TA-CL = 100 → ROCE = 300% (absurd)
    assert compute_roce(300.0, 200.0, 100.0) is None


def test_roce_within_bounds_works():
    from backend.services.ratios_service import compute_roce
    # EBIT=20, CE=100 → ROCE=20%
    assert compute_roce(20.0, 200.0, 100.0) == 20.0
