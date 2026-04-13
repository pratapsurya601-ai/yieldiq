# backend/tests/test_api.py
# Smoke tests for the YieldIQ API.
# Run: pytest backend/tests/test_api.py -v
from __future__ import annotations
import sys
from pathlib import Path

# Ensure project root is importable
_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest
from fastapi.testclient import TestClient
from backend.main import app

client = TestClient(app)


def test_health():
    r = client.get("/health")
    assert r.status_code == 200
    data = r.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_root():
    r = client.get("/")
    assert r.status_code == 200
    assert "YieldIQ" in r.json()["message"]


def test_docs_accessible():
    r = client.get("/api/docs")
    assert r.status_code == 200


def test_analysis_requires_auth():
    r = client.get("/api/v1/analysis/AAPL")
    assert r.status_code in (401, 403)


def test_market_pulse_requires_auth():
    r = client.get("/api/v1/market/pulse")
    assert r.status_code in (401, 403)


def test_portfolio_requires_auth():
    r = client.get("/api/v1/portfolio/holdings")
    assert r.status_code in (401, 403)


def test_watchlist_requires_auth():
    r = client.get("/api/v1/watchlist/")
    assert r.status_code in (401, 403)


def test_yieldiq50_requires_auth():
    r = client.get("/api/v1/yieldiq50")
    assert r.status_code in (401, 403)


def test_screener_requires_auth():
    r = client.get("/api/v1/screener/run")
    assert r.status_code in (401, 403)


def test_login_missing_body():
    r = client.post("/api/v1/auth/login")
    assert r.status_code == 422  # validation error


def test_register_missing_body():
    r = client.post("/api/v1/auth/register")
    assert r.status_code == 422
