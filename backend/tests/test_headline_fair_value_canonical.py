# backend/tests/test_headline_fair_value_canonical.py
# ═══════════════════════════════════════════════════════════════
# ROOT CAUSE #1 (2026-06-10) — canonical headline Fair Value contract.
#
# Pins the inject helper's resolution rule so any future change has to
# come through this test:
#   composite_intrinsic_value if finite + > 0 -> ("composite", value)
#   else valuation.fair_value if > 0          -> ("dcf",       value)
#   else None                                  -> (None,        None)
#
# Plus a snapshot-style assertion that the inject helper writes the SAME
# number into the field every consumer reads (no per-surface drift).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import math
import pytest

from backend.routers.analysis import (
    _inject_headline_fair_value_dict,
    _resolve_headline_fair_value,
)


# ── Resolution rule ─────────────────────────────────────────────


class TestResolveHeadlineFairValue:
    """Pin the composite-first / dcf-fallback / None branches."""

    def test_composite_preferred_when_positive(self):
        value, method = _resolve_headline_fair_value(
            composite_iv=1147.77, dcf_fv=1141.82,
        )
        assert method == "composite"
        assert value == 1147.77

    def test_dcf_fallback_when_composite_missing(self):
        value, method = _resolve_headline_fair_value(
            composite_iv=None, dcf_fv=1141.82,
        )
        assert method == "dcf"
        assert value == 1141.82

    def test_dcf_fallback_when_composite_zero(self):
        value, method = _resolve_headline_fair_value(
            composite_iv=0.0, dcf_fv=950.0,
        )
        assert method == "dcf"
        assert value == 950.0

    def test_dcf_fallback_when_composite_negative(self):
        value, method = _resolve_headline_fair_value(
            composite_iv=-50.0, dcf_fv=950.0,
        )
        assert method == "dcf"
        assert value == 950.0

    def test_dcf_fallback_when_composite_nan(self):
        value, method = _resolve_headline_fair_value(
            composite_iv=float("nan"), dcf_fv=950.0,
        )
        assert method == "dcf"
        assert value == 950.0

    def test_none_when_both_missing(self):
        value, method = _resolve_headline_fair_value(
            composite_iv=None, dcf_fv=None,
        )
        assert method is None
        assert value is None

    def test_none_when_both_non_positive(self):
        value, method = _resolve_headline_fair_value(
            composite_iv=0.0, dcf_fv=0.0,
        )
        assert method is None
        assert value is None

    def test_rounds_to_two_decimals(self):
        value, method = _resolve_headline_fair_value(
            composite_iv=1147.776666666, dcf_fv=None,
        )
        assert method == "composite"
        # 2dp rounding to keep payload byte-stable across cache writes.
        assert value == 1147.78

    def test_garbage_input_falls_back(self):
        # The helper must not raise on weird types; it should fall back
        # to the next branch.
        value, method = _resolve_headline_fair_value(
            composite_iv="not a number", dcf_fv=1141.82,
        )
        assert method == "dcf"
        assert value == 1141.82


# ── Dict-inject contract ────────────────────────────────────────


class TestInjectHeadlineFairValueDict:
    def test_populates_when_composite_present(self):
        payload = {
            "composite_intrinsic_value": 1147.77,
            "valuation": {"fair_value": 1141.82},
        }
        _inject_headline_fair_value_dict(payload)
        assert payload["headline_fair_value"] == 1147.77
        assert payload["headline_fair_value_method"] == "composite"

    def test_falls_back_to_dcf_when_composite_missing(self):
        payload = {
            "composite_intrinsic_value": None,
            "valuation": {"fair_value": 1141.82},
        }
        _inject_headline_fair_value_dict(payload)
        assert payload["headline_fair_value"] == 1141.82
        assert payload["headline_fair_value_method"] == "dcf"

    def test_writes_none_when_neither_present(self):
        payload = {
            "composite_intrinsic_value": None,
            "valuation": {"fair_value": 0.0},
        }
        _inject_headline_fair_value_dict(payload)
        assert payload["headline_fair_value"] is None
        assert payload["headline_fair_value_method"] is None

    def test_never_raises_on_broken_shape(self):
        # The inject helper must never break the response; broken shapes
        # leave the fields unset (or None) and the frontend resolver
        # supplies the same fallback chain client-side.
        broken = {}
        _inject_headline_fair_value_dict(broken)  # must not raise
        # Helper writes the keys even when both inputs are missing.
        assert "headline_fair_value" in broken
        assert broken["headline_fair_value"] is None

    def test_idempotent(self):
        payload = {
            "composite_intrinsic_value": 1147.77,
            "valuation": {"fair_value": 1141.82},
        }
        _inject_headline_fair_value_dict(payload)
        first_value = payload["headline_fair_value"]
        _inject_headline_fair_value_dict(payload)
        assert payload["headline_fair_value"] == first_value


# ── Consumer-parity invariant ───────────────────────────────────


class TestConsumerParityInvariant:
    """The whole point of ROOT CAUSE #1: every consumer reads the same
    number. This pin asserts that the value the inject helper writes is
    used as the source for the og-data summary projection too — so the
    hero pill and the OG card cannot drift again.
    """

    def test_og_summary_prefers_headline_over_dcf(self):
        # Mirror the call signature `resolve_fair_value` exposes after
        # the ROOT CAUSE #1 extension. Asserts the policy that
        # headline_fv wins when positive.
        from backend.services.summary_projection import resolve_fair_value

        out = resolve_fair_value(
            engine_fv=1141.82,
            base_case=1129.0,
            headline_fv=1147.77,
        )
        assert out == 1147.77

    def test_og_summary_falls_through_when_headline_absent(self):
        from backend.services.summary_projection import resolve_fair_value

        out = resolve_fair_value(
            engine_fv=1141.82,
            base_case=1129.0,
            headline_fv=None,
        )
        assert out == 1141.82


if __name__ == "__main__":  # pragma: no cover
    pytest.main([__file__, "-v"])
