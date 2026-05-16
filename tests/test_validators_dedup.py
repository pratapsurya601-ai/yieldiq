"""Regression tests for backend.services.validators dedup behavior.

Covers two Sentry-flood mitigations shipped 2026-05-03:

1. ``failed_fields`` dedup — a WACC value below 0.02 trips both the
   lower-BOUNDS check AND the RFR-floor check, previously appending
   'wacc' twice. The two natural orderings hashed to different dedup
   signatures, defeating ``log_validation``'s once-per-process Sentry
   gate. LTIM.NS produced 13,964 events/24h before the fix.

2. Signature dedup uses ``set()`` so any residual duplicate in
   ``failed_fields`` collapses to a single key.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services import validators as V  # noqa: E402


def _resp(wacc=None, market_cap=None, fv=100, cmp=100, mos=0):
    """Minimal AnalysisResponse-shaped object for validate_analysis."""
    return SimpleNamespace(
        ticker="LTIM.NS",
        valuation=SimpleNamespace(
            wacc=wacc,
            terminal_growth=0.04,
            fcf_growth_rate=0.10,
            confidence_score=80,
            margin_of_safety=mos,
            fair_value=fv,
            current_price=cmp,
            verdict="fair",
        ),
        quality=SimpleNamespace(
            roe=15.0, roce=15.0, de_ratio=0.5,
            yieldiq_score=50, piotroski_score=5, moat="Narrow",
        ),
        company=SimpleNamespace(market_cap=market_cap, company_name="Test"),
        cached=True,
    )


def test_low_wacc_does_not_double_add_failed_field():
    """WACC=0.01 trips both _check_bound (lower=0.02) AND the RFR-floor
    branch (<0.04). Prior to the fix, failed_fields would be
    ['wacc', 'wacc']; we now require a single entry."""
    r = V.validate_analysis(_resp(wacc=0.01, market_cap=1e11))
    assert r.failed_fields.count("wacc") == 1, r.failed_fields
    assert r.severity == "critical"


def test_log_signature_collapses_duplicate_fields(monkeypatch):
    """If failed_fields somehow contains a duplicate (e.g. a future
    validator forgets the guard), the dedup signature must still treat
    it as a single (ticker, fields) tuple."""
    V._LOGGED_CRITICAL_SIGS.clear()
    sent = []

    class _StubLogger:
        def error(self, *a, **kw): sent.append(("error", a))
        def warning(self, *a, **kw): sent.append(("warning", a))
        def info(self, *a, **kw): sent.append(("info", a))
        def debug(self, *a, **kw): pass

    monkeypatch.setattr(V, "logger", _StubLogger())
    monkeypatch.setattr(V, "_dcf_was_capped", lambda t: False)

    res = V.ValidationResult(
        ok=False, severity="critical",
        issues=["x", "y"],
        failed_fields=["wacc", "wacc", "market_cap_inr"],  # duplicate
    )
    V.log_validation("LTIM.NS", res)
    # First call → Sentry (logger.error)
    assert sent and sent[0][0] == "error"

    # Second call with the SAME fields in DIFFERENT order: must dedup.
    res2 = V.ValidationResult(
        ok=False, severity="critical",
        issues=["x", "y"],
        failed_fields=["market_cap_inr", "wacc"],  # no dup, different order
    )
    V.log_validation("LTIM.NS", res2)
    # Second call must NOT page Sentry (logger.error) — only warning.
    error_calls = [s for s in sent if s[0] == "error"]
    assert len(error_calls) == 1, sent


def test_clean_response_does_not_flag():
    """Sanity check: a healthy response produces no failed_fields."""
    r = V.validate_analysis(_resp(wacc=0.12, market_cap=5e11, fv=110, cmp=100, mos=10))
    assert r.failed_fields == []
    assert r.ok
