"""UX #130 (2026-05-23): below-fair-value count alignment.

Two widgets on the portfolio page render "{N} holdings below our model
fair value": the BelowFairValueBanner (frontend) and the Health card's
strengths list (backend `undervalued_count` field + observation string).
They previously used different MoS thresholds (15 vs 5) and disagreed
at the boundary — a user with 4 mildly-undervalued holdings saw "3"
in one widget and "4" in the other.

This test pins both paths at `mos > 0` — the same threshold used by
the per-row green/amber MoS chip — so the counts cannot drift again.
The matching frontend assertion lives in `__tests__/belowFairValueBanner.test.tsx`.
"""
from __future__ import annotations

from dashboard.utils.portfolio_health import calculate_portfolio_health


def _h(ticker: str, mos: float) -> dict:
    return {
        "ticker": ticker,
        "shares": 10,
        "avg_buy_price": 100.0,
        "current_price": 100.0,
        "yieldiq_score": 65,
        "mos": mos,
        "moat": "None",
        "red_flags": 0,
        "sector": "Financial Services",
    }


def test_undervalued_count_uses_mos_gt_zero():
    """The threshold MUST be > 0 to match BelowFairValueBanner."""
    holdings = [
        _h("A.NS", 25.0),   # below FV — counts
        _h("B.NS", 10.0),   # below FV — counts
        _h("C.NS", 2.0),    # marginally below — counts (was excluded at >5)
        _h("D.NS", 0.5),    # marginally below — counts (was excluded at >5)
        _h("E.NS", 0.0),    # exactly at FV — does NOT count
        _h("F.NS", -3.0),   # above FV — does NOT count
    ]
    result = calculate_portfolio_health(holdings)
    assert result["undervalued_count"] == 4, (
        f"expected 4 below-FV holdings, got {result['undervalued_count']}"
    )


def test_undervalued_count_strength_message_mentions_correct_count():
    holdings = [
        _h("A.NS", 30.0),
        _h("B.NS", 3.0),
        _h("C.NS", -5.0),
    ]
    result = calculate_portfolio_health(holdings)
    assert result["undervalued_count"] == 2
    msg = next(
        (s for s in result["strengths"] if "below our DCF fair value" in s),
        None,
    )
    assert msg is not None, result["strengths"]
    assert msg.startswith("2 holdings"), msg


def test_no_undervalued_message_when_zero():
    holdings = [_h("A.NS", -10.0), _h("B.NS", 0.0)]
    result = calculate_portfolio_health(holdings)
    assert result["undervalued_count"] == 0
    assert not any(
        "below our DCF fair value" in s for s in result["strengths"]
    )


def test_boundary_exactly_zero_excluded():
    """Strict > 0 — a holding exactly at fair value is not 'below'."""
    holdings = [_h("A.NS", 0.0)]
    result = calculate_portfolio_health(holdings)
    assert result["undervalued_count"] == 0
