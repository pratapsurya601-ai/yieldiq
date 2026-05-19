"""Tests for the /api/v1/admin/story-dcf-overrides endpoints.

The endpoints are read + preview only — operators submit a PR to
actually change config/story_dcf_overrides.json. These tests lock
in:

  * Authentication is required (anonymous → 401/403)
  * GET returns both overrides + industry_defaults + the read-only note
  * /preview rejects unsupported sectors with 400
  * /preview applies the hypothetical override on top of the industry
    default and produces a fair_value + in_band flag
  * /preview can simulate "no override" by omitting the override key
  * /audit returns one row per ticker in the override file
"""
from __future__ import annotations

import pytest

# Skip the whole module when fastapi isn't installed (e.g. local dev
# machine without the Railway runtime deps). CI installs the full
# requirements set and runs every test.
pytest.importorskip("fastapi")


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


# ── Auth ──────────────────────────────────────────────────────────


def _anon_client():
    from fastapi.testclient import TestClient
    try:
        from backend.main import app
    except ModuleNotFoundError as exc:
        pytest.skip(f"backend.main import failed in this env: {exc}")
    return TestClient(app)


def test_story_dcf_overrides_requires_auth():
    client = _anon_client()
    r = client.get("/api/v1/admin/story-dcf-overrides")
    assert r.status_code in (401, 403)


def test_story_dcf_preview_requires_auth():
    client = _anon_client()
    r = client.post(
        "/api/v1/admin/story-dcf-overrides/preview",
        json={
            "ticker": "PAYTM", "sector": "payments",
            "revenue_cr": 10000, "shares_cr": 63, "current_price": 900,
        },
    )
    assert r.status_code in (401, 403)


# ── GET ────────────────────────────────────────────────────────────


def test_get_returns_overrides_and_defaults():
    client, app, admin_mod = _build_client_with_admin_override()
    try:
        r = client.get("/api/v1/admin/story-dcf-overrides")
        assert r.status_code == 200
        body = r.json()
        assert "overrides" in body
        assert "industry_defaults" in body
        # PAYTM is in the shipped override file
        assert "PAYTM" in body["overrides"]
        # README/note keys must not leak
        assert not any(k.startswith("_") for k in body["overrides"].keys())
        # Industry defaults table has the 5 known industries
        for key in ("payments", "ecommerce", "fintech_broker",
                    "wealth_mgmt", "insurance_aggregator"):
            assert key in body["industry_defaults"], key
        # Each default carries the required fields
        d = body["industry_defaults"]["payments"]
        for f in ("initial_growth", "target_op_margin", "wacc",
                  "reinvestment_rate", "confidence_cap"):
            assert f in d
        # Read-only contract is documented in the response
        assert "submit a PR" in body["_meta"]["note"]
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)


# ── PREVIEW ───────────────────────────────────────────────────────


def test_preview_rejects_unsupported_sector():
    client, app, admin_mod = _build_client_with_admin_override()
    try:
        r = client.post(
            "/api/v1/admin/story-dcf-overrides/preview",
            json={
                "ticker": "RELIANCE", "sector": "energy",
                "revenue_cr": 100000, "shares_cr": 676, "current_price": 1300,
            },
        )
        assert r.status_code == 400
        assert "story-DCF eligible" in r.json()["detail"]
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)


def test_preview_uses_industry_default_when_no_override():
    """Omitting the override key → engine runs with INDUSTRY_STORY_DEFAULTS
    for the sector. Must produce a finite fair_value for healthy
    inputs."""
    client, app, admin_mod = _build_client_with_admin_override()
    try:
        r = client.post(
            "/api/v1/admin/story-dcf-overrides/preview",
            json={
                "ticker": "TESTPLATFORM", "sector": "fintech_broker",
                "revenue_cr": 4900, "shares_cr": 9, "current_price": 2500,
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "ok"
        assert body["industry_key"] == "fintech_broker"
        # default fintech_broker params surface in the response
        assert body["params"]["initial_growth"] == pytest.approx(0.20)
        assert body["params"]["target_op_margin"] == pytest.approx(0.20)
        # FV is finite and positive
        assert body["result"]["fair_value"] > 0
        assert body["result"]["in_safety_net_band"] in (True, False)
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)


def test_preview_applies_override_on_top_of_default():
    """Supplied override fields overlay onto the industry default."""
    client, app, admin_mod = _build_client_with_admin_override()
    try:
        r = client.post(
            "/api/v1/admin/story-dcf-overrides/preview",
            json={
                "ticker": "TESTPLATFORM", "sector": "fintech_broker",
                "revenue_cr": 4900, "shares_cr": 9, "current_price": 2500,
                "override": {
                    "initial_growth": 0.30,
                    "target_op_margin": 0.25,
                },
            },
        )
        assert r.status_code == 200
        body = r.json()
        # Override values applied
        assert body["params"]["initial_growth"] == pytest.approx(0.30)
        assert body["params"]["target_op_margin"] == pytest.approx(0.25)
        # Unspecified fields inherit from fintech_broker default
        assert body["params"]["reinvestment_rate"] == pytest.approx(0.60)
        assert body["params"]["wacc"] == pytest.approx(0.13)
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)


def test_preview_returns_engine_none_when_model_collapses():
    """Extreme inputs (huge reinvestment + low margin + tiny revenue)
    produce a model collapse — the endpoint returns status=
    'engine_returned_none' with a guidance reason instead of 500."""
    client, app, admin_mod = _build_client_with_admin_override()
    try:
        r = client.post(
            "/api/v1/admin/story-dcf-overrides/preview",
            json={
                "ticker": "TINY", "sector": "ecommerce",
                "revenue_cr": 10, "shares_cr": 1000, "current_price": 1000,
                "override": {
                    "target_op_margin": 0.02,
                    "reinvestment_rate": 0.95,
                },
            },
        )
        assert r.status_code == 200
        body = r.json()
        assert body["status"] == "engine_returned_none"
        assert "FCFFs" in body["reason"]
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)


def test_preview_includes_fv_cmp_ratio_and_band_flag():
    client, app, admin_mod = _build_client_with_admin_override()
    try:
        r = client.post(
            "/api/v1/admin/story-dcf-overrides/preview",
            json={
                "ticker": "NUVAMA", "sector": "wealth management",
                "revenue_cr": 2800, "shares_cr": 4, "current_price": 6500,
            },
        )
        assert r.status_code == 200
        body = r.json()
        result = body["result"]
        assert "fv_cmp_ratio" in result
        assert "in_safety_net_band" in result
        if result["fv_cmp_ratio"] is not None:
            assert isinstance(result["fv_cmp_ratio"], float)
            assert isinstance(result["in_safety_net_band"], bool)
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)


# ── AUDIT ──────────────────────────────────────────────────────────


def test_audit_returns_row_per_override_ticker():
    client, app, admin_mod = _build_client_with_admin_override()
    try:
        r = client.get("/api/v1/admin/story-dcf-overrides/audit")
        assert r.status_code == 200
        body = r.json()
        assert "rows" in body
        assert body["total"] == len(body["rows"])
        tickers = {row["ticker"] for row in body["rows"]}
        # PAYTM, ZOMATO, POLICYBZR all known overrides
        assert "PAYTM" in tickers
        assert "ZOMATO" in tickers
        # KNOWN_OUT_OF_BAND is exposed (so frontend can label rows)
        assert isinstance(body["known_out_of_band"], list)
        # PAYTM is documented as known-out-of-band
        assert "PAYTM" in body["known_out_of_band"]
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)


def test_audit_flags_known_out_of_band_for_review():
    client, app, admin_mod = _build_client_with_admin_override()
    try:
        r = client.get("/api/v1/admin/story-dcf-overrides/audit")
        assert r.status_code == 200
        body = r.json()
        # Every row carrying a known_out_of_band ticker must have
        # needs_review=true
        by_t = {row["ticker"]: row for row in body["rows"]}
        for t in body["known_out_of_band"]:
            if t in by_t:
                assert by_t[t]["needs_review"] is True, (
                    f"{t} is in KNOWN_OUT_OF_BAND but needs_review=False"
                )
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)
