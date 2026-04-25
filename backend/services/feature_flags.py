"""Feature-flag system for staged rollouts and Pro-tier early access.

Flags are defined as code (YAML/dict literal). Each flag has:
  - default: the value for ALL users when no override matches
  - tier_overrides: per-tier override (free / analyst / pro)
  - user_overrides: per-user-id override (for hand-targeted rollouts)
  - description: human-readable purpose

Resolution order (first match wins):
  1. user_overrides[user_id] if user is in the override list
  2. tier_overrides[user_tier] if user's tier has an override
  3. default

This is intentionally NOT a runtime DB lookup -- flags change rarely
enough that a deploy is acceptable, and avoiding the DB hit per request
keeps the flag check at ~50ns. If you need runtime flips later, swap
the dict for a Redis/Postgres-backed cache. Same call signature."""

from typing import Any, Optional

# Single source of truth for feature flags.
# Add a new flag: append a new dict entry below + import the helper
# wherever you want to gate code.
FEATURE_FLAGS: dict[str, dict[str, Any]] = {
    "beta_ring": {
        "description": "Pro tier early access to new features.",
        "default": False,
        "tier_overrides": {"pro": True},
        "user_overrides": {},  # populate with internal/QA user_ids
    },
    # Example flag for future use -- gates a hypothetical experimental
    # bond-yield input on the DCF page. Change `default` to True when
    # ready for general release.
    "experimental_bond_yield_input": {
        "description": "Experimental: let Pro users override the risk-free rate input.",
        "default": False,
        "tier_overrides": {"pro": True},
        "user_overrides": {},
    },
}


def is_enabled(flag: str, *, user_id: Optional[str] = None, tier: Optional[str] = None) -> bool:
    """Resolve a feature flag for a given user. See module docstring
    for resolution order."""
    spec = FEATURE_FLAGS.get(flag)
    if spec is None:
        # Unknown flag -- return False (safe default; never silently enable).
        return False
    if user_id and spec.get("user_overrides", {}).get(user_id) is not None:
        return bool(spec["user_overrides"][user_id])
    if tier and spec.get("tier_overrides", {}).get(tier) is not None:
        return bool(spec["tier_overrides"][tier])
    return bool(spec["default"])


def list_enabled_for(user_id: Optional[str], tier: Optional[str]) -> dict[str, bool]:
    """Return {flag_name: enabled} for ALL flags resolved against this
    user. Used by /auth/me so the frontend can branch on flags without
    a separate round-trip per flag."""
    return {
        flag: is_enabled(flag, user_id=user_id, tier=tier)
        for flag in FEATURE_FLAGS.keys()
    }
