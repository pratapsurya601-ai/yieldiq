"""Tests for the feature-flag resolution layer."""
from __future__ import annotations

import pytest

from backend.services import feature_flags
from backend.services.feature_flags import (
    FEATURE_FLAGS,
    is_enabled,
    list_enabled_for,
)


def test_beta_ring_default_off_for_free_tier():
    assert is_enabled("beta_ring", tier="free") is False


def test_beta_ring_on_for_pro_tier():
    assert is_enabled("beta_ring", tier="pro") is True


def test_beta_ring_off_for_analyst_tier_unless_overridden():
    # analyst tier has no beta_ring override -> falls through to default (False).
    assert is_enabled("beta_ring", tier="analyst") is False


def test_user_override_beats_tier_default(monkeypatch):
    """A user listed in user_overrides should win even when their tier
    would otherwise resolve to False."""
    # Patch in a VIP override for the duration of the test.
    monkeypatch.setitem(
        FEATURE_FLAGS["beta_ring"],
        "user_overrides",
        {"vip-user-1": True},
    )
    assert is_enabled("beta_ring", user_id="vip-user-1", tier="free") is True
    # And a different free-tier user still resolves to False.
    assert is_enabled("beta_ring", user_id="random-user", tier="free") is False


def test_user_override_can_force_off_for_pro(monkeypatch):
    """A False user_override should override a True tier_override."""
    monkeypatch.setitem(
        FEATURE_FLAGS["beta_ring"],
        "user_overrides",
        {"abusive-pro-user": False},
    )
    assert is_enabled("beta_ring", user_id="abusive-pro-user", tier="pro") is False


def test_unknown_flag_returns_false():
    assert is_enabled("nonexistent_flag") is False
    assert is_enabled("nonexistent_flag", tier="pro") is False
    assert is_enabled("nonexistent_flag", user_id="anyone", tier="pro") is False


def test_list_enabled_for_pro_returns_all_known_flags():
    out = list_enabled_for(user_id=None, tier="pro")
    assert isinstance(out, dict)
    # Every defined flag must appear in the resolved view.
    for name in FEATURE_FLAGS.keys():
        assert name in out
    # Both Pro-tier-overridden flags should resolve to True.
    assert out["beta_ring"] is True
    assert out["experimental_bond_yield_input"] is True


def test_list_enabled_for_logged_out_user_uses_defaults():
    out = list_enabled_for(user_id=None, tier=None)
    for name, spec in FEATURE_FLAGS.items():
        assert out[name] is bool(spec["default"])


def test_list_enabled_for_free_tier_matches_defaults():
    out = list_enabled_for(user_id="some-free-user", tier="free")
    for name, spec in FEATURE_FLAGS.items():
        assert out[name] is bool(spec["default"])
