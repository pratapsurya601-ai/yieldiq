# backend/tests/test_insurance_appraisal.py
#
# Covers the Appraisal-Value engine and the admin EV/VNB entry
# endpoints shipped in PR feat/insurance-ev-admin-ui.
#
# Test surface:
#   1. Engine math — known EV/VNB/g/RDR → expected FV.
#   2. N-multiplier clamps — floor 8, ceiling 25.
#   3. CRUD admin endpoints (list / upsert / delete) via TestClient
#      with the require_admin dependency overridden.
#   4. Auth gating — anon request returns 401/403.
#   5. Validation — bad ticker / negative EV / future period.
#   6. Routing — analysis service uses Appraisal Value when row
#      exists, falls through to existing path when no row exists.
#
# Run: pytest backend/tests/test_insurance_appraisal.py -v
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


# ─────────────────────────────────────────────────────────────────
# Pure engine tests (no DB).
# ─────────────────────────────────────────────────────────────────
def test_appraisal_value_known_inputs():
    """EV ₹500/share + VNB ₹50/share + g=12% + RDR=13% → FV ₹1750.

    N_raw = (1 + 0.12) / (0.13 - 0.12) = 112, clamped at 25.
    FV = 500 + 25 × 50 = 1750.
    """
    from backend.services.insurance_appraisal_service import (
        compute_appraisal_fair_value,
    )
    out = compute_appraisal_fair_value(
        ticker="HDFCLIFE",
        ev_per_share=500.0,
        vnb_per_share=50.0,
        growth=0.12,
        rdr=0.13,
    )
    assert out is not None
    assert out["valuation_method"] == "appraisal_value"
    assert out["fair_value"] == pytest.approx(1750.0, abs=0.5)
    meta = out["_meta"]
    assert meta["n_multiplier"] == pytest.approx(25.0, abs=0.001)


def test_n_multiplier_clamped_to_25():
    """High-growth case — N must cap at 25 (raw would blow up)."""
    from backend.services.insurance_appraisal_service import (
        compute_appraisal_fair_value,
    )
    out = compute_appraisal_fair_value(
        ticker="HDFCLIFE",
        ev_per_share=400.0,
        vnb_per_share=40.0,
        growth=0.30,  # will be clamped to 0.18 internally
        rdr=0.10,
    )
    assert out is not None
    assert out["_meta"]["n_multiplier"] <= 25.0
    # FV strictly bounded above by EV + 25 × VNB.
    assert out["fair_value"] <= 400.0 + 25.0 * 40.0 + 0.01


def test_n_multiplier_clamped_to_8():
    """Low-growth case (LICI-like) — N must floor at 8."""
    from backend.services.insurance_appraisal_service import (
        compute_appraisal_fair_value,
    )
    out = compute_appraisal_fair_value(
        ticker="LICI",
        ev_per_share=1000.0,
        vnb_per_share=80.0,
        growth=0.01,  # extreme — clamped up to G_FLOOR
        rdr=0.10,
    )
    assert out is not None
    assert out["_meta"]["n_multiplier"] >= 8.0


def test_compute_returns_none_for_zero_ev():
    from backend.services.insurance_appraisal_service import (
        compute_appraisal_fair_value,
    )
    assert (
        compute_appraisal_fair_value(
            ticker="HDFCLIFE", ev_per_share=0, vnb_per_share=10, growth=0.10,
        )
        is None
    )


# ─────────────────────────────────────────────────────────────────
# Routing tests — patch the persistence-layer helpers so the engine
# routing branch in analysis/service.py can be exercised without a
# live Postgres.
# ─────────────────────────────────────────────────────────────────
def test_routing_no_entry_returns_none():
    """HDFCLIFE with no row → get_appraisal_fair_value_for_ticker
    returns None → analysis service falls through to current P/BV
    path (unchanged behaviour)."""
    from backend.services import insurance_appraisal_service as svc
    with patch.object(svc, "load_latest_appraisal_inputs", return_value=None):
        out = svc.get_appraisal_fair_value_for_ticker("HDFCLIFE", shares=2.16e9)
    assert out is None


def test_routing_with_entry_returns_appraisal_fv():
    """HDFCLIFE with a row → returns appraisal-based FV dict."""
    from backend.services import insurance_appraisal_service as svc
    fake_row = {
        "ticker": "HDFCLIFE",
        "period_end": date(2026, 3, 31),
        "embedded_value_cr": 50000.0,         # ₹50,000 Cr
        "value_new_business_cr": 3900.0,      # ₹3,900 Cr (TTM)
        "vnb_margin_pct": 26.5,
        "ev_growth_yoy_pct": 17.0,
        "source_url": "https://www.hdfclife.com/about-us/investor-relations",
        "entered_by": "test@yieldiq.in",
        "entered_at": None,
        "notes": "FY26 EV report",
    }
    # 2.16 billion diluted shares (approx HDFCLIFE actual).
    with patch.object(svc, "load_latest_appraisal_inputs", return_value=fake_row):
        out = svc.get_appraisal_fair_value_for_ticker("HDFCLIFE", shares=2.16e9)
    assert out is not None
    assert out["valuation_method"] == "appraisal_value"
    # FV must be positive and contain the as-of provenance.
    assert out["fair_value"] > 0
    assert out["_meta"]["period_end"] == "2026-03-31"
    assert out["_meta"]["source_url"]
    # EV/share = 50000 Cr × 1e7 / 2.16e9 ≈ ₹231/share, VNB/share ≈ ₹18.
    # With g=17% (clamped to 18%), RDR=9.5% → N ≈ (1.18)/(0.095-0.18) clamps to 25.
    # FV ≈ 231 + 25 × 18 ≈ ₹681 — squarely in the design-doc [600,800] band.
    assert 600.0 <= out["fair_value"] <= 800.0


def test_routing_missing_shares_returns_none():
    from backend.services import insurance_appraisal_service as svc
    with patch.object(svc, "load_latest_appraisal_inputs", return_value={
        "ticker": "HDFCLIFE", "period_end": date(2026, 3, 31),
        "embedded_value_cr": 50000.0,
    }):
        assert svc.get_appraisal_fair_value_for_ticker("HDFCLIFE", shares=0) is None
        assert svc.get_appraisal_fair_value_for_ticker("HDFCLIFE", shares=None) is None


# ─────────────────────────────────────────────────────────────────
# Admin endpoint tests via FastAPI TestClient, with require_admin
# overridden and the database execute path mocked.
# ─────────────────────────────────────────────────────────────────
def _build_client_with_admin_override():
    from fastapi.testclient import TestClient
    from backend.routers import admin as admin_mod
    try:
        from backend.main import app
    except ModuleNotFoundError as exc:
        pytest.skip(f"backend.main import failed in this env: {exc}")
    app.dependency_overrides[admin_mod.require_admin] = lambda: {
        "email": "test@yieldiq.in", "id": "test-admin",
    }
    return TestClient(app), app, admin_mod


def test_insurance_inputs_requires_auth():
    """Anonymous GET must return 401 or 403."""
    from fastapi.testclient import TestClient
    try:
        from backend.main import app
    except ModuleNotFoundError as exc:
        pytest.skip(f"backend.main import failed in this env: {exc}")
    client = TestClient(app)
    r = client.get("/api/v1/admin/insurance-inputs")
    assert r.status_code in (401, 403), (
        f"endpoint must require auth; got {r.status_code}"
    )


def test_insurance_inputs_post_rejects_non_insurance_ticker():
    client, app, admin_mod = _build_client_with_admin_override()
    try:
        r = client.post(
            "/api/v1/admin/insurance-inputs",
            json={
                "ticker": "RELIANCE",
                "period_end": "2026-03-31",
                "embedded_value_cr": 1000,
            },
        )
        assert r.status_code == 400
        assert "INSURANCE_TICKERS" in r.json().get("detail", "")
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)


def test_insurance_inputs_post_rejects_negative_ev():
    client, app, admin_mod = _build_client_with_admin_override()
    try:
        r = client.post(
            "/api/v1/admin/insurance-inputs",
            json={
                "ticker": "HDFCLIFE",
                "period_end": "2026-03-31",
                "embedded_value_cr": -10,
            },
        )
        assert r.status_code == 400
        assert "> 0" in r.json().get("detail", "")
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)


def test_insurance_inputs_post_rejects_future_period():
    client, app, admin_mod = _build_client_with_admin_override()
    try:
        future = (date.today() + timedelta(days=30)).isoformat()
        r = client.post(
            "/api/v1/admin/insurance-inputs",
            json={
                "ticker": "HDFCLIFE",
                "period_end": future,
                "embedded_value_cr": 50000,
            },
        )
        assert r.status_code == 400
        assert "future" in r.json().get("detail", "").lower()
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)


def test_insurance_inputs_crud_roundtrip_with_mocked_db():
    """End-to-end list / upsert / delete with the SQLAlchemy session
    layer mocked. Verifies our SQL parameter binding shape and the
    response envelopes without needing a live Postgres."""
    from unittest.mock import MagicMock
    client, app, admin_mod = _build_client_with_admin_override()

    fake_session = MagicMock()
    # GET path: return one row.
    fake_session.execute.return_value.fetchall.return_value = [
        (
            "HDFCLIFE", date(2026, 3, 31), 50000.0, 3900.0, 26.5, 17.0,
            "https://www.hdfclife.com/", "admin@yieldiq.in", None,
            "first row",
        ),
    ]
    # DELETE path: 1 row affected.
    fake_session.execute.return_value.rowcount = 1
    fake_session_factory = MagicMock(return_value=fake_session)

    try:
        with patch("data_pipeline.db.Session", fake_session_factory):
            # LIST
            r = client.get("/api/v1/admin/insurance-inputs")
            assert r.status_code == 200
            body = r.json()
            assert body["count"] == 1
            assert body["rows"][0]["ticker"] == "HDFCLIFE"
            assert body["rows"][0]["embedded_value_cr"] == 50000.0

            # UPSERT
            r = client.post(
                "/api/v1/admin/insurance-inputs",
                json={
                    "ticker": "HDFCLIFE",
                    "period_end": "2026-03-31",
                    "embedded_value_cr": 50000,
                    "value_new_business_cr": 3900,
                    "vnb_margin_pct": 26.5,
                    "ev_growth_yoy_pct": 17.0,
                    "source_url": "https://www.hdfclife.com/",
                    "notes": "first row",
                },
            )
            assert r.status_code == 200, r.text
            assert r.json()["status"] == "ok"
            assert r.json()["ticker"] == "HDFCLIFE"
            assert r.json()["entered_by"] == "test@yieldiq.in"

            # DELETE
            r = client.delete(
                "/api/v1/admin/insurance-inputs",
                params={"ticker": "HDFCLIFE", "period_end": "2026-03-31"},
            )
            assert r.status_code == 200
            assert r.json()["status"] == "deleted"
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)


def test_insurance_inputs_delete_404_when_no_row():
    from unittest.mock import MagicMock
    client, app, admin_mod = _build_client_with_admin_override()
    fake_session = MagicMock()
    fake_session.execute.return_value.rowcount = 0
    fake_session_factory = MagicMock(return_value=fake_session)

    try:
        with patch("data_pipeline.db.Session", fake_session_factory):
            r = client.delete(
                "/api/v1/admin/insurance-inputs",
                params={"ticker": "HDFCLIFE", "period_end": "2026-03-31"},
            )
            assert r.status_code == 404
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)


# ─────────────────────────────────────────────────────────────────
# Sanity test: HDFCLIFE is in the insurance ticker set so the admin
# endpoint accepts it. Guards against an accidental future revert of
# the 2026-05-18 _INSURANCE_TICKERS expansion (LICI/ICICIPRULI).
# ─────────────────────────────────────────────────────────────────
def test_life_insurers_in_insurance_ticker_set():
    from backend.services.analysis.constants import _INSURANCE_TICKERS
    for t in ("HDFCLIFE", "SBILIFE", "ICICIPRULI", "LICI"):
        assert t in _INSURANCE_TICKERS, f"{t} must be in _INSURANCE_TICKERS"
