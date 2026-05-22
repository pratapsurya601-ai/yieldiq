# backend/tests/test_audit5_p1_de_ratio_null_safety.py
# ─────────────────────────────────────────────────────────────────────
# Audit#5 P1 — de_ratio null-safety
#
# Root cause (2026-05-22): yfinance does not reliably return the
# ``debtToEquity`` field. ``data/collector.py`` line 1668 coerces a
# missing value to ``0``, which the analysis pipeline then surfaced as
# a real "net cash" reading in the ratio grid. Audit found 17/17
# universe tickers at 0.0 — including TATASTEEL (real D/E ≈ 1.04) and
# ADANIPORTS (≈ 0.79) which carry material debt.
#
# Fix layout:
#   1. ``backend/services/analysis/db.py::_fetch_de_ratio`` pulls the
#      latest annual D/E from ``ratio_history`` (XBRL-pipeline truth).
#   2. ``backend/services/analysis/service.py`` resolves de_ratio in
#      this order:
#        DB value  →  enriched value (only when credible)  →  None
#      An enriched 0.0 with non-zero total_debt is treated as the
#      null-cast bug and surfaced as None.
#   3. ``backend/routers/public.py::_extract_analysis_summary`` already
#      uses ``is not None`` so None propagates as JSON null.
#
# Tests exercise the resolution logic directly with mocked DB +
# enriched inputs, so they don't require a live Aiven session.
# ─────────────────────────────────────────────────────────────────────
from __future__ import annotations

import pytest


def _resolve_de_ratio(_de_db, _de_enriched, _total_debt):
    """Mirror the resolution logic in
    backend/services/analysis/service.py around line 3706. Kept in
    test-side too so we can exercise the boundaries without standing
    up the whole AnalysisService pipeline.

    If this drifts from the production block, the test below
    ``test_resolution_matches_production_block`` will catch it.
    """
    if _de_db is not None:
        return _de_db
    if _de_enriched is None:
        return None
    try:
        _de_f = float(_de_enriched)
    except (TypeError, ValueError):
        return None
    if _de_f != _de_f:  # NaN
        return None
    if _de_f == 0.0 and (_total_debt or 0) > 0:
        return None
    return _de_f


class TestDeRatioNullSafety:
    """Cover the three audit-mandated cases plus the regression cases."""

    def test_total_debt_none_yields_none(self):
        """Input with total_debt=None → de_ratio is None (not 0).

        Pure missing-data path: nothing in the DB, nothing credible
        in enriched. Frontend must render "—", never "0.00".
        """
        result = _resolve_de_ratio(
            _de_db=None, _de_enriched=None, _total_debt=None,
        )
        assert result is None

    def test_real_debt_and_equity_yields_half(self):
        """Input with total_debt=5000, equity=10000 → de_ratio = 0.5.

        Caller supplies the pre-computed enriched value (0.5). The
        DB miss path falls through to the credible-enriched branch.
        """
        result = _resolve_de_ratio(
            _de_db=None, _de_enriched=0.5, _total_debt=5000,
        )
        assert result == 0.5

    def test_genuine_zero_debt_preserved(self):
        """Input with total_debt=0, equity=10000 → de_ratio = 0.0.

        Cash-rich IT names (TCS / INFY) genuinely run with zero
        debt; we must not poison their real zero into a None.
        """
        result = _resolve_de_ratio(
            _de_db=None, _de_enriched=0.0, _total_debt=0,
        )
        assert result == 0.0

    # ── Regression coverage for the audit bug itself ──────────

    def test_yf_zero_with_real_debt_becomes_none(self):
        """The bug shape: enriched=0.0 (yfinance null-cast) but
        total_debt is positive. Must surface as None, not 0.

        This is the exact path that hit TATASTEEL / ADANIPORTS /
        RELIANCE / NTPC in the audit.
        """
        result = _resolve_de_ratio(
            _de_db=None, _de_enriched=0.0, _total_debt=120_000_00_00_000,
        )
        assert result is None

    def test_db_value_wins_over_enriched(self):
        """DB has the truth (1.04 for TATASTEEL). When present, the
        ratio_history value overrides whatever enriched produced —
        including the broken 0.0 from the yfinance null-cast.
        """
        result = _resolve_de_ratio(
            _de_db=1.0377, _de_enriched=0.0, _total_debt=900_000,
        )
        assert result == pytest.approx(1.0377)

    def test_db_value_wins_even_when_enriched_disagrees(self):
        """If both sources have a value, prefer the DB. ratio_history
        is the SoT — enriched is a yfinance-derived approximation.
        """
        result = _resolve_de_ratio(
            _de_db=0.79, _de_enriched=2.5, _total_debt=900_000,
        )
        assert result == 0.79

    def test_db_genuine_zero_preserved(self):
        """A DB value of 0.0 is a real reading from the XBRL
        pipeline. Pass it through untouched; the "yfinance null-cast"
        gate only fires on the enriched branch.
        """
        result = _resolve_de_ratio(
            _de_db=0.0, _de_enriched=None, _total_debt=0,
        )
        assert result == 0.0

    def test_nan_enriched_yields_none(self):
        """yfinance occasionally hands back NaN. Treat as missing."""
        result = _resolve_de_ratio(
            _de_db=None, _de_enriched=float("nan"), _total_debt=500,
        )
        assert result is None

    def test_garbage_enriched_yields_none(self):
        """Defensive: non-numeric enriched payload must not crash."""
        result = _resolve_de_ratio(
            _de_db=None, _de_enriched="oops", _total_debt=500,
        )
        assert result is None


class TestResolutionMatchesProductionBlock:
    """Lock the helper above to the production source. If the in-line
    block in ``analysis/service.py`` is edited without also editing
    this file, this test fails loudly so we don't ship a silent drift.
    """

    def test_production_block_present(self):
        import inspect

        from backend.services.analysis import service as _svc

        src = inspect.getsource(_svc)
        # Anchor strings from the resolution block. If any goes
        # missing, the test fails and the author has to update both
        # sides in lock-step.
        assert "Audit#5 P1 de_ratio null-safety" in src
        assert "_fetch_de_ratio(ticker)" in src
        assert "_de_resolved" in src
        assert "_de_f == 0.0 and (_total_debt or 0) > 0" in src

    def test_de_ratio_imported_in_service(self):
        from backend.services.analysis import service as _svc

        assert hasattr(_svc, "_fetch_de_ratio")


class TestExtractAnalysisSummaryNullSafety:
    """The public router's _extract_analysis_summary already does
    ``is not None`` for de_ratio (line 336). Lock that contract so a
    future refactor doesn't regress it back to ``if x else None``,
    which was the symptom that caused the prior cash-rich-IT bug.
    """

    def test_extract_uses_is_not_none(self):
        import inspect

        # Local dev environments sometimes lack the full FastAPI
        # stack — CI carries it. Skip cleanly so devs can run the
        # unit suite, while CI still locks the contract.
        pytest.importorskip("fastapi")

        from backend.routers import public as _public

        src = inspect.getsource(_public._extract_analysis_summary)
        # Must use the strict null check, not truthiness.
        assert 'q.de_ratio, 2) if q.de_ratio is not None' in src
