"""Day-97 (2026-05-22): onboarding sample portfolio.

Goal: brand-new signups see the Portfolio Prism + observation engine
against a believable fixture instead of an empty state — the
"instant-value moment". Tests cover:

  Backend
    1. Sample fixture is well-formed (6 holdings, sector mix, sane
       notional, ST + LT mix on acquired_on).
    2. is_first_session heuristic: fresh iat -> True; stale iat ->
       False; missing iat -> False; future iat (clock skew) -> False.
    3. holdings-live response shape: empty + fresh login -> sample
       attached; empty + stale login -> no sample; has-holdings -> no
       sample regardless of iat.

  Frontend (source-text assertions)
    4. SamplePortfolioView component contains the required affordances
       (Sample badge, Import CTA, Continue CTA, dismissal hook).
    5. portfolio page wires dismissal via localStorage flag.

These are static-analysis style tests — they don't spin up the React
runtime; they assert the *source text* contains the required wiring,
which is the same pattern used in the Day-77 frontend test harness.
"""
from __future__ import annotations

import time
from pathlib import Path

import pytest

from backend.services.sample_portfolio import (
    SAMPLE_HOLDINGS,
    SESSION_WINDOW_S,
    build_sample_portfolio,
    is_first_session,
)


# ── Sample fixture shape ──────────────────────────────────────


def test_sample_has_six_holdings_across_sectors():
    """Six holdings spanning FMCG / Bank / IT / Conglomerate / Metals /
    Pharma so the Prism radar shows variety across pillars."""
    assert len(SAMPLE_HOLDINGS) == 6
    sectors = {h["sector"] for h in SAMPLE_HOLDINGS}
    # At least 6 distinct sectors — no duplication on the demo.
    assert len(sectors) == 6


def test_sample_tickers_are_the_required_set():
    tickers = {h["ticker"] for h in SAMPLE_HOLDINGS}
    assert tickers == {
        "ITC.NS", "HDFCBANK.NS", "TCS.NS",
        "RELIANCE.NS", "TATASTEEL.NS", "SUNPHARMA.NS",
    }


def test_sample_notional_in_target_range():
    """Total notional should be in the realistic Indian retail bracket
    (₹2-5L). A 10x miss would make the fixture feel wrong."""
    total = sum(h["quantity"] * h["avg_cost"] for h in SAMPLE_HOLDINGS)
    assert 200_000 <= total <= 500_000, total


def test_sample_has_mix_of_st_and_lt_acquired_on():
    """acquired_on spans both buckets so the TLH / tax-report demo
    surfaces ST + LT examples."""
    from datetime import date, datetime
    today = date.today()
    months = []
    for h in SAMPLE_HOLDINGS:
        d = datetime.fromisoformat(h["acquired_on"]).date()
        delta_days = (today - d).days
        months.append(delta_days // 30)
    # At least one ST (< 12mo) and at least one LT (>= 12mo).
    assert any(m < 12 for m in months), months
    assert any(m >= 12 for m in months), months


def test_build_sample_portfolio_shape():
    p = build_sample_portfolio()
    assert set(p.keys()) >= {"holdings", "summary", "label", "note"}
    assert p["summary"]["count"] == 6
    assert p["summary"]["total_invested"] > 0
    # Every row must self-identify as a sample so the FE can render
    # the badge without inferring.
    for row in p["holdings"]:
        assert row["is_sample"] is True
        assert row["display_ticker"] == row["ticker"].replace(".NS", "")
        assert row["invested_value"] == pytest.approx(
            row["quantity"] * row["entry_price"]
        )


# ── First-session heuristic ───────────────────────────────────


def test_is_first_session_true_for_fresh_iat():
    now = 1_700_000_000.0
    assert is_first_session(now - 30, now_epoch=now) is True


def test_is_first_session_false_for_stale_iat():
    now = 1_700_000_000.0
    # 10 minutes old — past the 5-minute window.
    assert is_first_session(now - (SESSION_WINDOW_S + 60), now_epoch=now) is False


def test_is_first_session_false_for_missing_iat():
    assert is_first_session(None) is False


def test_is_first_session_false_for_future_iat():
    """Clock-skewed future iat must NOT count as first session —
    otherwise an attacker forging a token with iat in the future would
    permanently see the sample affordances."""
    now = 1_700_000_000.0
    assert is_first_session(now + 600, now_epoch=now) is False


# ── Endpoint wiring (handler-level; no FastAPI app boot needed) ──
#
# We exercise the get_holdings_live coroutine directly with monkey-
# patched portfolio_service.get_holdings_with_live_data so the test
# doesn't depend on Supabase.


def _call_holdings_live(monkeypatch, *, has_holdings: bool, iat: float | None):
    """Invoke the holdings-live handler synchronously for assertions."""
    import asyncio

    def _fake_live(email):
        if has_holdings:
            return {
                "holdings": [{"ticker": "INFY.NS", "quantity": 1}],
                "summary": {"count": 1},
            }
        return {"holdings": [], "summary": {}}

    monkeypatch.setattr(
        "backend.services.portfolio_service.get_holdings_with_live_data",
        _fake_live,
    )
    from backend.routers.portfolio import get_holdings_live
    user = {"email": "demo@example.com", "iat": iat}
    return asyncio.get_event_loop().run_until_complete(get_holdings_live(user))


def test_endpoint_empty_plus_fresh_iat_returns_sample(monkeypatch):
    now = time.time()
    res = _call_holdings_live(monkeypatch, has_holdings=False, iat=now - 30)
    assert res["holdings"] == []
    assert "sample_portfolio" in res
    assert res["sample_portfolio"]["summary"]["count"] == 6


def test_endpoint_empty_plus_stale_iat_no_sample(monkeypatch):
    now = time.time()
    res = _call_holdings_live(
        monkeypatch, has_holdings=False, iat=now - (SESSION_WINDOW_S + 120)
    )
    assert res["holdings"] == []
    assert "sample_portfolio" not in res


def test_endpoint_with_holdings_never_returns_sample(monkeypatch):
    now = time.time()
    res = _call_holdings_live(monkeypatch, has_holdings=True, iat=now - 10)
    assert res["holdings"], "fake holdings should be returned"
    assert "sample_portfolio" not in res


# ── Frontend wiring (source-text assertions) ──────────────────


REPO_ROOT = Path(__file__).resolve().parent.parent.parent
FE_COMPONENT = REPO_ROOT / "frontend" / "src" / "components" / "portfolio" / "SamplePortfolioView.tsx"
FE_PAGE = REPO_ROOT / "frontend" / "src" / "app" / "(app)" / "portfolio" / "page.tsx"


def test_frontend_sample_component_has_badge_and_ctas():
    src = FE_COMPONENT.read_text(encoding="utf-8")
    # Explicit Sample badge on every row + CTAs from the spec.
    assert "sample-badge-" in src
    assert "Import your real holdings" in src
    assert "Continue exploring sample" in src
    # Dismissal hook is exported.
    assert "SAMPLE_DISMISSED_KEY" in src
    assert "yieldiq_sample_portfolio_dismissed" in src


def test_frontend_page_wires_dismissal_via_localstorage():
    src = FE_PAGE.read_text(encoding="utf-8")
    assert "SamplePortfolioView" in src
    assert "SAMPLE_DISMISSED_KEY" in src
    assert "localStorage.setItem(SAMPLE_DISMISSED_KEY" in src
    # Sample only renders when there are zero real holdings.
    assert "holdings.length === 0" in src
