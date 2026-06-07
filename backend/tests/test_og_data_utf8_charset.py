# backend/tests/test_og_data_utf8_charset.py
# ═══════════════════════════════════════════════════════════════
# Regression test for fix/og-data-utf8-mojibake.
#
# Bug: OG image titles on yieldiq.in rendered "â‚¹" instead of "₹"
# on every Twitter / WhatsApp / Slack social share preview.
#
# Root cause: backend /api/v1/analysis/{ticker}/og-data declared
# `Content-Type: application/json` with NO `charset=utf-8`
# parameter. The body bytes were already clean UTF-8 (e2 82 b9
# for ₹), but the Next.js Satori Edge runtime fetch — and several
# OG scrapers — fall back to latin-1 when no charset is declared,
# decoding the three UTF-8 bytes of ₹ as the three latin-1 chars
# â + ‚ + ¹.
#
# Fix: a custom `_UTF8JSONResponse` class with
# `media_type = "application/json; charset=utf-8"` wired as the
# route's `response_class`. The body bytes are unchanged; only the
# Content-Type response header now includes the charset parameter
# so consumers stop guessing.
#
# This test asserts BOTH halves of the fix using FastAPI's
# TestClient, which exercises the full response-class pipeline
# (unlike the unit-style tests in test_og_data_extended.py which
# call the coroutine directly and get back a raw dict):
#
#   1. The response Content-Type header includes `charset=utf-8`.
#   2. The response body, decoded as UTF-8, contains a real ₹
#      (U+20B9) — not the mojibake `â‚¹`.
#   3. The raw response bytes contain the UTF-8 sequence
#      b"\xe2\x82\xb9" (₹) and do NOT contain the mojibake
#      sequence b"\xc3\xa2\xe2\x80\x9a\xc2\xb9" (â‚¹ as UTF-8).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Test helpers ────────────────────────────────────────────────


def _fake_analysis_response():
    """Minimal AnalysisResponse-shaped namespace for the og-data
    handler. Must include the fields the handler reads to render
    the `description` string that contains ₹."""
    return SimpleNamespace(
        company=SimpleNamespace(company_name="HDFC Bank Ltd"),
        valuation=SimpleNamespace(
            fair_value=1145.96,
            current_price=747.05,
            margin_of_safety=53.4,
            verdict="undervalued",
            base_case=1145.96,
            bear_case=954.97,
            bull_case=1527.95,
            wacc=0.098,
            mos_is_extreme=False,
            ttm_source="nse_xbrl",
            quarterly_last_filed_at="2026-03-31",
        ),
        quality=SimpleNamespace(yieldiq_score=78, moat="Wide", roe=0.18, roce=0.22),
        insights=SimpleNamespace(ev_ebitda=14.0),
    )


@pytest.fixture
def client():
    """Mount just the analysis router on a fresh FastAPI app and
    exercise via TestClient, which hits the real
    `response_class=_UTF8JSONResponse` pipeline."""
    from backend.routers.analysis import router as analysis_router

    app = FastAPI()
    # analysis_router is already constructed with prefix="/api/v1"
    app.include_router(analysis_router)
    return TestClient(app)


def _cache_get(key, version_keyed=False):
    """og: cache empty, analysis: cache populated with the fake.
    Matches the helper in test_og_data_extended.py."""
    if key.startswith("og:"):
        return None
    if key.startswith("analysis:"):
        return _fake_analysis_response()
    return None


# ── Test 1: Content-Type header carries charset=utf-8 ───────────


def test_og_data_response_declares_utf8_charset(client):
    """The Content-Type header MUST include `charset=utf-8`. Without
    it, downstream consumers (Next.js Satori Edge fetch, WhatsApp
    OG scraper, etc.) fall back to latin-1 and produce mojibake."""
    with patch("backend.routers.analysis.cache.get", side_effect=_cache_get), \
         patch("backend.routers.analysis.cache.set", return_value=None), \
         patch(
             "backend.services.coverage_tier_service.summary_for_og",
             return_value=None,
         ):
        resp = client.get("/api/v1/analysis/HDFCBANK.NS/og-data")

    assert resp.status_code == 200
    ctype = resp.headers.get("content-type", "")
    assert "application/json" in ctype, f"unexpected content-type: {ctype!r}"
    assert "charset=utf-8" in ctype.lower(), (
        f"og-data response Content-Type missing charset=utf-8: {ctype!r}. "
        f"This is the exact boundary that caused the â‚¹ mojibake on "
        f"every social share preview."
    )


# ── Test 2: body bytes contain the real ₹ (U+20B9), not mojibake ──


def test_og_data_response_body_contains_real_rupee_bytes(client):
    """The response body MUST contain the UTF-8 sequence for ₹
    (b'\\xe2\\x82\\xb9') and MUST NOT contain the UTF-8-encoded
    mojibake form of â‚¹ (b'\\xc3\\xa2\\xe2\\x80\\x9a\\xc2\\xb9').

    Also asserts the decoded JSON contains a real ₹ character in
    the description — catching any future double-encoding regression
    that produces the right Content-Type header but the wrong body."""
    with patch("backend.routers.analysis.cache.get", side_effect=_cache_get), \
         patch("backend.routers.analysis.cache.set", return_value=None), \
         patch(
             "backend.services.coverage_tier_service.summary_for_og",
             return_value=None,
         ):
        resp = client.get("/api/v1/analysis/HDFCBANK.NS/og-data")

    assert resp.status_code == 200

    raw = resp.content
    # The real ₹ symbol in UTF-8.
    rupee_utf8 = b"\xe2\x82\xb9"
    # The mojibake `â‚¹` re-encoded as UTF-8 (what we'd see if the
    # source string had already been double-decoded somewhere).
    mojibake_utf8 = "â‚¹".encode("utf-8")

    assert rupee_utf8 in raw, (
        f"response body missing real ₹ bytes (b'\\xe2\\x82\\xb9'); "
        f"first 300 bytes: {raw[:300]!r}"
    )
    assert mojibake_utf8 not in raw, (
        f"response body contains mojibake `â‚¹` byte sequence "
        f"{mojibake_utf8!r} — double-encoding regression"
    )

    # And the JSON decoded as UTF-8 has a real ₹ in description.
    body = resp.json()
    assert "₹" in body["description"], (
        f"description missing real ₹: {body['description']!r}"
    )
    assert "â‚¹" not in body["description"], (
        f"description contains mojibake â‚¹: {body['description']!r}"
    )
