# backend/services/real_estate_developer_service.py
"""
Real Estate Developer Cap-Rate / NAV Engine — T3.4 Phase A.

YieldIQ already values listed Indian REITs and InvITs via the
existing realty path (``realty_valuation_service``), but listed
Indian real-estate DEVELOPERS — DLF, GODREJPROP, OBEROIRLTY,
PRESTIGE, PHOENIXLTD, BRIGADE, SOBHA, MAHLIFE, SUNTECK, LODHA —
are a structurally different animal. They are not yield vehicles
holding completed stabilized assets; they are land-bank +
forward-sales + annuity-rental businesses where:

  * The land bank sits on the balance sheet at decades-old
    acquisition cost; current realizable value is a multiple of
    book.
  * Forward sales (pre-bookings on projects under construction)
    are the leading revenue indicator and are largely
    off-statement.
  * Completed rental assets (malls, offices, hospitality) throw
    annuity cash that capitalises at a sector-specific cap rate
    (lower for residential luxury anchor stores, higher for
    grade-B commercial).

Generic FCF-DCF systematically mis-prices this cohort. The
correct framing is asset-NAV plus forward-sales pipeline minus
net debt, with a cap-rate haircut on the annuity slice. This
module provides that NAV calculator as a standalone service so
Phase A can ship without touching the analysis hot path.

Per-segment cap rates (per the brief and consistent with the
PHOENIXLTD constant in ``realty_valuation_service``):

  - residential   : 7.0%
  - commercial    : 8.0%
  - mixed         : 7.5%
  - luxury        : 6.0%

Phase A is standalone — no wiring into ``AnalysisResponse`` or
``composite_iv_service``. Phase B (separate PR) will route the
ten ``RE_DEVELOPER_TICKERS`` through ``compute_developer_nav``
and surface the per-share NAV alongside generic DCF on the
analysis page.

Defensive: every public entry point catches bad inputs (None,
NaN, non-positive shares, negative land bank) and returns a
``REDeveloperResult`` with ``method="unavailable"`` and a
sanity-warnings list rather than raising. The function is safe
to call from the engine hot path.
"""
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger("yieldiq.real_estate_developer")

REDeveloperSegment = Literal["residential", "commercial", "mixed", "luxury"]


# ─────────────────────────────────────────────────────────────────
# Universe — Indian listed real-estate developers we route through
# the cap-rate / NAV engine. Each maps to its dominant segment so
# the default cap rate can be inferred when not supplied.
#
# Keep in lockstep with the cache_invalidation_manifest entry's
# scope.tickers — every ticker here must appear there.
# ─────────────────────────────────────────────────────────────────
RE_DEVELOPER_TICKERS: dict[str, REDeveloperSegment] = {
    "DLF": "mixed",
    "GODREJPROP": "residential",
    "OBEROIRLTY": "luxury",
    "PRESTIGE": "mixed",
    "PHOENIXLTD": "commercial",
    "BRIGADE": "mixed",
    "SOBHA": "residential",
    "MAHLIFE": "residential",
    "SUNTECK": "luxury",
    "LODHA": "residential",
}


# ─────────────────────────────────────────────────────────────────
# Per-segment cap rates. Lower cap rate = higher capitalisation
# multiple = a single rupee of annuity rent is worth more (markets
# are willing to pay up for stabilised luxury / anchor properties;
# grade-B commercial trades on a higher cap to reflect lease-up
# and tenant-credit risk).
# ─────────────────────────────────────────────────────────────────
_SEGMENT_CAP_RATE_PCT: dict[REDeveloperSegment, float] = {
    "residential": 7.0,
    "commercial": 8.0,
    "mixed": 7.5,
    "luxury": 6.0,
}


# ─────────────────────────────────────────────────────────────────
# Inputs / Result dataclasses
# ─────────────────────────────────────────────────────────────────
@dataclass
class REDeveloperInputs:
    """Inputs for a single developer NAV calculation.

    Units (sticking with the brief — no implicit conversions):
      - ``land_bank_msf``       : million sq ft
      - ``realization_per_sf_inr`` : ₹ per saleable square foot
      - ``construction_cost_per_sf_inr`` : ₹ per square foot
      - ``operating_margin_pct``: 0-100 (percent)
      - ``cap_rate_pct``        : 0-100 (percent)
      - ``forward_sales_pipeline_inr_cr`` : ₹ crore
      - ``completed_rental_yield_pct`` : 0-100 (percent of land bank
        gross sale value that throws stabilised annuity rent)
      - ``net_debt_inr_cr``     : ₹ crore (positive = net debt; can
        be negative for a net-cash developer)
      - ``shares_outstanding``  : absolute share count (NOT in crores)

    All percentages are in 0-100 not 0-1, matching the rest of the
    codebase (see ``it_services_overlay_service``).
    """
    land_bank_msf: float
    realization_per_sf_inr: float = 8000.0
    construction_cost_per_sf_inr: float = 3000.0
    operating_margin_pct: float = 25.0
    cap_rate_pct: float = 8.0
    forward_sales_pipeline_inr_cr: float = 0.0
    completed_rental_yield_pct: float = 7.5
    net_debt_inr_cr: float = 0.0
    shares_outstanding: float = 0.0
    segment: REDeveloperSegment = "residential"


@dataclass
class REDeveloperResult:
    """Result of a developer NAV calculation.

    - ``nav_per_share``: NAV divided by ``shares_outstanding``;
      ``None`` when the inputs are unrecoverably bad (no shares,
      no land bank, negative aggregate value, etc.).
    - ``components``: per-driver rupee values for transparency on
      the analysis page ("how was this NAV built?"). All ₹ crore.
    - ``method``: ``"nav_developer"`` on success,
      ``"unavailable"`` on hard failure.
    - ``sanity_warnings``: caller-facing notes about bad inputs the
      engine had to neutralize.
    """
    nav_per_share: Optional[float]
    components: dict
    method: str = "nav_developer"
    sanity_warnings: list[str] = field(default_factory=list)


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────
def _is_finite_number(x) -> bool:
    """True iff x is an int/float that's finite (not NaN, not inf)."""
    if x is None:
        return False
    if isinstance(x, bool):
        return False
    if not isinstance(x, (int, float)):
        return False
    try:
        return math.isfinite(float(x))
    except (TypeError, ValueError):
        return False


def _clamp(x: float, lo: float, hi: float) -> float:
    return max(lo, min(hi, x))


def _clean_ticker(ticker: str) -> str:
    return (ticker or "").replace(".NS", "").replace(".BO", "").upper().strip()


# ─────────────────────────────────────────────────────────────────
# Per-segment cap-rate lookup
# ─────────────────────────────────────────────────────────────────
def get_segment_cap_rate(segment: str) -> float:
    """Return the per-segment cap rate (in 0-100 percent units).

    Falls back to the residential cap rate (7%) when the segment
    label is unknown. We choose residential as the conservative
    default because (a) it's the modal segment in the universe and
    (b) bumping the cap rate slightly understates NAV rather than
    overstating it.
    """
    if not segment or not isinstance(segment, str):
        return _SEGMENT_CAP_RATE_PCT["residential"]
    key = segment.lower().strip()
    if key in _SEGMENT_CAP_RATE_PCT:
        return _SEGMENT_CAP_RATE_PCT[key]  # type: ignore[index]
    return _SEGMENT_CAP_RATE_PCT["residential"]


# ─────────────────────────────────────────────────────────────────
# Core NAV calculator
# ─────────────────────────────────────────────────────────────────
def compute_developer_nav(inputs: REDeveloperInputs) -> REDeveloperResult:
    """Compute per-share NAV for a listed Indian RE developer.

    NAV = land_bank_value
        + forward_sales_value
        + rental_perpetuity
        - net_debt

    where:

    * ``land_bank_value`` (₹ Cr)
          = land_bank_msf * 1e6
            * (realization_per_sf - construction_cost_per_sf)
            * (operating_margin_pct / 100)
            / 1e7   (₹ → ₹ Cr)

      The margin term reflects that the per-sf spread (realization
      minus construction) is not the developer's profit — capex,
      SG&A, marketing, finance costs and approval costs eat into
      it. Operating margin is the conservative way to anchor
      "what fraction of the gross spread accrues to equity".

    * ``forward_sales_value`` (₹ Cr)
          = forward_sales_pipeline_inr_cr
            * (operating_margin_pct / 100)

      Forward sales are already in ₹ Cr; the margin haircut
      converts top-line bookings into the equity-attributable
      slice of pre-sold inventory.

    * ``rental_perpetuity`` (₹ Cr)
          = (land_bank_msf * 1e6 * realization_per_sf / 1e7)
            * (completed_rental_yield_pct / 100)
            / (cap_rate_pct / 100)

      We approximate stabilised annuity NOI as the completed-rental
      slice of land-bank gross sale value, then capitalise at the
      segment cap rate. This is the standard developer-cohort
      cap-rate proxy when granular per-asset NOI isn't curated.

    * ``net_debt`` (₹ Cr) — subtracted directly. Can be negative
      (net cash) which legitimately bumps NAV up.

    NAV per share = (NAV in ₹ Cr * 1e7) / shares_outstanding

    Defensive — never raises. On invalid inputs (no shares, no
    land bank, no cap rate, etc.) returns ``method="unavailable"``
    and ``nav_per_share=None`` so the caller can fall back to
    generic DCF without a try/except.
    """
    warnings: list[str] = []

    # ── Validate shares ──────────────────────────────────────────
    if not _is_finite_number(inputs.shares_outstanding) or inputs.shares_outstanding <= 0:
        warnings.append(
            "shares_outstanding invalid (None/NaN/non-positive); NAV unavailable"
        )
        return REDeveloperResult(
            nav_per_share=None,
            components={
                "land_bank_value": 0.0,
                "forward_sales_value": 0.0,
                "rental_perpetuity": 0.0,
                "net_debt": 0.0,
            },
            method="unavailable",
            sanity_warnings=warnings,
        )

    # ── Validate land bank ───────────────────────────────────────
    if not _is_finite_number(inputs.land_bank_msf):
        warnings.append("land_bank_msf invalid; treated as 0")
        land_bank_msf = 0.0
    else:
        land_bank_msf = max(0.0, float(inputs.land_bank_msf))
        if inputs.land_bank_msf < 0:
            warnings.append(
                f"land_bank_msf={inputs.land_bank_msf} negative; clamped to 0"
            )

    # ── Validate per-sf economics ────────────────────────────────
    if not _is_finite_number(inputs.realization_per_sf_inr):
        warnings.append("realization_per_sf_inr invalid; defaulted to 8000")
        realization = 8000.0
    else:
        realization = max(0.0, float(inputs.realization_per_sf_inr))

    if not _is_finite_number(inputs.construction_cost_per_sf_inr):
        warnings.append("construction_cost_per_sf_inr invalid; defaulted to 3000")
        construction = 3000.0
    else:
        construction = max(0.0, float(inputs.construction_cost_per_sf_inr))

    # Inverted economics — construction exceeds realization. Don't
    # raise; emit a warning and clamp the spread to zero so the
    # land-bank slice contributes nothing rather than going negative.
    spread = realization - construction
    if spread < 0:
        warnings.append(
            f"construction_cost_per_sf_inr ({construction}) exceeds "
            f"realization_per_sf_inr ({realization}); land-bank spread "
            f"clamped to 0"
        )
        spread = 0.0

    # ── Validate margin ──────────────────────────────────────────
    if not _is_finite_number(inputs.operating_margin_pct):
        warnings.append("operating_margin_pct invalid; defaulted to 25")
        margin_pct = 25.0
    else:
        margin_pct = _clamp(float(inputs.operating_margin_pct), 0.0, 100.0)
        if not (0.0 <= float(inputs.operating_margin_pct) <= 100.0):
            warnings.append(
                f"operating_margin_pct={inputs.operating_margin_pct} outside [0,100]; clamped"
            )

    # ── Validate cap rate (must be > 0 to divide) ────────────────
    if not _is_finite_number(inputs.cap_rate_pct) or inputs.cap_rate_pct <= 0:
        # Fall back to segment cap rate
        seg_cap = get_segment_cap_rate(inputs.segment)
        warnings.append(
            f"cap_rate_pct={inputs.cap_rate_pct} invalid; using segment "
            f"default {seg_cap}% for {inputs.segment!r}"
        )
        cap_rate_pct = seg_cap
    else:
        cap_rate_pct = _clamp(float(inputs.cap_rate_pct), 0.5, 20.0)
        if not (0.5 <= float(inputs.cap_rate_pct) <= 20.0):
            warnings.append(
                f"cap_rate_pct={inputs.cap_rate_pct} outside sane band [0.5, 20]; clamped"
            )

    # ── Validate forward sales ───────────────────────────────────
    if not _is_finite_number(inputs.forward_sales_pipeline_inr_cr):
        warnings.append("forward_sales_pipeline_inr_cr invalid; treated as 0")
        forward_sales_cr = 0.0
    else:
        forward_sales_cr = max(0.0, float(inputs.forward_sales_pipeline_inr_cr))
        if inputs.forward_sales_pipeline_inr_cr < 0:
            warnings.append(
                "forward_sales_pipeline_inr_cr negative; clamped to 0"
            )

    # ── Validate completed rental yield ──────────────────────────
    if not _is_finite_number(inputs.completed_rental_yield_pct):
        warnings.append("completed_rental_yield_pct invalid; defaulted to 7.5")
        rental_yield_pct = 7.5
    else:
        rental_yield_pct = _clamp(
            float(inputs.completed_rental_yield_pct), 0.0, 100.0
        )

    # ── Validate net debt ────────────────────────────────────────
    if not _is_finite_number(inputs.net_debt_inr_cr):
        warnings.append("net_debt_inr_cr invalid; treated as 0")
        net_debt_cr = 0.0
    else:
        net_debt_cr = float(inputs.net_debt_inr_cr)

    # ── Component math (all in ₹ Cr) ─────────────────────────────
    # Land bank value:
    #   total sq ft = land_bank_msf * 1e6
    #   gross profit per sf = spread (₹/sf)
    #   gross profit (₹) = total_sqft * spread
    #   convert ₹ → ₹ Cr by /1e7
    #   then apply operating margin
    land_bank_value_cr = (
        land_bank_msf * 1e6 * spread / 1e7
    ) * (margin_pct / 100.0)

    # Forward-sales value: ₹ Cr top-line * margin
    forward_sales_value_cr = forward_sales_cr * (margin_pct / 100.0)

    # Rental perpetuity:
    #   gross_sale_value_cr = land_bank_msf * 1e6 * realization / 1e7
    #   annuity NOI ₹ Cr/yr = gross_sale_value_cr * rental_yield_pct/100
    #   capitalised value ₹ Cr = annuity NOI / (cap_rate_pct/100)
    gross_sale_value_cr = land_bank_msf * 1e6 * realization / 1e7
    annuity_noi_cr = gross_sale_value_cr * (rental_yield_pct / 100.0)
    rental_perpetuity_cr = (
        annuity_noi_cr / (cap_rate_pct / 100.0)
        if cap_rate_pct > 0 else 0.0
    )

    # ── Aggregate NAV ────────────────────────────────────────────
    nav_cr = (
        land_bank_value_cr
        + forward_sales_value_cr
        + rental_perpetuity_cr
        - net_debt_cr
    )

    components = {
        "land_bank_value": round(land_bank_value_cr, 2),
        "forward_sales_value": round(forward_sales_value_cr, 2),
        "rental_perpetuity": round(rental_perpetuity_cr, 2),
        "net_debt": round(net_debt_cr, 2),
    }

    # If aggregate NAV is non-positive, return unavailable (a developer
    # with net debt eating the whole asset stack is not value-priced
    # off NAV — the caller should fall back to generic DCF / liquidation
    # framing rather than show a negative per-share NAV).
    if nav_cr <= 0:
        warnings.append(
            f"aggregate NAV ({round(nav_cr, 2)} ₹ Cr) non-positive; "
            "NAV framework not applicable — fall back to generic DCF"
        )
        return REDeveloperResult(
            nav_per_share=None,
            components=components,
            method="unavailable",
            sanity_warnings=warnings,
        )

    # ── Per-share NAV ────────────────────────────────────────────
    nav_per_share = (nav_cr * 1e7) / float(inputs.shares_outstanding)

    return REDeveloperResult(
        nav_per_share=round(nav_per_share, 2),
        components=components,
        method="nav_developer",
        sanity_warnings=warnings,
    )


# ─────────────────────────────────────────────────────────────────
# Applicability gate
# ─────────────────────────────────────────────────────────────────
def is_re_developer_applicable(
    ticker: str,
    sector: Optional[str] = None,
) -> tuple[bool, str]:
    """Return ``(applicable, reason)``.

    True iff the ticker is in ``RE_DEVELOPER_TICKERS``. We
    intentionally do NOT fall back to a sector-string match: the
    listed REIT cohort (EMBASSY, MINDSPACE, BROOKFIELD) is also
    tagged "Realty" and they are valued by the existing
    ``realty_valuation_service``, not this engine. Tightening the
    gate to the explicit ticker list prevents the wrong-engine
    cross-routing that bit us on Bug-D (ITCHOTELS / ABLBL).

    ``sector`` is accepted but unused — it's part of the signature
    so future callers (Phase B router) can pass it for telemetry
    without breaking the contract.
    """
    if not ticker or not isinstance(ticker, str):
        return False, "ticker is empty or non-string"

    normalized = _clean_ticker(ticker)
    if normalized in RE_DEVELOPER_TICKERS:
        return (
            True,
            f"{normalized} is in RE_DEVELOPER_TICKERS "
            f"({RE_DEVELOPER_TICKERS[normalized]})",
        )

    return False, (
        f"ticker {normalized!r} not in RE developer universe; "
        f"sector={sector!r}"
    )


# ─────────────────────────────────────────────────────────────────
# JSON helper
# ─────────────────────────────────────────────────────────────────
def to_dict(result: REDeveloperResult) -> dict:
    """JSON-safe projection of the result for API surfaces."""
    return {
        "nav_per_share": result.nav_per_share,
        "components": dict(result.components),
        "method": result.method,
        "sanity_warnings": list(result.sanity_warnings),
    }
