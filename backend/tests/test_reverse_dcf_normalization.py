"""
Tests for the reverse-DCF upstream FCF normalisation (v2 of PR #305,
which was reverted via PR #308 due to a masked exception that took
down /analysis endpoints).

The contract these tests enforce:

1. `_compute_fcf_base` ALWAYS leaves `enriched["normalized_fcf_base"]`
   and `enriched["normalized_fcf_margin"]` defined — including on the
   "no candidates → unreliable" early-return path. Downstream readers
   in backend/services/analysis/service.py rely on .get(...) but the
   discipline of "stash always defined" eliminates the class of bugs
   the v1 patch was reverted for.

2. The reverse-DCF service uses the upstream-normalised anchor when
   one is supplied, and degrades silently to current_fcf on bad
   inputs (None, NaN, Inf, negative, zero, wrong type).

3. The QualityOutput Pydantic model round-trips the two new fields
   with None defaults so legacy v100 cached payloads load cleanly.
"""

from __future__ import annotations

import math
import numpy as np
import pandas as pd

from models.forecaster import _compute_fcf_base
from backend.services.reverse_dcf_service import compute_reverse_dcf
from backend.services.analysis.utils import _safe_float, _safe_div_1e7
from backend.models.responses import QualityOutput


# ─── _compute_fcf_base contract: stashes always defined ──────────


def test_empty_enriched_leaves_stashes_none():
    """No candidates → early return path. Stashes must still be set."""
    enriched: dict = {"ticker": "X.NS"}
    base, method = _compute_fcf_base(enriched)
    assert base == 0.0
    assert method == "unreliable_loss_company"
    assert enriched["normalized_fcf_base"] is None
    assert enriched["normalized_fcf_margin"] is None


def test_healthy_non_cyclical_stashes_populated():
    enriched = {
        "ticker": "TCS.NS",
        "latest_fcf": 45000e7,
        "latest_revenue": 240000e7,
        "op_margin": 0.25,
        "sector": "it_services",
        "cf_df": pd.DataFrame({
            "year": [2020, 2021, 2022, 2023, 2024],
            "fcf":  [30000e7, 33000e7, 38000e7, 42000e7, 45000e7],
            "capex": [-3000e7] * 5,
        }),
        "income_df": pd.DataFrame({
            "year": [2020, 2021, 2022, 2023, 2024],
            "revenue": [160000e7, 175000e7, 195000e7, 220000e7, 240000e7],
            "op_margin": [0.25] * 5,
        }),
    }
    base, _ = _compute_fcf_base(enriched)
    assert base > 0
    assert enriched["normalized_fcf_base"] is not None
    assert enriched["normalized_fcf_base"] > 0
    assert enriched["normalized_fcf_margin"] is not None
    assert 0.05 < enriched["normalized_fcf_margin"] < 0.30


def test_malformed_income_df_no_raise():
    """income_df missing 'revenue' must not crash margin compute."""
    enriched = {
        "ticker": "BAD.NS",
        "latest_fcf": 1000e7,
        "latest_revenue": 10000e7,
        "op_margin": 0.10,
        "cf_df": pd.DataFrame({"year": [2022, 2023, 2024], "fcf": [500e7, 700e7, 1000e7]}),
        "income_df": pd.DataFrame({"year": [2022, 2023, 2024]}),
    }
    base, _ = _compute_fcf_base(enriched)
    assert base > 0
    # margin must degrade to None, NOT raise
    assert enriched["normalized_fcf_margin"] is None
    assert enriched["normalized_fcf_base"] is not None


def test_nan_inf_in_fcf_no_raise():
    enriched = {
        "ticker": "NAN.NS",
        "latest_fcf": 1000e7,
        "latest_revenue": 10000e7,
        "op_margin": 0.10,
        "cf_df": pd.DataFrame({
            "year": [2020, 2021, 2022, 2023, 2024],
            "fcf": [np.nan, np.inf, 500e7, 700e7, 1000e7],
        }),
        "income_df": pd.DataFrame({
            "year": [2020, 2021, 2022, 2023, 2024],
            "revenue": [5000e7, 6000e7, 7000e7, 8000e7, 10000e7],
            "op_margin": [0.10] * 5,
        }),
    }
    base, _ = _compute_fcf_base(enriched)
    assert base > 0
    # Should fall through cleanly; margin computed from positive-only rows
    nm = enriched["normalized_fcf_margin"]
    assert nm is None or math.isfinite(nm)


# ─── compute_reverse_dcf: normalized_fcf integration ─────────────


_RDCF_BASE = dict(
    ticker="RELIANCE.NS",
    current_price=2900.0,
    wacc=0.12,
    current_margin=0.018,
    current_revenue=900000e7,
    total_debt=300000e7,
    total_cash=200000e7,
    shares=676e7,
    terminal_g=0.04,
)


def test_reverse_dcf_no_norm_baseline():
    r = compute_reverse_dcf(current_fcf=15000e7, **_RDCF_BASE)
    assert r is not None
    assert r["inputs"]["normalization_applied"] is False
    assert r["inputs"]["fcf_anchor_used"] == 15000e7


def test_reverse_dcf_norm_applied():
    r = compute_reverse_dcf(
        current_fcf=15000e7, normalized_fcf=50000e7, **_RDCF_BASE,
    )
    assert r["inputs"]["normalization_applied"] is True
    assert r["inputs"]["fcf_anchor_used"] == 50000e7


def test_reverse_dcf_bad_norm_inputs_degrade():
    """None, NaN, Inf, negative, zero → fall back to current_fcf."""
    for bad in [None, float("nan"), float("inf"), -1000.0, 0.0, "abc"]:
        r = compute_reverse_dcf(
            current_fcf=15000e7, normalized_fcf=bad, **_RDCF_BASE,
        )
        assert r is not None, f"crashed on bad={bad!r}"
        assert r["inputs"]["fcf_anchor_used"] == 15000e7, f"bad={bad!r}"
        assert r["inputs"]["normalization_applied"] is False, f"bad={bad!r}"


# ─── QualityOutput Pydantic round-trip ──────────────────────────


def test_quality_output_defaults_none():
    q = QualityOutput()
    assert q.fcf_margin_5y is None
    assert q.normalized_fcf_cr is None


def test_quality_output_accepts_floats():
    q = QualityOutput(fcf_margin_5y=0.085, normalized_fcf_cr=45000.0)
    assert q.fcf_margin_5y == 0.085
    assert q.normalized_fcf_cr == 45000.0


def test_quality_output_accepts_int():
    q = QualityOutput(fcf_margin_5y=0, normalized_fcf_cr=100)
    assert q.fcf_margin_5y == 0.0
    assert q.normalized_fcf_cr == 100.0


# ─── _safe_float / _safe_div_1e7 helpers ───────────────────────


def test_safe_float_rejects_garbage():
    assert _safe_float(None) is None
    assert _safe_float("abc") is None
    assert _safe_float(float("nan")) is None
    assert _safe_float(float("inf")) is None
    assert _safe_float(float("-inf")) is None
    assert _safe_float(1.5) == 1.5
    assert _safe_float("2.5") == 2.5
    assert _safe_float(np.float64(3.0)) == 3.0


def test_safe_div_1e7():
    assert _safe_div_1e7(None) is None
    assert _safe_div_1e7(1e7) == 1.0
    assert _safe_div_1e7(5e10) == 5000.0
    assert _safe_div_1e7(float("nan")) is None
