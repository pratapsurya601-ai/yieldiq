"""Phase B.1 (2026-05-24) — in-memory cache drain on manifest apply.

Locks in the invariants from
docs/diagnostics/phase-b-cache-paths-2026-05-24.md §5 (B.1):

  1. delete_by_prefix drains BOTH non-version-keyed and version-keyed
     entries under the same user-key prefix in a single call.
  2. The default drain hook (registered at module import) drains the
     analysis: and public:stock-summary: prefixes when fired.
  3. Drain hooks are idempotent — firing twice doesn't blow up.
  4. The import-time sweep replays only entries within
     DRAIN_LOOKBACK_HOURS, not the entire historical manifest.
  5. ``get_canonical_payload`` is a thin wrapper that delegates to
     ``get_cached`` (manifest-respecting) by default, and falls
     through to ``get_cached_latest`` (manifest-bypassing) only when
     allow_stale=True.
  6. Hook exceptions are caught — one misbehaving hook doesn't take
     down the others.
  7. CACHE_MANIFEST_DISABLED short-circuits the sweep.
"""
from __future__ import annotations

import importlib
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))


# ─────────────────────────────────────────────────────────────────
# delete_by_prefix on CacheService
# ─────────────────────────────────────────────────────────────────


def test_delete_by_prefix_drains_non_version_keyed():
    from backend.services.cache_service import CacheService

    c = CacheService()
    c.set("analysis:HDFCBANK.NS", {"score": 50}, ttl=3600)
    c.set("analysis:ICICIBANK.NS:raw", {"score": 60}, ttl=3600)
    c.set("unrelated:foo", "bar", ttl=3600)

    removed = c.delete_by_prefix("analysis:")
    assert removed == 2
    assert c.get("analysis:HDFCBANK.NS") is None
    assert c.get("analysis:ICICIBANK.NS:raw") is None
    assert c.get("unrelated:foo") == "bar"


def test_delete_by_prefix_drains_version_keyed():
    from backend.services.cache_service import CacheService

    c = CacheService()
    c.set("public:stock-summary:HDFCBANK.NS", {"fv": 1097}, ttl=3600,
          version_keyed=True)
    c.set("public:stock-summary:INFY.NS", {"fv": 1845}, ttl=3600,
          version_keyed=True)
    c.set("analysis:HDFCBANK.NS", "should-not-match", ttl=3600)

    removed = c.delete_by_prefix("public:stock-summary:")
    assert removed == 2
    assert c.get("public:stock-summary:HDFCBANK.NS",
                 version_keyed=True) is None
    assert c.get("public:stock-summary:INFY.NS",
                 version_keyed=True) is None
    # adjacent prefix untouched
    assert c.get("analysis:HDFCBANK.NS") == "should-not-match"


def test_delete_by_prefix_idempotent():
    from backend.services.cache_service import CacheService

    c = CacheService()
    c.set("analysis:X", 1, ttl=3600)
    assert c.delete_by_prefix("analysis:") == 1
    # Second call on the drained store is a no-op, not an error.
    assert c.delete_by_prefix("analysis:") == 0
    assert c.delete_by_prefix("analysis:") == 0


# ─────────────────────────────────────────────────────────────────
# Hook registry + import-time sweep
# ─────────────────────────────────────────────────────────────────


def _utc(year, month, day, hour=0, minute=0):
    return datetime(year, month, day, hour, minute, tzinfo=timezone.utc)


def test_notify_fires_every_registered_hook():
    import backend.services.cache_invalidation_manifest as m
    importlib.reload(m)

    seen: list[str] = []
    m.MANIFEST_APPLIED_HOOKS.clear()
    m.register_manifest_applied_hook(
        lambda e: seen.append("hook1:" + (e.get("version_id") or "")))
    m.register_manifest_applied_hook(
        lambda e: seen.append("hook2:" + (e.get("version_id") or "")))

    m.notify_manifest_entry_applied({"version_id": "v_test"})
    assert seen == ["hook1:v_test", "hook2:v_test"]


def test_hook_exceptions_are_swallowed():
    import backend.services.cache_invalidation_manifest as m
    importlib.reload(m)

    fired: list[str] = []
    m.MANIFEST_APPLIED_HOOKS.clear()

    def _boom(entry):
        raise RuntimeError("intentional")

    m.register_manifest_applied_hook(_boom)
    m.register_manifest_applied_hook(lambda e: fired.append("ok"))

    # MUST NOT raise — and the second hook still runs.
    m.notify_manifest_entry_applied({"version_id": "v_x"})
    assert fired == ["ok"]


def test_sweep_only_picks_recent_entries():
    import backend.services.cache_invalidation_manifest as m
    importlib.reload(m)

    fired: list[str] = []
    m.MANIFEST_APPLIED_HOOKS.clear()
    m.register_manifest_applied_hook(
        lambda e: fired.append(e.get("version_id")))

    now = _utc(2026, 5, 24, 12)
    fake_manifest = [
        {"version_id": "v_old",
         "applied_at": _utc(2026, 1, 1),
         "scope": {"tickers": "*", "fields": "*"}},
        {"version_id": "v_recent",
         "applied_at": _utc(2026, 5, 24, 0),  # 12h ago vs now
         "scope": {"tickers": "*", "fields": "*"}},
        {"version_id": "v_just_outside",
         "applied_at": _utc(2026, 5, 23, 0),  # 36h ago — outside 24h
         "scope": {"tickers": "*", "fields": "*"}},
    ]
    count = m.sweep_recent_entries(
        manifest=fake_manifest, lookback_hours=24, now=now)
    assert count == 1
    assert fired == ["v_recent"]


def test_sweep_disabled_by_env(monkeypatch):
    monkeypatch.setenv("CACHE_MANIFEST_DISABLED", "1")
    import backend.services.cache_invalidation_manifest as m
    importlib.reload(m)

    fired: list[str] = []
    m.MANIFEST_APPLIED_HOOKS.clear()
    m.register_manifest_applied_hook(lambda e: fired.append("x"))

    now = _utc(2026, 5, 24, 12)
    fake_manifest = [{
        "version_id": "v_recent",
        "applied_at": _utc(2026, 5, 24, 0),
        "scope": {"tickers": "*", "fields": "*"},
    }]
    assert m.sweep_recent_entries(
        manifest=fake_manifest, lookback_hours=24, now=now) == 0
    assert fired == []


# ─────────────────────────────────────────────────────────────────
# End-to-end: import-time sweep wires the cache_service drain
# ─────────────────────────────────────────────────────────────────


def test_default_hook_drains_inmem_cache():
    """The import-time-registered default hook actually clears
    analysis:* and public:stock-summary:* on the singleton cache."""
    import backend.services.cache_invalidation_manifest as m
    from backend.services.cache_service import cache
    importlib.reload(m)

    cache.set("analysis:HDFCBANK.NS", "stale", ttl=3600)
    cache.set("analysis:HDFCBANK.NS:raw", {"v": 1}, ttl=3600)
    cache.set("public:stock-summary:HDFCBANK.NS", {"v": 2},
              ttl=3600, version_keyed=True)
    cache.set("keep:me", "untouched", ttl=3600)

    # Fire the default hook explicitly via notify (don't depend on
    # wall-clock-sensitive import sweep here).
    m.notify_manifest_entry_applied(m.MANIFEST[-1])

    assert cache.get("analysis:HDFCBANK.NS") is None
    assert cache.get("analysis:HDFCBANK.NS:raw") is None
    assert cache.get("public:stock-summary:HDFCBANK.NS",
                     version_keyed=True) is None
    assert cache.get("keep:me") == "untouched"


def test_default_hook_idempotent_on_empty_store():
    import backend.services.cache_invalidation_manifest as m
    from backend.services.cache_service import cache
    importlib.reload(m)
    cache.clear()
    # Two drains in a row — must not raise.
    m.notify_manifest_entry_applied(m.MANIFEST[-1])
    m.notify_manifest_entry_applied(m.MANIFEST[-1])


# ─────────────────────────────────────────────────────────────────
# get_canonical_payload
# ─────────────────────────────────────────────────────────────────


def test_canonical_payload_respects_manifest_by_default(monkeypatch):
    """allow_stale=False → goes through get_cached → on miss, does NOT
    fall through to get_cached_latest."""
    from backend.services import analysis_cache_service as acs

    called: dict[str, int] = {"cached": 0, "latest": 0}

    def fake_get_cached(ticker, fields_needed=None):
        called["cached"] += 1
        return None

    def fake_get_latest(ticker, max_age_hours=168):
        called["latest"] += 1
        return {"sentinel": "latest"}

    monkeypatch.setattr(acs, "get_cached", fake_get_cached)
    monkeypatch.setattr(acs, "get_cached_latest", fake_get_latest)

    out = acs.get_canonical_payload("HDFCBANK.NS")
    assert out is None
    assert called == {"cached": 1, "latest": 0}


def test_canonical_payload_allow_stale_falls_through(monkeypatch):
    from backend.services import analysis_cache_service as acs

    def fake_get_cached(ticker, fields_needed=None):
        return None

    def fake_get_latest(ticker, max_age_hours=168):
        return {"sentinel": "stale-but-served"}

    monkeypatch.setattr(acs, "get_cached", fake_get_cached)
    monkeypatch.setattr(acs, "get_cached_latest", fake_get_latest)

    out = acs.get_canonical_payload("HDFCBANK.NS", allow_stale=True)
    assert out == {"sentinel": "stale-but-served"}


def test_canonical_payload_returns_fresh_when_available(monkeypatch):
    """When get_cached returns a hit, get_cached_latest must NOT be
    invoked, regardless of allow_stale."""
    from backend.services import analysis_cache_service as acs

    latest_called: list[bool] = []

    def fake_get_cached(ticker, fields_needed=None):
        return {"sentinel": "fresh"}

    def fake_get_latest(ticker, max_age_hours=168):
        latest_called.append(True)
        return {"sentinel": "stale"}

    monkeypatch.setattr(acs, "get_cached", fake_get_cached)
    monkeypatch.setattr(acs, "get_cached_latest", fake_get_latest)

    assert acs.get_canonical_payload("X", allow_stale=False) == {
        "sentinel": "fresh"}
    assert acs.get_canonical_payload("X", allow_stale=True) == {
        "sentinel": "fresh"}
    assert latest_called == []


def test_canonical_payload_forwards_fields_needed(monkeypatch):
    """fields_needed must reach get_cached so the manifest gate can
    do field-scoped invalidation."""
    from backend.services import analysis_cache_service as acs

    seen: dict[str, object] = {}

    def fake_get_cached(ticker, fields_needed=None):
        seen["fields"] = fields_needed
        return {"ok": True}

    monkeypatch.setattr(acs, "get_cached", fake_get_cached)
    acs.get_canonical_payload("X", fields_needed=["fair_value", "verdict"])
    assert seen["fields"] == ["fair_value", "verdict"]


# ─────────────────────────────────────────────────────────────────
# Day-113 manifest entry presence
# ─────────────────────────────────────────────────────────────────


def test_day113_manifest_entry_present():
    """The Phase B.1 deploy must add the v_day113 entry so that fresh
    workers re-import the manifest module and run the import-time sweep
    with this entry inside the lookback window."""
    import backend.services.cache_invalidation_manifest as m
    importlib.reload(m)
    ids = [e.get("version_id") for e in m.MANIFEST]
    assert any(vid and "day113_phase_b1" in vid for vid in ids), \
        f"v_day113 entry missing from manifest: {ids[-3:]}"
