# backend/services/telecom_arpu_service.py
# ═══════════════════════════════════════════════════════════════
# Telecom ARPU-driven valuation service (T3.11 Phase A).
#
# Standalone service. Phase B wires into the analysis route in a
# separate PR — this Phase A ships only the engine math, the
# applicability gate, and a JSON-safe serializer so the wiring PR
# can mirror the financial / regulated-utility / insurance plumbing
# without touching any caller today.
#
# Why this exists:
#   Standard DCF mis-prices Indian listed telecom for three reasons:
#
#     1. Revenue = subscribers × ARPU × usage. A 4% revenue-CAGR
#        assumption (the generic-DCF default) hides the actual
#        operating reality where subscriber count can decline 2%
#        while ARPU rises 8% — same top-line, very different
#        terminal value.
#     2. Heavy capex front-loading (5G rollout 2023-2026 in India)
#        depresses FCF in transition years. The street values
#        telecom on next-cycle EBITDA, not trailing FCF.
#     3. Spectrum auctions are episodic capex shocks. Treating
#        ₹40,000+ Cr 5G airwave payments as a recurring cash drag
#        understates fair value by 20-40% in a post-auction year.
#
#   Industry-standard frame: 5y explicit subscriber + ARPU forecast
#   driving revenue → EBITDA → unlevered FCF → discounted plus Gordon
#   terminal value. Cross-checked by an EV/EBITDA peer multiple on
#   next-year EBITDA (Bharti / Jio mid-cycle 7-9x, Vodafone-Idea
#   distress 4-5x, Indus Towers stable 9x).
#
# Indian listed telecom universe covered:
#   BHARTIARTL    — Bharti Airtel, integrated #2 by sub share
#   VODAFONEIDEA  — Vi, structurally distressed; needs floor in DCF
#   BHARTIHEXA    — Bharti Hexacom, North-East circles spin-off
#   INDUSTOWER    — Indus Towers, passive infra (towers, no ARPU)
#
#   RELIANCE explicitly excluded — Jio is a segment of RIL and
#   requires SOTP, not an ARPU-only model. SOTP is T1.4 territory.
#
# Caller contract (Phase B will wire these):
#   compute_arpu_driven_fv(inputs: TelecomInputs) -> TelecomValuationResult
#   compute_ev_ebitda_multiple(...) -> Optional[float]
#   is_telecom_arpu_applicable(ticker, sector) -> tuple[bool, str]
#   to_dict(result) -> dict   # JSON-safe shape
#
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from typing import Literal, Optional

logger = logging.getLogger("yieldiq.telecom_arpu")


# ── Type aliases ────────────────────────────────────────────────
TelecomSegment = Literal["mobile", "fixed_broadband", "enterprise", "towers"]


# ── Ticker universe + EV/EBITDA defaults ────────────────────────
#
# RELIANCE intentionally NOT in TELECOM_TICKERS — Jio is a segment of
# RIL (alongside O2C, retail, digital, EPC). SOTP is the correct
# approach, not single-business ARPU DCF. T1.4 of the roadmap covers
# RIL SOTP separately.
#
# Multiples reflect mid-cycle peer reads as of 2026:
#   BHARTIARTL  : 8.5x  — premium-tier integrated, 4G/5G data revenue mix
#   VODAFONEIDEA: 4.5x  — financial-stress discount, AGR overhang, sub losses
#   BHARTIHEXA  : 8.0x  — North-East telecom growth, share-of-wallet leader
#   INDUSTOWER  : 9.0x  — passive infra SPV, tenancy revenue, BHARTI-anchored
TELECOM_TICKERS: frozenset[str] = frozenset({
    "BHARTIARTL", "VODAFONEIDEA", "BHARTIHEXA", "INDUSTOWER",
})

DEFAULT_MULTIPLES: dict[str, float] = {
    "BHARTIARTL":   8.5,
    "VODAFONEIDEA": 4.5,
    "BHARTIHEXA":   8.0,
    "INDUSTOWER":   9.0,
}

# Fallback if a non-known telecom ticker is passed (defensive — caller
# should gate via is_telecom_arpu_applicable first).
_FALLBACK_MULTIPLE = 7.5

# ARPU-DCF default assumptions when the operator hasn't supplied
# explicit forecasts.
_DEFAULT_ARPU_GROWTH_PCT = 5.0      # Indian telecom secular ARPU lift assumption
_DEFAULT_SUB_GROWTH_PCT = 1.5       # Net add tailwind, sub-1% in mature mobile
_DEFAULT_CHURN_PCT = 2.5            # Monthly churn, % of base

# Months in a year, used to lift monthly ARPU to annual revenue.
_MONTHS_PER_YEAR = 12

# 1 INR Crore = 1e7 INR. Revenue projections are kept in INR-Crores
# throughout so the dataclass numbers match how operators read
# financials in India (always ₹Cr in filings + screener).
_INR_PER_CRORE = 1.0e7


# ── Data classes ────────────────────────────────────────────────
@dataclass
class SubscriberForecast:
    """One year of subscriber + ARPU forecast.

    ``year_offset`` is the offset from today (0 = current year, 1 =
    year +1, etc.). The DCF only consumes year_offset >= 1 for the
    explicit horizon; year_offset == 0 supplies the baseline anchor.
    """
    year_offset: int
    subscriber_count_millions: float
    arpu_inr_per_month: float
    churn_rate_pct: float                  # 0-100, monthly %
    data_usage_gb: Optional[float] = None


@dataclass
class TelecomInputs:
    current_subscribers_millions: float
    current_arpu_inr: float
    forecast_horizon_years: int = 5
    forecasts: list[SubscriberForecast] = field(default_factory=list)

    # P&L + capex bridge (defaults are BHARTIARTL-shaped mid-cycle).
    operating_margin_pct: float = 30.0
    maintenance_capex_pct_of_revenue: float = 12.0
    growth_capex_pct_of_revenue: float = 5.0
    spectrum_capex_one_time: float = 0.0       # ₹Cr, hits year 1

    # Discounting.
    tax_rate: float = 0.22
    discount_rate: float = 0.11
    terminal_growth: float = 0.04

    # Per-share derivation.
    shares_outstanding: float = 0.0            # in Cr (matches Indian convention)
    segment: TelecomSegment = "mobile"


@dataclass
class TelecomValuationResult:
    fair_value_per_share: Optional[float]
    aggregate_ev: Optional[float]              # Enterprise Value, ₹Cr
    revenue_year_5: float                      # bridge metric, ₹Cr
    ebitda_year_5: float                       # bridge metric, ₹Cr
    components: dict                           # year-by-year FCF, terminal, factors
    method: str                                # arpu_dcf | ev_ebitda_multiple | unavailable
    sanity_warnings: list[str]


# ── Helpers ─────────────────────────────────────────────────────
def _clean_ticker(t: Optional[str]) -> str:
    return (t or "").replace(".NS", "").replace(".BO", "").upper()


def _safe_float(x, default: float = 0.0) -> float:
    try:
        if x is None:
            return default
        v = float(x)
        if math.isnan(v) or math.isinf(v):
            return default
        return v
    except (TypeError, ValueError):
        return default


# ── Core engine ─────────────────────────────────────────────────
def project_revenue(
    forecast: SubscriberForecast,
    operating_margin_pct: float,
) -> tuple[float, float]:
    """Return (revenue_inr_cr, ebitda_inr_cr) for a single year.

    Revenue = subscribers (M) × ARPU (₹/mo) × 12 / 1e7 → ₹Cr
            = subs(M) × ARPU(₹/mo) × 12 × 1e6 / 1e7
            = subs(M) × ARPU(₹/mo) × 12 / 10

    The 1e6 factor lifts millions-of-subs to absolute headcount; the
    1e7 divisor folds INR to Crores. Net = ×12 / 10.

    EBITDA = revenue × operating_margin / 100.
    """
    subs_m = _safe_float(forecast.subscriber_count_millions)
    arpu = _safe_float(forecast.arpu_inr_per_month)
    margin_pct = _safe_float(operating_margin_pct)

    # Subs in millions → absolute (×1e6); ARPU/month × 12 → annual ₹;
    # then / 1e7 to land in ₹Cr. Combined factor: 12 × 1e6 / 1e7 = 1.2.
    revenue_cr = subs_m * arpu * 1.2
    ebitda_cr = revenue_cr * (margin_pct / 100.0)
    return revenue_cr, ebitda_cr


def _pad_forecasts(inputs: TelecomInputs) -> list[SubscriberForecast]:
    """Build an explicit per-year forecast list covering year_offset
    1..horizon. Uses operator-supplied entries where present; pads the
    tail by extrapolating the last supplied year forward at default
    growth assumptions (or extrapolating the baseline when the
    forecasts list is empty).
    """
    horizon = max(1, int(inputs.forecast_horizon_years or 5))
    supplied = sorted(
        [f for f in (inputs.forecasts or []) if f.year_offset >= 1],
        key=lambda f: f.year_offset,
    )
    by_year = {f.year_offset: f for f in supplied}

    # Anchor: use the last supplied year, else synthesize from baseline.
    if supplied:
        anchor = supplied[-1]
    else:
        anchor = SubscriberForecast(
            year_offset=0,
            subscriber_count_millions=_safe_float(inputs.current_subscribers_millions),
            arpu_inr_per_month=_safe_float(inputs.current_arpu_inr),
            churn_rate_pct=_DEFAULT_CHURN_PCT,
        )

    out: list[SubscriberForecast] = []
    for year in range(1, horizon + 1):
        if year in by_year:
            out.append(by_year[year])
            continue
        # Extrapolate from anchor at default growth rates. Years past
        # the anchor compound; years before the anchor (gaps inside the
        # supplied range) interpolate by holding the anchor flat — the
        # supplied entry wins anyway, so the gap-fill is a soft default.
        years_from_anchor = year - anchor.year_offset
        if years_from_anchor < 1:
            years_from_anchor = 1
        sub_growth = (1.0 + _DEFAULT_SUB_GROWTH_PCT / 100.0) ** years_from_anchor
        arpu_growth = (1.0 + _DEFAULT_ARPU_GROWTH_PCT / 100.0) ** years_from_anchor
        out.append(SubscriberForecast(
            year_offset=year,
            subscriber_count_millions=_safe_float(anchor.subscriber_count_millions) * sub_growth,
            arpu_inr_per_month=_safe_float(anchor.arpu_inr_per_month) * arpu_growth,
            churn_rate_pct=_safe_float(anchor.churn_rate_pct, _DEFAULT_CHURN_PCT),
            data_usage_gb=anchor.data_usage_gb,
        ))
    return out


def compute_arpu_driven_fv(inputs: TelecomInputs) -> TelecomValuationResult:
    """5-year explicit ARPU-DCF with Gordon terminal value.

    Steps per year y in [1..horizon]:
      revenue_y = subs_y × ARPU_y × 12  (in ₹Cr via project_revenue)
      ebitda_y  = revenue_y × op_margin
      ebit_y    = ebitda_y − D&A proxy (= maintenance_capex_pct × revenue)
      nopat_y   = ebit_y × (1 − tax_rate)
      fcf_y     = nopat_y + D&A − (maintenance + growth) capex
                − spectrum_capex_one_time (year 1 only)

    Terminal value at year horizon:
      TV = fcf_horizon × (1 + g) / (r − g)

    Discount: each year's FCF and TV are pulled back to today by
    1 / (1 + r)^y.

    Aggregate EV = sum of discounted FCFs + discounted TV.
    FV per share = EV (₹Cr) × 1e7 / shares_outstanding_count.

    Note: shares_outstanding in TelecomInputs is in Cr (Indian
    convention); the conversion below folds back to absolute shares.
    """
    warnings: list[str] = []
    horizon = max(1, int(inputs.forecast_horizon_years or 5))

    supplied_count = sum(1 for f in (inputs.forecasts or []) if f.year_offset >= 1)
    forecasts = _pad_forecasts(inputs)
    if supplied_count < horizon:
        warnings.append(
            f"padded forecasts to horizon ({supplied_count}/{horizon} supplied)"
        )

    r = _safe_float(inputs.discount_rate, 0.11)
    g_t = _safe_float(inputs.terminal_growth, 0.04)
    # Defensive: keep at least 100bps between r and g_t so the Gordon
    # formula doesn't divide by ~zero.
    if r - g_t < 0.01:
        warnings.append("discount−terminal spread <100bps; clamped to 0.01")
        g_t = r - 0.01

    tax = _safe_float(inputs.tax_rate, 0.22)
    maint_pct = _safe_float(inputs.maintenance_capex_pct_of_revenue, 12.0)
    grow_pct = _safe_float(inputs.growth_capex_pct_of_revenue, 5.0)
    spectrum_oneoff = _safe_float(inputs.spectrum_capex_one_time, 0.0)
    op_margin = _safe_float(inputs.operating_margin_pct, 30.0)

    years: list[dict] = []
    sum_pv_fcf = 0.0
    revenue_year_5 = 0.0
    ebitda_year_5 = 0.0
    fcf_terminal = 0.0

    for idx, fc in enumerate(forecasts[:horizon], start=1):
        revenue, ebitda = project_revenue(fc, op_margin)
        # D&A proxy = maintenance_capex on revenue (the steady-state
        # identity for capital-heavy businesses).
        d_and_a = revenue * (maint_pct / 100.0)
        ebit = ebitda - d_and_a
        nopat = ebit * (1.0 - tax)
        capex_total = revenue * (maint_pct + grow_pct) / 100.0
        spectrum = spectrum_oneoff if idx == 1 else 0.0
        fcf = nopat + d_and_a - capex_total - spectrum
        df = 1.0 / ((1.0 + r) ** idx)
        pv = fcf * df
        sum_pv_fcf += pv
        years.append({
            "year_offset": fc.year_offset,
            "subscribers_millions": round(_safe_float(fc.subscriber_count_millions), 2),
            "arpu_inr": round(_safe_float(fc.arpu_inr_per_month), 2),
            "revenue_inr_cr": round(revenue, 2),
            "ebitda_inr_cr": round(ebitda, 2),
            "nopat_inr_cr": round(nopat, 2),
            "capex_inr_cr": round(capex_total + spectrum, 2),
            "fcf_inr_cr": round(fcf, 2),
            "discount_factor": round(df, 5),
            "pv_fcf_inr_cr": round(pv, 2),
        })
        if idx == horizon:
            revenue_year_5 = revenue
            ebitda_year_5 = ebitda
            fcf_terminal = fcf
        elif idx == 5 and horizon > 5:
            revenue_year_5 = revenue
            ebitda_year_5 = ebitda

    # Gordon terminal value off the last horizon-year FCF.
    if r - g_t > 0:
        terminal_value = fcf_terminal * (1.0 + g_t) / (r - g_t)
    else:
        terminal_value = 0.0
        warnings.append("terminal value zeroed (r ≤ g)")
    pv_terminal = terminal_value / ((1.0 + r) ** horizon)
    aggregate_ev = sum_pv_fcf + pv_terminal

    # Per-share. shares_outstanding is in Cr in TelecomInputs to match
    # Indian filings; aggregate_ev is in ₹Cr too, so per-share is direct
    # division (no 1e7 conversion needed).
    shares_cr = _safe_float(inputs.shares_outstanding, 0.0)
    if shares_cr > 0 and aggregate_ev > 0:
        fv_per_share = aggregate_ev / shares_cr
    else:
        fv_per_share = None
        if shares_cr <= 0:
            warnings.append("shares_outstanding missing/zero — per-share suppressed")
        if aggregate_ev <= 0:
            warnings.append("aggregate EV non-positive — likely distress profile (Vi-shape)")

    # Distress flag: negative FCF in year 1 is a real telecom pattern
    # (5G capex + spectrum), but persistent negative FCFs across horizon
    # is a warning the caller should surface.
    negative_fcf_years = sum(1 for y in years if y["fcf_inr_cr"] < 0)
    if negative_fcf_years >= max(1, horizon - 2):
        warnings.append(f"{negative_fcf_years}/{horizon} explicit FCF years negative — distress")

    components = {
        "years": years,
        "terminal_value_inr_cr": round(terminal_value, 2),
        "pv_terminal_inr_cr": round(pv_terminal, 2),
        "sum_pv_explicit_inr_cr": round(sum_pv_fcf, 2),
        "discount_rate": round(r, 4),
        "terminal_growth": round(g_t, 4),
        "tax_rate": round(tax, 4),
        "operating_margin_pct": round(op_margin, 2),
        "maintenance_capex_pct": round(maint_pct, 2),
        "growth_capex_pct": round(grow_pct, 2),
        "spectrum_capex_one_time_inr_cr": round(spectrum_oneoff, 2),
        "segment": inputs.segment,
        "shares_outstanding_cr": round(shares_cr, 4),
    }

    return TelecomValuationResult(
        fair_value_per_share=round(fv_per_share, 2) if fv_per_share is not None else None,
        aggregate_ev=round(aggregate_ev, 2),
        revenue_year_5=round(revenue_year_5, 2),
        ebitda_year_5=round(ebitda_year_5, 2),
        components=components,
        method="arpu_dcf" if fv_per_share is not None else "unavailable",
        sanity_warnings=warnings,
    )


def compute_ev_ebitda_multiple(
    next_year_ebitda: float,
    multiple: float,
    net_debt: float,
    shares_outstanding: float,
) -> Optional[float]:
    """Cross-check via EV/EBITDA multiple.

    EV         = next_year_ebitda × multiple
    Equity     = EV − net_debt
    Per-share  = Equity (₹Cr) / shares_outstanding (Cr)

    All amounts in ₹Cr. Returns None when shares are missing/zero
    or when implied equity is non-positive (distress-distressed cases
    where even mid-cycle multiple can't cover the debt load).
    """
    ebitda = _safe_float(next_year_ebitda)
    mult = _safe_float(multiple)
    debt = _safe_float(net_debt)
    shares = _safe_float(shares_outstanding)
    if ebitda <= 0 or mult <= 0 or shares <= 0:
        return None
    ev = ebitda * mult
    equity = ev - debt
    if equity <= 0:
        return None
    return round(equity / shares, 2)


def select_ev_ebitda_multiple(
    ticker: str,
    market_share_trend: Optional[str] = None,
) -> float:
    """Per-ticker EV/EBITDA multiple with ±1 adjustment by trend.

    Trend semantics:
      "gaining" → +1.0  (market-share momentum justifies multiple lift)
      "stable"  →  0.0  (default)
      "losing"  → −1.0  (multiple compresses with share loss)
      None / other → no adjustment

    Unknown ticker → fallback 7.5x.
    """
    clean = _clean_ticker(ticker)
    base = DEFAULT_MULTIPLES.get(clean, _FALLBACK_MULTIPLE)
    trend = (market_share_trend or "").strip().lower()
    if trend == "gaining":
        return round(base + 1.0, 2)
    if trend == "losing":
        return round(max(2.0, base - 1.0), 2)
    return round(base, 2)


def is_telecom_arpu_applicable(
    ticker: str,
    sector: Optional[str],
) -> tuple[bool, str]:
    """Gate for whether the ARPU-DCF engine should fire.

    Returns ``(applicable, reason)``. RELIANCE — even though Jio is a
    telecom business — is NOT applicable because it requires SOTP;
    return reason makes that explicit so a Phase B caller can route
    to T1.4 SOTP territory cleanly.
    """
    clean = _clean_ticker(ticker)
    if not clean:
        return False, "empty ticker"
    if clean in TELECOM_TICKERS:
        return True, f"{clean} in TELECOM_TICKERS"
    if clean == "RELIANCE":
        return False, "RELIANCE requires SOTP (Jio is a segment) — see T1.4"
    sec = (sector or "").strip().lower()
    if "telecom" in sec or "communication services" in sec:
        # Sector-tagged but not on our explicit list. Allow with a soft
        # signal so the caller can choose to fire defensively.
        return False, f"sector tagged telecom but {clean} not in TELECOM_TICKERS"
    return False, f"{clean} not a telecom ticker"


# ── JSON-safe serializer ────────────────────────────────────────
def to_dict(result: TelecomValuationResult) -> dict:
    """Project a TelecomValuationResult into a plain dict for JSON
    responses or DB persistence. Numbers are kept as floats; no
    datetime / Decimal types in the output.
    """
    return {
        "fair_value_per_share": result.fair_value_per_share,
        "aggregate_ev_inr_cr": result.aggregate_ev,
        "revenue_year_5_inr_cr": result.revenue_year_5,
        "ebitda_year_5_inr_cr": result.ebitda_year_5,
        "method": result.method,
        "components": result.components,
        "sanity_warnings": list(result.sanity_warnings),
    }
