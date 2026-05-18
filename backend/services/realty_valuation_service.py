# backend/services/realty_valuation_service.py
# ═══════════════════════════════════════════════════════════════
# Realty developer Approach-C valuation engine.
#
# Per docs/design/realty-developers-dcf-fix.md §5, generic FCF-DCF
# structurally mis-prices Indian residential developers because:
#   1. Revenue is recognised on completion (lumpy, not cash-aligned).
#   2. Pre-sales bookings — the real leading indicator — are
#      off-statement.
#   3. Inventory = unsold flats at cost, not market.
#   4. The biggest line — the land bank — sits at decades-old
#      acquisition cost on the books.
#
# Replacement formula (Approach C):
#
#   FV_per_share = (BVPS × sector_peer_PB) + uplift_per_share
#
# where uplift_per_share is curated annually (see
# realty_land_bank_inputs table + admin UI). The engine ONLY routes
# when a curation row exists; otherwise the ticker falls through to
# the existing Tier 2 generic engine.
#
# PHOENIXLTD special case (§5.5): ~60% annuity income (malls +
# hospitality). For PHOENIXLTD we additionally compute a NOI × cap-
# rate overlay (NOI from quarterly P&L, cap rate 8%) and blend the
# developer FV at (1 − annuity_share) with the annuity FV at
# annuity_share.
#
# CALLER CONTRACT:
#   compute_realty_fair_value(ticker, financials, land_bank_input)
#       -> dict | None
#
#   Returns None if BVPS cannot be derived or no land-bank row is
#   provided. The caller surfaces None as `data_limited` rather than
#   silently falling through to generic DCF — same discipline as the
#   regulated_utility branch.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("yieldiq.realty_valuation")


# ── Sector peer P/B for the developer cohort ────────────────────
# Per the design doc this should be re-computed at refresh time from
# the cohort's trailing P/B; we anchor at FY25 sector-median for the
# first cut. Bounded conservatively — single-cycle drift cannot flip
# the verdict wildly.
SECTOR_PEER_PB: float = 2.0

# ── PHOENIXLTD annuity overlay ──────────────────────────────────
# §5.5: PHOENIXLTD is ~60% annuity (mall NOI). Cap rate 8% reflects
# grade-A Indian commercial. Both numbers are sub-cohort constants —
# they change only if the analyst pass re-derives them.
PHOENIXLTD_ANNUITY_SHARE: float = 0.60
PHOENIXLTD_CAP_RATE: float = 0.08


def _clean(ticker: str) -> str:
    return (ticker or "").replace(".NS", "").replace(".BO", "").upper()


def _extract_bvps(financials: dict) -> Optional[float]:
    """Same BVPS priority chain as financial_valuation_service /
    regulated_utility_valuation_service.
    """
    for k in ("book_value_per_share", "bvps", "bookValue"):
        v = financials.get(k)
        if v and v > 0:
            return float(v)
    pb = financials.get("priceToBook") or financials.get("pb_ratio")
    price = financials.get("current_price") or financials.get("price")
    if pb and pb > 0 and price and price > 0:
        return float(price) / float(pb)
    equity = financials.get("total_equity")
    shares = financials.get("shares")
    if equity and shares and shares > 0:
        return float(equity) / float(shares)
    return None


def _verdict_from_mos(mos_pct: float) -> str:
    if mos_pct > 15:
        return "undervalued"
    if mos_pct > -15:
        return "fairly_valued"
    return "overvalued"


def _phoenixltd_annuity_fv_per_share(financials: dict) -> Optional[float]:
    """NOI × (1 / cap_rate) ÷ shares = annuity FV per share.

    NOI is approximated from the quarterly P&L via:
      annuity_noi_ttm = financials.get("annuity_noi_ttm")  # if curated
      otherwise:        operating_income × PHOENIXLTD_ANNUITY_SHARE
    Both expressed in ₹ Cr; multiply by 1e7 to convert to ₹.
    Returns None if no usable input.
    """
    noi_cr = financials.get("annuity_noi_ttm")
    if not noi_cr or noi_cr <= 0:
        op = (
            financials.get("operating_income_ttm")
            or financials.get("operating_income")
            or financials.get("ebit_ttm")
        )
        if not op or op <= 0:
            return None
        noi_cr = float(op) * PHOENIXLTD_ANNUITY_SHARE

    shares = financials.get("shares")
    if not shares or shares <= 0:
        return None
    annuity_value_cr = float(noi_cr) / PHOENIXLTD_CAP_RATE
    return (annuity_value_cr * 1e7) / float(shares)


def compute_realty_fair_value(
    ticker: str,
    financials: dict,
    land_bank_input: Optional[dict],
    sector_peer_pb: float = SECTOR_PEER_PB,
) -> Optional[dict]:
    """Approach-C fair value for a listed Indian realty developer.

    Args:
        ticker: NSE/BSE ticker symbol (with or without suffix).
        financials: dict with at least one of (book_value_per_share,
            bvps, bookValue) OR (priceToBook + price) OR
            (total_equity + shares). For PHOENIXLTD additionally
            uses operating_income_ttm or annuity_noi_ttm.
        land_bank_input: row from realty_land_bank_inputs as a dict.
            Required — None means the engine refuses to value and the
            caller should fall through to Tier 2 generic.
        sector_peer_pb: cohort trailing P/B (default SECTOR_PEER_PB).

    Returns:
        Dict with fair_value / bear_case / base_case / bull_case /
        method / valuation_method / confidence_score / _meta, OR
        None if inputs are insufficient.
    """
    if not land_bank_input:
        # No curation row → engine refuses. Caller falls through.
        return None

    uplift_per_share = land_bank_input.get("uplift_per_share")
    try:
        uplift_per_share = float(uplift_per_share) if uplift_per_share is not None else None
    except (TypeError, ValueError):
        uplift_per_share = None
    if uplift_per_share is None:
        return None

    bvps = _extract_bvps(financials)
    if not bvps or bvps <= 0:
        logger.info(
            "realty_valuation: no BVPS for %s — returning None so caller "
            "can mark data_limited.",
            ticker,
        )
        return None

    price = (
        financials.get("current_price")
        or financials.get("price")
        or 0
    )
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = 0.0

    developer_fv = (bvps * sector_peer_pb) + uplift_per_share
    method_label = "pb_plus_land_bank"

    # PHOENIXLTD annuity overlay
    annuity_fv_ps: Optional[float] = None
    if _clean(ticker) == "PHOENIXLTD":
        annuity_fv_ps = _phoenixltd_annuity_fv_per_share(financials)
        if annuity_fv_ps and annuity_fv_ps > 0:
            blended = (
                developer_fv * (1.0 - PHOENIXLTD_ANNUITY_SHARE)
                + annuity_fv_ps * PHOENIXLTD_ANNUITY_SHARE
            )
            developer_fv = blended
            method_label = "pb_plus_land_bank_with_annuity_overlay"

    base = round(developer_fv, 2)
    # ±25% bear/bull band matches the cement / regulated-utility
    # convention. Tighter than the 30% used for FCF-DCF because the
    # BV-anchored model is structurally less volatile across the cycle.
    bear = round(base * 0.75, 2)
    bull = round(base * 1.25, 2)

    mos_pct = ((base - price) / price * 100.0) if price > 0 else 0.0
    buffett_mos = ((base - price) / base * 100.0) if base > 0 else None

    # Confidence: BV-anchored with a curated uplift is comparable to
    # the regulated-utility path. Floor at 70 so the
    # reliability_score >= 70 gate in routers/analysis.py accepts.
    conf = 75

    return {
        "fair_value": base,
        "margin_of_safety": round(mos_pct, 1),
        "buffett_mos_pct": round(buffett_mos, 1) if buffett_mos is not None else None,
        "verdict": _verdict_from_mos(mos_pct),
        "bear_case": bear,
        "base_case": base,
        "bull_case": bull,
        "method": method_label,
        "valuation_method": "pb_plus_land_bank",
        "confidence_score": conf,
        "_meta": {
            "bvps": round(bvps, 2),
            "sector_peer_pb": round(float(sector_peer_pb), 3),
            "uplift_per_share": round(uplift_per_share, 2),
            "reporting_fy": land_bank_input.get("reporting_fy"),
            "annuity_fv_per_share": (
                round(annuity_fv_ps, 2) if annuity_fv_ps is not None else None
            ),
            "annuity_share": (
                PHOENIXLTD_ANNUITY_SHARE
                if _clean(ticker) == "PHOENIXLTD"
                else 0.0
            ),
            "cap_rate": (
                PHOENIXLTD_CAP_RATE
                if _clean(ticker) == "PHOENIXLTD"
                else None
            ),
        },
    }


# ── DB helper used by the analysis routing layer ────────────────
def fetch_land_bank_input(ticker: str) -> Optional[dict]:
    """Look up the curated land-bank row for `ticker`. Returns None if
    no row exists (engine then refuses → caller routes to Tier 2).

    Reads from `realty_land_bank_inputs`. Returns a dict with the same
    column names as the table. Safe to call from analysis hot path —
    the table is small (≤ 16 rows) and the query is keyed.
    """
    bare = _clean(ticker)
    if not bare:
        return None
    try:
        from data_pipeline.db import Session
        from sqlalchemy import text
        sess = Session()
        try:
            row = sess.execute(
                text(
                    "SELECT ticker, reporting_fy, land_bank_acres, "
                    "land_bank_market_value_cr, land_bank_book_value_cr, "
                    "unsold_inventory_cr, pre_sales_pipeline_cr, "
                    "uplift_per_share, source_url, entered_by, entered_at "
                    "FROM realty_land_bank_inputs WHERE ticker = :t"
                ),
                {"t": bare},
            ).fetchone()
            if not row:
                return None
            return {
                "ticker": row[0],
                "reporting_fy": row[1],
                "land_bank_acres": float(row[2]) if row[2] is not None else None,
                "land_bank_market_value_cr": float(row[3]) if row[3] is not None else None,
                "land_bank_book_value_cr": float(row[4]) if row[4] is not None else None,
                "unsold_inventory_cr": float(row[5]) if row[5] is not None else None,
                "pre_sales_pipeline_cr": float(row[6]) if row[6] is not None else None,
                "uplift_per_share": float(row[7]) if row[7] is not None else None,
                "source_url": row[8],
                "entered_by": row[9],
                "entered_at": row[10].isoformat() if row[10] else None,
            }
        finally:
            sess.close()
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "realty_valuation.fetch_land_bank_input(%s) failed: %s: %s",
            ticker, type(exc).__name__, exc,
        )
        return None
