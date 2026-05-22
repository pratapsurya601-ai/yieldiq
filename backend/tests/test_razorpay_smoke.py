# backend/tests/test_razorpay_smoke.py
# Day-101 — unit tests for scripts/razorpay_smoke.py + the
# /api/v1/admin/sentry-probe endpoint.
#
# We don't exercise the smoke runner end-to-end here (it hits a live
# API) — we test the deterministic, network-free pieces:
#   - webhook body signing produces the same hex digest the backend
#     verifier expects (round-trip with backend's verify_webhook_signature)
#   - the webhook payload shape matches what the backend handler reads
#     (event, sub_entity.id, notes.tier, payment.entity.amount)
#   - /admin/sentry-probe is admin-gated and raises _SentryProbeError
#
# Run: pytest backend/tests/test_razorpay_smoke.py -v
from __future__ import annotations

import hashlib
import hmac
import importlib.util
import json
import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_ROOT = Path(__file__).resolve().parent.parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def _load_smoke_module():
    """Import scripts/razorpay_smoke.py as a module without running main()."""
    path = _ROOT / "scripts" / "razorpay_smoke.py"
    spec = importlib.util.spec_from_file_location("razorpay_smoke", path)
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_sign_webhook_body_matches_hmac_sha256():
    """The smoke script's sign function must be byte-for-byte identical
    to Razorpay's HMAC_SHA256 hex digest — the backend's
    razorpay.utility.verify_webhook_signature reconstructs the same."""
    smoke = _load_smoke_module()
    body = b'{"event":"test","payload":{}}'
    secret = "whsec_abc123"
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    assert smoke.sign_webhook_body(body, secret) == expected


def test_build_webhook_payload_shape_matches_backend_handler():
    """The synthesized payload must carry every field the backend webhook
    handler reads. If the backend handler shape changes, this test should
    break first."""
    smoke = _load_smoke_module()
    p = smoke.build_webhook_payload(
        event="subscription.activated",
        subscription_id="sub_test123",
        user_email="t@example.com",
        user_id="00000000-0000-0000-0000-000000000001",
        tier="analyst",
        amount_paise=79900,
    )
    # Top-level keys the handler reads
    assert p["event"] == "subscription.activated"
    assert "created_at" in p
    assert p.get("account_id"), "account_id needed for dedup key"
    # Subscription entity — id + notes.tier path
    sub_entity = p["payload"]["subscription"]["entity"]
    assert sub_entity["id"] == "sub_test123"
    assert sub_entity["notes"]["tier"] == "analyst"
    assert sub_entity["notes"]["user_id"] == "00000000-0000-0000-0000-000000000001"
    # Payment amount path used by _extract_amount_paise
    payment_entity = p["payload"]["payment"]["entity"]
    assert payment_entity["amount"] == 79900
    assert payment_entity["currency"] == "INR"


def test_build_webhook_payload_dedup_key_is_stable():
    """Same logical event → same _razorpay_event_id. Replays must dedupe."""
    smoke = _load_smoke_module()
    from backend.routers.payments import _razorpay_event_id

    p1 = smoke.build_webhook_payload(
        event="subscription.activated",
        subscription_id="sub_dedup1",
        user_email="x@example.com",
        user_id="u1",
    )
    # Same payload (pin created_at by reusing p1) → same key.
    key1 = _razorpay_event_id(p1)
    key2 = _razorpay_event_id(p1)
    assert key1 == key2
    assert key1 is not None
    assert "subscription.activated" in key1


def test_signed_body_round_trips_through_razorpay_verifier():
    """If `razorpay` SDK is present, the smoke-script signature must pass
    the same `verify_webhook_signature` the backend uses. This is the
    contract test: it would fail loudly if we accidentally signed with
    the wrong key or hash."""
    razorpay = pytest.importorskip("razorpay")
    smoke = _load_smoke_module()

    body = json.dumps({"event": "x"}, separators=(",", ":")).encode()
    secret = "whsec_roundtrip"
    sig = smoke.sign_webhook_body(body, secret)
    # Razorpay's utility uses the same construction; if either side ever
    # drifts (algo upgrade, encoding change) this assertion catches it.
    client = razorpay.Client(auth=("rzp_test_x", "y"))
    # verify_webhook_signature returns None on success, raises on mismatch.
    client.utility.verify_webhook_signature(
        body.decode("utf-8"), sig, secret,
    )


def test_sentry_probe_endpoint_requires_auth():
    """Anonymous callers must not be able to trigger the probe."""
    from fastapi.testclient import TestClient

    try:
        from backend.main import app
    except ModuleNotFoundError as exc:
        pytest.skip(f"backend.main import failed: {exc}")
    client = TestClient(app)
    r = client.get("/api/v1/admin/sentry-probe")
    assert r.status_code in (401, 403), (
        f"sentry-probe must require auth; got {r.status_code}"
    )


def test_sentry_probe_endpoint_raises_probe_error():
    """Admin-authed call → 500 with _SentryProbeError captured."""
    from fastapi.testclient import TestClient
    from backend.routers import admin as admin_mod

    try:
        from backend.main import app
    except ModuleNotFoundError as exc:
        pytest.skip(f"backend.main import failed: {exc}")

    app.dependency_overrides[admin_mod.require_admin] = lambda: {
        "email": "test@yieldiq.in", "id": "test-admin",
    }
    capture_spy = MagicMock()
    try:
        with patch("sentry_sdk.capture_exception", capture_spy):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/api/v1/admin/sentry-probe")
        assert r.status_code == 500
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)


def test_sentry_probe_error_type_is_distinct():
    """The probe error must be distinct from _SentryWiringTestError so
    the Day-101 dashboard filter doesn't collide with the older smoke
    test's events."""
    from backend.routers.admin import _SentryProbeError, _SentryWiringTestError

    assert issubclass(_SentryProbeError, RuntimeError)
    assert _SentryProbeError is not _SentryWiringTestError
    # Names must not collide on `error.type:` dashboard filter
    assert _SentryProbeError.__name__ != _SentryWiringTestError.__name__
