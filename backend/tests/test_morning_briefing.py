"""Unit + integration tests for the Morning Briefing service.

Covers the four acceptance scenarios in the brief:

  1. Full briefing — portfolio + watchlist + NIFTY all populated.
  2. Empty portfolio — new user with no holdings.
  3. No watchlist — populated portfolio, empty watchlist (no third
     sentence about watched movers).
  4. Cache hit — second call within TTL returns the SAME object
     without re-running the fetchers.

Plus pure-function coverage on the composer and SEBI vocab checks
on the rendered prose (banned: buy/sell/should/recommend/etc.).

All external I/O (Supabase, Aiven, live_quotes, earnings calendar)
is stubbed via monkeypatch on the service module — no network.
"""
from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services import morning_briefing_service as svc  # noqa: E402


# Banned vocab — keep in sync with scripts/check_sebi_words.py.
# These MUST NOT appear in any rendered briefing prose.
_BANNED = (
    "buy", "sell", "hold", "recommend", "recommendation",
    "should", "appears", "outperform", "underperform",
    "attractive", "cheap", "expensive", "accumulate",
)


def _assert_sebi_clean(text: str) -> None:
    """Every banned word check is word-boundary, case-insensitive."""
    import re
    low = text.lower()
    for word in _BANNED:
        pattern = re.compile(rf"\b{re.escape(word)}\b")
        assert not pattern.search(low), (
            f"SEBI lint hit in briefing prose: {word!r} found in: {text!r}"
        )


# ─────────────────────────────────────────────────────────────────
# Composer unit tests (no fetch plumbing)
# ─────────────────────────────────────────────────────────────────


def test_compose_briefing_full_path():
    text = svc._compose_briefing_text(
        has_portfolio=True,
        nifty_change_pct=-1.1,
        biggest_mover={
            "ticker": "HDFCBANK.NS", "display": "HDFCBANK",
            "pct": -0.8, "direction": "drag",
        },
        watch_movers_count=3,
        earnings_event={"ticker": "ITC.NS", "date": date(2026, 6, 15)},
    )
    # NIFTY direction sentence
    assert "NIFTY 50" in text
    assert "down 1.1%" in text
    # Biggest holding sentence
    assert "HDFCBANK" in text
    assert "drag" in text
    # Watchlist sentence — uses _WATCH_MOVE_THRESHOLD_PCT (2.0).
    assert "3 stocks you watch moved" in text
    assert "more than 2%" in text
    # Earnings sentence
    assert "ITC" in text
    assert "reports earnings" in text
    # SEBI lint
    _assert_sebi_clean(text)
    # 4 sentences (period-terminated)
    assert text.count(".") >= 4


def test_compose_briefing_empty_portfolio():
    text = svc._compose_briefing_text(
        has_portfolio=False,
        nifty_change_pct=0.5,
        biggest_mover=None,
        watch_movers_count=0,
        earnings_event=None,
    )
    # Empty-portfolio path mentions onboarding only, no biggest-mover
    # / watchlist / earnings sentences.
    assert "Welcome" in text
    assert "add your first stock" in text
    assert "drag" not in text
    assert "lift" not in text
    _assert_sebi_clean(text)


def test_compose_briefing_no_watchlist_movement():
    # 0 watchlist movers → no "N stocks you watch moved" sentence.
    text = svc._compose_briefing_text(
        has_portfolio=True,
        nifty_change_pct=0.3,
        biggest_mover={
            "ticker": "TCS.NS", "display": "TCS",
            "pct": 1.2, "direction": "lift",
        },
        watch_movers_count=0,
        earnings_event=None,
    )
    assert "TCS" in text
    assert "lift" in text
    assert "stocks you watch" not in text
    _assert_sebi_clean(text)


def test_biggest_holding_mover_picks_largest_abs():
    holdings = [
        {"ticker": "ITC.NS", "day_change_pct": 0.5},
        {"ticker": "HDFCBANK.NS", "day_change_pct": -2.3},
        {"ticker": "TCS.NS", "day_change_pct": 1.1},
    ]
    best = svc._biggest_holding_mover(holdings)
    assert best is not None
    assert best["ticker"] == "HDFCBANK.NS"
    assert best["direction"] == "drag"  # negative → drag
    assert abs(best["pct"] - (-2.3)) < 1e-9


def test_biggest_holding_mover_handles_missing_pct():
    # Holdings with day_change_pct=None should be skipped, not crash.
    holdings = [
        {"ticker": "ITC.NS", "day_change_pct": None},
        {"ticker": "TCS.NS", "day_change_pct": 0.7},
    ]
    best = svc._biggest_holding_mover(holdings)
    assert best is not None
    assert best["ticker"] == "TCS.NS"


def test_biggest_holding_mover_empty_returns_none():
    assert svc._biggest_holding_mover([]) is None
    assert svc._biggest_holding_mover([{"ticker": "X", "day_change_pct": None}]) is None


def test_count_watch_movers_strict_threshold():
    # Threshold is STRICTLY greater than 2.0% — exactly 2.0 should NOT count.
    quotes = {
        "A.NS": {"change_pct": 2.5},    # counts (>2)
        "B.NS": {"change_pct": -3.1},   # counts (|.|>2)
        "C.NS": {"change_pct": 2.0},    # does NOT count (==2, not strictly >)
        "D.NS": {"change_pct": 0.5},    # does NOT count
        "E.NS": {"change_pct": None},   # does NOT count
        "F.NS": {},                     # missing key → 0
    }
    n = svc._count_watch_movers(
        ["A.NS", "B.NS", "C.NS", "D.NS", "E.NS", "F.NS", "GHOST.NS"],
        quotes,
    )
    # A, B count. C is on the boundary and excluded.
    assert n == 2


def test_portfolio_block_empty_returns_none():
    assert svc._portfolio_block([], {}) is None


def test_portfolio_block_sums_day_change_abs():
    holdings = [
        {"day_change_abs": 100.0},
        {"day_change_abs": -25.0},
        {"day_change_abs": None},  # skipped, not summed
    ]
    summary = {"total_current_value": 1075.0}
    block = svc._portfolio_block(holdings, summary)
    assert block is not None
    assert block["total_value"] == pytest.approx(1075.0)
    assert block["day_change"] == pytest.approx(75.0)
    # day_change_pct derived from yesterday = 1000, change = +75 → +7.5%
    assert block["day_change_pct"] == pytest.approx(7.5)


def test_fmt_arrow_pct_directions():
    assert "down 1.1%" == svc._fmt_arrow_pct(-1.1)
    assert "up 0.8%" == svc._fmt_arrow_pct(0.8)
    assert "flat" == svc._fmt_arrow_pct(None)


def test_display_name_from_email_strips_separators():
    assert svc._display_name_from_email("surya.pratap@x.com") == "Surya"
    assert svc._display_name_from_email("vinit_kumar@x.com") == "Vinit"
    assert svc._display_name_from_email("anon+test@x.com") == "Anon"
    assert svc._display_name_from_email("") == "there"
    assert svc._display_name_from_email(None) == "there"


# ─────────────────────────────────────────────────────────────────
# build_morning_briefing integration — all I/O stubbed
# ─────────────────────────────────────────────────────────────────


@pytest.fixture
def patched_fetchers(monkeypatch):
    """Stub every fetch_* helper on the service module. Returns a
    mutable spec dict the test can mutate before calling build."""
    spec: dict = {
        "portfolio": {"holdings": [], "summary": {}},
        "watch_tickers": [],
        "quotes": {},
        "nifty": {},
        "sparkline": [],
        "earnings": None,
    }

    monkeypatch.setattr(svc, "_fetch_portfolio_with_day_change",
                        lambda _e: spec["portfolio"])
    monkeypatch.setattr(svc, "_fetch_watchlist_tickers",
                        lambda _e: spec["watch_tickers"])
    monkeypatch.setattr(svc, "_fetch_live_quotes",
                        lambda _t: spec["quotes"])
    monkeypatch.setattr(svc, "_fetch_nifty_snapshot",
                        lambda: spec["nifty"])
    monkeypatch.setattr(svc, "_fetch_index_sparkline_7d",
                        lambda _s="NIFTY 50": spec["sparkline"])
    monkeypatch.setattr(svc, "_fetch_upcoming_earnings",
                        lambda _ts: spec["earnings"])
    # Clean cache between tests so cache-hit logic doesn't bleed.
    from backend.services.cache_service import cache as _c
    _c.delete("briefing:morning:user-test-1")
    _c.delete("briefing:morning:user-test-2")
    return spec


def test_build_full_briefing_populated(patched_fetchers):
    """Scenario 1 — portfolio + watchlist + NIFTY all populated.
    Validates wire shape AND SEBI cleanliness on the rendered prose.
    """
    patched_fetchers["portfolio"] = {
        "holdings": [
            {
                "ticker": "HDFCBANK.NS",
                "day_change_pct": -0.8,
                "day_change_abs": -1200.0,
            },
            {
                "ticker": "ITC.NS",
                "day_change_pct": 0.5,
                "day_change_abs": 220.0,
            },
        ],
        "summary": {"total_current_value": 342_180.50},
    }
    patched_fetchers["watch_tickers"] = ["RELIANCE.NS", "TCS.NS", "INFY.NS"]
    patched_fetchers["quotes"] = {
        "RELIANCE.NS": {"change_pct": 3.1},
        "TCS.NS": {"change_pct": -2.4},
        "INFY.NS": {"change_pct": 0.4},
    }
    patched_fetchers["nifty"] = {
        "symbol": "NIFTY 50", "price": 23_123.45, "change_pct": -1.10,
    }
    patched_fetchers["sparkline"] = [23_300, 23_280, 23_350, 23_400, 23_290, 23_200, 23_123]

    user = {"user_id": "user-test-1", "email": "surya@example.com"}
    payload = svc.build_morning_briefing(user)

    # Wire-shape contract
    assert set(payload.keys()) >= {
        "as_of", "user_name", "portfolio", "market", "briefing_text",
    }
    assert payload["user_name"] == "Surya"
    # Portfolio tile
    assert payload["portfolio"] is not None
    assert payload["portfolio"]["total_value"] == pytest.approx(342_180.50)
    assert payload["portfolio"]["day_change"] == pytest.approx(-980.0)
    # Market tile
    assert payload["market"]["nifty_value"] == pytest.approx(23_123.45)
    assert payload["market"]["nifty_change_pct"] == pytest.approx(-1.10)
    assert payload["market"]["nifty_sparkline_7d"] == [
        23_300, 23_280, 23_350, 23_400, 23_290, 23_200, 23_123,
    ]
    # Briefing prose — observational, mentions biggest drag + 2 watchers >2%.
    text = payload["briefing_text"]
    assert "NIFTY 50" in text
    assert "HDFCBANK" in text
    assert "drag" in text
    assert "2 stocks you watch moved" in text  # RELIANCE (3.1) + TCS (-2.4)
    _assert_sebi_clean(text)


def test_build_briefing_empty_portfolio(patched_fetchers):
    """Scenario 2 — new user with zero holdings.

    The portfolio tile MUST be None (frontend hides it). The briefing
    line is the onboarding welcome, not a stale "biggest drag" line.
    """
    patched_fetchers["nifty"] = {
        "symbol": "NIFTY 50", "price": 23_500.0, "change_pct": 0.42,
    }
    # holdings already [], watchlist already []

    user = {"user_id": "user-test-2", "email": "newbie@example.com"}
    payload = svc.build_morning_briefing(user)

    assert payload["portfolio"] is None
    assert payload["market"]["nifty_value"] == pytest.approx(23_500.0)
    text = payload["briefing_text"]
    assert "Welcome" in text
    assert "add your first stock" in text
    # No "biggest drag/lift" prose on the empty path.
    assert "drag" not in text
    assert "lift" not in text
    _assert_sebi_clean(text)


def test_build_briefing_no_watchlist_no_earnings(patched_fetchers):
    """Scenario 3 — populated portfolio, empty watchlist.

    Briefing skips the "N stocks you watch moved" sentence entirely.
    Earnings sentence also skipped (no upcoming event in horizon).
    """
    patched_fetchers["portfolio"] = {
        "holdings": [
            {"ticker": "TCS.NS", "day_change_pct": 1.4, "day_change_abs": 850.0},
        ],
        "summary": {"total_current_value": 100_000.0},
    }
    patched_fetchers["nifty"] = {"price": 23_400.0, "change_pct": 0.3}
    # watch_tickers, earnings already empty/None

    user = {"user_id": "user-test-1", "email": "x@example.com"}
    payload = svc.build_morning_briefing(user)

    text = payload["briefing_text"]
    assert "TCS" in text
    assert "lift" in text
    assert "stocks you watch" not in text  # third sentence omitted
    assert "reports earnings" not in text  # fourth sentence omitted
    _assert_sebi_clean(text)


def test_build_briefing_cache_hit_skips_refetch(patched_fetchers):
    """Scenario 4 — second call within TTL must NOT re-invoke the
    fetchers. We swap the stubs to a sentinel that would change the
    output, then assert the second call returned the cached payload.
    """
    patched_fetchers["portfolio"] = {
        "holdings": [
            {"ticker": "ITC.NS", "day_change_pct": 0.5, "day_change_abs": 100.0},
        ],
        "summary": {"total_current_value": 50_000.0},
    }
    patched_fetchers["nifty"] = {"price": 23_000.0, "change_pct": 0.1}

    user = {"user_id": "user-test-1", "email": "cache@example.com"}
    first = svc.build_morning_briefing(user)
    first_text = first["briefing_text"]

    # Now mutate every fetcher's return to obviously-different data.
    # A cache miss would surface NIFTY at 99000 + a brand-new ticker.
    patched_fetchers["portfolio"] = {
        "holdings": [
            {"ticker": "WIPRO.NS", "day_change_pct": -9.9, "day_change_abs": -999.0},
        ],
        "summary": {"total_current_value": 999_999.99},
    }
    patched_fetchers["nifty"] = {"price": 99_000.0, "change_pct": -5.0}

    second = svc.build_morning_briefing(user)
    # Cache must return the SAME payload — text + portfolio totals unchanged.
    assert second["briefing_text"] == first_text
    assert second["portfolio"]["total_value"] == first["portfolio"]["total_value"]
    assert second["market"]["nifty_value"] == first["market"]["nifty_value"]
    # And the new fetchers were never used — explicitly assert WIPRO didn't leak.
    assert "WIPRO" not in second["briefing_text"]


def test_build_briefing_anonymous_user_does_not_cache(patched_fetchers, monkeypatch):
    """Defensive — a user dict missing user_id (legacy token / dev
    impersonation) must bypass the cache entirely so the cross-user
    leak guard holds.
    """
    patched_fetchers["nifty"] = {"price": 23_000.0, "change_pct": 0.1}

    set_called: list[str] = []
    real_set = None
    from backend.services.cache_service import cache as _c
    real_set = _c.set
    def _spy_set(key, *args, **kwargs):
        if isinstance(key, str) and key.startswith("briefing:morning:"):
            set_called.append(key)
        return real_set(key, *args, **kwargs)
    monkeypatch.setattr(_c, "set", _spy_set)

    user_no_id = {"email": "anon@example.com"}  # NO user_id
    svc.build_morning_briefing(user_no_id)
    assert set_called == []  # nothing written to cache for anonymous

    user_with_id = {"user_id": "user-test-1", "email": "ok@example.com"}
    svc.build_morning_briefing(user_with_id)
    assert set_called == ["briefing:morning:user-test-1"]
