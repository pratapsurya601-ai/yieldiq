"""UX #129 (2026-05-23): sector counting in `calculate_portfolio_health`.

Before this fix, 9 holdings whose `sector` field was missing or
literally "Unknown" all collapsed into one bucket, producing the
misleading observation "1 sector represented in portfolio". The
fix excludes empty/Unknown values from the distinct-sector count
and surfaces them as a classification-pending data gap instead.

These tests pin the new behaviour so a future refactor can't quietly
restore the conflation.
"""
from __future__ import annotations

from dashboard.utils.portfolio_health import calculate_portfolio_health


def _h(ticker: str, sector: str = "", mos: float = 0.0) -> dict:
    """Minimal holding dict shaped like the router's `mapped` list."""
    return {
        "ticker": ticker,
        "shares": 10,
        "avg_buy_price": 100.0,
        "current_price": 100.0,
        "yieldiq_score": 65,
        "mos": mos,
        "moat": "None",
        "red_flags": 0,
        "sector": sector,
    }


def test_diversified_portfolio_reports_distinct_known_sectors():
    holdings = [
        _h("HDFCBANK.NS", "Financial Services"),
        _h("TCS.NS", "Information Technology"),
        _h("ITC.NS", "Consumer Defensive"),
        _h("RELIANCE.NS", "Energy"),
        _h("SUNPHARMA.NS", "Healthcare"),
    ]
    result = calculate_portfolio_health(holdings)
    # Should hit the "Diversified across N sectors" strength branch.
    assert any("Diversified across 5 sectors" in s for s in result["strengths"]), (
        result["strengths"],
    )
    # Should NOT emit a "1 sector" observation.
    assert not any("1 sector" in i for i in result["issues"]), result["issues"]


def test_unknown_sectors_are_not_counted_as_a_real_bucket():
    """Regression for UX #129: 9 holdings, all sector='Unknown',
    must NOT render as '1 sector represented in portfolio'."""
    holdings = [_h(f"T{i}.NS", "Unknown") for i in range(9)]
    result = calculate_portfolio_health(holdings)
    # No "{N} sector(s) represented" line — we have zero known sectors.
    assert not any(
        "sector" in i and "represented" in i for i in result["issues"]
    ), result["issues"]
    # Instead we surface the data gap so the user understands the cause.
    assert any(
        "Sector classification pending" in i for i in result["issues"]
    ), result["issues"]


def test_blank_sector_string_treated_as_unknown():
    holdings = [_h(f"T{i}.NS", "") for i in range(5)]
    result = calculate_portfolio_health(holdings)
    assert not any(
        "0 sectors" in i or "1 sector" in i for i in result["issues"]
    ), result["issues"]
    assert any(
        "Sector classification pending for 5 holdings" in i
        for i in result["issues"]
    ), result["issues"]


def test_partial_classification_surfaces_count_plus_gap():
    """3 known sectors + 2 unknown → "3 sectors represented … (2 holding pending classification)" only fires for <3. So test 2 known + 2 unknown."""
    holdings = [
        _h("A.NS", "Financial Services"),
        _h("B.NS", "Information Technology"),
        _h("C.NS", "Unknown"),
        _h("D.NS", ""),
    ]
    result = calculate_portfolio_health(holdings)
    msg = next(
        (i for i in result["issues"] if "represented in portfolio" in i),
        None,
    )
    assert msg is not None, result["issues"]
    assert "2 sectors represented" in msg
    assert "2 holdings pending classification" in msg


def test_case_insensitive_unknown_filter():
    holdings = [
        _h("A.NS", "unknown"),
        _h("B.NS", "UNKNOWN"),
        _h("C.NS", "Banks - Private Sector"),
    ]
    result = calculate_portfolio_health(holdings)
    msg = next(
        (i for i in result["issues"] if "represented in portfolio" in i),
        None,
    )
    assert msg is not None, result["issues"]
    assert "1 sector represented" in msg
    assert "2 holdings pending classification" in msg
