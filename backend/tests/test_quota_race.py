# backend/tests/test_quota_race.py
# Regression test for the over-quota race that let a free-tier user's
# nav counter render "14/5 today" (observed in prod 2026-04-25).
#
# Two layers of defence are tested:
#   1. RateLimiter.check_and_increment is concurrency-safe — under N
#      simultaneous calls on a fresh user with limit=L, exactly L
#      increments succeed and N-L are denied. The DB count never
#      exceeds L.
#   2. clamped_used() never returns a value greater than the limit,
#      regardless of how high the raw DB count drifted (e.g. via a
#      tier flip).
#
# The first layer exercises the in-memory fallback (no DATABASE_URL
# in the test env) which uses a threading.Lock — the SQL UPSERT path
# has the same contract via Postgres row locking and is exercised by
# the canary harness in CI.
#
# Run: pytest backend/tests/test_quota_race.py -v
from __future__ import annotations

import sys
import threading
import uuid
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest

from backend.middleware.rate_limit import RateLimiter, clamped_used


def test_clamped_used_never_exceeds_limit():
    # Happy path
    assert clamped_used(0, 5) == 0
    assert clamped_used(3, 5) == 3
    assert clamped_used(5, 5) == 5
    # Drift cases — the bug we're fixing
    assert clamped_used(14, 5) == 5
    assert clamped_used(999, 5) == 5
    # Defensive edges
    assert clamped_used(-1, 5) == 0
    assert clamped_used(0, 0) == 0
    assert clamped_used(99, 0) == 0


def test_concurrent_increments_respect_limit():
    """6 concurrent requests on a fresh user, limit=5 → exactly 5 allowed."""
    limiter = RateLimiter()
    # Force in-memory path (DATABASE_URL may or may not be set in the
    # test env; we want this test to be hermetic).
    limiter._get_session = lambda: None  # type: ignore[assignment]

    user_id = f"test-user-{uuid.uuid4()}"
    results: list[tuple[bool, int, int]] = []
    results_lock = threading.Lock()
    barrier = threading.Barrier(6)

    def worker():
        # Synchronise so all 6 hit check_and_increment as close to
        # simultaneously as the GIL + scheduler will allow.
        barrier.wait()
        r = limiter.check_and_increment(user_id, "free")
        with results_lock:
            results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(6)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    allowed_results = [r for r in results if r[0]]
    denied_results = [r for r in results if not r[0]]

    assert len(allowed_results) == 5, (
        f"expected exactly 5 allowed, got {len(allowed_results)}: {results}"
    )
    assert len(denied_results) == 1, (
        f"expected exactly 1 denied (429), got {len(denied_results)}: {results}"
    )
    # Final DB count must be ≤ limit
    final_used, final_limit = limiter.get_usage(user_id, "free")
    assert final_used == 5, f"counter drifted: used={final_used}"
    assert final_limit == 5
    # Each `allowed` result reports its own post-increment count; those
    # should be a permutation of 1..5 (no duplicates → no double-count).
    counts = sorted(r[1] for r in allowed_results)
    assert counts == [1, 2, 3, 4, 5], f"duplicate counts (race!): {counts}"


def test_check_and_increment_blocks_at_limit():
    """Once at limit, further calls return (False, limit, limit)."""
    limiter = RateLimiter()
    limiter._get_session = lambda: None  # type: ignore[assignment]

    user_id = f"test-user-{uuid.uuid4()}"
    for _ in range(5):
        allowed, used, limit = limiter.check_and_increment(user_id, "free")
        assert allowed
    for _ in range(3):
        allowed, used, limit = limiter.check_and_increment(user_id, "free")
        assert not allowed
        assert used == 5
        assert limit == 5
        # And the display clamp would render this as 5/5, not 6/5 etc.
        assert clamped_used(used, limit) == 5
