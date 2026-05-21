"""Day-55 (2026-05-21): /admin/validation-trace/{ticker} diagnostic.

Source-text regression guards for the new admin diagnostic that
surfaces validate_analysis issue lists for a single ticker.

Built to investigate Bug D (ITCHOTELS / ABLBL both return
under_review with issue_count >= 2 but the public endpoint hides
which checks failed).
"""
from __future__ import annotations
from pathlib import Path


_ADMIN = Path(__file__).resolve().parents[2] / "backend" / "routers" / "admin.py"


def test_validation_trace_endpoint_defined():
    src = _ADMIN.read_text(encoding="utf-8")
    assert '@router.get("/validation-trace/{ticker}")' in src
    assert "async def get_validation_trace(" in src


def test_validation_trace_gated_by_require_admin():
    src = _ADMIN.read_text(encoding="utf-8")
    # The endpoint must depend on require_admin; without it, anyone
    # could enumerate validation failures to fingerprint our engine.
    idx = src.index("async def get_validation_trace(")
    head = src[idx : idx + 600]
    assert "Depends(require_admin)" in head


def test_validation_trace_returns_full_issue_list():
    src = _ADMIN.read_text(encoding="utf-8")
    # The whole point: surface issues + failed_fields that the
    # public quarantine response deliberately hides.
    assert '"issues": list(vr.issues)' in src
    assert '"failed_fields": list(vr.failed_fields)' in src
    assert '"severity": vr.severity' in src


def test_validation_trace_includes_payload_snapshot():
    src = _ADMIN.read_text(encoding="utf-8")
    # Snapshot of the fields that typically trip validation —
    # without these the issue strings ("wacc=0.4 out of bounds")
    # are hard to act on.
    for field in (
        '"fair_value"', '"wacc"', '"terminal_growth"',
        '"fair_value_ratio"', '"data_issues"',
        '"valuation_engine_used"', '"market_cap_inr"',
    ):
        assert field in src, f"snapshot missing field {field}"


def test_validation_trace_uses_sanitize_error_on_exception():
    """Compute can crash on delisted/missing-data tickers; the
    error path must not leak DB URLs or secrets."""
    src = _ADMIN.read_text(encoding="utf-8")
    assert "_sanitize_error(exc, 'validation-trace')" in src


def test_validation_trace_calls_analysis_service():
    src = _ADMIN.read_text(encoding="utf-8")
    # Same compute path the public endpoint uses on cache miss
    # (so the validator sees identical input).
    assert "from backend.services.analysis_service import AnalysisService" in src
    assert "svc.get_full_analysis(ticker)" in src


def test_validation_trace_calls_validate_analysis():
    src = _ADMIN.read_text(encoding="utf-8")
    assert "from backend.services.validators import validate_analysis" in src
    assert "validate_analysis(response)" in src
