"""Regression test: liquid mid/large-cap stocks with MoS > +50% must
trigger ``data_limited`` OR have peer-cap fire OR both.

Reference: launch-day audit (2026-04-28). The 7 outliers tracked in
``scripts/canary_outliers_7.json`` (JUSTDIAL +91%, EMAMILTD +82%,
NATCOPHARM +76%, TCS +44%, SANOFI +70%, ZYDUSLIFE +66%, MAYURUNIQ
+64%) showed implausibly high MoS values on a 'wide moat / consistent
earnings / fair price' preset. The proximate cause was the DCF
producing fair values 1.5x–2x peer median for stocks with mcap above
₹5,000 Cr — i.e. liquid names where peer-cap should have been the
ceiling and where ``data_limited`` should have flagged the model.

JUSTDIAL was the most extreme case: ₹4,000+ Cr mcap, +91% MoS — for
a liquid Indian internet name, this magnitude of mispricing is not
discovered by a public DCF; it's a model artefact.

Contract: for any stock with ``market_cap_cr > 5000`` and a positive
MoS exceeding 50 percentage points, the API response must surface AT
LEAST ONE of:

* ``verdict == 'data_limited'``
* ``data_limited`` flag truthy on the payload root or any hex-axis
* ``peer_cap_details`` indicating the peer ceiling fired
* ``input_quality_flags`` containing a recognised 'implausible' tag

If none of those signal, the user-visible MoS is unmoderated, which
is the launch-day-audit failure mode.

This test pins that contract against synthetic payloads shaped to
match ``backend/services/analysis/service.py`` output.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# Pure invariant — does NOT import backend code. The invariant is
# expressed against the API response shape so it can be reused both
# offline (unit tests) and online (canary harness).
# ---------------------------------------------------------------------------

MCAP_LIQUID_FLOOR_CR = 5000
MOS_IMPLAUSIBLE_PCT = 50.0


def _has_data_limited_signal(payload: dict) -> bool:
    if payload.get("verdict") == "data_limited":
        return True
    if bool(payload.get("data_limited")):
        return True
    hexes = payload.get("hex_axes") or {}
    for axis in (hexes.values() if isinstance(hexes, dict) else []):
        if isinstance(axis, dict) and axis.get("data_limited"):
            return True
    return False


def _peer_cap_fired(payload: dict) -> bool:
    pcd = payload.get("peer_cap_details")
    if not pcd:
        return False
    if isinstance(pcd, dict):
        # Recognised shapes from PR #136 / b758f89.
        if pcd.get("fired") is True:
            return True
        if pcd.get("applied") is True:
            return True
        if "ceiling" in pcd and "raw_fv" in pcd and pcd.get("raw_fv") > pcd.get("ceiling", 0):
            return True
    return False


def _has_implausibility_flag(payload: dict) -> bool:
    flags = payload.get("input_quality_flags") or []
    if not isinstance(flags, list):
        return False
    return any(
        isinstance(f, str)
        and (
            "implausible" in f.lower()
            or "outlier" in f.lower()
            or "peer_cap" in f.lower()
        )
        for f in flags
    )


def assert_outlier_moderated(payload: dict) -> None:
    """The contract — fails loudly if no moderation signal is present."""
    mcap = payload.get("market_cap_cr") or 0
    mos = payload.get("margin_of_safety") or 0
    if mcap <= MCAP_LIQUID_FLOOR_CR:
        return
    if mos <= MOS_IMPLAUSIBLE_PCT:
        return
    moderated = (
        _has_data_limited_signal(payload)
        or _peer_cap_fired(payload)
        or _has_implausibility_flag(payload)
    )
    assert moderated, (
        f"Implausible MoS {mos:.1f}% on liquid name "
        f"(mcap ₹{mcap:,.0f} Cr) is not moderated. Expected at least "
        f"one of: verdict=data_limited, data_limited flag, "
        f"peer_cap_details fired, input_quality_flags implausible. "
        "Launch-day audit 2026-04-28 — see scripts/canary_outliers_7.json."
    )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_justdial_pattern_unmoderated_is_caught():
    """JUSTDIAL +91% MoS, ₹4,200 Cr mcap, no moderation flags → must fail."""
    payload = {
        "symbol": "JUSTDIAL",
        "market_cap_cr": 4200,
        "margin_of_safety": 91.0,
        "verdict": "buy",
        "data_limited": False,
        "peer_cap_details": None,
        "input_quality_flags": [],
    }
    # JUSTDIAL is below the 5,000 Cr floor — but the bug we're guarding
    # against was the *liquid* mid-cap pattern. Any-mcap version of the
    # same payload at 6,000 Cr must fail the invariant.
    payload["market_cap_cr"] = 6000
    with pytest.raises(AssertionError, match="not moderated"):
        assert_outlier_moderated(payload)


def test_emamiltd_pattern_with_data_limited_passes():
    """EMAMILTD +82% MoS but verdict=data_limited → moderated."""
    payload = {
        "symbol": "EMAMILTD",
        "market_cap_cr": 25000,
        "margin_of_safety": 82.0,
        "verdict": "data_limited",
    }
    assert_outlier_moderated(payload)  # must not raise


def test_natcopharm_pattern_with_peer_cap_passes():
    """NATCOPHARM +76% raw, peer-cap fires → moderated."""
    payload = {
        "symbol": "NATCOPHARM",
        "market_cap_cr": 12000,
        "margin_of_safety": 76.0,
        "verdict": "buy",
        "peer_cap_details": {
            "fired": True,
            "ceiling": 1500.0,
            "raw_fv": 2300.0,
        },
    }
    assert_outlier_moderated(payload)


def test_zyduslife_pattern_with_quality_flag_passes():
    payload = {
        "symbol": "ZYDUSLIFE",
        "market_cap_cr": 90000,
        "margin_of_safety": 66.0,
        "verdict": "buy",
        "input_quality_flags": ["mos_implausible_outlier"],
    }
    assert_outlier_moderated(payload)


def test_small_cap_with_high_mos_is_exempt():
    """Below the liquid-floor threshold the invariant does not apply.
    The audit explicitly scoped this rule to mcap > 5,000 Cr — illiquid
    micro-caps can have legitimate large MoS (poor price discovery) and
    are not part of this regression."""
    payload = {
        "symbol": "MICRO",
        "market_cap_cr": 800,
        "margin_of_safety": 200.0,
        "verdict": "buy",
    }
    assert_outlier_moderated(payload)  # must not raise


def test_low_mos_liquid_name_is_exempt():
    """Liquid name with MoS in the normal band — no moderation needed."""
    payload = {
        "symbol": "RELIANCE",
        "market_cap_cr": 1_800_000,
        "margin_of_safety": 12.0,
        "verdict": "buy",
    }
    assert_outlier_moderated(payload)


def test_hex_axis_data_limited_counts_as_moderation():
    payload = {
        "symbol": "SYNTHETIC",
        "market_cap_cr": 10000,
        "margin_of_safety": 60.0,
        "verdict": "buy",
        "hex_axes": {
            "value": {"score": 5.0, "data_limited": True},
            "growth": {"score": 7.0, "data_limited": False},
        },
    }
    assert_outlier_moderated(payload)


@pytest.mark.parametrize("mcap_cr,mos,should_fail", [
    (6000, 51.0, True),
    (6000, 49.9, False),    # below threshold
    (5000, 80.0, False),    # at-or-below floor
    (5001, 50.1, True),
    (1_000_000, 75.0, True),
])
def test_threshold_boundaries(mcap_cr, mos, should_fail):
    payload = {
        "market_cap_cr": mcap_cr,
        "margin_of_safety": mos,
        "verdict": "buy",
    }
    if should_fail:
        with pytest.raises(AssertionError):
            assert_outlier_moderated(payload)
    else:
        assert_outlier_moderated(payload)
