"""Tests for the Pro-tier API key system.

Covers:
  * Key generation format (yk_ prefix, 35 chars total)
  * SHA-256 hashing (64 hex chars)
  * create_key returns raw + persists hash, NOT raw
  * authenticate(raw) hits / misses / rejects malformed input
  * revoke_key flips state and breaks subsequent authenticate
  * check_and_increment_quota allows up to cap, denies cap+1
  * Race test: 105 concurrent calls → exactly 100 allowed

Hermetic — runs against the in-memory fallback so no DATABASE_URL is
required. The DB path uses the same atomic UPSERT semantics that
backend/middleware/rate_limit.py already exercises in CI against
real Postgres.
"""
from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest

from backend.services import api_keys_service as svc


@pytest.fixture(autouse=True)
def _reset():
    """Wipe in-memory state before every test so they don't bleed."""
    svc._reset_memory_for_tests()
    yield
    svc._reset_memory_for_tests()


def _force_memory_path(monkeypatch):
    """Make sure tests use the in-memory store even if DATABASE_URL is set."""
    monkeypatch.setattr(svc, "_connect", lambda: None)


# ── Generation + hashing ────────────────────────────────────────────

def test_generate_raw_key_format():
    raw = svc._generate_raw_key()
    assert raw.startswith("yk_")
    assert len(raw) == 35  # 'yk_' (3) + 32 body chars
    body = raw[3:]
    assert len(body) == 32
    # Charset: lowercase + digits only
    assert all(c.isalnum() and (c.islower() or c.isdigit()) for c in body)


def test_generate_raw_key_unique():
    seen = {svc._generate_raw_key() for _ in range(50)}
    assert len(seen) == 50  # cryptographic randomness — no collisions


def test_hash_sha256_64_hex():
    h = svc._hash("yk_testkey")
    assert len(h) == 64
    int(h, 16)  # must parse as hex


# ── create / list / authenticate / revoke ───────────────────────────

def test_create_key_returns_raw_and_persists_hash(monkeypatch):
    _force_memory_path(monkeypatch)
    user = "user-1"
    result = svc.create_key(user, "My script")
    assert result["raw"].startswith("yk_")
    assert result["prefix"] == result["raw"][:10]
    assert result["label"] == "My script"
    assert isinstance(result["id"], int)

    # Verify storage: hash present, raw NOT present anywhere in the
    # in-memory row.
    row = svc._mem_keys[result["id"]]
    assert row["key_hash"] == svc._hash(result["raw"])
    assert result["raw"] not in str(row)


def test_create_key_default_label(monkeypatch):
    _force_memory_path(monkeypatch)
    r = svc.create_key("user-1", "")
    assert r["label"] == "Untitled"


def test_list_keys_excludes_raw_and_revoked(monkeypatch):
    _force_memory_path(monkeypatch)
    user = "user-2"
    a = svc.create_key(user, "A")
    b = svc.create_key(user, "B")
    listing = svc.list_keys(user)
    assert len(listing) == 2
    for row in listing:
        assert "raw" not in row
        assert "key_hash" not in row
    # Revoke one — list shrinks.
    assert svc.revoke_key(user, a["id"]) is True
    listing2 = svc.list_keys(user)
    assert len(listing2) == 1
    assert listing2[0]["id"] == b["id"]


def test_list_keys_scoped_per_user(monkeypatch):
    _force_memory_path(monkeypatch)
    svc.create_key("user-A", "alpha")
    svc.create_key("user-B", "beta")
    assert len(svc.list_keys("user-A")) == 1
    assert len(svc.list_keys("user-B")) == 1
    assert len(svc.list_keys("user-C")) == 0


def test_authenticate_hit(monkeypatch):
    _force_memory_path(monkeypatch)
    r = svc.create_key("user-1", "k")
    info = svc.authenticate(r["raw"])
    assert info is not None
    assert info["user_id"] == "user-1"
    assert info["api_key_id"] == r["id"]


def test_authenticate_miss_unknown_key(monkeypatch):
    _force_memory_path(monkeypatch)
    # Well-formed but never-issued key.
    bogus = "yk_" + "a" * 32
    assert svc.authenticate(bogus) is None


@pytest.mark.parametrize("bad", [
    "",
    None,
    "not a real key",
    "Bearer yk_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx",
    "xk_short",
    "yk_short",
    "yk_" + "a" * 31,   # one too short
    "yk_" + "a" * 33,   # one too long
])
def test_authenticate_rejects_malformed(monkeypatch, bad):
    _force_memory_path(monkeypatch)
    assert svc.authenticate(bad) is None


def test_revoke_then_authenticate_misses(monkeypatch):
    _force_memory_path(monkeypatch)
    r = svc.create_key("user-1", "k")
    assert svc.authenticate(r["raw"]) is not None
    assert svc.revoke_key("user-1", r["id"]) is True
    assert svc.authenticate(r["raw"]) is None


def test_revoke_other_users_key_returns_false(monkeypatch):
    _force_memory_path(monkeypatch)
    r = svc.create_key("user-1", "k")
    # user-2 cannot revoke user-1's key.
    assert svc.revoke_key("user-2", r["id"]) is False
    assert svc.authenticate(r["raw"]) is not None  # still alive


def test_revoke_twice_second_returns_false(monkeypatch):
    _force_memory_path(monkeypatch)
    r = svc.create_key("user-1", "k")
    assert svc.revoke_key("user-1", r["id"]) is True
    assert svc.revoke_key("user-1", r["id"]) is False


# ── Quota ───────────────────────────────────────────────────────────

def test_quota_allows_up_to_cap(monkeypatch):
    _force_memory_path(monkeypatch)
    r = svc.create_key("user-1", "k")
    cap = svc.DAILY_REQUEST_CAP
    for i in range(cap):
        allowed, count, returned_cap = svc.check_and_increment_quota(r["id"])
        assert allowed, f"call {i+1}/{cap} should be allowed"
        assert count == i + 1
        assert returned_cap == cap


def test_quota_denies_over_cap(monkeypatch):
    _force_memory_path(monkeypatch)
    r = svc.create_key("user-1", "k")
    cap = svc.DAILY_REQUEST_CAP
    for _ in range(cap):
        svc.check_and_increment_quota(r["id"])
    allowed, count, returned_cap = svc.check_and_increment_quota(r["id"])
    assert not allowed
    assert count == cap
    assert returned_cap == cap


def test_quota_concurrent_105_yields_exactly_100(monkeypatch):
    """Race test — fire 105 concurrent quota checks against a single key.
    Exactly DAILY_REQUEST_CAP (100) must be allowed; the rest must
    be denied. The in-memory path uses a threading.Lock so this is a
    real concurrency test of the compare-and-swap.
    """
    _force_memory_path(monkeypatch)
    r = svc.create_key("user-1", "race")
    cap = svc.DAILY_REQUEST_CAP
    n = cap + 5

    results: list[tuple[bool, int, int]] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(n)

    def worker():
        barrier.wait()
        out = svc.check_and_increment_quota(r["id"])
        with results_lock:
            results.append(out)

    threads = [threading.Thread(target=worker) for _ in range(n)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    allowed = [x for x in results if x[0]]
    denied = [x for x in results if not x[0]]
    assert len(allowed) == cap, (
        f"expected exactly {cap} allowed, got {len(allowed)}"
    )
    assert len(denied) == 5, (
        f"expected exactly 5 denied, got {len(denied)}"
    )
    # The set of post-increment counts on allowed calls must be 1..cap
    # — no duplicates would mean a double-count race slipped through.
    counts = sorted(x[1] for x in allowed)
    assert counts == list(range(1, cap + 1))


def test_quota_per_key_not_per_user(monkeypatch):
    """Two keys under the same user have INDEPENDENT counters."""
    _force_memory_path(monkeypatch)
    a = svc.create_key("user-1", "a")
    b = svc.create_key("user-1", "b")
    cap = svc.DAILY_REQUEST_CAP
    # Burn out key A.
    for _ in range(cap):
        svc.check_and_increment_quota(a["id"])
    a_blocked, _, _ = svc.check_and_increment_quota(a["id"])
    assert not a_blocked
    # Key B is still fresh.
    b_allowed, b_count, _ = svc.check_and_increment_quota(b["id"])
    assert b_allowed
    assert b_count == 1
