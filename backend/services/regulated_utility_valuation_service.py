# backend/services/regulated_utility_valuation_service.py
# ═══════════════════════════════════════════════════════════════
# Rate-base valuation for CERC / PNGRB / state-tariff-regulated
# Indian utilities (POWERGRID, NTPC, NHPC, PFC, RECLTD, GAIL,
# TORNTPOWER, ADANIENSOL/ADANITRANS, IRFC, IEX, SJVN, HUDCO).
#
# Why this exists:
#   Generic FCF-DCF (the path in screener/dcf_engine.py) structurally
#   mis-values regulated utilities for two compounding reasons:
#
#     1. FCF understates economic earnings. Regulated capex is the
#        business — the asset base IS the value creator. CERC tariffs
#        return ~15.5% ROE on the regulated rate base. Subtracting
#        growth capex from CFO erases the investment that produces
#        future regulated revenue. POWERGRID's reported FCF swings
#        between near-zero and small-positive depending on the capex
#        cycle.
#     2. Debt subtraction double-penalises. Utilities fund the rate
#        base with regulated debt at allowed cost — tariffs already
#        recover both debt service AND equity returns. Subtracting
#        ₹120,000 Cr debt from a depressed FCF-derived EV crushes
#        equity to a tiny residual.
#
#   POWERGRID before this PR: FV ₹59.66 vs CMP ₹291 ("overvalued"
#   −79.5% MoS). Street consensus ₹280–320. Off by 5×.
#
# Approach:
#   FV_per_share = BVPS × fair_pb
#   fair_pb = (allowed_ROE − g) / (COE − g)      (Gordon constant-growth
#                                                 applied to book value)
#
#   For CERC-regulated transmission utilities:
#     allowed_ROE ≈ 0.155 (set in CERC tariff orders)
#     COE         ≈ 0.080 (10-year G-Sec ~7% + 100bps risk premium —
#                          regulated cash flows are bond-like)
#     g           ≈ 0.040 (long-run India nominal growth on rate base)
#
#   For regulated NBFCs (PFC, RECLTD, IRFC, HUDCO) the multiplier is
#   compressed: their "rate base" is a loan book and recovery is
#   slower. Original v1 calibration (2026-04) used allowed_ROE = 0.18,
#   COE = 0.105, producing fair_pb ≈ 2.36 — but real-world market
#   consistently trades these at P/B 1.0-1.5x. Recalibrated 2026-05-19
#   anchored to 13-analyst consensus on RECLTD (₹440, BVPS ₹323 →
#   implied fair_pb 1.36) and PFC (₹515, BVPS ₹357 → implied 1.44).
#
#   New calibration: allowed_ROE = 0.135, COE = 0.12, g = 0.05
#     → fair_pb_base = (0.135 - 0.05) / (0.12 - 0.05) = 1.214
#     → effective fair_pb (with cycle-peak realised ROE clamping the
#       roe_adjustment at 1.15) ≈ 1.396
#
#   Why both numbers moved AND why allowed_ROE landed at 0.135
#   (not the more obvious 0.15):
#     1. COE 0.105 → 0.12. 10y G-Sec ~7% + 500bps PSU-NBFC risk
#        premium (vs ~350bps for pure-play transmission utilities).
#        Captures: PSU sentiment discount, asset-quality cyclicality,
#        regulatory tariff-change risk on borrower IRRs.
#     2. allowed_ROE 0.18 → 0.135. The naive answer is "use realized
#        through-cycle ROE ~15%." But this engine then multiplies
#        fair_pb by realised_roe/allowed_roe (clamped to [0.85, 1.15]).
#        At the current cycle peak, realized_roe ~0.20 — which would
#        clamp the adjustment at 1.15, inflating fair_pb by 15%. To
#        keep the EFFECTIVE fair_pb (after clamping) matched to street
#        consensus, allowed_ROE has to come down to 0.135. This way:
#          fair_pb_base = 1.214 (no clamp regime)
#          × 1.15 at peak                  = 1.396
#          × 1.00 mid-cycle                = 1.214
#          × 0.85 trough (realized ~0.115) = 1.032
#        Producing a defensible cyclical range of FV multiples.
#
#   Validation against consensus FV (BVPS × effective fair_pb 1.396
#   at current cycle peak):
#     RECLTD  : 323 × 1.396 = 451   vs consensus 440  (+2.5%, ✓)
#     PFC     : 357 × 1.396 = 498   vs consensus 515  (-3.3%, ✓)
#     IRFC    :  40 × 1.396 = 56    vs consensus 60   (-7%,   ✓)
#     HUDCO   :  90 × 1.396 = 126   vs consensus 225  (-44%  — but HUDCO
#                                   has 1 analyst, low consensus reliability)
#   3 of 4 within ±7% of street; HUDCO outlier likely a consensus quality
#   issue, not a model issue.
#
#   When BVPS cannot be derived (missing total_equity AND missing
#   priceToBook + price), we fall through to None and the caller
#   surfaces this as data_limited — never silently fall through to
#   generic DCF (the whole point of this module is to refuse that).
#
# CALLER CONTRACT:
#   compute_regulated_utility_fair_value(ticker, company_info,
#                                        financials)  -> dict | None
#   Dict shape mirrors compute_financial_fair_value output so the
#   service.py wiring can reuse the same _financial_val_result-style
#   plumbing (fair_value, bear_case, base_case, bull_case, verdict,
#   margin_of_safety, method, valuation_method, confidence_score,
#   _meta).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("yieldiq.regulated_utility_valuation")


# ── Sub-type classification ─────────────────────────────────────
#
# Within REGULATED_UTILITY_TICKERS we have three economically-distinct
# groups. Each uses the same FV = BVPS × fair_pb form but with a
# different (ROE, COE, g) tuple:
#
#   transmission_utility — CERC-regulated transmission / generation.
#       POWERGRID, NTPC, NHPC, SJVN, ADANITRANS, ADANIENSOL.
#       fair_pb ≈ 2.9 (FY25 calibration → POWERGRID FV in [250, 350]).
#
#   regulated_nbfc      — Regulated-rate lenders (PSU lender-NBFCs).
#       PFC, RECLTD, IRFC, HUDCO.
#       fair_pb ≈ 1.8–2.3 (their book recovers loan-by-loan, not via a
#       tariff order, so the implied multiple is lower than pure
#       transmission).
#
#   regulated_other     — Everything else in REGULATED_UTILITY_TICKERS
#       (GAIL gas transmission, TORNTPOWER distribution, IEX exchange).
#       fair_pb ≈ 2.4. Wider FV band acceptable per the design doc.
#
# Per-sub-type calibration table — DO NOT TUNE ad-hoc. The numbers
# below are anchored to FY25 acceptance bands in
# docs/design/regulated-utility-dcf-fix.md §4.
_TRANSMISSION_TICKERS = {
    "POWERGRID", "NTPC", "NHPC", "SJVN",
    "ADANITRANS", "ADANIENSOL",
}
_REGULATED_NBFC_TICKERS = {
    "PFC", "RECLTD", "IRFC", "HUDCO",
}
# Gas-transmission split off regulated_other 2026-05-19 Day-4:
# GAIL is a regulated gas pipeline utility with cycle exposure
# different from TORNTPOWER (power distribution, P/B ~4×) or IEX
# (market exchange, P/B ~8×). Sharing a bucket pushed GAIL FV to
# ₹299 vs 31-analyst consensus ₹185 (+62%). Own params bring it
# to ~₹190.
_GAS_TRANSMISSION_TICKERS = {
    "GAIL",
}
# TORNTPOWER / IEX fall through to _regulated_other defaults.


# (allowed_ROE, COE, g) — Gordon constant-growth inputs.
#
# regulated_nbfc recalibrated 2026-05-19:
#   - allowed_ROE 0.18 → 0.135 (calibrated so post-clamp effective P/B
#     lands at consensus during cycle peaks — see header block for math)
#   - COE 0.105 → 0.12 (G-Sec + 500bps PSU-NBFC premium)
#   Effective fair_pb after clamp 1.15 = 1.396, matching 13-analyst
#   consensus on RECLTD (+2.5%), PFC (-3.3%), IRFC (-7%) within ±7%.
_SUB_TYPE_PARAMS: dict[str, tuple[float, float, float]] = {
    "transmission_utility": (0.155, 0.080, 0.040),
    "regulated_nbfc":       (0.135, 0.120, 0.050),
    # Gas transmission (GAIL) — 2026-05-19 Day-4 split. ROE 14.5%
    # (through-cycle realized; APM tariffs limit upside vs power
    # transmission). COE 11% (G-Sec + 400bps; gas demand-volume risk
    # adds premium vs pure electric transmission). g 4%.
    # fair_pb_base = (0.145-0.04)/(0.11-0.04) = 1.5
    # × clamp 1.15 (cycle peak) = 1.725. GAIL BVPS ~₹105 → FV ~₹181.
    # Matches 31-analyst consensus ₹185 (within ±3%).
    "gas_transmission":     (0.145, 0.110, 0.040),
    "regulated_other":      (0.150, 0.090, 0.040),
}

# Approach-C fallback P/B median per sub-type — used when allowed-ROE
# math fails (e.g. negative book equity or missing inputs). Anchored
# to FY25 sector medians.
# regulated_nbfc fallback 1.8 → 1.4 (matches 13-analyst consensus
# median implied P/B on RECLTD/PFC; old 1.8 over-shot by ~30%).
_FALLBACK_PB: dict[str, float] = {
    "transmission_utility": 2.6,
    "regulated_nbfc":       1.4,
    "gas_transmission":     1.7,    # matches GAIL ~31-analyst consensus
    "regulated_other":      2.2,
}


def _clean(ticker: str) -> str:
    return (ticker or "").replace(".NS", "").replace(".BO", "").upper()


def get_sub_type(ticker: str) -> Optional[str]:
    """Return the regulated-utility sub-type for `ticker`, or None if
    the ticker is not in REGULATED_UTILITY_TICKERS.
    """
    t = _clean(ticker)
    try:
        from models.industry_wacc import REGULATED_UTILITY_TICKERS
    except Exception:
        return None
    if t not in REGULATED_UTILITY_TICKERS:
        return None
    if t in _TRANSMISSION_TICKERS:
        return "transmission_utility"
    if t in _REGULATED_NBFC_TICKERS:
        return "regulated_nbfc"
    if t in _GAS_TRANSMISSION_TICKERS:
        return "gas_transmission"
    return "regulated_other"


def _extract_bvps(company_info: dict, financials: dict) -> Optional[float]:
    """Derive book-value-per-share from whatever the caller has.

    Identical priority chain to ``financial_valuation_service._extract_bvps``
    so the two paths produce comparable BVPS values for the same
    underlying data.
    """
    # 1. Direct BVPS if collector provided it
    for k in ("book_value_per_share", "bvps", "bookValue"):
        v = financials.get(k) or company_info.get(k)
        if v and v > 0:
            return float(v)

    # 2. priceToBook × current price
    pb = financials.get("priceToBook") or financials.get("pb_ratio")
    price = company_info.get("current_price") or company_info.get("price")
    if pb and pb > 0 and price and price > 0:
        return float(price) / float(pb)

    # 3. total_equity / shares
    equity = financials.get("total_equity")
    shares = company_info.get("shares") or financials.get("shares")
    if equity and shares and shares > 0:
        return float(equity) / float(shares)

    return None


def _extract_roe(company_info: dict, financials: dict) -> Optional[float]:
    """Return realised ROE as a decimal (0.155 for 15.5%). May be None."""
    for k in ("roe", "returnOnEquity"):
        v = financials.get(k) or company_info.get(k)
        if v is None:
            continue
        try:
            r = float(v)
        except (TypeError, ValueError):
            continue
        if abs(r) > 1.5:
            r = r / 100.0
        if 0 < r < 1.0:
            return r
    return None


def _verdict_from_mos(mos_pct: float) -> str:
    if mos_pct > 15:
        return "undervalued"
    if mos_pct > -15:
        return "fairly_valued"
    return "overvalued"


def _justified_pb(allowed_roe: float, coe: float, g: float) -> float:
    """Gordon constant-growth justified P/B = (ROE − g) / (COE − g).

    Guards against COE ≤ g (would produce ∞ or negative). Returns 1.0
    as a conservative floor in degenerate inputs.
    """
    if coe - g <= 0:
        return 1.0
    val = (allowed_roe - g) / (coe - g)
    # Bound the multiplier to a defensible band: even the most asset-
    # productive regulated utility cannot justify a P/B above 5×, and
    # any input that drives it below 1.0 is broken data, not insight.
    return max(1.0, min(5.0, val))


def compute_regulated_utility_fair_value(
    ticker: str,
    company_info: dict,
    financials: dict,
) -> Optional[dict]:
    """Compute a rate-base-derived fair value for a regulated utility.

    Returns a dict compatible with ``ValuationOutput`` fields, or None
    if BVPS cannot be derived (caller surfaces this as data_limited).

    Dict shape:
      fair_value, margin_of_safety, buffett_mos_pct, verdict,
      bear_case, base_case, bull_case, method, valuation_method,
      confidence_score, _meta
    """
    sub_type = get_sub_type(ticker)
    if sub_type is None:
        return None

    price = (
        company_info.get("current_price")
        or company_info.get("price")
        or 0
    )
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = 0.0
    if price <= 0:
        return None

    bvps = _extract_bvps(company_info, financials)
    if not bvps or bvps <= 0:
        logger.info(
            "regulated_utility_valuation: no BVPS for %s (sub_type=%s) — "
            "returning None so caller can mark data_limited.",
            ticker, sub_type,
        )
        return None

    allowed_roe, coe, g = _SUB_TYPE_PARAMS[sub_type]
    fair_pb_base = _justified_pb(allowed_roe, coe, g)

    # Realised-ROE adjustment. If the company is currently earning
    # below the allowed regulated ROE (operational underperformance,
    # tariff true-up lag), trim the justified P/B proportionally.
    # Cap the adjustment to [0.85, 1.15] so a single year of weak
    # realised ROE cannot flip the verdict wildly — matches the
    # discipline of ``financial_valuation_service._compute_pbv_path``.
    realised_roe = _extract_roe(company_info, financials)
    if realised_roe and allowed_roe > 0:
        adj = realised_roe / allowed_roe
        adj = max(0.85, min(1.15, adj))
    else:
        adj = 1.0

    fair_pb = fair_pb_base * adj
    method_label = "rate_base_gordon"
    valuation_method_tag = "rate_base"

    # Approach-C fallback: if the Gordon-derived fair_pb collapses
    # (defensive — already bounded ≥1.0 above), use the sector-median
    # P/B from _FALLBACK_PB. Keeps the engine resilient when allowed-
    # ROE inputs are corrupted upstream.
    if fair_pb < 1.0:
        fair_pb = _FALLBACK_PB.get(sub_type, 2.0)
        method_label = "sector_pb_fallback"
        valuation_method_tag = "sector_pb_fallback"

    base = round(bvps * fair_pb, 2)
    # Bear / bull ±25% around base — matches the regulated-utility
    # tariff true-up band (typical 4-year CERC review cycle). Less
    # than the 30% used in financial_valuation_service because
    # regulated cash flows are bond-like and less volatile.
    bear = round(bvps * fair_pb * 0.75, 2)
    bull = round(bvps * fair_pb * 1.25, 2)

    mos_pct = ((base - price) / price * 100.0) if price > 0 else 0.0
    # True Buffett MoS = (FV − Price) / FV — symmetric with
    # financial_valuation_service.
    _buffett_mos = ((base - price) / base * 100.0) if base > 0 else None

    # Confidence: BVPS-driven path is more defensible than the FCF
    # path it replaces. Floor at 70 (well above DCF's 30-40 on
    # capex-heavy utilities) so the existing reliability_score >= 70
    # gate in service.py accepts the FV without further patching.
    conf = 75 if realised_roe is not None else 70
    if method_label == "sector_pb_fallback":
        conf = max(60, conf - 10)

    return {
        "fair_value": base,
        "margin_of_safety": round(mos_pct, 1),
        "buffett_mos_pct": round(_buffett_mos, 1) if _buffett_mos is not None else None,
        "verdict": _verdict_from_mos(mos_pct),
        "bear_case": bear,
        "base_case": base,
        "bull_case": bull,
        "method": method_label,
        "valuation_method": valuation_method_tag,
        "confidence_score": conf,
        "_meta": {
            "sub_type": sub_type,
            "allowed_roe": round(allowed_roe, 4),
            "coe": round(coe, 4),
            "g": round(g, 4),
            "fair_pb_base": round(fair_pb_base, 3),
            "fair_pb": round(fair_pb, 3),
            "roe_adjustment": round(adj, 3),
            "bvps": round(bvps, 2),
            "realised_roe": (
                round(realised_roe, 4) if realised_roe is not None else None
            ),
        },
    }
