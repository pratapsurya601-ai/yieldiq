# backend/services/financial_valuation_service.py
# ═══════════════════════════════════════════════════════════════
# Sector-appropriate valuation for banks, NBFCs, and insurers.
#
# Why this exists:
#   FCF-based DCF is not meaningful for financials (loans = operating
#   outflows). The existing P/B × fixed-multiplier path in
#   analysis_service handles the common case, but it uses a single
#   hardcoded multiplier per sub-sector and no ROE adjustment, so for
#   many Nifty-50 financials (PFC, REC, IRFC, LIC etc.) the sanity
#   gate in routers/analysis.py flips them to "data_limited".
#
# This module replaces that simple multiplier with a peer-median P/BV
# band, adjusted for the company's ROE relative to peers, plus P/E
# and P/EV alternatives for growth NBFCs and insurers.
#
# CALLER CONTRACT:
#   compute_financial_fair_value(ticker, company_info, financials,
#                                shareholding)  -> dict | None
#   Returns None when inputs are insufficient; caller keeps the
#   existing data_limited behaviour in that case.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import statistics
import time as _time
from typing import Optional

logger = logging.getLogger("yieldiq.financial_valuation")


# ── Peer groups (clean tickers, no .NS/.BO) ─────────────────────
FINANCIAL_PEER_GROUPS: dict[str, list[str]] = {
    "psu_banks":         ["SBIN", "BANKBARODA", "PNB", "CANBK", "UNIONBANK", "INDIANB"],
    "private_banks":     ["HDFCBANK", "ICICIBANK", "KOTAKBANK", "AXISBANK", "INDUSINDBK", "FEDERALBNK"],
    "growth_nbfc":       ["BAJFINANCE", "BAJAJFINSV", "CHOLAFIN", "MUTHOOTFIN", "MANAPPURAM", "SBICARD"],
    "govt_nbfc":         ["PFC", "REC", "IRFC", "HUDCO"],
    "life_insurance":    ["LICI", "HDFCLIFE", "SBILIFE"],
    "general_insurance": ["ICICIGI", "STARHEALTH"],
    "housing_finance":   ["LICHSGFIN", "CANFINHOME", "PNBHOUSING", "AAVAS", "HOMEFIRST"],
    "asset_mgmt":        ["HDFCAMC", "ICICIAMC"],
}

# Which valuation method each group uses
_GROUP_METHOD = {
    "psu_banks":         "p_bv_peer",
    "private_banks":     "p_bv_peer",
    "growth_nbfc":       "p_e_peer",
    "govt_nbfc":         "p_bv_peer",
    "life_insurance":    "p_ev_peer",
    "general_insurance": "p_bv_peer",
    "housing_finance":   "p_bv_peer",
    "asset_mgmt":        "p_e_peer",
}

# Sector-reasonable fallback medians when DB peer lookup returns nothing.
# Calibrated from FY25 trailing data; used only on cold start / DB down.
_FALLBACK_PB = {
    "psu_banks":         (0.9, 0.14),   # (median P/BV, median ROE as decimal)
    "private_banks":     (2.4, 0.16),
    "growth_nbfc":       (4.0, 0.20),
    "govt_nbfc":         (1.2, 0.18),
    "life_insurance":    (2.0, 0.14),   # P/EV approximated via P/BV
    "general_insurance": (3.0, 0.15),
    "housing_finance":   (1.3, 0.13),
    "asset_mgmt":        (8.0, 0.25),   # AMCs trade rich
}

_FALLBACK_PE = {
    "growth_nbfc":       (25.0, 0.20),
    "asset_mgmt":        (30.0, 0.25),
}


# ── Peer-median cache (1h TTL) ──────────────────────────────────
_PEER_CACHE: dict[str, tuple[float, dict]] = {}
_PEER_CACHE_TTL = 3600  # seconds


def _clean(ticker: str) -> str:
    return ticker.replace(".NS", "").replace(".BO", "").upper()


def get_peer_group(ticker: str) -> Optional[str]:
    """Return the peer-group key for a financial ticker, or None."""
    t = _clean(ticker)
    for key, members in FINANCIAL_PEER_GROUPS.items():
        if t in members:
            return key
    return None


def _fetch_peer_medians_from_db(group_key: str) -> Optional[dict]:
    """
    Query latest MarketMetrics + Financials for every member of a peer group
    and return median P/BV and ROE. Returns None if DB unavailable or no rows.
    """
    try:
        # Lazy import — this module must not hard-depend on the pipeline
        from backend.services.analysis_service import _get_pipeline_session
    except Exception:
        return None

    db = _get_pipeline_session()
    if db is None:
        return None
    try:
        from data_pipeline.models import MarketMetrics, Financials
        from sqlalchemy import desc

        members = FINANCIAL_PEER_GROUPS.get(group_key, [])
        if not members:
            return None

        pb_values: list[float] = []
        pe_values: list[float] = []
        roe_values: list[float] = []

        for peer in members:
            # Latest market metrics row
            mm = (
                db.query(MarketMetrics)
                .filter(MarketMetrics.ticker == peer)
                .order_by(desc(MarketMetrics.trade_date))
                .first()
            )
            if mm:
                if mm.pb_ratio and mm.pb_ratio > 0:
                    pb_values.append(float(mm.pb_ratio))
                if mm.pe_ratio and mm.pe_ratio > 0:
                    pe_values.append(float(mm.pe_ratio))

            # Latest annual ROE
            fin = (
                db.query(Financials)
                .filter(Financials.ticker == peer,
                        Financials.period_type == "annual")
                .order_by(desc(Financials.period_end))
                .first()
            )
            if fin and fin.roe is not None:
                r = float(fin.roe)
                # Normalize: some rows store %, some decimals
                if abs(r) > 1.5:
                    r = r / 100.0
                if 0 < r < 1.0:
                    roe_values.append(r)

        if len(pb_values) < 2 and len(pe_values) < 2:
            return None

        out = {}
        if pb_values:
            out["median_pb"] = statistics.median(pb_values)
        if pe_values:
            out["median_pe"] = statistics.median(pe_values)
        if roe_values:
            out["median_roe"] = statistics.median(roe_values)
        out["n_pb"] = len(pb_values)
        out["n_pe"] = len(pe_values)
        out["n_roe"] = len(roe_values)
        return out
    except Exception as exc:
        logger.warning("peer_medians DB query failed for %s: %s", group_key, exc)
        return None
    finally:
        try:
            db.close()
        except Exception:
            pass


def get_peer_medians(group_key: str) -> dict:
    """
    Return peer medians for a group: {median_pb, median_pe, median_roe}.
    Cached in memory for 1h. Falls back to hardcoded values if DB empty.
    """
    now = _time.time()
    cached = _PEER_CACHE.get(group_key)
    if cached and (now - cached[0]) < _PEER_CACHE_TTL:
        return cached[1]

    medians = _fetch_peer_medians_from_db(group_key) or {}

    # Fill gaps from fallbacks
    fb_pb, fb_roe = _FALLBACK_PB.get(group_key, (2.0, 0.15))
    medians.setdefault("median_pb", fb_pb)
    medians.setdefault("median_roe", fb_roe)
    if group_key in _FALLBACK_PE:
        fb_pe, _ = _FALLBACK_PE[group_key]
        medians.setdefault("median_pe", fb_pe)

    _PEER_CACHE[group_key] = (now, medians)
    return medians


def _extract_bvps(company_info: dict, financials: dict) -> Optional[float]:
    """Derive book-value-per-share from whatever the caller has."""
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


def _extract_eps(company_info: dict, financials: dict) -> Optional[float]:
    for k in ("diluted_eps", "eps_diluted", "trailingEps", "eps", "fh_eps_ttm"):
        v = financials.get(k) or company_info.get(k)
        if v and v > 0:
            return float(v)
    # Derive from PAT / shares
    pat = financials.get("pat") or financials.get("latest_pat")
    shares = company_info.get("shares") or financials.get("shares")
    if pat and pat > 0 and shares and shares > 0:
        return float(pat) / float(shares)
    return None


def _extract_roe(company_info: dict, financials: dict) -> Optional[float]:
    """Return ROE as a decimal (0.18 for 18%)."""
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


def _compute_pbv_path(
    ticker: str,
    price: float,
    bvps: float,
    roe: Optional[float],
    medians: dict,
) -> Optional[dict]:
    median_pb = medians.get("median_pb")
    median_roe = medians.get("median_roe")
    if not median_pb or median_pb <= 0:
        return None

    # ROE adjustment: fair P/BV scales with ROE relative to peer median.
    # Cap the adjustment to [0.85, 1.4] so a single-year ROE blip cannot
    # flip the verdict wildly.
    #
    # BUG FIX (2026-04-24, revised v54->v55): floor was 0.7, then
    # bumped to 0.85. Investigation revealed HDFCBANK total_equity
    # is stored as 862k Cr (inflated ~50% vs real ~570k) — likely
    # because yfinance includes minority-interest / Tier-1 perpetual
    # bonds in "stockholders equity". This halves the computed ROE
    # (67k / 862k = 7.8% vs real 11-12%). The floor=0.85 still
    # produced MoS=-30% because the ROE/median_roe ratio was
    # halved by data, not by business weakness.
    #
    # Raising floor to 0.95 effectively neutralises the ROE
    # adjustment when data confidence is low — the 5% max penalty
    # is now a soft signal, not a verdict-flipping one. Better
    # long-term fix: correct the equity data source for banks.
    # See docs/audit/HEX_AXIS_SOURCE_MAP.md for the pending
    # bank-equity investigation.
    if roe and median_roe and median_roe > 0:
        adj = roe / median_roe
        adj = max(0.95, min(1.4, adj))
    else:
        adj = 1.0

    fair_pb = median_pb * adj

    # ── Top private banks COE bump (P1 launch-aftermath, 2026-04-30) ──
    # HDFCBANK / ICICIBANK / KOTAKBANK / AXISBANK have cost of equity
    # ~10.5-11.5% (mature deposit franchise) vs generic 12.5% used in
    # the peer-median P/BV. Lower COE → higher justified P/BV via
    # Gordon: P/B = (ROE - g) / (COE - g). A 150bps COE compression
    # for top private banks lifts justified P/BV ≈ 15%, which we
    # apply directly here. PSU banks deliberately not bumped (higher
    # asset-quality + governance risk → COE stays ~12.5%).
    try:
        from backend.services.analysis.constants import (
            is_top_private_bank,
            TOP_PRIVATE_BANK_PB_BUMP,
        )
        if is_top_private_bank(ticker):
            fair_pb = fair_pb * TOP_PRIVATE_BANK_PB_BUMP
            logger.info(
                "TOP_PRIVATE_BANK_PB_BUMP applied: %s fair_pb x %.3f",
                ticker, TOP_PRIVATE_BANK_PB_BUMP,
            )
    except Exception as _coe_exc:  # pragma: no cover — defensive
        logger.debug("top-private-bank P/BV bump skipped %s: %s", ticker, _coe_exc)
    base = round(bvps * fair_pb, 2)
    # PR-BANKSC-2: bear/bull must scale off the SAME fair_pb that base
    # uses, otherwise when `adj` hits the 0.7/1.4 clamp, base lands
    # exactly at the bear (or bull) mark and the scenarios collapse to
    # bear=base. Concrete repro: HDFCBANK with adj=0.7 produced
    # base = bvps × median_pb × 0.7, identical to the (wrong)
    # bear = bvps × median_pb × 0.7. Now bear/bull are always proper
    # ±30% of the actual base.
    bear = round(bvps * fair_pb * 0.7, 2)
    bull = round(bvps * fair_pb * 1.3, 2)

    mos_pct = ((base - price) / price * 100.0) if price > 0 else 0.0

    # Confidence: more peers with real data = higher confidence.
    n_pb = medians.get("n_pb", 0) or 0
    n_roe = medians.get("n_roe", 0) or 0
    conf = 55 + min(25, n_pb * 5) + (10 if roe is not None else 0) + (5 if n_roe >= 2 else 0)
    conf = max(40, min(90, conf))

    return {
        "fair_value": base,
        "margin_of_safety": round(mos_pct, 1),
        "verdict": _verdict_from_mos(mos_pct),
        "bear_case": bear,
        "base_case": base,
        "bull_case": bull,
        "method": "p_bv_peer",
        "confidence_score": conf,
        "_meta": {
            "peer_median_pb": round(median_pb, 2),
            "roe_adjustment": round(adj, 2),
            "fair_pb": round(fair_pb, 2),
            "bvps": round(bvps, 2),
        },
    }


def _compute_pe_path(
    ticker: str,
    price: float,
    eps: float,
    medians: dict,
) -> Optional[dict]:
    median_pe = medians.get("median_pe")
    if not median_pe or median_pe <= 0:
        return None

    base = round(eps * median_pe, 2)
    bear = round(eps * median_pe * 0.7, 2)
    bull = round(eps * median_pe * 1.3, 2)

    mos_pct = ((base - price) / price * 100.0) if price > 0 else 0.0

    n_pe = medians.get("n_pe", 0) or 0
    conf = 50 + min(25, n_pe * 5)
    conf = max(40, min(85, conf))

    return {
        "fair_value": base,
        "margin_of_safety": round(mos_pct, 1),
        "verdict": _verdict_from_mos(mos_pct),
        "bear_case": bear,
        "base_case": base,
        "bull_case": bull,
        "method": "p_e_peer",
        "confidence_score": conf,
        "_meta": {
            "peer_median_pe": round(median_pe, 2),
            "eps": round(eps, 2),
        },
    }


def compute_financial_fair_value(
    ticker: str,
    company_info: dict,
    financials: dict,
    shareholding: Optional[dict] = None,
) -> Optional[dict]:
    """
    Compute a peer-based fair value for a financial company.

    Returns a dict compatible with ValuationOutput fields, or None if
    data is insufficient (caller keeps its existing fallback).

    Dict shape:
      fair_value, margin_of_safety (percent), verdict,
      bear_case, base_case, bull_case, method, confidence_score
    """
    group = get_peer_group(ticker)
    if group is None:
        return None

    price = company_info.get("current_price") or company_info.get("price") or 0
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = 0.0
    if price <= 0:
        return None

    medians = get_peer_medians(group)
    method = _GROUP_METHOD.get(group, "p_bv_peer")
    roe = _extract_roe(company_info, financials)

    # Try P/E first for growth NBFCs / AMCs
    if method == "p_e_peer":
        eps = _extract_eps(company_info, financials)
        if eps and eps > 0:
            result = _compute_pe_path(ticker, price, eps, medians)
            if result:
                return result
        # Fall through to P/BV as backup

    # P/BV path (default for banks, govt NBFCs, insurers, HFCs)
    bvps = _extract_bvps(company_info, financials)
    if bvps and bvps > 0:
        result = _compute_pbv_path(ticker, price, bvps, roe, medians)
        if result:
            return result

    # P/E fallback if P/BV unavailable
    eps = _extract_eps(company_info, financials)
    if eps and eps > 0 and medians.get("median_pe"):
        result = _compute_pe_path(ticker, price, eps, medians)
        if result:
            return result

    return None
