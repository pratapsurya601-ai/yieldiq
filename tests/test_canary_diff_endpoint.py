"""Pin the canary's data-source endpoint to the unauth /og-data path.

Background: prior to fix/canary-use-public-ogdata the harness fetched
from `/api/v1/analysis/{T}.NS?include_summary=false`, which requires a
Supabase admin JWT. Those tokens expire in ~1 hour, so the canary
silently broke every hour with HTTP 401. The fix switched the URL to
`/api/v1/analysis/{T}.NS/og-data` (unauth, same canonical
fair_value/score/verdict/mos values).

If a future refactor accidentally points fetch_authed back at the
admin-gated route — or adds an Authorization header to the og-data
request — this test fires and blocks the merge.
"""
from __future__ import annotations

from unittest.mock import patch

from scripts import canary_diff


def test_fetch_authed_uses_unauth_og_data_endpoint():
    """The constructed URL must be the public /og-data path."""
    captured: dict = {}

    def fake_http_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return ({"fair_value": 1.0, "price": 1.0, "mos": 0.0}, None)

    with patch.object(canary_diff, "_http_get", side_effect=fake_http_get):
        canary_diff.fetch_authed("RELIANCE", token="should-be-ignored",
                                 api_base="https://api.example.com")

    assert captured["url"] == "https://api.example.com/api/v1/analysis/RELIANCE.NS/og-data", (
        f"Canary must hit unauth og-data endpoint, got: {captured['url']}"
    )
    # Old admin-gated shape must not reappear.
    assert "include_summary" not in captured["url"]
    assert "?" not in captured["url"]


def test_fetch_authed_sends_no_authorization_header():
    """Bearer token must NOT be sent — og-data is public.

    Pin this so a well-intentioned refactor doesn't reintroduce the
    1-hour JWT-expiry footgun.
    """
    captured: dict = {}

    def fake_http_get(url, headers=None, timeout=None):
        captured["headers"] = headers or {}
        return ({"fair_value": 1.0}, None)

    with patch.object(canary_diff, "_http_get", side_effect=fake_http_get):
        canary_diff.fetch_authed("TCS", token="ya29.dummy-bearer-token-value",
                                 api_base="https://api.example.com")

    # Either no headers at all, or no Authorization header — both fine.
    assert "Authorization" not in captured["headers"], (
        "fetch_authed must not send Authorization header for og-data"
    )


def test_fetch_authed_no_token_does_not_error():
    """With CANARY_AUTH_TOKEN unset the canary must still work."""
    def fake_http_get(url, headers=None, timeout=None):
        return ({"fair_value": 2500.0, "price": 3000.0, "mos": -16.7,
                 "verdict": "fairly_valued", "score": 72}, None)

    with patch.object(canary_diff, "_http_get", side_effect=fake_http_get):
        payload, err = canary_diff.fetch_authed("INFY", token="",
                                                api_base="https://api.example.com")

    assert err is None
    assert payload is not None
    assert payload["fair_value"] == 2500.0


def test_extract_fields_handles_og_data_shape():
    """og-data uses `price` and `mos`; canonical names must resolve."""
    og_payload = {
        "ticker": "RELIANCE.NS",
        "fair_value": 1450.0,
        "price": 1320.0,
        "mos": 9.85,
        "verdict": "undervalued",
        "score": 78,
    }
    fields = canary_diff.extract_fields(og_payload)
    assert fields["fair_value"] == 1450.0
    assert fields["cmp"] == 1320.0, "og-data `price` must map to canonical `cmp`"
    assert fields["margin_of_safety"] == 9.85, "og-data `mos` must map to canonical `margin_of_safety`"
    assert fields["verdict"] == "undervalued"
    assert fields["score"] == 78
