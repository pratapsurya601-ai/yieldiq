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
# purposes. 36 months ≈ three annual reports post-listing — the DCF
# engine needs ≥3 years of audited history before its trailing FCF
# medians stop being noisy. Names like WAAREEINDO (listed 2024) and
# ETERNAL/Zomato (listed 2021) were producing garbage FVs under the
# generic DCF path because the trailing-FCF window had <3 prints.
_RECENT_IPO_WINDOW_MONTHS = 36

# Sector-aware override (PR feat/pharma-dcf-fix, 2026-05-18). Pharma has
# slower-maturing economics than the typical IPO cohort: post-launch
# product ramps, US ANDA approval cycles, and post-M&A working-capital
# absorption (Mankind / Bharat Serums FY24) take longer than 36 months
# to settle. Use 60 months (~5 annual reports) so MANKIND-style names
# stay routed through the sector-relative cohort valuation rather than
# falling off the cliff at month 37. Default (36) applies to every other
# sector. Keys MUST be lower-cased sector slugs as emitted by
# `models/industry_wacc.py` (e.g. "pharma", "it_services").
_RECENT_IPO_WINDOW_MONTHS_BY_SECTOR: dict[str, int] = {
    "pharma": 60,
}


def _window_months_for_sector(sector: str | None) -> int:
    if not sector:
        return _RECENT_IPO_WINDOW_MONTHS
    return _RECENT_IPO_WINDOW_MONTHS_BY_SECTOR.get(
        str(sector).strip().lower(), _RECENT_IPO_WINDOW_MONTHS
    )

# Minimum annual reports required for the generic DCF path. Below this,
# we treat the ticker as a "data-side recent IPO" even when yfinance
# fails to surface a listing date (defence-in-depth for the case where
# `firstTradeDateEpochUtc` is absent but `len(annual_financials) < 3`
# tells us the same story).
MIN_ANNUAL_REPORTS_FOR_DCF = 3


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


def is_recent_ipo(
    ticker: str,
    listing_date: str | None,
    sector: str | None = None,
) -> bool:
    """Return True if the stock listed within the recent-IPO window.

    The window is sector-aware: pharma gets 60 months, every other sector
    keeps the legacy 36-month default. Pass `sector` as the lower-case
    canonical slug used elsewhere in the pipeline (e.g. "pharma",
    "it_services"). When `sector` is None the default 36-month window is
    used — back-compatible with the original single-arg call sites.

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
    window = _window_months_for_sector(sector)
    return _months_between(parsed, today) < window


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


# ── Sector-relative valuation for recent IPOs ─────────────────────
# (Phase 1, feat/recent-ipo-sector-relative-valuation, 2026-05-17)
#
# Until prospectus-anchored DCF lands (Phase 2), recent IPOs get a
# sector-relative fair value derived from the sector-cohort medians
# already computed by `backend/services/sector_percentile.py`. The
# function below is intentionally tiny + side-effect free so service.py
# can call it once after `enriched` is built and either substitute the
# returned FV for the DCF FV or fall back gracefully when the inputs
# are missing.


def _median(values: list[float]) -> float | None:
    cleaned = sorted(
        v for v in values
        if isinstance(v, (int, float)) and v == v and v > 0
    )
    if not cleaned:
        return None
    n = len(cleaned)
    mid = n // 2
    if n % 2 == 1:
        return float(cleaned[mid])
    return (cleaned[mid - 1] + cleaned[mid]) / 2.0


def compute_sector_relative_fv(
    *,
    eps_ttm: float | None,
    revenue_per_share: float | None,
    cohort: list[dict],
    price: float | None,
) -> dict:
    """Sector-relative FV for a recent IPO.

    Inputs:
      - `eps_ttm`: trailing-12m EPS (INR/share). May be None or non-positive
        for pre-profit IPOs.
      - `revenue_per_share`: trailing revenue / diluted shares (INR/share).
      - `cohort`: rows from `sector_percentile.compute_sector_cohort` —
        dicts with `pe_ratio` and (optionally) `pb_ratio`. We use the cohort
        P/E median directly; P/S is approximated from P/E × cohort margin
        when available, otherwise we fall back to applying the cohort
        P/E median to revenue_per_share as a coarse proxy.
      - `price`: current market price, used only to derive a deviation
        ratio for the verdict cap.

    Returns a dict with keys:
      - `fair_value`: float (INR/share) or None when no signal could be derived.
      - `method`: one of "sector_pe", "sector_ps", "none".
      - `median_pe`, `median_ps`: floats or None.
      - `n_peers`: int.
      - `deviation_pct`: (fv - price) / price * 100 or None.
      - `verdict_hint`: one of "undervalued", "fairly_valued", "overvalued",
         "data_limited". Service.py caps at `data_limited` unless the
         deviation is > 30% in either direction (clear signal).
    """
    out: dict = {
        "fair_value": None,
        "method": "none",
        "median_pe": None,
        "median_ps": None,
        "n_peers": int(len(cohort or [])),
        "deviation_pct": None,
        "verdict_hint": "data_limited",
    }

    median_pe = _median([row.get("pe_ratio") for row in (cohort or [])])
    out["median_pe"] = median_pe

    fv: float | None = None
    method = "none"
    # Primary: sector P/E × ticker EPS (works for profitable IPOs).
    if median_pe is not None and eps_ttm is not None and eps_ttm > 0:
        fv = float(median_pe) * float(eps_ttm)
        method = "sector_pe"
    # Fallback: cohort P/E applied to revenue/share, severely discounted
    # (×0.10) so pre-profit IPOs anchor at a defensible P/S band rather
    # than the absurd P/E × revenue product. Better than nothing when
    # earnings are negative or absent.
    elif median_pe is not None and revenue_per_share is not None and revenue_per_share > 0:
        fv = float(median_pe) * float(revenue_per_share) * 0.10
        method = "sector_ps"
        out["median_ps"] = round(float(median_pe) * 0.10, 4)

    if fv is None or fv <= 0:
        return out

    out["fair_value"] = round(float(fv), 2)
    out["method"] = method

    if price and price > 0:
        dev = (fv - float(price)) / float(price) * 100.0
        out["deviation_pct"] = round(dev, 1)
        # Clear-signal threshold: >30% deviation in either direction.
        # Within ±30% → keep `data_limited` (the discipline cap).
        if dev > 30:
            out["verdict_hint"] = "undervalued"
        elif dev < -30:
            out["verdict_hint"] = "overvalued"
        else:
            out["verdict_hint"] = "data_limited"

    return out
