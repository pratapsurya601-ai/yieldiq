"""Tests for backend/services/weekly_digest_service.py.

Focus: the two-branch logic (watchlist vs no-watchlist) and the
SEBI-safe label mapping. DB access is patched to controlled fakes
so the suite runs offline.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

from backend.services import weekly_digest_service as wds


# ── label helper -------------------------------------------------

def test_fv_label_below():
    assert wds._fv_label_from_mos(25.0) == "Below Fair Value"


def test_fv_label_above():
    assert wds._fv_label_from_mos(-20.0) == "Above Fair Value"


def test_fv_label_around():
    assert wds._fv_label_from_mos(5.0) == "Around Fair Value"
    assert wds._fv_label_from_mos(-5.0) == "Around Fair Value"


def test_fv_label_unknown():
    assert wds._fv_label_from_mos(None) == "—"


# ── watchlist branch --------------------------------------------

def test_generate_digest_watchlist_branch():
    """When the user has watchlist tickers, the heading is the
    personalized one and the CTA goes to /account."""
    with patch.object(wds, "_supabase_client", return_value=object()), \
         patch.object(wds, "_get_user_watchlist", return_value=["TCS.NS", "INFY.NS"]), \
         patch.object(wds, "_fetch_watchlist_rows", return_value=[
             wds.DigestRow(ticker="TCS", company_name="TCS",
                           price=3500.0, fv_label="Below Fair Value",
                           score=82, note=""),
         ]):
        d = wds.generate_digest("u@example.com")

    assert "watchlist" in d.subject.lower() or "watchlist" in d.html.lower()
    assert "Your watchlist this week" in d.html
    assert "/account" in d.html
    # SEBI compliance: no recommendation verbs
    _assert_sebi_clean(d.html)
    _assert_sebi_clean(d.text)


# ── no-watchlist branch (activation cohort) ---------------------

def test_generate_digest_no_watchlist_uses_movers():
    """Users with empty watchlist (the 5/5-didn't-return cohort) get
    the YieldIQ-50 movers list with the /discover CTA."""
    movers = [
        wds.DigestRow(ticker="HDFCBANK", company_name="HDFC Bank",
                      price=1500.0, fv_label="Below Fair Value",
                      score=78, note="+4 score WoW"),
    ]
    with patch.object(wds, "_supabase_client", return_value=object()), \
         patch.object(wds, "_get_user_watchlist", return_value=[]), \
         patch.object(wds, "_fetch_movers_rows", return_value=movers):
        d = wds.generate_digest("new@example.com")

    assert "Stocks moving this week" in d.html
    assert "/discover" in d.html
    assert "HDFCBANK" in d.html
    _assert_sebi_clean(d.html)
    _assert_sebi_clean(d.text)


def test_generate_digest_handles_no_data_gracefully():
    """If the movers query returns nothing, we still produce a valid
    digest (no exception) with the friendly fallback copy."""
    with patch.object(wds, "_supabase_client", return_value=None), \
         patch.object(wds, "_get_user_watchlist", return_value=[]), \
         patch.object(wds, "_fetch_movers_rows", return_value=[]):
        d = wds.generate_digest("ghost@example.com")

    assert "No data this week" in d.html
    assert d.subject  # non-empty


# ── SEBI vocabulary helper --------------------------------------

_BANNED = (
    "buy now", "sell now", "strong buy", "must buy", "top picks",
    "top opportunities", "should buy", "should sell", "guaranteed",
)


def _assert_sebi_clean(s: str) -> None:
    low = s.lower()
    for term in _BANNED:
        assert term not in low, f"SEBI-banned phrase {term!r} in email body"
