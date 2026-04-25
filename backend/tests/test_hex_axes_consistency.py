"""Locks the contract: hex axes computed from the SAME inputs give
the SAME numbers no matter which call site invoked them.

If anyone introduces a divergent axis-derivation path (e.g. a
copy-pasted compute_axes_from_payload in another module), this test
fails and the PR is blocked. This is the architectural moat against
the 2026-04-25 hex_history seeder bug class — where the seeder read
``payload["hex"]["axes"]`` (a key that is never written) and silently
returned 0 rows for all 50 canary tickers.

Same pattern as backend/tests/test_formula_consistency.py
(introduced in PR #89 for ratio formulas).
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.services.analysis.hex_axes import (
    HexAxes,
    compute_axes_for_ticker,
    compute_axes_from_payload,
    _axes_dict_to_hexaxes,
    _coerce_axis_score,
    _neutral_hexaxes,
)


# ── Pure-shape tests (no DB / no network) ──────────────────────────
def test_hexaxes_dataclass_is_frozen():
    """HexAxes must be immutable so a downstream caller can't tweak
    one axis after the fact and reintroduce drift."""
    axes = HexAxes(pulse=5, quality=6, moat=7, safety=4, growth=3, value=8)
    with pytest.raises((AttributeError, Exception)):
        axes.pulse = 9.0  # type: ignore[misc]


def test_hexaxes_as_dict_key_order_matches_api():
    """The API response orders axes as
    pulse, quality, moat, safety, growth, value. Anything that
    reorders this would break frontend assertions about field order
    in the OG card SVG — keep the order locked."""
    axes = HexAxes(pulse=1, quality=2, moat=3, safety=4, growth=5, value=6)
    assert list(axes.as_dict().keys()) == [
        "pulse", "quality", "moat", "safety", "growth", "value",
    ]


@pytest.mark.parametrize("raw,expected", [
    (5.0, 5.0),
    (0, 0.0),
    (10, 10.0),
    (-1, 0.0),                 # below floor → clamp to 0
    (11, 10.0),                # above ceiling → clamp to 10
    (None, 5.0),               # missing → neutral
    ("garbage", 5.0),          # unparseable → neutral
    (float("nan"), 5.0),       # NaN → neutral
    (float("inf"), 5.0),       # inf → neutral
    ({"score": 7.3}, 7.3),     # envelope-shape from compute_hex
    ({"score": None}, 5.0),    # envelope with missing score
    ({"score": 99}, 10.0),     # envelope with out-of-range score
    ({}, 5.0),                 # empty envelope
])
def test_coerce_axis_score_clamps_and_neutralises(raw, expected):
    assert _coerce_axis_score(raw) == expected


def test_axes_dict_to_hexaxes_handles_envelope_shape():
    """compute_hex emits ``{score, label, why, data_limited}`` per
    axis. The bridge must extract just the score and clamp."""
    live_shape = {
        "pulse":   {"score": 6.5, "label": "Positive", "why": "x", "data_limited": False},
        "quality": {"score": 7.2, "label": "Strong",  "why": "y", "data_limited": False},
        "moat":    {"score": 5.0, "label": "Moderate","why": "z", "data_limited": True},
        "safety":  {"score": 4.1, "label": "Moderate","why": "w", "data_limited": False},
        "growth":  {"score": 8.8, "label": "Strong",  "why": "v", "data_limited": False},
        "value":   {"score": 3.4, "label": "Weak",    "why": "u", "data_limited": False},
    }
    out = _axes_dict_to_hexaxes(live_shape)
    assert out == HexAxes(
        pulse=6.5, quality=7.2, moat=5.0,
        safety=4.1, growth=8.8, value=3.4,
    )


# ── Bounded-output contract ────────────────────────────────────────
@pytest.mark.parametrize("axes", [
    HexAxes(0, 0, 0, 0, 0, 0),
    HexAxes(10, 10, 10, 10, 10, 10),
    HexAxes(5, 5, 5, 5, 5, 5),
])
def test_axes_within_documented_range(axes):
    """Every axis must be in [0, 10] — the contract every consumer
    (UI, OG card, hex_history table) relies on."""
    for k, v in axes.as_dict().items():
        assert 0.0 <= v <= 10.0, f"{k}={v} out of [0,10]"


# ── Neutral fallback contract ──────────────────────────────────────
def test_neutral_hexaxes_is_all_fives():
    """The seeder's never-fail path returns this when no usable
    ticker / payload is provided."""
    n = _neutral_hexaxes()
    assert n == HexAxes(5.0, 5.0, 5.0, 5.0, 5.0, 5.0)


# ── Single-source-of-truth contract ────────────────────────────────
# These tests use a stub compute_hex_safe so they don't need a live
# DB. The point is to lock the relationship between the live render
# path and the new bridge — NOT to retest hex_service's own logic.
_FAKE_LIVE_RESPONSE = {
    "ticker": "RELIANCE.NS",
    "axes": {
        "pulse":   {"score": 5.5, "label": "Neutral",  "why": "fake", "data_limited": False},
        "quality": {"score": 7.1, "label": "Strong",   "why": "fake", "data_limited": False},
        "moat":    {"score": 6.8, "label": "Moderate", "why": "fake", "data_limited": False},
        "safety":  {"score": 6.2, "label": "Moderate", "why": "fake", "data_limited": False},
        "growth":  {"score": 5.9, "label": "Moderate", "why": "fake", "data_limited": False},
        "value":   {"score": 4.3, "label": "Weak",     "why": "fake", "data_limited": False},
    },
    "overall": 6.0,
}


def test_compute_axes_for_ticker_delegates_to_compute_hex_safe():
    """compute_axes_for_ticker MUST go through hex_service.compute_hex_safe.
    This is the single-source-of-truth contract — if some future PR
    introduces a parallel compute path here, this test fails."""
    with patch(
        "backend.services.hex_service.compute_hex_safe",
        return_value=_FAKE_LIVE_RESPONSE,
    ) as mock_live:
        axes = compute_axes_for_ticker("RELIANCE.NS")
    assert mock_live.called, (
        "compute_axes_for_ticker must delegate to hex_service.compute_hex_safe"
    )
    assert axes == HexAxes(
        pulse=5.5, quality=7.1, moat=6.8,
        safety=6.2, growth=5.9, value=4.3,
    )


def test_seeder_path_and_render_path_produce_identical_axes():
    """The whole point of this PR: the live render path and the
    hex_history seeder path MUST produce byte-identical 6-tuple
    output for the same ticker. Any divergence here is the bug class
    we are eliminating."""
    with patch(
        "backend.services.hex_service.compute_hex_safe",
        return_value=_FAKE_LIVE_RESPONSE,
    ):
        # Live render path (frontend reads this).
        live_axes_dict = _FAKE_LIVE_RESPONSE["axes"]
        live = _axes_dict_to_hexaxes(live_axes_dict)

        # Seeder path (hex_history table reads this).
        seeded = compute_axes_for_ticker("RELIANCE.NS")

    assert live == seeded, (
        f"render path produced {live} but seeder path produced {seeded} "
        f"— single-source-of-truth contract violated"
    )


def test_compute_axes_from_payload_prefers_inline_hex_block():
    """When the API response carries an already-computed
    payload['hex']['axes'], use it directly — no second call to
    compute_hex_safe (which would touch the DB unnecessarily)."""
    payload = {
        "ticker": "RELIANCE.NS",
        "hex": {"axes": {
            "pulse":   {"score": 6.0},
            "quality": {"score": 6.5},
            "moat":    {"score": 7.0},
            "safety":  {"score": 5.5},
            "growth":  {"score": 4.5},
            "value":   {"score": 3.5},
        }},
    }
    with patch(
        "backend.services.hex_service.compute_hex_safe",
    ) as mock_live:
        out = compute_axes_from_payload(payload)
    assert not mock_live.called, (
        "must NOT re-derive axes when payload already carries them"
    )
    assert out == HexAxes(
        pulse=6.0, quality=6.5, moat=7.0,
        safety=5.5, growth=4.5, value=3.5,
    )


def test_compute_axes_from_payload_falls_back_to_ticker_lookup():
    """When the cache-row shape lacks a pre-computed hex block, the
    function must delegate to compute_axes_for_ticker (i.e. the live
    render path) using the payload's ticker — the only correct way
    to get the 6 axes from the cache shape."""
    payload = {
        "ticker": "RELIANCE.NS",
        "quality": {"piotroski_score": 7, "roce": 18.0},
        "valuation": {"margin_of_safety": -10.0},
        # no `hex` block on purpose
    }
    with patch(
        "backend.services.hex_service.compute_hex_safe",
        return_value=_FAKE_LIVE_RESPONSE,
    ) as mock_live:
        out = compute_axes_from_payload(payload)
    assert mock_live.called, (
        "must delegate to live render when payload lacks hex block"
    )
    assert out.value == 4.3  # from _FAKE_LIVE_RESPONSE


def test_compute_axes_from_payload_neutral_on_empty_input():
    """Defensive: never raise on garbage input — the seeder's
    never-fail contract depends on this."""
    assert compute_axes_from_payload({}) == _neutral_hexaxes()
    assert compute_axes_from_payload(None) == _neutral_hexaxes()  # type: ignore[arg-type]
    assert compute_axes_from_payload({"hex": "not a dict"}) == _neutral_hexaxes()
    assert compute_axes_from_payload({"hex": {}, "ticker": ""}) == _neutral_hexaxes()


def test_get_hex_axes_is_re_exported_from_hex_service():
    """hex_service.get_hex_axes is the public typed entry point.
    It must exist AND must return the SAME values as
    compute_axes_for_ticker."""
    from backend.services import hex_service
    assert hasattr(hex_service, "get_hex_axes"), (
        "hex_service.get_hex_axes must be re-exported as the public entry"
    )
    with patch(
        "backend.services.hex_service.compute_hex_safe",
        return_value=_FAKE_LIVE_RESPONSE,
    ):
        via_service = hex_service.get_hex_axes("RELIANCE.NS")
        via_module = compute_axes_for_ticker("RELIANCE.NS")
    assert via_service == via_module
