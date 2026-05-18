"""Tests for the live_quotes write-time sanity gate.

Gate lives in `backend.workers.market_data_refresher._sanity_check_quote`
(and is mirrored in `scripts.data_pipelines.bulk_refresh_live_quotes` —
that copy is exercised indirectly through the same scenarios).

Background: on 2026-05-18 POLICYBZR had live_quotes.price = ₹16,479
(true CMP ~₹1,718, ~9x inflation) because yfinance fast_info returned
one absurd tick and the refresher accepted it. PR #317 added a READ-
time staleness gate; this gate is the WRITE-time complement that
prevents the bad value from ever landing.

Scenarios covered (matches the PR brief):
  1. New ticker with no prev → accept.
  2. Stable prev, normal ±5% move → accept.
  3. POLICYBZR-class: prev ₹1,718, new ₹16,479 → REJECT.
  4. Split-day-shaped move (prev ₹100, new ₹3) → REJECT with caveat
     about a future corporate-actions allow-list.
  5. prev_close band: new is double the prev_close (huge gap-up) →
     REJECT when a prev_live row exists.
  6. Defensive: non-positive new price → REJECT.

These tests are pure offline — no yfinance, no DB. They exercise the
pure helper directly so they run in <50ms and have zero flake surface.
"""
from __future__ import annotations

import pytest

from backend.workers.market_data_refresher import (
    INTRADAY_MAX_MOVE,
    PREV_CLOSE_LOWER_BAND,
    PREV_CLOSE_UPPER_BAND,
    _sanity_check_quote,
)


def test_new_ticker_no_prev_is_accepted():
    """First-ever fetch must seed the row — gate cannot block it."""
    accept, reason = _sanity_check_quote(
        ticker="NEWCO.NS",
        new_price=500.0,
        prev_close=None,
        prev_live_price=None,
    )
    assert accept is True
    assert reason is None


def test_stable_prev_small_move_is_accepted():
    """A normal intraday wiggle (±5%) is well within both bands."""
    # +5% from prev_live, +5% vs prev_close → ratio 1.05, inside [0.80, 1.20]
    accept, reason = _sanity_check_quote(
        ticker="TCS.NS",
        new_price=3150.0,
        prev_close=3000.0,
        prev_live_price=3000.0,
    )
    assert accept is True, f"unexpected reject: {reason}"


def test_stable_prev_minus_five_percent_is_accepted():
    accept, reason = _sanity_check_quote(
        ticker="TCS.NS",
        new_price=2850.0,
        prev_close=3000.0,
        prev_live_price=3000.0,
    )
    assert accept is True, f"unexpected reject: {reason}"


def test_policybzr_class_corruption_is_rejected():
    """The exact case from 2026-05-18: prev ₹1,718, new ₹16,479 (9.6x)."""
    accept, reason = _sanity_check_quote(
        ticker="POLICYBZR.NS",
        new_price=16479.0,
        prev_close=1715.0,  # consistent with prev_live
        prev_live_price=1718.0,
    )
    assert accept is False
    assert reason is not None
    assert "intraday_move" in reason
    # Sanity: the rejected move is dramatically > the 50% threshold.
    move = abs(16479.0 - 1718.0) / 1718.0
    assert move > INTRADAY_MAX_MOVE


def test_split_day_shaped_move_is_rejected_with_caveat():
    """A 1:33 split shows up as a 97% drop. The gate rejects this.

    CAVEAT: this is the documented false-positive case. On a real
    corporate-action ex-date the refresher will reject the (legitimate)
    post-split price until human intervention or the planned
    (ticker, date) allow-list lands. Logging the reject as a warning
    means it shows up in the Railway worker logs the same day.
    """
    accept, reason = _sanity_check_quote(
        ticker="SPLITCO.NS",
        new_price=3.0,
        prev_close=100.0,
        prev_live_price=100.0,
    )
    assert accept is False
    assert reason is not None


def test_prev_close_band_rejects_when_prev_live_exists():
    """If yfinance reports new=2x prev_close, that is implausible for
    equities (NSE circuit-breakers cap at ±20%). With a prev_live row
    in place, the gate should reject even if the move vs prev_live
    happens to be small (i.e. both prev_live and prev_close are stale
    /wrong in the same direction)."""
    # new vs prev_live is exactly INTRADAY_MAX_MOVE (50%), so we set
    # new slightly under that threshold to isolate the prev_close band.
    # prev_live = 100, new = 140 → 40% intraday (under 50% gate).
    # prev_close = 100, new = 140 → ratio 1.40 (over 1.20 band) → reject.
    accept, reason = _sanity_check_quote(
        ticker="GAPPER.NS",
        new_price=140.0,
        prev_close=100.0,
        prev_live_price=100.0,
    )
    assert accept is False
    assert reason is not None
    assert "prev_close_band" in reason


def test_prev_close_band_lower_side():
    accept, reason = _sanity_check_quote(
        ticker="GAPPER.NS",
        new_price=70.0,           # 30% gap-down vs prev_close
        prev_close=100.0,
        prev_live_price=100.0,    # 30% intraday — under 50% gate
    )
    assert accept is False
    assert "prev_close_band" in (reason or "")


def test_non_positive_price_is_rejected():
    accept, reason = _sanity_check_quote(
        ticker="ZERO.NS",
        new_price=0.0,
        prev_close=100.0,
        prev_live_price=100.0,
    )
    assert accept is False
    assert reason == "non_positive_price"


def test_boundary_exactly_at_intraday_threshold_accepted():
    """A move of exactly 50% (≤ gate) is accepted; >50% is rejected.

    Locks in the inclusive boundary so a future refactor that flips it
    to a strict `>=` doesn't silently change behaviour.
    """
    accept, _ = _sanity_check_quote(
        ticker="EDGE.NS",
        new_price=150.0,           # exactly +50%
        prev_close=150.0,           # ratio 1.00 vs prev_close
        prev_live_price=100.0,
    )
    assert accept is True


def test_no_prev_close_means_only_intraday_check_applies():
    """If yfinance fails to return previous_close, we still rely on the
    intraday gate. A normal-ish move should pass; a 9x move should fail.
    """
    ok_accept, _ = _sanity_check_quote(
        ticker="NOPC.NS",
        new_price=105.0,
        prev_close=None,
        prev_live_price=100.0,
    )
    assert ok_accept is True

    bad_accept, bad_reason = _sanity_check_quote(
        ticker="NOPC.NS",
        new_price=900.0,
        prev_close=None,
        prev_live_price=100.0,
    )
    assert bad_accept is False
    assert "intraday_move" in (bad_reason or "")


# ─── Bulk-refresh script twin gate — tested through its own module so
#     a copy-paste drift between the two implementations is caught. ───

def test_bulk_refresh_gate_matches_canonical():
    """The standalone script copy of the gate must behave identically
    to the canonical one on the headline POLICYBZR scenario. Catches
    accidental drift between the two files."""
    from scripts.data_pipelines.bulk_refresh_live_quotes import (
        _sanity_check_quote as bulk_gate,
    )

    canonical = _sanity_check_quote(
        "POLICYBZR.NS", 16479.0, 1715.0, 1718.0,
    )
    bulk = bulk_gate("POLICYBZR.NS", 16479.0, 1715.0, 1718.0)
    assert canonical[0] == bulk[0] is False
    # Reasons should look alike (both encode the intraday-move detail).
    assert "intraday_move" in canonical[1]
    assert "intraday_move" in bulk[1]


def test_bulk_refresh_gate_accepts_first_fetch():
    from scripts.data_pipelines.bulk_refresh_live_quotes import (
        _sanity_check_quote as bulk_gate,
    )
    accept, reason = bulk_gate("NEWCO.NS", 500.0, None, None)
    assert accept is True
    assert reason is None


@pytest.mark.parametrize(
    "upper,lower",
    [(PREV_CLOSE_UPPER_BAND, PREV_CLOSE_LOWER_BAND)],
)
def test_band_constants_are_symmetric(upper, lower):
    """Locks in the ±20% band invariant so a future tweak that only
    moves one side gets caught."""
    assert pytest.approx(upper - 1.0, rel=1e-9) == 1.0 - lower
