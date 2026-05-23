"""Phase B.3 (2026-05-24) — guard against confidence-field leak in
``/api/v1/public/stock-summary``.

Background
----------
The Phase B.0 live probe surfaced LICI.NS shipping
``"confidence": 1089072600041`` and SBILIFE.NS ``64158800032`` while
the documented contract is a 0-100 integer. Likely a stale cached
``ValuationOutput.confidence_score`` from an earlier write path where
a wrong field leaked in. ``ValuationOutput.confidence_score`` is typed
``int`` with no upper bound so the bad value rode end-to-end into the
public payload.

These tests pin the new ``_sanitize_confidence`` clamp at the public
projection layer: in-range stays in-range, out-of-range collapses to
None (so the frontend hides the chip) and emits a warning log. Direct
unit tests — no DB / cache fixtures required.
"""
from __future__ import annotations

import logging

import pytest

from backend.routers.public import _sanitize_confidence


class TestSanitizeConfidence:
    """Direct unit tests for the clamp helper."""

    def test_in_range_passes_through(self):
        # Typical values from compute_confidence_score / financial paths
        for v in (0, 1, 50, 67, 80, 90, 100):
            assert _sanitize_confidence(v, "TCS") == v

    def test_boundary_values(self):
        assert _sanitize_confidence(0, "X") == 0
        assert _sanitize_confidence(100, "X") == 100

    def test_none_returns_none(self):
        assert _sanitize_confidence(None, "X") is None

    def test_negative_clamped_to_none(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert _sanitize_confidence(-1, "X") is None
        assert any("out of range" in r.message for r in caplog.records)

    def test_above_100_clamped_to_none(self, caplog):
        with caplog.at_level(logging.WARNING):
            assert _sanitize_confidence(101, "X") is None
        assert any("out of range" in r.message for r in caplog.records)

    def test_lici_leak_value_clamped(self, caplog):
        """Regression: the exact bad value the live probe surfaced for
        LICI.NS must collapse to None and emit a warning naming the
        ticker for ops debugging."""
        with caplog.at_level(logging.WARNING):
            assert _sanitize_confidence(1089072600041, "LICI.NS") is None
        assert any(
            "LICI.NS" in r.message and "1089072600041" in r.message
            for r in caplog.records
        ), "warning must include ticker + bad value for ops debugging"

    def test_sbilife_leak_value_clamped(self):
        # The second leak the sweep surfaced.
        assert _sanitize_confidence(64158800032, "SBILIFE.NS") is None

    def test_float_in_range_coerces_to_int(self):
        assert _sanitize_confidence(67.4, "X") == 67

    def test_non_numeric_returns_none(self):
        assert _sanitize_confidence("nope", "X") is None
        assert _sanitize_confidence({"score": 50}, "X") is None


class TestSummaryProjectionUsesGuard:
    """End-to-end smoke through ``_extract_analysis_summary``: a bad
    confidence_score on the cached AnalysisResponse must NOT leak into
    the public payload — it must surface as None.

    Builds a minimal fake AnalysisResponse-shaped object rather than
    constructing the full Pydantic model (which has dozens of required
    fields). The projection helper only reads attributes via ``.``.
    """

    def _make_fake_result(self, confidence_score):
        class _V:
            pass

        class _Q:
            pass

        class _C:
            pass

        v = _V()
        v.fair_value = 1640.32
        v.current_price = 840.05
        v.margin_of_safety = 95.3
        v.verdict = "undervalued"
        v.bear_case = 1312.26
        v.base_case = 1640.32
        v.bull_case = 1968.38
        v.wacc = 0.102
        v.confidence_score = confidence_score
        v.peer_cap_details = None
        v.fair_value_source = "dcf"
        v.valuation_model = "appraisal_value"

        q = _Q()
        q.yieldiq_score = 40
        q.grade = "C"
        q.moat = "Moderate"
        q.piotroski_score = 7
        q.roe = 37.98
        q.de_ratio = 0.0
        q.roce = 90.0
        q.debt_ebitda = None
        q.interest_coverage = None
        q.current_ratio = None
        q.asset_turnover = None
        q.revenue_cagr_3y = 0.0703
        q.revenue_cagr_5y = None

        c = _C()
        c.company_name = "Life Insurance Corporation Of India"
        c.sector = "Insurance"
        c.industry = "Insurance - Life"
        c.exchange = "NSE"
        c.currency = "INR"
        c.market_cap = 5313314241515.605

        class _Result:
            pass

        r = _Result()
        r.ticker = "LICI.NS"
        r.valuation = v
        r.quality = q
        r.company = c
        r.insights = None
        r.ai_summary = None
        r.timestamp = "2026-05-24T00:00:00"
        return r

    def test_legit_confidence_passes(self, monkeypatch):
        from backend.routers import public as pub

        monkeypatch.setattr(pub, "_safe_compute_cagr_panel", lambda t: None)
        out = pub._extract_analysis_summary(self._make_fake_result(80))
        assert out["confidence"] == 80

    def test_leaked_timestamp_value_becomes_none(self, monkeypatch, caplog):
        from backend.routers import public as pub

        monkeypatch.setattr(pub, "_safe_compute_cagr_panel", lambda t: None)
        with caplog.at_level(logging.WARNING):
            out = pub._extract_analysis_summary(
                self._make_fake_result(1089072600041)
            )
        assert out["confidence"] is None, (
            "12-digit confidence must NOT leak to public payload"
        )
        # Other fields stay intact — guard is scoped to confidence only.
        assert out["fair_value"] == 1640.32
        assert out["score"] == 40


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(pytest.main([__file__, "-v"]))
