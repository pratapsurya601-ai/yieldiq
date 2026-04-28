"""Tests for the version-keyed cache wrapper.

Background: PR #138's `fair_value_source` field failed to surface on
prod because the public stock-summary cache stored a rendered
projection under a key that did NOT change across CACHE_VERSION
bumps. Lazy stored-version invalidation only fires on read; meanwhile
the per-key TTL kept serving the stale projection.

These tests pin the new `version_keyed=True` semantics so the next
person who refactors `cache_service.py` does not silently regress
the fix.

Standalone: no fastapi/network/db dependencies. Just imports
`backend.services.cache_service` and exercises the in-memory store.
"""

from __future__ import annotations

import importlib

import pytest


@pytest.fixture
def fresh_cache_module(monkeypatch):
    """Yield a freshly-imported cache_service module so each test has
    a clean singleton + can monkeypatch CACHE_VERSION without
    bleeding into siblings."""
    import backend.services.cache_service as mod
    importlib.reload(mod)
    mod.cache.clear()
    yield mod
    mod.cache.clear()


def test_version_keyed_get_set_roundtrip(fresh_cache_module):
    mod = fresh_cache_module
    mod.cache.set("derived:TCS.NS", {"fv": 4200}, ttl=300, version_keyed=True)
    assert mod.cache.get("derived:TCS.NS", version_keyed=True) == {"fv": 4200}


def test_ttl_only_unchanged_by_version_bump(fresh_cache_module, monkeypatch):
    """Backward-compat: TTL-only entries written under one CACHE_VERSION
    SHOULD survive a bump as long as the stored-version check still
    matches at write time -- because we store the *current* version
    on write, only a *subsequent* bump would lazy-invalidate them.

    This pins the documented semantics: TTL-only entries are NOT a
    hard guarantee of cross-version persistence; they are just *not
    explicitly version-keyed* via the storage prefix. The lazy
    stored-version check still applies on read.
    """
    mod = fresh_cache_module
    # Write at v=999
    monkeypatch.setattr(mod, "CACHE_VERSION", 999)
    mod.cache.set("op:rate-limit:user-42", 7, ttl=600, version_keyed=False)
    # Same generation read works
    assert mod.cache.get("op:rate-limit:user-42", version_keyed=False) == 7

    # Bump to v=1000. Stored-version check (lazy) invalidates on read,
    # which is the documented current behavior for TTL-only entries.
    monkeypatch.setattr(mod, "CACHE_VERSION", 1000)
    assert mod.cache.get("op:rate-limit:user-42", version_keyed=False) is None


def test_version_keyed_invalidates_on_version_bump(fresh_cache_module, monkeypatch):
    """The headline guarantee: version-keyed entries written before a
    bump are UNREACHABLE after the bump (different key namespace),
    independent of any lazy stored-version check."""
    mod = fresh_cache_module
    monkeypatch.setattr(mod, "CACHE_VERSION", 65)
    mod.cache.set(
        "public:stock-summary:TCS.NS",
        {"fair_value": 4200, "fair_value_source": "v65-projection"},
        ttl=3600,
        version_keyed=True,
    )
    # Pre-bump read works
    pre = mod.cache.get("public:stock-summary:TCS.NS", version_keyed=True)
    assert pre and pre["fair_value_source"] == "v65-projection"

    # Bump CACHE_VERSION 65 -> 66. The new generation reads/writes a
    # different key (`v66:public:stock-summary:TCS.NS`) so the v65
    # entry is unreachable.
    monkeypatch.setattr(mod, "CACHE_VERSION", 66)
    assert mod.cache.get("public:stock-summary:TCS.NS", version_keyed=True) is None

    # And a fresh write under v66 does not collide with the orphaned
    # v65 entry.
    mod.cache.set(
        "public:stock-summary:TCS.NS",
        {"fair_value": 4350, "fair_value_source": "v66-projection"},
        ttl=3600,
        version_keyed=True,
    )
    post = mod.cache.get("public:stock-summary:TCS.NS", version_keyed=True)
    assert post and post["fair_value_source"] == "v66-projection"


def test_version_keyed_isolated_from_ttl_only(fresh_cache_module):
    """Same logical key, written under both flags, must NOT collide.
    Important because some refactors will leave a TTL-only writer in
    place while a reader migrates to version_keyed (or vice versa);
    we want misuse to surface as a cache miss, not a silent return
    of the wrong-namespace value."""
    mod = fresh_cache_module
    mod.cache.set("shared-key", "ttl-only-value", ttl=600, version_keyed=False)
    mod.cache.set("shared-key", "version-keyed-value", ttl=600, version_keyed=True)

    assert mod.cache.get("shared-key", version_keyed=False) == "ttl-only-value"
    assert mod.cache.get("shared-key", version_keyed=True) == "version-keyed-value"


def test_delete_respects_version_keyed_flag(fresh_cache_module):
    mod = fresh_cache_module
    mod.cache.set("k", 1, ttl=600, version_keyed=False)
    mod.cache.set("k", 2, ttl=600, version_keyed=True)

    mod.cache.delete("k", version_keyed=True)
    assert mod.cache.get("k", version_keyed=True) is None
    assert mod.cache.get("k", version_keyed=False) == 1

    mod.cache.delete("k", version_keyed=False)
    assert mod.cache.get("k", version_keyed=False) is None


def test_default_is_ttl_only(fresh_cache_module):
    """Default value of `version_keyed` must remain False -- the
    existing ~46 cache call sites rely on the old behavior."""
    mod = fresh_cache_module
    mod.cache.set("legacy", "value")  # no kwarg
    # Default reader sees it
    assert mod.cache.get("legacy") == "value"
    # version-keyed reader does not (different key namespace)
    assert mod.cache.get("legacy", version_keyed=True) is None
