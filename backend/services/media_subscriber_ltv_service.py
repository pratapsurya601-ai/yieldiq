# backend/services/media_subscriber_ltv_service.py
# =====================================================================
# MEDIA SUBSCRIBER LTV — standalone valuation service (T3.14 Phase A)
# =====================================================================
#
# Why this exists
# ---------------
# Indian media + entertainment is mid-stream in the OTT transition:
# legacy linear-TV broadcasters (ZEEL, SUNTV, NETWORK18, TV18BRDCST),
# cinema exhibitors (PVRINOX, INOXLEISURE), music-rights catalogues
# (TIPSINDLTD, SAREGAMA), and now a small gaming franchise (NAZARA).
# Reported revenue mixes one-shot ad inventory, subscription ARPU,
# theatrical box-office and licensing royalties — all with very
# different terminal economics.
#
# Two-stage DCF on aggregate revenue mis-prices these names because
# the durable cash-flow unit is the SUBSCRIBER (or in cinema, the
# repeat visitor; in music, the catalogue royalty stream). The
# Damodaran / Mauboussin framework for subscription media is:
#
#     Customer Lifetime Value (LTV) = ARPU * GM% * avg_lifetime_months
#     avg_lifetime_months           = 1 / monthly_churn_rate
#     Subscriber book value         = paying_subscribers * LTV
#     Equity value                  = subscriber_book
#                                   + advertising_revenue * peer_mult
#                                   + other_revenue * peer_mult
#                                   - SAC drag on new acquisitions
#                                   - net_debt
#
# A segment-specific LTV multiple is applied to the subscriber book to
# capture franchise persistence (music catalogues > OTT > broadcast).
#
# What this module is and is NOT
# ------------------------------
# IS:
#   - A standalone, pure-function service returning a
#     MediaSubscriberResult given canonical inputs.
#   - Independent of the heavy analysis pipeline. No imports from
#     backend.services.analysis.*; no DB access; no caching.
#   - Symmetrical with three_stage_dcf_service.py and
#     insurance_appraisal_service.py — pure math, easy to unit-test.
#
# IS NOT (Phase A scope):
#   - NOT wired into composite_iv_service. Existing engines remain
#     byte-identical. Phase B adds an opt-in `media_subscriber_fv`
#     field that the composite can weight against current estimators.
#   - NOT a sector classifier. The caller decides which segment a
#     ticker belongs to and supplies it via inputs.segment (or relies
#     on MEDIA_TICKERS mapping for known names).
#   - NOT an ARPU / churn data source. Phase A trusts operator-supplied
#     numbers from EV reports / Investor Day decks; Phase B will pull
#     these from a media_subscriber_inputs table analogous to the
#     insurance appraisal entry path.
#
# Algorithm summary
# -----------------
# Given canonical inputs:
#
#   avg_lifetime_months = 1 / max(monthly_churn_rate_pct/100, floor)
#   LTV = ARPU * (gross_margin_pct/100) * avg_lifetime_months
#   ltv_cac_ratio = LTV / SAC
#   subscriber_book_inr_cr =
#       (paying_subscribers_mn * 1e6) * LTV / 1e7    # to INR Cr
#
#   ancillary_inr_cr = (advertising_revenue_inr_cr
#                       + other_revenue_inr_cr) * ANCILLARY_MULTIPLE
#
#   gross_equity_value_inr_cr = subscriber_book_inr_cr * SEGMENT_LTV_MULT
#                              + ancillary_inr_cr
#                              - net_debt_inr_cr
#
#   fair_value_per_share = gross_equity_value_inr_cr * 1e7
#                          / shares_outstanding
# =====================================================================
from __future__ import annotations

import logging
import math
from dataclasses import asdict, dataclass, field
from typing import Literal, Optional

log = logging.getLogger("yieldiq.media_subscriber_ltv_service")


# ---------------------------------------------------------------------
# Segment taxonomy
# ---------------------------------------------------------------------
MediaSegment = Literal[
    "broadcaster",
    "ott_streaming",
    "cinema_exhibition",
    "music_rights",
    "gaming",
]


# Bare-ticker -> segment map for the 9 in-scope Indian media names.
# Used by is_media_applicable() to gate the engine. The classification
# is conservative — borderline names (NAZARA as gaming, NETWORK18 /
# TV18BRDCST as broadcasters with diminishing linear-TV economics) are
# included so the engine is at least computable, with Phase B sector
# calibration tuning the LTV multiples per cohort.
MEDIA_TICKERS: dict[str, MediaSegment] = {
    "ZEEL": "broadcaster",
    "SUNTV": "broadcaster",
    "PVRINOX": "cinema_exhibition",
    "INOXLEISURE": "cinema_exhibition",
    "TIPSINDLTD": "music_rights",
    "SAREGAMA": "music_rights",
    "NETWORK18": "broadcaster",
    "TV18BRDCST": "broadcaster",
    "NAZARA": "gaming",
}


# Segment-specific LTV multiples applied to the subscriber book value.
# Rationale per cohort:
#   - music_rights (5.0x): catalogue royalty streams are near-perpetual;
#     publishing rights compound for decades (Saregama's pre-1970s
#     catalogue is still earning).
#   - gaming (4.0x): high LTV from in-app purchases + battle-pass
#     cohorts; offset by short franchise half-life (mobile-game churn).
#   - ott_streaming (3.0x): persistent subscription but rising content
#     amortisation cost (originals) compress GM over time.
#   - cinema_exhibition (2.5x): "subscriber" is the repeat visitor;
#     LTV is occasion-driven, not contractual. Lower multiple but
#     higher than broadcast because pricing power on F&B + premium
#     screens.
#   - broadcaster (1.5x): linear-TV ARPU declining as cord-cutting
#     accelerates; aggressive multiple discount captures the secular
#     headwind explicitly rather than over-paying on a fading book.
SEGMENT_LTV_MULTIPLES: dict[MediaSegment, float] = {
    "ott_streaming": 3.0,
    "broadcaster": 1.5,
    "music_rights": 5.0,
    "cinema_exhibition": 2.5,
    "gaming": 4.0,
}


# Multiple applied to advertising + other ancillary revenue to convert
# trailing INR-Cr revenue into a present-value contribution. Conservative
# (1.0x) — ad revenue is one-shot and volatile, so we treat it as a
# perpetuity at the cost-of-equity rather than apply a growth premium.
# Phase B may refine per-segment.
ANCILLARY_REVENUE_MULTIPLE = 1.0


# ---------------------------------------------------------------------
# Defensive floors / clamps
# ---------------------------------------------------------------------
# Monthly churn rate floor — prevents division-by-zero and stops the
# LTV from extrapolating to infinity when an operator enters 0.0%
# (effectively claiming a perpetual customer). 0.5%/mo => 200-month
# avg lifetime, which is the longest plausible cohort behaviour
# disclosed by any India-market OTT operator (vs SaaS norms 2-5%/mo).
MIN_MONTHLY_CHURN_PCT = 0.5
MAX_MONTHLY_CHURN_PCT = 50.0  # 50%/mo => 2-month lifetime; sanity bound.

# Gross-margin clamp — keeps obviously-corrupt inputs out of the math.
MIN_GROSS_MARGIN_PCT = 5.0
MAX_GROSS_MARGIN_PCT = 95.0

# Cost-of-equity clamp matches the rest of the engine's WACC band.
MIN_COE = 0.06
MAX_COE = 0.20


# ---------------------------------------------------------------------
# LTV/CAC health-tier thresholds (SaaS-style framework adapted for
# Indian media: healthy >3, ok 2-3, stressed <2).
# ---------------------------------------------------------------------
LTV_CAC_HEALTHY_THRESHOLD = 3.0
LTV_CAC_OK_THRESHOLD = 2.0


# ---------------------------------------------------------------------
# Inputs / result dataclasses
# ---------------------------------------------------------------------
@dataclass
class MediaSubscriberInputs:
    """Canonical inputs for the media subscriber LTV valuation.

    Units:
        paying_subscribers_mn   : millions of paying subscribers
        arpu_per_month_inr      : INR per subscriber per month
        monthly_churn_rate_pct  : percent per month (4.0 = 4%/mo)
        gross_margin_pct        : percent (55.0 = 55%)
        subscriber_acquisition_cost_inr : INR per net new subscriber
        advertising_revenue_inr_cr : trailing 12m ad revenue, INR Crores
        other_revenue_inr_cr    : trailing 12m other revenue, INR Crores
        cost_of_equity          : decimal (0.12 = 12%)
        net_debt_inr_cr         : net debt (debt - cash), INR Crores
        shares_outstanding      : count (NOT in Crores) — divide by
                                  this to get per-share figures
        segment                 : MediaSegment literal; defaults to
                                  ott_streaming as the canonical case.
    """

    paying_subscribers_mn: float
    arpu_per_month_inr: float
    monthly_churn_rate_pct: float = 4.0       # 4% = 25-month avg life
    gross_margin_pct: float = 55.0
    subscriber_acquisition_cost_inr: float = 800.0
    advertising_revenue_inr_cr: float = 0.0
    other_revenue_inr_cr: float = 0.0
    cost_of_equity: float = 0.12
    net_debt_inr_cr: float = 0.0
    shares_outstanding: float = 0.0
    segment: MediaSegment = "ott_streaming"


@dataclass
class MediaSubscriberResult:
    """Output of the media subscriber LTV valuation.

    method:
        - "media_subscriber_ltv" on success
        - "unavailable" when inputs fail validation; check
          sanity_warnings for the reason
    components:
        - per-bucket equity-value contributions in INR Crores, useful
          for surfacing a SOTP-style breakdown in the UI:
            subscriber_book_inr_cr
            ancillary_revenue_inr_cr
            sac_drag_inr_cr
            net_debt_inr_cr
            gross_equity_value_inr_cr
    """

    fair_value_per_share: Optional[float]
    avg_subscriber_lifetime_months: float
    customer_lifetime_value_inr: float        # ARPU * GM% * lifetime
    ltv_cac_ratio: float
    subscriber_book_value_inr_cr: float
    components: dict = field(default_factory=dict)
    method: str = "media_subscriber_ltv"
    sanity_warnings: list[str] = field(default_factory=list)


# ---------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------
def _is_finite_number(x: Optional[float]) -> bool:
    """True iff x is a finite float (rejects None, NaN, +/-inf)."""
    if x is None:
        return False
    try:
        xf = float(x)
    except (TypeError, ValueError):
        return False
    return math.isfinite(xf)


def _is_finite_non_negative(x: Optional[float]) -> bool:
    return _is_finite_number(x) and float(x) >= 0


def _is_finite_positive(x: Optional[float]) -> bool:
    return _is_finite_number(x) and float(x) > 0


def _clean_ticker(t: Optional[str]) -> str:
    if not t:
        return ""
    bare = t
    for suffix in (".NS", ".BO", ".BSE", ".NSE"):
        if bare.endswith(suffix):
            bare = bare[: -len(suffix)]
            break
    return bare.upper()


def _unavailable_result(warnings: list[str]) -> MediaSubscriberResult:
    """Construct an `unavailable` result. Caller keys off
    ``method == "unavailable"`` to fall through to the prior path.
    """
    return MediaSubscriberResult(
        fair_value_per_share=None,
        avg_subscriber_lifetime_months=0.0,
        customer_lifetime_value_inr=0.0,
        ltv_cac_ratio=0.0,
        subscriber_book_value_inr_cr=0.0,
        components={},
        method="unavailable",
        sanity_warnings=list(warnings),
    )


# ---------------------------------------------------------------------
# Pure-math primitives — exported so callers / tests can exercise the
# LTV math independent of the full valuation pipeline.
# ---------------------------------------------------------------------
def compute_ltv(
    arpu_monthly: float,
    churn_monthly: float,
    gross_margin_pct: float,
    discount_rate: float = 0.01,
) -> float:
    """Customer Lifetime Value, in INR.

    LTV = ARPU * GM% * avg_lifetime_months

    The geometric-series identity gives::

        avg_lifetime_months = 1 / churn_monthly

    where ``churn_monthly`` is the monthly attrition rate as a decimal
    (0.04 = 4%/mo). When ``churn_monthly`` is below MIN_MONTHLY_CHURN
    we clamp upward to avoid infinite lifetimes — see
    MIN_MONTHLY_CHURN_PCT for the rationale.

    ``discount_rate`` is accepted for API-compatibility with a future
    monthly-discounted LTV variant, but Phase A uses the simple
    undiscounted geometric mean (the cost-of-equity discount is
    applied at the equity-bridge step instead). The parameter has no
    effect on the returned value today.
    """
    if not _is_finite_positive(arpu_monthly):
        return 0.0
    if not _is_finite_number(gross_margin_pct):
        return 0.0
    # Clamp churn to the defensive band before inverting.
    churn_pct = (
        max(MIN_MONTHLY_CHURN_PCT, min(MAX_MONTHLY_CHURN_PCT, float(churn_monthly) * 100.0))
        if _is_finite_positive(churn_monthly)
        else MIN_MONTHLY_CHURN_PCT
    )
    churn_dec = churn_pct / 100.0
    avg_lifetime_months = 1.0 / churn_dec
    gm = max(MIN_GROSS_MARGIN_PCT, min(MAX_GROSS_MARGIN_PCT, float(gross_margin_pct))) / 100.0
    return float(arpu_monthly) * gm * avg_lifetime_months


def classify_ltv_cac_health(ratio: float) -> str:
    """Return a short health tier label for an LTV/CAC ratio.

    Convention (SaaS-style):
        ratio >= 3   -> "healthy"
        2 <= ratio < 3 -> "ok"
        ratio < 2    -> "stressed"
        non-finite / non-positive -> "unknown"
    """
    if not _is_finite_positive(ratio):
        return "unknown"
    if ratio >= LTV_CAC_HEALTHY_THRESHOLD:
        return "healthy"
    if ratio >= LTV_CAC_OK_THRESHOLD:
        return "ok"
    return "stressed"


def _compute_avg_lifetime_months(monthly_churn_rate_pct: float) -> float:
    """Defensive helper — convert clamped churn pct to expected
    lifetime in months. Always returns a finite positive number.
    """
    churn_pct = max(
        MIN_MONTHLY_CHURN_PCT,
        min(MAX_MONTHLY_CHURN_PCT, float(monthly_churn_rate_pct)),
    )
    return 100.0 / churn_pct


# ---------------------------------------------------------------------
# Main entry
# ---------------------------------------------------------------------
def compute_media_fv(inputs: MediaSubscriberInputs) -> MediaSubscriberResult:
    """Media subscriber LTV valuation.

    Validation (hard — returns unavailable):
        - All inputs must be finite numbers.
        - paying_subscribers_mn must be > 0. The engine is meaningless
          for a zero-subscriber business; the caller falls through to
          aggregate-revenue methods.
        - arpu_per_month_inr must be > 0.
        - segment must be a known MediaSegment.

    Soft warnings (the model still computes):
        - monthly_churn_rate_pct clamped to [MIN, MAX] band.
        - gross_margin_pct clamped to [MIN, MAX] band.
        - cost_of_equity clamped to [MIN, MAX] band.
        - ltv_cac_ratio < OK threshold -> "stressed unit economics".
        - shares_outstanding == 0 -> per-share FV reported as None but
          the components dict (with INR-Cr totals) is still returned.
        - net_debt > 0 and exceeds gross asset value -> negative equity
          warning; FV may be 0 or negative.
    """
    warnings: list[str] = []

    # --- Hard validation -----------------------------------------
    if not _is_finite_positive(inputs.paying_subscribers_mn):
        warnings.append("paying_subscribers_mn must be positive and finite")
        return _unavailable_result(warnings)

    if not _is_finite_positive(inputs.arpu_per_month_inr):
        warnings.append("arpu_per_month_inr must be positive and finite")
        return _unavailable_result(warnings)

    if not _is_finite_number(inputs.monthly_churn_rate_pct):
        warnings.append("monthly_churn_rate_pct must be a finite number")
        return _unavailable_result(warnings)

    if not _is_finite_number(inputs.gross_margin_pct):
        warnings.append("gross_margin_pct must be a finite number")
        return _unavailable_result(warnings)

    if not _is_finite_non_negative(inputs.subscriber_acquisition_cost_inr):
        warnings.append(
            "subscriber_acquisition_cost_inr must be a non-negative finite number"
        )
        return _unavailable_result(warnings)

    if not _is_finite_non_negative(inputs.advertising_revenue_inr_cr):
        warnings.append(
            "advertising_revenue_inr_cr must be a non-negative finite number"
        )
        return _unavailable_result(warnings)

    if not _is_finite_non_negative(inputs.other_revenue_inr_cr):
        warnings.append("other_revenue_inr_cr must be a non-negative finite number")
        return _unavailable_result(warnings)

    if not _is_finite_positive(inputs.cost_of_equity):
        warnings.append("cost_of_equity must be positive and finite")
        return _unavailable_result(warnings)

    if not _is_finite_number(inputs.net_debt_inr_cr):
        warnings.append("net_debt_inr_cr must be a finite number")
        return _unavailable_result(warnings)

    if not _is_finite_non_negative(inputs.shares_outstanding):
        warnings.append("shares_outstanding must be a non-negative finite number")
        return _unavailable_result(warnings)

    if inputs.segment not in SEGMENT_LTV_MULTIPLES:
        warnings.append(
            f"segment '{inputs.segment}' is not a known MediaSegment "
            f"(expected one of {sorted(SEGMENT_LTV_MULTIPLES)})"
        )
        return _unavailable_result(warnings)

    # --- Soft clamps with warnings -------------------------------
    churn_raw = float(inputs.monthly_churn_rate_pct)
    churn_used = max(MIN_MONTHLY_CHURN_PCT, min(MAX_MONTHLY_CHURN_PCT, churn_raw))
    if churn_used != churn_raw:
        warnings.append(
            f"monthly_churn_rate_pct clamped from {churn_raw:.3f} to "
            f"{churn_used:.3f} (band [{MIN_MONTHLY_CHURN_PCT}, "
            f"{MAX_MONTHLY_CHURN_PCT}])"
        )

    gm_raw = float(inputs.gross_margin_pct)
    gm_used = max(MIN_GROSS_MARGIN_PCT, min(MAX_GROSS_MARGIN_PCT, gm_raw))
    if gm_used != gm_raw:
        warnings.append(
            f"gross_margin_pct clamped from {gm_raw:.3f} to {gm_used:.3f} "
            f"(band [{MIN_GROSS_MARGIN_PCT}, {MAX_GROSS_MARGIN_PCT}])"
        )

    coe_raw = float(inputs.cost_of_equity)
    coe_used = max(MIN_COE, min(MAX_COE, coe_raw))
    if coe_used != coe_raw:
        warnings.append(
            f"cost_of_equity clamped from {coe_raw:.4f} to {coe_used:.4f} "
            f"(band [{MIN_COE}, {MAX_COE}])"
        )

    # --- LTV / lifetime ------------------------------------------
    avg_lifetime_months = _compute_avg_lifetime_months(churn_used)
    ltv_per_subscriber_inr = float(inputs.arpu_per_month_inr) * (gm_used / 100.0) * avg_lifetime_months

    sac = float(inputs.subscriber_acquisition_cost_inr)
    if sac > 0:
        ltv_cac_ratio = ltv_per_subscriber_inr / sac
    else:
        # SAC=0 is legitimate for music-rights / catalogue businesses
        # where there is no "acquisition cost" per subscriber. Report
        # the ratio as +inf, the health classifier returns "healthy".
        ltv_cac_ratio = float("inf")

    if _is_finite_positive(ltv_cac_ratio) and ltv_cac_ratio < LTV_CAC_OK_THRESHOLD:
        warnings.append(
            f"ltv_cac_ratio={ltv_cac_ratio:.2f} below OK threshold "
            f"({LTV_CAC_OK_THRESHOLD}); unit economics stressed"
        )

    # --- Subscriber book value -----------------------------------
    # paying_subscribers_mn * 1e6 subscribers * LTV INR / 1e7 -> Cr
    subscribers_count = float(inputs.paying_subscribers_mn) * 1e6
    subscriber_book_inr = subscribers_count * ltv_per_subscriber_inr
    subscriber_book_inr_cr = subscriber_book_inr / 1e7

    # --- Segment multiple applied to subscriber book -------------
    seg_mult = SEGMENT_LTV_MULTIPLES[inputs.segment]
    subscriber_contribution_inr_cr = subscriber_book_inr_cr * seg_mult

    # --- Ancillary (ad + other) revenue --------------------------
    ancillary_inr_cr = (
        float(inputs.advertising_revenue_inr_cr)
        + float(inputs.other_revenue_inr_cr)
    ) * ANCILLARY_REVENUE_MULTIPLE

    # --- SAC drag on near-term acquisitions ----------------------
    # Reflects the cash cost of replacing churned subscribers over one
    # year of churn at the clamped rate. churn_used%/mo * 12 = annual
    # churn fraction; multiplied by the current paying base and SAC,
    # then divided by the cost-of-equity to capitalise into a perp
    # contribution. This captures the franchise penalty for high churn
    # without double-counting the LTV reduction already baked in.
    annual_churn_fraction = (churn_used / 100.0) * 12.0
    annual_replacement_subs = subscribers_count * annual_churn_fraction
    annual_sac_outlay_inr_cr = annual_replacement_subs * sac / 1e7
    sac_drag_inr_cr = annual_sac_outlay_inr_cr / coe_used if coe_used > 0 else 0.0

    # --- Equity-value bridge -------------------------------------
    gross_equity_value_inr_cr = (
        subscriber_contribution_inr_cr
        + ancillary_inr_cr
        - sac_drag_inr_cr
        - float(inputs.net_debt_inr_cr)
    )

    if gross_equity_value_inr_cr <= 0:
        warnings.append(
            f"gross_equity_value_inr_cr={gross_equity_value_inr_cr:.2f} <= 0 "
            f"(net_debt and SAC drag exceed franchise + ancillary value)"
        )

    # --- Per share ------------------------------------------------
    if inputs.shares_outstanding > 0:
        fv_per_share: Optional[float] = (
            gross_equity_value_inr_cr * 1e7 / float(inputs.shares_outstanding)
        )
    else:
        fv_per_share = None
        warnings.append(
            "shares_outstanding == 0; per-share FV is None (components still populated)"
        )

    components = {
        "subscriber_book_inr_cr": round(subscriber_book_inr_cr, 2),
        "segment_ltv_multiple": seg_mult,
        "subscriber_contribution_inr_cr": round(subscriber_contribution_inr_cr, 2),
        "ancillary_revenue_inr_cr": round(ancillary_inr_cr, 2),
        "sac_drag_inr_cr": round(sac_drag_inr_cr, 2),
        "net_debt_inr_cr": round(float(inputs.net_debt_inr_cr), 2),
        "gross_equity_value_inr_cr": round(gross_equity_value_inr_cr, 2),
        "segment": inputs.segment,
        "ltv_cac_health": classify_ltv_cac_health(ltv_cac_ratio),
        "churn_used_pct": round(churn_used, 4),
        "gm_used_pct": round(gm_used, 4),
        "coe_used": round(coe_used, 4),
    }

    return MediaSubscriberResult(
        fair_value_per_share=fv_per_share,
        avg_subscriber_lifetime_months=avg_lifetime_months,
        customer_lifetime_value_inr=ltv_per_subscriber_inr,
        ltv_cac_ratio=ltv_cac_ratio,
        subscriber_book_value_inr_cr=subscriber_book_inr_cr,
        components=components,
        method="media_subscriber_ltv",
        sanity_warnings=warnings,
    )


# ---------------------------------------------------------------------
# Applicability gate
# ---------------------------------------------------------------------
# Sector keywords that route into the media subscriber engine when the
# ticker isn't explicitly listed in MEDIA_TICKERS. Phase A defaults to
# False for unknown tickers + unknown sectors — the engine only fires
# for the operator-curated cohort. Phase B may relax this once we have
# a media-sector classifier in stocks.industry.
_MEDIA_SECTOR_KEYWORDS: tuple[str, ...] = (
    "media",
    "entertainment",
    "broadcasting",
    "broadcaster",
    "ott",
    "streaming",
    "cinema",
    "exhibition",
    "music",
    "publishing",
    "gaming",
)


def is_media_applicable(
    ticker: Optional[str],
    sector: Optional[str],
) -> tuple[bool, str]:
    """Decide whether to run the media subscriber engine.

    Returns (applicable, reason). ``reason`` is a short machine-readable
    tag the caller can log / surface; on True it identifies HOW the
    routing decision was made (ticker map vs sector keyword).
    """
    clean = _clean_ticker(ticker)
    if clean and clean in MEDIA_TICKERS:
        return (True, f"in_media_ticker_map:{MEDIA_TICKERS[clean]}")

    if sector:
        s = str(sector).strip().lower()
        for kw in _MEDIA_SECTOR_KEYWORDS:
            if kw in s:
                return (True, f"sector_keyword_match:{kw}")

    return (False, "not_a_media_ticker")


# ---------------------------------------------------------------------
# JSON serialization
# ---------------------------------------------------------------------
def to_dict(result: MediaSubscriberResult) -> dict:
    """JSON-safe dict shape. Used when the result is embedded in an
    API response payload or logged.

    Floats / ints / lists / dicts only — no dataclass instances or
    other non-JSON types. The ``ltv_cac_ratio`` may be ``inf`` (when
    SAC == 0); we coerce that to ``None`` for JSON-safety.
    """
    if not isinstance(result, MediaSubscriberResult):
        raise TypeError(
            f"to_dict expects MediaSubscriberResult, got {type(result).__name__}"
        )

    ltv_cac = result.ltv_cac_ratio
    if not _is_finite_number(ltv_cac):
        ltv_cac_serial: Optional[float] = None
    else:
        ltv_cac_serial = float(ltv_cac)

    return {
        "fair_value_per_share": result.fair_value_per_share,
        "avg_subscriber_lifetime_months": result.avg_subscriber_lifetime_months,
        "customer_lifetime_value_inr": result.customer_lifetime_value_inr,
        "ltv_cac_ratio": ltv_cac_serial,
        "subscriber_book_value_inr_cr": result.subscriber_book_value_inr_cr,
        "components": dict(result.components),
        "method": result.method,
        "sanity_warnings": list(result.sanity_warnings),
    }


__all__ = [
    "MediaSegment",
    "MediaSubscriberInputs",
    "MediaSubscriberResult",
    "MEDIA_TICKERS",
    "SEGMENT_LTV_MULTIPLES",
    "compute_ltv",
    "classify_ltv_cac_health",
    "compute_media_fv",
    "is_media_applicable",
    "to_dict",
]
