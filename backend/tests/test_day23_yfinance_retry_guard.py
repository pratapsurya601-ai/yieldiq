"""Day-23 (2026-05-20): regression guard for the yfinance retry-chain
tightening. Day-22 baseline profile flagged 30+ tickers historically
taking 45-62 seconds in the yfinance fallback (worst case 3 attempts
× ~15s + 3s+6s sleep = 54s). Day-23 cut to 2 attempts + 1s backoff
+ 15s wall-time guard = ~17s worst case.

Source-text grep — no heavy imports, no live API needed.
"""
from __future__ import annotations
from pathlib import Path


_SERVICE = Path(__file__).resolve().parents[2] / "backend" / "services" / "analysis" / "service.py"


def test_yfinance_retry_count_reduced_to_2():
    """The retry loop must iterate AT MOST 2 attempts. The old code
    was `for _attempt in range(3)`. The new code is `for _attempt in
    range(2)`."""
    src = _SERVICE.read_text(encoding="utf-8")
    assert "for _attempt in range(2):" in src, (
        "yfinance retry loop should use range(2), not range(3). "
        "3 attempts produces 45-62s worst case (live data Day-22)."
    )
    # Confirm the old 3-attempt loop is removed
    # (use a unique surrounding line to avoid matching the new code)
    assert "for _attempt in range(3):" not in src, (
        "Old `range(3)` loop still present somewhere in service.py — "
        "Day-23 cut to range(2). Find and remove the stale one."
    )


def test_yfinance_wall_time_guard_present():
    """A 15s wall-time guard must short-circuit the retry loop if
    earlier attempts already burned the budget. Without this guard,
    a single slow yfinance call (~15s) followed by a successful one
    could still take 30s total."""
    src = _SERVICE.read_text(encoding="utf-8")
    assert "_YF_WALL_BUDGET_S = 15.0" in src, (
        "Wall-time guard constant missing or value changed."
    )
    assert "(_time.perf_counter() - _yf_t_start) > _YF_WALL_BUDGET_S" in src, (
        "Wall-time guard check missing from retry loop."
    )


def test_yfinance_backoff_reduced_to_1s():
    """The inter-attempt sleep should be 1.0s, not 3s + 6s. With only
    2 attempts, the long backoff (originally to give yfinance auth
    flips time to recover) is no longer cost-effective — Day-22 data
    showed auth flips don't recover in 1-9s anyway."""
    src = _SERVICE.read_text(encoding="utf-8")
    assert "_time.sleep(1.0)" in src, (
        "Day-23 backoff should be _time.sleep(1.0). Check the value."
    )
    # Old code had `_time.sleep(3 + _attempt * 3)` — must be removed
    assert "_time.sleep(3 + _attempt * 3)" not in src, (
        "Old 3s+6s backoff still present — remove."
    )


def test_yfinance_backoff_only_between_attempts():
    """Sleep must be guarded by `_attempt < 1` (not the old
    `_attempt < 2`). With 2 attempts indexed 0,1: sleep should
    happen ONCE between them."""
    src = _SERVICE.read_text(encoding="utf-8")
    assert "if raw is None and _attempt < 1:" in src, (
        "Backoff guard not updated to `_attempt < 1` for the 2-attempt "
        "loop. The old guard `_attempt < 2` would still sleep AFTER "
        "the last attempt (waste)."
    )


def test_yfinance_change_documented_with_day23_comment():
    """The change must carry an explanatory comment so a future
    engineer knows why the retry was tightened (not a random tweak)."""
    src = _SERVICE.read_text(encoding="utf-8")
    assert "Day-23 (2026-05-20)" in src
    assert "45-62s" in src or "54s worst case" in src, (
        "Day-23 comment should reference the observed live latency that "
        "motivated the change."
    )
