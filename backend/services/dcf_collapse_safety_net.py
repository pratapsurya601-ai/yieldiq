"""
DCF-collapse safety net.

═════════════════════════════════════════════════════════════════════
Why this exists
─────────────────────────────────────────────────────────────────────
Day-1 benchmark reconciliation (2026-05-19) surfaced 338 outliers —
301 "we're too low" + 37 "we're too high". The worst "under" cases
showed generic-DCF fair values of ₹0.77, ₹15.60, ₹19.25 on tickers
where the live price is ₹305, ₹245, ₹304. These are *broken-DCF*
results — a tiny negative or near-zero trailing FCF, run through the
generic engine, collapses the terminal value to near-zero. Shipping
"Notably Undervalued at ₹0.77" when CMP is ₹405 is dishonest.

This module is a small, conservative safety net that runs AFTER
generic DCF and AFTER all sector overlays / peer-cap. When the
resulting FV is wildly out of range vs price AND the ticker is on
the generic-DCF path (not a dedicated sector engine, not a cyclical
trough anchor), we attempt a Tier 2 cohort-multiple fallback. If
Tier 2 also can't compute (loss-making EPS, missing peers, etc.) the
caller surfaces the analysis as `data_limited` rather than emitting
the broken FV.

Design discipline
─────────────────
1. **Conservative over aggressive.** Better to NOT fire than to
   over-fire and disturb correct values. The fallback only triggers
   when iv/price is outside [0.1, 5.0] — a 10× compression or 5×
   inflation. Normal DCF dispersion lives comfortably inside that
   band.

2. **Engine-respecting.** Tickers routed through a dedicated sector
   engine (rate_base for utilities, pb_ratio for banks, REIT NAV,
   ETF NAV, holding-company SOTP, insurance appraisal, realty
   PB+land-bank) are NEVER touched. Those engines are authoritative
   for their cohorts — the safety net would silently second-guess
   them.

3. **Cyclical-trough aware.** Tickers in CYCLICAL_SECTORS / cyclical
   trough anchor sectors legitimately produce FV << price at the
   bottom of the cycle (steel, oil & gas, metals). The existing
   cyclical-trough anchor (service.py L1746-) handles those — this
   safety net stays out of the way.

4. **Returns None to mean "I can't help".** Caller surfaces None as
   `data_limited` with a caveat explaining manual review is needed.

Wired into:
  backend/services/analysis/service.py — see `dcf_collapse_safety_net`
  call site after the peer-cap block.

CACHE_VERSION bump:
  113 → 115 (114 reserved for in-flight confidence-verdict-gating PR).
  Cached payloads with broken sub-rupee FVs need recompute; the
  verdict / fair_value can flip on this PR.

Sector-scope: * (universal — applies to every generic-DCF ticker).
═════════════════════════════════════════════════════════════════════
"""
from __future__ import annotations

import logging
from typing import Optional, Tuple

logger = logging.getLogger("yieldiq.dcf_collapse_safety_net")


# ── Heuristic band: what counts as "unreasonable" ───────────────────
# An FV/price ratio inside [LO, HI] is considered plausible and the
# safety net stays out of the way. Anything outside indicates the
# generic DCF either collapsed (ratio < LO) or exploded (ratio > HI).
# These bounds are deliberately wide — peer-cap already trims
# 1.5×-overshoots, and the trough anchor already pins cyclical lows.
# We only want to catch the residual broken-math cases.
COLLAPSED_RATIO_LO: float = 0.1   # FV < 10% of price  → collapsed
INFLATED_RATIO_HI: float = 5.0    # FV > 500% of price → exploded


# ── Sector engines that own their own valuation math ─────────────────
# When `sector_engine_used` is one of these, the displayed FV is
# already from a dedicated engine, NOT from generic DCF. The safety
# net must not interfere — the engine is authoritative for its cohort.
# These string labels match the `valuation_method` / `valuation_model`
# enums emitted by backend/services/analysis/service.py.
SECTOR_ENGINE_AUTHORITATIVE: frozenset[str] = frozenset({
    "rate_base",                       # regulated utilities (POWERGRID …)
    "appraisal_value",                 # insurance (SBILIFE / HDFCLIFE …)
    "pb_plus_land_bank",               # realty developers (DLF / GODREJPROP …)
    "reit_nav_dpu_required",           # REITs (EMBASSY / MINDSPACE …)
    "etf_nav_based",                   # ETFs
    "holding_company_sotp_required",   # holdcos (BAJAJHLDNG / TATAINVEST …)
    "pb_ratio",                        # banks / NBFCs (HDFCBANK / SBIN …)
    "pb_residual_income",              # bank PB residual income variant
    "sector_relative_recent_ipo",      # recent-IPO sector-relative path
})


# ── Sectors where DCF<<price is a legitimate trough signal ──────────
# At the bottom of a steel / oil cycle, the trailing-FCF DCF can land
# at 0.4-0.7× CMP and be telling the truth about where free cash
# flow currently is. The cyclical-trough anchor (service.py L1746-)
# handles these by pinning bear/base/bull to 0.85/0.95/1.10× price.
# The safety net should NOT second-guess that anchor — listing the
# affected sectors here as a belt-and-braces veto.
#
# Note: we intentionally only include the sectors that have a
# documented trough-anchor path. Cement (despite being capex-heavy)
# was REMOVED from CYCLICAL_SECTORS on 2026-04-24 — cement broken
# DCFs (INDIACEM at ₹0.77) are exactly the cases this safety net
# is meant to catch, NOT exempt.
CYCLICAL_SECTORS_TROUGH_ALLOWED: frozenset[str] = frozenset({
    "metals & mining",
    "oil & gas",
    "steel",
})


def _norm(s: Optional[str]) -> str:
    return (s or "").strip().lower()


def is_fv_unreasonable(
    current_fv: Optional[float], current_price: Optional[float],
) -> bool:
    """Return True if current_fv is unreasonable vs current_price.

    "Unreasonable" = the FV/price ratio sits outside [0.1, 5.0]. That
    catches collapsed-DCF cases (sub-rupee FV on ₹400 stocks) and
    blown-up cases (₹2000 FV on ₹400 stocks).

    A None / zero / negative FV or price counts as "we can't even
    evaluate" — return False so the caller's None-handling path runs
    instead of attempting fallback on garbage inputs.
    """
    try:
        fv = float(current_fv) if current_fv is not None else 0.0
        px = float(current_price) if current_price is not None else 0.0
    except (TypeError, ValueError):
        return False
    if fv <= 0 or px <= 0:
        return False
    ratio = fv / px
    return ratio < COLLAPSED_RATIO_LO or ratio > INFLATED_RATIO_HI


def attempt_tier2_fallback(
    ticker: str,
    current_fv: Optional[float],
    current_price: Optional[float],
    sector: Optional[str],
    sector_engine_used: Optional[str],
    financials: Optional[dict] = None,
    peers: Optional[list[dict]] = None,
) -> Optional[Tuple[float, str]]:
    """When DCF FV is unreasonable vs price, try Tier 2 cohort.

    Returns:
      (new_fv, "tier2_fallback_after_dcf_collapse") on success.
      None when the safety net does NOT engage OR when Tier 2 also
        cannot produce a fair value. Caller must treat None as "set
        data_limited verdict" UNLESS `is_fv_unreasonable(...)` was
        False to begin with — in that case the existing FV is fine.

    Args:
      ticker             : bare or .NS/.BO ticker symbol.
      current_fv         : the FV produced by generic DCF (post peer-cap).
      current_price      : the snapshot CMP used to compute MoS.
      sector             : resolved sector string.
      sector_engine_used : the engine label that produced current_fv —
                           one of valuation_method values. If this
                           identifies a dedicated sector engine the
                           safety net stays out of the way.
      financials         : OPTIONAL dict with EPS / ROCE / Piotroski /
                           market_cap_cr / etc. Forwarded to Tier 2.
      peers              : OPTIONAL list of PeerRecord dicts for the
                           Tier 2 cohort. When None or empty Tier 2
                           cannot fire and we return None (caller →
                           data_limited).
    """
    if not ticker:
        return None

    # Guard 1: the FV must actually be unreasonable.
    if not is_fv_unreasonable(current_fv, current_price):
        return None

    # Guard 2: never override a dedicated sector engine — it owns its
    # cohort's valuation math. The safety net is for the generic-DCF
    # path only.
    if sector_engine_used and sector_engine_used in SECTOR_ENGINE_AUTHORITATIVE:
        logger.info(
            "dcf_collapse_safety_net: %s — sector_engine=%s is authoritative, "
            "leaving FV ₹%s as-is (price ₹%s)",
            ticker, sector_engine_used, current_fv, current_price,
        )
        return None

    # Guard 3: cyclical sectors at trough may legitimately have FV<<price.
    # The trough anchor (service.py L1746-) is the correct mechanism for
    # those; the safety net should never override it.
    if _norm(sector) in CYCLICAL_SECTORS_TROUGH_ALLOWED:
        logger.info(
            "dcf_collapse_safety_net: %s — sector=%s in trough-allowed list, "
            "trough anchor owns this case",
            ticker, sector,
        )
        return None

    # Try the Tier 2 cohort engine. Import is local so this module
    # stays import-safe even if tier2_cohort_valuation_service has a
    # downstream import problem on a given environment.
    try:
        from backend.services.tier2_cohort_valuation_service import (
            compute_tier2_fair_value,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "dcf_collapse_safety_net: %s — tier2 import failed: %s",
            ticker, exc,
        )
        return None

    fin = dict(financials) if isinstance(financials, dict) else {}
    # Make sure Tier 2 has the current_price for MoS computation.
    if "current_price" not in fin and current_price:
        try:
            fin["current_price"] = float(current_price)
        except (TypeError, ValueError):
            pass

    peer_list = list(peers) if peers else []

    # 2026-05-19 hardening: if the caller passed an empty / minimal
    # peer list, attempt a direct lookup from the tier2_peer_metrics
    # table using the canonical DIRECT_PEERS sector mapping. The
    # original implementation depended on peer_cap_service which
    # returns empty for many sectors (cement, retail, etc.), causing
    # the safety net to fail closed even when the cement cohort DOES
    # exist in tier2_peer_metrics. This adds a second source of truth.
    if len(peer_list) < 5:
        try:
            from backend.services.tier2_peer_lookup import (
                fetch_peers_from_metrics_table,
            )
            _fetched = fetch_peers_from_metrics_table(ticker, sector)
            if _fetched and len(_fetched) >= 5:
                peer_list = _fetched
                logger.info(
                    "dcf_collapse_safety_net: %s — peer_list bootstrapped "
                    "from tier2_peer_metrics (%d peers)",
                    ticker, len(_fetched),
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug(
                "dcf_collapse_safety_net: tier2_peer_lookup unavailable "
                "for %s: %s — proceeding with whatever peers caller gave",
                ticker, exc,
            )

    try:
        result = compute_tier2_fair_value(
            ticker=ticker, sector=sector, financials=fin, peers=peer_list,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning(
            "dcf_collapse_safety_net: %s — tier2 raised: %s",
            ticker, exc,
        )
        return None

    if not result:
        logger.info(
            "dcf_collapse_safety_net: %s — tier2 returned None "
            "(loss-making EPS / no peers / etc.) → caller should "
            "mark data_limited",
            ticker,
        )
        return None

    fv = result.get("fair_value")
    try:
        fv_f = float(fv) if fv is not None else 0.0
    except (TypeError, ValueError):
        fv_f = 0.0
    if fv_f <= 0:
        return None

    # Sanity: if Tier 2 ALSO produced an unreasonable FV, refuse it.
    # Two failing engines in a row → honest answer is data_limited.
    if is_fv_unreasonable(fv_f, current_price):
        logger.info(
            "dcf_collapse_safety_net: %s — tier2 FV ₹%.2f still unreasonable "
            "vs price ₹%s; declining fallback",
            ticker, fv_f, current_price,
        )
        return None

    logger.info(
        "dcf_collapse_safety_net: %s — DCF collapse caught "
        "(was ₹%s vs price ₹%s); tier2 fallback FV ₹%.2f",
        ticker, current_fv, current_price, fv_f,
    )
    return fv_f, "tier2_fallback_after_dcf_collapse"


__all__ = [
    "COLLAPSED_RATIO_LO",
    "INFLATED_RATIO_HI",
    "SECTOR_ENGINE_AUTHORITATIVE",
    "CYCLICAL_SECTORS_TROUGH_ALLOWED",
    "is_fv_unreasonable",
    "attempt_tier2_fallback",
]
