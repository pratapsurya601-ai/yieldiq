"""Phase 0 scaffold tests for the IPO-aware framework.

Covers:
  1. is_recent_ipo() — True for 12-month-old listing, False for 30-month-
     old listing, False when listing_date is None.
  2. ipo_caveat() — non-empty string with months_since substituted.

No DCF routing is exercised here; that lands in a later phase once
verified DRHP financials are populated in IPO_PROSPECTUS_FINANCIALS.
"""
from __future__ import annotations

from datetime import date

from backend.services.analysis.ipo_framework import (
    IPO_PROSPECTUS_FINANCIALS,
    ipo_caveat,
    is_recent_ipo,
)


def _iso_months_ago(months: int) -> str:
    """Stdlib-only month subtraction (avoids dateutil dependency)."""
    today = date.today()
    total_month_index = today.year * 12 + (today.month - 1) - months
    new_year, new_month0 = divmod(total_month_index, 12)
    new_month = new_month0 + 1
    # Clamp day to 28 to dodge month-end edge cases (e.g. Mar 31 - 1mo).
    return date(new_year, new_month, min(today.day, 28)).isoformat()


# ─────────────────────────────────────────────────────────────────
# 1. is_recent_ipo gate
# ─────────────────────────────────────────────────────────────────

def test_is_recent_ipo_true_for_12_months_ago():
    assert is_recent_ipo("NEWCO", _iso_months_ago(12)) is True


def test_is_recent_ipo_false_for_30_months_ago():
    assert is_recent_ipo("OLDCO", _iso_months_ago(30)) is False


def test_is_recent_ipo_false_for_none():
    assert is_recent_ipo("NOLIST", None) is False


# ─────────────────────────────────────────────────────────────────
# 2. ipo_caveat string
# ─────────────────────────────────────────────────────────────────

def test_ipo_caveat_returns_non_empty_with_months_substituted():
    listing = _iso_months_ago(8)
    msg = ipo_caveat("NEWCO", listing)
    assert isinstance(msg, str) and msg.strip(), "caveat must be non-empty"
    # months_since (8) should appear in the rendered string
    assert "8 months" in msg, f"expected '8 months' substring in: {msg!r}"


# ─────────────────────────────────────────────────────────────────
# 3. Scaffold safety — prospectus dict starts empty
# ─────────────────────────────────────────────────────────────────

def test_prospectus_financials_is_empty_scaffold():
    """Phase 0 must NOT seed any synthetic prospectus data."""
    assert IPO_PROSPECTUS_FINANCIALS == {}
