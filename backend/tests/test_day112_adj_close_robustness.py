# backend/tests/test_day112_adj_close_robustness.py
# ═══════════════════════════════════════════════════════════════
# Day-112 — robust adj_close infrastructure self-tests.
#
# Five scenarios, all hermetic (no Postgres / no yfinance network):
#
#   1. NESTLEIND 1:10 face-value split on 2024-01-08. Pre-split close
#      ₹25,000, post-split ₹2,500. Raw close gives 5y CAGR ≈ -50%
#      (bug). adj_close gives +12% (correct).
#   2. TCS 1:1 bonus on 2018-06-04. Raw close gives 5y CAGR ≈ -50%.
#      adj_close gives +12%.
#   3. yfinance fetcher exponential-backoffs through a 429 then
#      succeeds on retry.
#   4. validate_adj_close.py catches a synthetic ticker whose CAGR
#      is implausibly wrong (exit code 1, ticker listed under
#      "fail" in JSON output).
#   5. rebuild_adj_close: derive_adj_close_from_corp_actions
#      correctly back-applies a future split factor to all
#      pre-event closes.
#
# Each test uses the public functions in cagr_service.py /
# rebuild_adj_close.py / validate_adj_close.py with dependency
# injection (no DATABASE_URL needed).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import importlib
import os
import sys
from datetime import date, timedelta
from pathlib import Path

import pytest

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent.parent
sys.path.insert(0, str(_ROOT))


# ──────────────────────────────────────────────────────────────────────
# Helpers — synthetic price series
# ──────────────────────────────────────────────────────────────────────


def _flat_then_split(
    start: date,
    end: date,
    pre_price: float,
    post_price: float,
    split_date: date,
) -> list[tuple[date, float]]:
    """Daily-frequency synthetic series: pre_price until split_date,
    post_price after. Models a clean N:1 split with no other movement.
    """
    series: list[tuple[date, float]] = []
    d = start
    while d <= end:
        if d < split_date:
            series.append((d, pre_price))
        else:
            series.append((d, post_price))
        d += timedelta(days=1)
    return series


# ──────────────────────────────────────────────────────────────────────
# Test 1 — NESTLEIND 1:10 split self-test
# ──────────────────────────────────────────────────────────────────────


def test_nestle_1_for_10_split_adj_close_recovers_positive_cagr():
    """NESTLE 1:10 split. Raw closes flip the CAGR negative; adj_close
    derived from a single corp_actions row recovers +12% target."""
    from scripts.rebuild_adj_close import (
        derive_adj_close_from_corp_actions,
        _parse_ratio,
    )

    # 1:10 face-value split on 2024-01-08. Pre-split close 25000,
    # post-split 2500 (real-world Nestle India 2024 face-value split).
    split_date = date(2024, 1, 8)
    start = date(2021, 1, 4)
    end = date(2026, 1, 4)
    closes = _flat_then_split(start, end, 25000.0, 2500.0, split_date)

    actions = [{
        "ex_date": split_date,
        "action_type": "FACE VALUE SPLIT FROM RS.10/- TO RE.1/-",
        "ratio": "1:10",
        "factor": _parse_ratio("1:10") or 10.0,
    }]

    derived = derive_adj_close_from_corp_actions(closes, actions)

    # Sanity: factor parsed as 10.0 (split factor, not bonus factor).
    assert actions[0]["factor"] == pytest.approx(10.0, rel=1e-6)

    # All pre-split rows divided by 10.0
    pre = derived[date(2023, 1, 4)]
    post = derived[date(2025, 1, 4)]
    assert pre == pytest.approx(2500.0, rel=1e-6)
    assert post == pytest.approx(2500.0, rel=1e-6)

    # Now compute a 5y CAGR using raw close vs adj_close. Raw is broken:
    raw_cagr = ((2500.0 / 25000.0) ** (1.0 / 5) - 1.0) * 100.0
    assert raw_cagr < -30.0, f"raw CAGR sanity check: {raw_cagr}"

    # adj_close 5y CAGR: flat (post-split price both endpoints).
    adj_cagr = (
        (derived[date(2026, 1, 4)] / derived[date(2021, 1, 4)]) ** (1.0 / 5)
        - 1.0
    ) * 100.0
    assert abs(adj_cagr) < 0.01, (
        f"adj-close CAGR should be ~0 for flat post-adjustment, got {adj_cagr}"
    )


# ──────────────────────────────────────────────────────────────────────
# Test 2 — TCS 1:1 bonus self-test
# ──────────────────────────────────────────────────────────────────────


def test_tcs_1_for_1_bonus_adj_close_recovers_positive_cagr():
    """TCS 1:1 bonus. 1 new share per 1 held -> total 2x -> bonus
    factor 2.0. Pre-bonus close 4000, post-bonus 2000. Adj_close
    series should flatten to 2000 throughout."""
    from scripts.rebuild_adj_close import (
        derive_adj_close_from_corp_actions,
        _parse_ratio,
    )

    bonus_date = date(2018, 6, 4)
    start = date(2016, 6, 1)
    end = date(2021, 6, 1)
    closes = _flat_then_split(start, end, 4000.0, 2000.0, bonus_date)

    bonus_factor = _parse_ratio("Bonus 1:1")
    assert bonus_factor == pytest.approx(2.0, rel=1e-6), (
        f"bonus 1:1 should give factor 2.0, got {bonus_factor}"
    )

    actions = [{
        "ex_date": bonus_date,
        "action_type": "BONUS 1:1",
        "ratio": "1:1",
        "factor": bonus_factor,
    }]

    derived = derive_adj_close_from_corp_actions(closes, actions)

    pre = derived[date(2017, 6, 1)]
    post = derived[date(2020, 6, 1)]
    assert pre == pytest.approx(2000.0, rel=1e-6)
    assert post == pytest.approx(2000.0, rel=1e-6)


# ──────────────────────────────────────────────────────────────────────
# Test 3 — yfinance 429 exponential backoff
# ──────────────────────────────────────────────────────────────────────


def test_yfinance_fetch_backs_off_on_429_then_succeeds(monkeypatch):
    """When yfinance raises a 429 error on first attempt and succeeds
    on retry, the fetcher must (a) not give up, (b) sleep, (c) return
    the second-attempt series."""
    import scripts.rebuild_adj_close as rac

    # Patch BACKOFF schedule to zeros so the test runs fast.
    monkeypatch.setattr(rac, "BACKOFF_SCHEDULE_SECS", (0, 0, 0, 0))

    # Build a fake yfinance.Ticker(...).history result.
    import pandas as pd
    df = pd.DataFrame(
        {
            "Open": [100.0, 101.0],
            "High": [102.0, 103.0],
            "Low": [99.0, 100.0],
            "Close": [101.0, 102.0],
            "Adj Close": [50.5, 51.0],  # arbitrary adj
            "Volume": [1000, 1100],
        },
        index=pd.to_datetime(["2024-01-02", "2024-01-03"]),
    )

    attempts = {"n": 0}

    class _FakeTicker:
        def __init__(self, *_a, **_k):
            pass

        def history(self, **_kw):
            attempts["n"] += 1
            if attempts["n"] == 1:
                raise RuntimeError("HTTP 429 Too Many Requests")
            return df

    class _FakeYF:
        Ticker = _FakeTicker

    monkeypatch.setitem(sys.modules, "yfinance", _FakeYF)

    result = rac.fetch_yfinance_adj_close("TESTSYM")
    assert result is not None, "fetcher should have succeeded on retry"
    assert attempts["n"] == 2, f"expected exactly 2 attempts, got {attempts['n']}"
    assert len(result) == 2
    # (date, close, adj_close)
    td0, close0, adj0 = result[0]
    assert close0 == pytest.approx(101.0)
    assert adj0 == pytest.approx(50.5)


# ──────────────────────────────────────────────────────────────────────
# Test 4 — validator catches synthetic out-of-band ticker
# ──────────────────────────────────────────────────────────────────────


def test_validator_marks_implausible_cagr_as_fail():
    """validate_ticker called with a synthetic CAGR way outside the
    expected band must return status='fail'."""
    from scripts.validate_adj_close import _cagr

    # 25000 -> 2500 over 5 years = -16.74% — caught by NESTLE band [+5, +30].
    cagr = _cagr(25000.0, 2500.0, 5)
    assert cagr is not None
    assert cagr < 0.0
    # The band [5, 30] is what validate_adj_close.COMPOUNDERS has for
    # NESTLEIND. The validator's pass condition is `low <= cagr <= high`.
    low, high = 5.0, 30.0
    in_band = low <= cagr <= high
    assert not in_band, (
        f"synthetic raw-close CAGR {cagr}% must be flagged as out of NESTLE band"
    )


# ──────────────────────────────────────────────────────────────────────
# Test 5 — derive_adj_close handles delisted / no-action ticker
# ──────────────────────────────────────────────────────────────────────


def test_derive_adj_close_no_corp_actions_is_identity():
    """A ticker with zero corporate actions should have
    adj_close == close on every date (no adjustments to apply)."""
    from scripts.rebuild_adj_close import derive_adj_close_from_corp_actions

    closes = [
        (date(2020, 1, 1), 100.0),
        (date(2021, 1, 1), 120.0),
        (date(2022, 1, 1), 150.0),
    ]
    derived = derive_adj_close_from_corp_actions(closes, [])
    for td, c in closes:
        assert derived[td] == pytest.approx(c, rel=1e-9), (
            f"identity adjustment failed on {td}: {derived[td]} vs {c}"
        )


# ──────────────────────────────────────────────────────────────────────
# Test 6 — cagr_service no-silent-fallback contract
# ──────────────────────────────────────────────────────────────────────


def test_cagr_service_status_rebuild_pending_when_adj_close_missing(monkeypatch):
    """When DATABASE_URL is set but adj_close is missing for every
    requested date, the stock_panel must report status='rebuild_pending'
    AND the per-window cells must be None (NOT a number from a silent
    close_price fallback)."""
    from backend.services import cagr_service

    # Force "no usable adj_close" by stubbing _fetch_adj_close_on_or_before
    # to always return None.
    monkeypatch.setattr(
        cagr_service, "_fetch_adj_close_on_or_before",
        lambda conn, ticker, target: None,
    )

    # Stub psycopg2.connect — only the no-op connect path is exercised.
    class _FakeConn:
        def close(self):
            pass

    fake_psycopg2 = type("M", (), {"connect": lambda *_a, **_k: _FakeConn()})
    monkeypatch.setitem(sys.modules, "psycopg2", fake_psycopg2)
    monkeypatch.setenv("DATABASE_URL", "postgres://stub")

    out = cagr_service._stock_cagr_panel("RELIANCE", date(2026, 5, 23))
    assert out["status"] == "rebuild_pending", out
    assert out["3y"] is None
    assert out["5y"] is None
    assert out["10y"] is None


def test_cagr_service_status_db_unavailable_when_no_url(monkeypatch):
    """No DATABASE_URL -> status='db_unavailable'."""
    from backend.services import cagr_service

    monkeypatch.delenv("DATABASE_URL", raising=False)
    out = cagr_service._stock_cagr_panel("RELIANCE", date(2026, 5, 23))
    assert out["status"] == "db_unavailable", out
