"""Tests for scripts/post_deploy_smoke_test.py.

We monkey-patch the module's `fetch` function so no network I/O occurs.
"""
from __future__ import annotations

import importlib.util
import json
import pathlib
import sys

import pytest

# Load scripts/post_deploy_smoke_test.py as a module without requiring it to
# sit on PYTHONPATH (it lives in scripts/, not in a package).
_REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
_SCRIPT_PATH = _REPO_ROOT / "scripts" / "post_deploy_smoke_test.py"
_spec = importlib.util.spec_from_file_location("post_deploy_smoke_test", _SCRIPT_PATH)
assert _spec and _spec.loader
smoke = importlib.util.module_from_spec(_spec)
sys.modules["post_deploy_smoke_test"] = smoke
_spec.loader.exec_module(smoke)  # type: ignore[union-attr]


# ---------------------------------------------------------------------------
# Synthetic API responses keyed by ticker.
#
# These satisfy every anchor in SMOKE_TEST_ANCHORS:
#   - cmp inside cmp_band
#   - fv inside fv_band (where applicable)
#   - verdict in verdict_set
#   - valuation_model in method_set
# ---------------------------------------------------------------------------
ALL_PASS_RESPONSES: dict[str, dict] = {
    "TCS.NS": {
        "ticker": "TCS.NS", "current_price": 3000.0, "price": 3000.0,
        "fair_value": 3200.0, "verdict": "undervalued",
        "valuation_model": "dcf",
    },
    "INFY.NS": {
        "ticker": "INFY.NS", "current_price": 1500.0, "price": 1500.0,
        "fair_value": 1800.0, "verdict": "fairly_valued",
        "valuation_model": "dcf",
    },
    "HDFCBANK.NS": {
        "ticker": "HDFCBANK.NS", "current_price": 900.0, "price": 900.0,
        "fair_value": 1000.0, "verdict": "fairly_valued",
        "valuation_model": "pb_ratio",
    },
    "HINDUNILVR.NS": {
        "ticker": "HINDUNILVR.NS", "current_price": 2400.0, "price": 2400.0,
        "fair_value": 2500.0, "verdict": "fairly_valued",
        "valuation_model": "dcf",
    },
    "RELIANCE.NS": {
        "ticker": "RELIANCE.NS", "current_price": 1400.0, "price": 1400.0,
        "fair_value": 1500.0, "verdict": "fairly_valued",
        "valuation_model": "peer_capped",
    },
    "POWERGRID.NS": {
        "ticker": "POWERGRID.NS", "current_price": 300.0, "price": 300.0,
        "fair_value": 350.0, "verdict": "undervalued",
        "valuation_model": "rate_base",
    },
    "NTPC.NS": {
        "ticker": "NTPC.NS", "current_price": 400.0, "price": 400.0,
        "fair_value": 500.0, "verdict": "undervalued",
        "valuation_model": "rate_base",
    },
    "SUNPHARMA.NS": {
        "ticker": "SUNPHARMA.NS", "current_price": 1900.0, "price": 1900.0,
        "fair_value": 1500.0, "verdict": "overvalued",
        "valuation_model": "dcf",
    },
    "MANKIND.NS": {
        "ticker": "MANKIND.NS", "current_price": 2200.0, "price": 2200.0,
        "fair_value": 1200.0, "verdict": "overvalued",
        "valuation_model": "dcf",
    },
    "NIFTYBEES.NS": {
        "ticker": "NIFTYBEES.NS", "current_price": 350.0, "price": 350.0,
        "fair_value": 0.0, "verdict": "data_limited",
        "valuation_model": "etf_nav_based",
    },
    "EMBASSY.NS": {
        "ticker": "EMBASSY.NS", "current_price": 370.0, "price": 370.0,
        "fair_value": 0.0, "verdict": "data_limited",
        "valuation_model": "reit_nav_dpu_required",
    },
    "BAJAJHLDNG.NS": {
        "ticker": "BAJAJHLDNG.NS", "current_price": 10000.0, "price": 10000.0,
        "fair_value": 0.0, "verdict": "data_limited",
        "valuation_model": "holding_company_sotp_required",
    },
}


def _make_fetch(responses: dict[str, dict]):
    """Return a fake fetch(url) -> (status, json) using the provided table."""
    def _fetch(url: str, timeout: int = 30):
        # url ends in /api/v1/public/stock-summary/{TICKER}
        ticker = url.rsplit("/", 1)[-1]
        if ticker in responses:
            return 200, responses[ticker]
        return 404, None
    return _fetch


def test_all_pass_returns_zero(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(smoke, "fetch", _make_fetch(ALL_PASS_RESPONSES))
    report_path = tmp_path / "smoke_report.json"
    rc = smoke.run(
        api_base="http://fake.local",
        report_path=str(report_path),
        verbose=True,
    )
    out = capsys.readouterr().out
    assert rc == 0, f"expected rc=0, got {rc}\nOUTPUT:\n{out}"
    assert "12/12 passed" in out
    assert "[FAIL]" not in out

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["total"] == 12
    assert report["passed"] == 12
    assert report["failed"] == 0
    assert report["blocking"] is False


def test_single_ticker_out_of_band_fails(monkeypatch, tmp_path, capsys):
    bad = {k: dict(v) for k, v in ALL_PASS_RESPONSES.items()}
    # Knock POWERGRID's fair_value way out of the [250, 380] band.
    bad["POWERGRID.NS"]["fair_value"] = 9999.0

    monkeypatch.setattr(smoke, "fetch", _make_fetch(bad))
    report_path = tmp_path / "smoke_report.json"
    rc = smoke.run(
        api_base="http://fake.local",
        report_path=str(report_path),
        verbose=False,
    )
    out = capsys.readouterr().out
    assert rc == 1, f"expected rc=1, got {rc}\nOUTPUT:\n{out}"
    assert "[FAIL] POWERGRID.NS" in out
    assert "outside expected band" in out

    report = json.loads(report_path.read_text(encoding="utf-8"))
    assert report["failed"] == 1
    failing = [r for r in report["results"] if not r["passed"]]
    assert len(failing) == 1
    assert failing[0]["ticker"] == "POWERGRID.NS"


def test_under_review_is_soft_pass_for_etf(monkeypatch, capsys):
    resp = {k: dict(v) for k, v in ALL_PASS_RESPONSES.items()}
    # NIFTYBEES is transient_ok=True -- under_review should be a soft pass.
    resp["NIFTYBEES.NS"] = {
        "status": "under_review",
        "ticker": "NIFTYBEES.NS",
        "reason": "cache_miss_recompute_failed",
    }
    monkeypatch.setattr(smoke, "fetch", _make_fetch(resp))
    rc = smoke.run(api_base="http://fake.local", report_path=None, verbose=False)
    assert rc == 0


def test_under_review_is_hard_fail_for_dcf_anchor(monkeypatch, capsys):
    resp = {k: dict(v) for k, v in ALL_PASS_RESPONSES.items()}
    # TCS has no transient_ok -- under_review must be flagged as a failure.
    resp["TCS.NS"] = {
        "status": "under_review",
        "ticker": "TCS.NS",
        "reason": "cache_miss_recompute_failed",
    }
    monkeypatch.setattr(smoke, "fetch", _make_fetch(resp))
    rc = smoke.run(api_base="http://fake.local", report_path=None, verbose=False)
    out = capsys.readouterr().out
    assert rc == 1
    assert "[FAIL] TCS.NS" in out
    assert "under_review" in out


def test_anchor_table_covers_all_required_paths():
    """Guard against accidentally deleting an anchor that covers a unique path."""
    methods_covered = set()
    for spec in smoke.SMOKE_TEST_ANCHORS.values():
        for m in spec.get("method_set", ()):
            methods_covered.add(m)
    # These are the production paths we want at least one anchor for.
    required = {"dcf", "rate_base", "etf_nav_based"}
    missing = required - methods_covered
    assert not missing, f"smoke anchors missing coverage for: {missing}"


def test_anchor_count_is_twelve():
    assert len(smoke.SMOKE_TEST_ANCHORS) == 12
