"""Day-100a (2026-05-22): PWA install funnel telemetry.

Locks the contract on POST /api/v1/telemetry/pwa-event:

  1. Valid event names (prompted/installed/dismissed/ios_hint_shown)
     return 200 with {"ok": true}.
  2. Unknown event names are rejected with 422 by Pydantic's Literal.
  3. Long UA strings are accepted but truncated to 80 chars in the log
     line so we never leak fingerprintable PII.
  4. No auth is required — the funnel includes pre-login installs.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.routers import telemetry as telemetry_router  # noqa: E402


@pytest.fixture()
def client() -> TestClient:
    app = FastAPI()
    app.include_router(telemetry_router.router)
    return TestClient(app)


def test_valid_events_accepted(client: TestClient) -> None:
    for event in ("prompted", "installed", "dismissed", "ios_hint_shown"):
        r = client.post(
            "/api/v1/telemetry/pwa-event",
            json={"event": event, "ua": "Mozilla/5.0"},
        )
        assert r.status_code == 200, (event, r.text)
        assert r.json() == {"ok": True}


def test_unknown_event_rejected(client: TestClient) -> None:
    r = client.post(
        "/api/v1/telemetry/pwa-event",
        json={"event": "garbage_value", "ua": "Mozilla/5.0"},
    )
    assert r.status_code == 422


def test_missing_event_rejected(client: TestClient) -> None:
    r = client.post("/api/v1/telemetry/pwa-event", json={"ua": "x"})
    assert r.status_code == 422


def test_ua_optional(client: TestClient) -> None:
    r = client.post("/api/v1/telemetry/pwa-event", json={"event": "prompted"})
    assert r.status_code == 200


def test_ua_truncated_to_80_chars(
    client: TestClient, caplog: pytest.LogCaptureFixture
) -> None:
    long_ua = "X" * 500
    with caplog.at_level(logging.INFO, logger="backend.routers.telemetry"):
        r = client.post(
            "/api/v1/telemetry/pwa-event",
            json={"event": "installed", "ua": long_ua},
        )
    assert r.status_code == 200
    # Find the pwa_event log line and confirm the UA segment is <= 80 chars.
    pwa_lines = [m for m in caplog.messages if m.startswith("pwa_event ")]
    assert pwa_lines, caplog.messages
    ua_part = pwa_lines[-1].split("ua=", 1)[1]
    assert len(ua_part) == 80
    assert ua_part == "X" * 80
