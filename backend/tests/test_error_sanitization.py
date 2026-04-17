# backend/tests/test_error_sanitization.py
"""
Regression test for the JWT_SECRET-in-error-string leak (2026-04-17).

Background: `/api/v1/debug/fv-history-stats` returned a Postgres error
whose message contained `JWT_SECRET=...` because the secret had been
concatenated into DATABASE_URL. The raw exception string was shipped
back to any unauthenticated caller via `HTTPException(detail=f"...: {e}")`.

`_sanitize_error` now stands between exceptions and response bodies:
it must NEVER include `str(exc)` in its return value.
"""
from backend.routers.admin import _sanitize_error


FAKE_SECRET = "s3cr3t_XXXXX"


def test_sanitize_error_omits_secret_value():
    """The secret-looking substring in the exception message must not leak."""
    exc = RuntimeError(f"connection failed: password={FAKE_SECRET} at host=db")
    sanitized = _sanitize_error(exc)

    assert FAKE_SECRET not in sanitized, (
        f"_sanitize_error leaked the secret value: {sanitized!r}"
    )
    assert "password=" not in sanitized, (
        f"_sanitize_error leaked the secret key/value pair: {sanitized!r}"
    )


def test_sanitize_error_includes_class_name():
    """Callers still need the exception type for triage."""
    exc = RuntimeError("irrelevant message")
    sanitized = _sanitize_error(exc)
    assert "RuntimeError" in sanitized


def test_sanitize_error_jwt_secret_case():
    """The exact JWT_SECRET pattern from the 2026-04-17 incident must be scrubbed."""
    exc = Exception(
        "psycopg2.OperationalError: invalid DSN "
        "'postgresql://u:pJWT_SECRET=2cacebdcc123abc@host/db'"
    )
    sanitized = _sanitize_error(exc)
    assert "2cacebdcc123abc" not in sanitized
    assert "JWT_SECRET" not in sanitized
