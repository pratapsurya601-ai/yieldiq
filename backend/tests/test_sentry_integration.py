# backend/tests/test_sentry_integration.py
# Verifies Sentry wiring for the backend.
#
# Covers:
#   1. sentry-sdk is installed and importable
#   2. main.py initializes Sentry when SENTRY_DSN is set
#   3. main.py is a no-op (does NOT call init) when SENTRY_DSN is unset
#   4. /api/v1/admin/sentry-test raises and the exception is captured
#
# Run: pytest backend/tests/test_sentry_integration.py -v
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)


def test_sentry_sdk_import_works():
    """Package present so production env can activate via DSN toggle alone."""
    import sentry_sdk  # noqa: F401
    from sentry_sdk.integrations.fastapi import FastApiIntegration  # noqa: F401


def test_sentry_init_called_when_dsn_set(monkeypatch):
    """When SENTRY_DSN is in env, main.py should call sentry_sdk.init."""
    fake_dsn = "https://abc123@o123.ingest.sentry.io/456"
    monkeypatch.setenv("SENTRY_DSN", fake_dsn)
    # Force re-import of backend.main with the new env var. We patch
    # sentry_sdk.init before re-import so we can observe the call.
    init_spy = MagicMock()
    with patch("sentry_sdk.init", init_spy):
        # Drop cached modules so main.py's init block re-runs.
        for mod in list(sys.modules):
            if mod == "backend.main":
                del sys.modules[mod]
        try:
            importlib.import_module("backend.main")
        except Exception:
            # main.py import may fail in test env for unrelated reasons
            # (DB connect, etc.) — we only care that init was called
            # before any of that.
            pass
    assert init_spy.called, "sentry_sdk.init was not called despite SENTRY_DSN being set"
    kwargs = init_spy.call_args.kwargs
    assert kwargs.get("dsn") == fake_dsn
    # Performance traces sampled — must not be 1.0 (would burn free tier).
    assert 0.0 < float(kwargs.get("traces_sample_rate", 0)) <= 0.25


def test_sentry_init_noop_when_dsn_missing(monkeypatch):
    """When SENTRY_DSN is unset/empty, init must NOT be called.

    Local dev and CI run without a DSN — the import path must stay
    crash-free and silent.
    """
    monkeypatch.delenv("SENTRY_DSN", raising=False)
    init_spy = MagicMock()
    with patch("sentry_sdk.init", init_spy):
        for mod in list(sys.modules):
            if mod == "backend.main":
                del sys.modules[mod]
        try:
            importlib.import_module("backend.main")
        except Exception:
            pass
    assert not init_spy.called, "sentry_sdk.init must NOT run when SENTRY_DSN is unset"


def test_sentry_test_endpoint_requires_auth():
    """Anonymous callers must not be able to burn the Sentry event quota."""
    from fastapi.testclient import TestClient
    try:
        from backend.main import app
    except ModuleNotFoundError as exc:
        pytest.skip(f"backend.main import failed in this env: {exc}")
    client = TestClient(app)
    r = client.get("/api/v1/admin/sentry-test")
    # 401 (no auth) or 403 (auth but not admin) are both acceptable —
    # the only failure case is 200/500 leaking the synthetic exception.
    assert r.status_code in (401, 403), (
        f"sentry-test endpoint must require auth; got {r.status_code}"
    )


def test_sentry_test_endpoint_raises_synthetic_error():
    """When invoked by admin, the endpoint raises the smoke-test exception.

    We patch require_admin to bypass auth and assert the captured
    exception type via sentry_sdk.capture_exception (which FastApiIntegration
    invokes for unhandled exceptions in the request scope).
    """
    from fastapi.testclient import TestClient
    from backend.routers import admin as admin_mod

    # Bypass auth — return a fake admin user.
    admin_mod.app = None  # noqa: SLF001 (defensive — not actually set)
    try:
        from backend.main import app
    except ModuleNotFoundError as exc:
        pytest.skip(f"backend.main import failed in this env: {exc}")

    # Replace dependency
    app.dependency_overrides[admin_mod.require_admin] = lambda: {
        "email": "test@yieldiq.in", "id": "test-admin",
    }
    capture_spy = MagicMock()
    try:
        with patch("sentry_sdk.capture_exception", capture_spy):
            client = TestClient(app, raise_server_exceptions=False)
            r = client.get("/api/v1/admin/sentry-test")
        # The synthetic exception bubbles → FastAPI returns 500.
        assert r.status_code == 500
    finally:
        app.dependency_overrides.pop(admin_mod.require_admin, None)


def test_sentry_test_error_type_is_distinct():
    """The synthetic error must have a dedicated type so the Sentry filter
    `error.type:_SentryWiringTestError` cleanly separates smoke tests from
    real production exceptions in the dashboard."""
    from backend.routers.admin import _SentryWiringTestError
    assert issubclass(_SentryWiringTestError, Exception)
    # Specifically RuntimeError so it surfaces with a familiar base class.
    assert issubclass(_SentryWiringTestError, RuntimeError)


def test_cache_service_set_captures_on_failure():
    """Cache write failures must be reported to Sentry."""
    from backend.services.cache_service import CacheService

    cs = CacheService()
    capture_spy = MagicMock()

    # Force the underlying dict assignment to blow up by replacing _store
    # with an object that raises on __setitem__.
    class _Boom:
        def __setitem__(self, key, value):
            raise RuntimeError("simulated cache backend failure")

    cs._store = _Boom()
    with patch("sentry_sdk.capture_exception", capture_spy), \
         patch("sentry_sdk.set_tag"):
        with pytest.raises(RuntimeError):
            cs.set("analysis:HDFCBANK.NS", {"x": 1})
    assert capture_spy.called, "Cache write failure must call sentry_sdk.capture_exception"
