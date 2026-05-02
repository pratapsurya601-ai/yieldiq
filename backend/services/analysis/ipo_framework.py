"""IPO-aware valuation framework — Phase 0 scaffold.

Recent IPOs break generic DCF in three ways:
1. <3 years of audited financials → trailing FCF medians are noisy or absent.
2. Listing-day pricing is dominated by sentiment, not fundamentals → CMP
   anchoring distorts FV/CMP ratios.
3. Prospectus (DRHP/RHP) projections are the only forward-looking signal,
   but they're issuer-supplied and need a risk premium.

This module is the SCAFFOLD only. It exposes:

- `is_recent_ipo()` — gate that decides whether IPO routing should apply.
- `ipo_caveat()` — honest user-facing message explaining the methodology.
- `IPO_PROSPECTUS_FINANCIALS` — empty dict, to be populated in a later
  session ONLY from verified DRHP PDFs supplied by the user. Never seed
  with synthetic / model-estimated numbers.
- `compute_ipo_dcf()` — stub. Real implementation lands in Phase 2 once
  prospectus financials are loaded and the elevated-WACC formula is
  reviewed.

NO DCF routing changes are wired in service.py yet. Routing is added in
a follow-up PR after the helpers + prospectus data are reviewed.
"""

from __future__ import annotations

from datetime import date, datetime


# Window during which a stock is treated as a "recent IPO" for routing
# purposes. 24 months ≈ two annual reports post-listing — by then there
# is usually enough audited data for the standard DCF to behave.
_RECENT_IPO_WINDOW_MONTHS = 24


# Populated in a later session from verified DRHP PDFs supplied by the
# user. Schema (TBD, do not rely on this yet) will look roughly like:
#   {
#       "TICKER": {
#           "listing_date": "YYYY-MM-DD",
#           "drhp_source": "url-or-filename",
#           "revenue_fy_minus_3": float,  # in ₹ Cr
#           "revenue_fy_minus_2": float,
#           "revenue_fy_minus_1": float,
#           "ebitda_margin": float,
#           "projected_capex": float,
#           ...
#       }
#   }
# Intentionally EMPTY. Do not commit synthetic numbers here.
IPO_PROSPECTUS_FINANCIALS: dict[str, dict] = {}


def _months_between(earlier: date, later: date) -> int:
    """Whole-month gap between two dates (later − earlier)."""
    months = (later.year - earlier.year) * 12 + (later.month - earlier.month)
    if later.day < earlier.day:
        months -= 1
    return max(months, 0)


def _parse_iso(d: str) -> date | None:
    try:
        return datetime.strptime(d, "%Y-%m-%d").date()
    except (ValueError, TypeError):
        return None


def is_recent_ipo(ticker: str, listing_date: str | None) -> bool:
    """Return True if the stock listed within the recent-IPO window.

    Returns False when listing_date is None, unparseable, in the future,
    or older than the configured window.
    """
    if not listing_date:
        return False
    parsed = _parse_iso(listing_date)
    if parsed is None:
        return False
    today = date.today()
    if parsed > today:
        return False
    return _months_between(parsed, today) < _RECENT_IPO_WINDOW_MONTHS


def ipo_caveat(ticker: str, listing_date: str) -> str:
    """User-facing caveat explaining the IPO-aware methodology."""
    parsed = _parse_iso(listing_date)
    months_since = _months_between(parsed, date.today()) if parsed else 0
    return (
        f"Recent IPO ({months_since} months listed). DCF uses elevated WACC "
        f"(+2pp risk premium) and prospectus-anchored projections; revisit "
        f"after Q4 results."
    )


def compute_ipo_dcf(*args, **kwargs):
    """Phase 2 — IPO-specific DCF engine.

    Will consume `IPO_PROSPECTUS_FINANCIALS[ticker]` plus a +2pp WACC
    risk premium and produce a bear/base/bull spread anchored on
    prospectus projections rather than (absent) trailing FCF.
    """
    raise NotImplementedError(
        "Phase 2: requires verified prospectus financials"
    )
