# backend/services/tier2_cohort_valuation_service.py
# ═══════════════════════════════════════════════════════════════
# Tier 2 — Quality-weighted sector cohort multiples
# (Layer B Week 1 PR 1; see
# docs/design/valuation-architecture-simplification.md §2.2)
#
# Why this exists:
#   Layer B replaces the ~6 partial sector engines (Pharma R&D-adj
#   FCF, FMCG brand-premium overlay, Capital Goods 7y WC-FCF, ...)
#   with one cohort engine. The structural insight is that custom
#   per-sector DCFs are anchored on the same trailing-FCF series
#   that breaks generic DCF — smoothing or extending the window
#   only re-weights noise. The signal lives in "what comparable,
#   similarly-profitable peers trade at."
#
# The MANKIND fix:
#   Today's sector-relative mean drags franchise pharma (MANKIND,
#   ROCE 27%, Piotroski 8, mcap ₹68k Cr) down to the generic-
#   exporter median. Quality bucketing pins MANKIND to the
#   **Premium pharma** cohort (DIVISLAB / SUNPHARMA-tier moats),
#   not against LAURUSLABS / GRANULES / AUROBINDO-tier generics.
#
# The math (see design doc §2.2):
#
#   FV_per_share = peer_bucket_PE_median × ticker_EPS × adjustment
#
#   Quality buckets within each sector:
#     Premium : ROCE > 25%   AND  Piotroski >= 7  AND  top-tertile mcap
#     Core    : ROCE 15-25%  OR   Piotroski 5-6
#     Tail    : everything else
#
# CALLER CONTRACT:
#   compute_tier2_fair_value(ticker, sector, financials, peers) -> dict | None
#   Returns None when the cohort cannot satisfy the sanity guards
#   (bucket size < 5, missing ticker EPS, peer median out of band).
#   Caller surfaces None as data_limited.
#
#   Dict shape mirrors compute_financial_fair_value /
#   compute_regulated_utility_fair_value so the service.py wiring
#   can reuse the same _val_result-style plumbing.
#
# Feature flag:
#   The routing branch in backend/services/analysis/service.py is
#   gated on env var TIER2_ENABLED (default False). This module is
#   import-safe regardless — callers can compute Tier 2 FV without
#   the flag for diagnostics / canary runs.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import os
from statistics import median
from typing import Any, Iterable, Optional

logger = logging.getLogger("yieldiq.tier2_cohort")


# ── Feature flag ────────────────────────────────────────────────
def tier2_enabled() -> bool:
    """Read TIER2_ENABLED env var.  Default False (no breaking change)."""
    raw = (os.environ.get("TIER2_ENABLED") or "").strip().lower()
    return raw in {"1", "true", "yes", "on"}


# ── Skip-path sectors (never route through Tier 2) ──────────────
# These have dedicated sector engines or a skip path. Tier 2 is the
# default for "everything else" only — banks/utilities/REITs/ETFs/
# holdcos keep their existing engines per the routing tree in §2.4.
TIER2_SKIP_SECTORS: set[str] = {
    "banking", "nbfc", "insurance", "financial services", "financial",
    "regulated utility", "regulated utilities",
    "etf", "reit", "real estate investment trust",
    "holding company", "holdcos",
}


# ── Quality-bucket thresholds (design doc §2.2 table) ───────────
# ROCE in PERCENTAGE form (27.0 means 27%). market_cap in CRORE.
PREMIUM_ROCE = 25.0
PREMIUM_PIOTROSKI = 7
PREMIUM_MIN_MCAP_CR = 50_000.0    # "top tertile of sector"

CORE_ROCE_LOW = 15.0
CORE_ROCE_HIGH = 25.0
CORE_PIOTROSKI_LOW = 5
CORE_PIOTROSKI_HIGH = 6

# Minimum cohort size in a single bucket for Tier 2 to fire.
# Below this we return None (caller surfaces as data_limited).
MIN_BUCKET_SIZE = 5

# Sanity bands on bucket P/E. Anything outside is data noise.
MIN_PEER_PE = 5.0
MAX_PEER_PE = 80.0

# Hard FV cap to prevent SCHAEFFLER-style 280% over-shoots when
# peer-median × ticker-EPS is multiplied through a one-off peak EPS.
MAX_FV_TO_BVPS_RATIO = 8.0  # FV ≤ 8× BVPS

# Confidence ceiling — Tier 2 is sector-relative; inherently less
# precise than a properly-anchored DCF. Caps at 75 per design doc.
TIER2_CONFIDENCE_CAP = 75


# ── Sectors that prefer EV/EBITDA over P/E ──────────────────────
# For capital-intensive / project businesses where reported EPS is
# distorted by D&A policy, EV/EBITDA is the more honest multiple.
# Pharma stays on P/E because the franchise multiples are P/E-anchored
# in street research.
EV_EBITDA_PREFERRED_SECTORS: set[str] = {
    "capital goods", "industrials", "cement",
    "engineering", "engineering & construction",
    "metals & mining", "steel",
}


# ── Public type alias (documentation only) ──────────────────────
# A peer record is a dict with whichever of the following fields the
# caller can provide. Missing fields = peer is skipped from that leg.
#
#   {
#     "ticker": str,
#     "pe":            Optional[float],   # trailing P/E
#     "ev_ebitda":     Optional[float],   # EV / EBITDA TTM
#     "roce":          Optional[float],   # in PERCENT (27.0 for 27%)
#     "piotroski":     Optional[int],     # 0-9 F-score
#     "market_cap_cr": Optional[float],   # market cap in CRORE
#   }
PeerRecord = dict[str, Any]


def _clean(ticker: str) -> str:
    return (ticker or "").replace(".NS", "").replace(".BO", "").upper()


def _norm_sector(sector: Optional[str]) -> str:
    return (sector or "").strip().lower()


# ── Quality bucketing ───────────────────────────────────────────
def _bucket_for(
    roce: Optional[float],
    piotroski: Optional[int],
    market_cap_cr: Optional[float],
) -> str:
    """Return 'premium' / 'core' / 'tail' for a ticker's quality bucket.

    Bucketing rules (refined 2026-05-19 v2 — Day 2 follow-up to PR #376/#378):

      Premium  : mcap >= 50,000 Cr  AND any of:
                   • ROCE IS NULL  AND  Piotroski >= 7      (banks carve-out)
                   • ROCE >= 25    AND  Piotroski >= 5
                   • ROCE >= 15    AND  Piotroski >= 7
      Core     : ROCE >= 15  OR  Piotroski >= 5
      Tail     : everything else

    Why this specific shape (vs. the simpler OR rule we tried first):

    1. Banks (HDFCBANK, ICICIBANK, INFY w/r/t its services BS quirks)
       structurally have NULL ROCE — there's no meaningful capital-
       employed denominator in book accounting. A simple "ROCE >= 25
       OR Piotroski >= 7" rule handled this correctly but also let
       low-quality peers in: BHEL passed on Piotroski 7 despite a
       crushed 2.7% ROCE; BAJAJ-AUTO passed on ROCE 32.5 despite a
       weak Piotroski 4. Premium is meant to be elite peers; one good
       axis paired with a clearly broken other axis isn't elite.

    2. The "both clear meaningful floors" framing eliminates that.
       The carve-out for NULL ROCE keeps banks in Premium where they
       belong (Piotroski 7+ on a large lender is a strong signal).

    3. Real-world impact from 2026-05-19 cohort: rule v1 produced 30
       Premium peers with 6 obvious junk inclusions (BHEL ROCE 2.7,
       AMBUJACEM ROCE 11.6, TECHM ROCE 12.2, BAJAJ-AUTO Piot 4, ABB
       Piot 4, BPCL Piot 3). Rule v2 produces ~24 Premium peers, all
       defensibly elite. The 6 demotees land in Core (still ROCE≥15
       or Piot≥5), which is the correct slot.

    Core remains permissive (open-ended high side on either axis) —
    we want the Core cohort large enough that bucket-widening rarely
    fires. Tail is the genuine bottom: low on both axes or all-NULL.

    Backwards-compat: every test case in the original
    test_bucket_for_premium_core_tail still passes — old positives
    remain positive, old negatives remain negative.
    """
    r = float(roce) if roce is not None else None
    p = int(piotroski) if piotroski is not None else None
    m = float(market_cap_cr) if market_cap_cr is not None else None

    # PREMIUM: large + both quality axes clear meaningful floors.
    if m is not None and m >= PREMIUM_MIN_MCAP_CR:
        # Banks/financials carve-out: NULL ROCE is structural, not bad.
        if r is None and p is not None and p >= PREMIUM_PIOTROSKI:
            return "premium"
        # High ROCE peer must have at least non-deteriorating Piotroski.
        if (r is not None and r >= PREMIUM_ROCE) and (
            p is not None and p >= CORE_PIOTROSKI_LOW
        ):
            return "premium"
        # High Piotroski peer must have at least decent ROCE.
        if (p is not None and p >= PREMIUM_PIOTROSKI) and (
            r is not None and r >= CORE_ROCE_LOW
        ):
            return "premium"

    # CORE: good on at least one quality axis (open-ended high side).
    # CORE_ROCE_HIGH and CORE_PIOTROSKI_HIGH retained as module-level
    # constants for back-compat with importers, but no longer used as
    # ceilings here — peers above them belong in Premium (gated by
    # mcap above) or fall here naturally if they're sub-Premium-mcap.
    if (r is not None and r >= CORE_ROCE_LOW) or (
        p is not None and p >= CORE_PIOTROSKI_LOW
    ):
        return "core"

    return "tail"


def _peers_in_bucket(
    peers: Iterable[PeerRecord], bucket: str,
) -> list[PeerRecord]:
    out: list[PeerRecord] = []
    for p in peers or []:
        b = _bucket_for(
            p.get("roce"), p.get("piotroski"), p.get("market_cap_cr"),
        )
        if b == bucket:
            out.append(p)
    return out


def _median_or_none(
    values: Iterable[Optional[float]], lo: float, hi: float,
) -> Optional[float]:
    cleaned = [
        float(v) for v in values
        if v is not None and lo <= float(v) <= hi
    ]
    if not cleaned:
        return None
    return float(median(cleaned))


def _verdict_from_mos(mos_pct: float) -> str:
    if mos_pct > 15:
        return "undervalued"
    if mos_pct > -15:
        return "fairly_valued"
    return "overvalued"


def _prefers_ev_ebitda(sector: Optional[str]) -> bool:
    return _norm_sector(sector) in EV_EBITDA_PREFERRED_SECTORS


def is_tier2_skip_sector(sector: Optional[str]) -> bool:
    """Return True if sector has its own engine / skip path and
    should bypass Tier 2 entirely (routed by sector-specific branches
    in service.py instead).
    """
    return _norm_sector(sector) in TIER2_SKIP_SECTORS


# ── Main entrypoint ────────────────────────────────────────────
def compute_tier2_fair_value(
    ticker: str,
    sector: Optional[str],
    financials: dict,
    peers: Iterable[PeerRecord],
) -> Optional[dict]:
    """Compute quality-bucketed sector-cohort fair value for `ticker`.

    Args:
      ticker     : bare or .NS/.BO-suffixed symbol.
      sector     : resolved sector string (e.g. "Pharma", "Capital Goods").
      financials : dict with at least
          eps          : TTM diluted EPS (₹/share)
          ebitda       : TTM EBITDA (₹ Cr or absolute — see below)
          shares       : shares outstanding (used for EV/EBITDA leg)
          roce         : ticker's ROCE in PERCENT
          piotroski    : ticker's Piotroski F-score
          market_cap_cr: ticker market cap in CRORE
          bvps         : optional — book-value per share for the FV cap
          net_debt_cr  : optional — net debt in CRORE (for EV/EBITDA leg)
          current_price: optional — used to compute MoS
      peers      : iterable of peer dicts (see PeerRecord above).

    Returns:
      dict with fields {fair_value, bear_case, base_case, bull_case,
                        margin_of_safety, buffett_mos_pct, verdict,
                        method, valuation_method, confidence_score,
                        _meta}
      OR None when the cohort cannot satisfy the sanity guards (caller
      surfaces None as data_limited).
    """
    if not ticker:
        return None
    if is_tier2_skip_sector(sector):
        logger.info(
            "tier2_cohort: skip-sector for %s (sector=%s) — routing back",
            ticker, sector,
        )
        return None

    eps = financials.get("eps")
    try:
        eps_f = float(eps) if eps is not None else None
    except (TypeError, ValueError):
        eps_f = None
    if eps_f is None or eps_f <= 0:
        # Loss-making or missing EPS → Tier 2 cannot fire. Caller
        # surfaces as data_limited (matches Tier 3 in design doc §2.3).
        return None

    bucket = _bucket_for(
        financials.get("roce"),
        financials.get("piotroski"),
        financials.get("market_cap_cr"),
    )

    bucket_peers = _peers_in_bucket(peers, bucket)
    bucket_widened = False
    if len(bucket_peers) < MIN_BUCKET_SIZE:
        # Per design doc §2.2 sanity guards: if bucket has < 5 peers,
        # widen one step (Premium → Premium+Core) before giving up.
        if bucket == "premium":
            bucket_peers = (
                _peers_in_bucket(peers, "premium")
                + _peers_in_bucket(peers, "core")
            )
            bucket_widened = True
        elif bucket == "tail":
            bucket_peers = (
                _peers_in_bucket(peers, "tail")
                + _peers_in_bucket(peers, "core")
            )
            bucket_widened = True
        # core never widens further — its neighbours are both
        # asymmetric. Cohorts that can't reach MIN_BUCKET_SIZE with
        # Premium∪Core OR Tail∪Core fall through.
        if len(bucket_peers) < MIN_BUCKET_SIZE:
            logger.info(
                "tier2_cohort: %s — bucket=%s peers<%d after widen, "
                "returning None (caller=data_limited)",
                _clean(ticker), bucket, MIN_BUCKET_SIZE,
            )
            return None

    use_ev_ebitda = _prefers_ev_ebitda(sector)
    method_label = "cohort_ev_ebitda" if use_ev_ebitda else "cohort_pe"

    peer_pe_median = _median_or_none(
        (p.get("pe") for p in bucket_peers),
        MIN_PEER_PE, MAX_PEER_PE,
    )
    peer_ev_ebitda_median = _median_or_none(
        (p.get("ev_ebitda") for p in bucket_peers),
        3.0, 50.0,
    )

    fv: Optional[float] = None
    leg_used: Optional[str] = None

    if use_ev_ebitda and peer_ev_ebitda_median is not None:
        ebitda = financials.get("ebitda")
        shares = financials.get("shares")
        net_debt = financials.get("net_debt_cr") or 0
        try:
            ebitda_f = float(ebitda) if ebitda is not None else None
            shares_f = float(shares) if shares is not None else None
            net_debt_f = float(net_debt)
        except (TypeError, ValueError):
            ebitda_f, shares_f, net_debt_f = None, None, 0.0
        if (
            ebitda_f is not None and ebitda_f > 0
            and shares_f is not None and shares_f > 0
        ):
            ev = peer_ev_ebitda_median * ebitda_f
            equity = ev - net_debt_f
            fv = max(0.0, equity / shares_f)
            leg_used = "ev_ebitda"

    if fv is None and peer_pe_median is not None:
        fv = peer_pe_median * eps_f
        leg_used = "pe"
        method_label = "cohort_pe"

    if fv is None or fv <= 0:
        logger.info(
            "tier2_cohort: %s — no usable peer multiple (bucket=%s, "
            "pe_median=%s, ev_ebitda_median=%s)",
            _clean(ticker), bucket, peer_pe_median, peer_ev_ebitda_median,
        )
        return None

    # FV-to-BVPS cap — prevents SCHAEFFLER-style over-shoots when a
    # peak-EPS year is multiplied by a peer multiple.
    bvps = financials.get("bvps")
    try:
        bvps_f = float(bvps) if bvps is not None else None
    except (TypeError, ValueError):
        bvps_f = None
    fv_capped = False
    if bvps_f is not None and bvps_f > 0:
        cap = MAX_FV_TO_BVPS_RATIO * bvps_f
        if fv > cap:
            logger.info(
                "tier2_cohort: %s — FV %.2f capped at %.2f (%.1f×BVPS)",
                _clean(ticker), fv, cap, MAX_FV_TO_BVPS_RATIO,
            )
            fv = cap
            fv_capped = True

    # Bear / bull = ±25% band. The cohort median is itself a noisy
    # estimator; wider bands risk masking the signal, tighter bands
    # over-claim precision. ±25% mirrors the regulated-utility band
    # used by regulated_utility_valuation_service.
    base = round(fv, 2)
    bear = round(fv * 0.75, 2)
    bull = round(fv * 1.25, 2)

    price = financials.get("current_price") or 0
    try:
        price = float(price)
    except (TypeError, ValueError):
        price = 0.0
    mos_pct = ((base - price) / price * 100.0) if price > 0 else 0.0
    buffett_mos = ((base - price) / base * 100.0) if base > 0 else None

    # Confidence:
    #   Base 70 for full-bucket Premium/Core/Tail hits.
    #   −10 if we had to widen the bucket (less precise cohort).
    #   −5  if FV had to be capped (signal that ticker is an outlier).
    #   Capped at TIER2_CONFIDENCE_CAP (75) regardless.
    conf = 70
    if not bucket_widened and bucket == "premium":
        # Premium cohort with enough native peers is the strongest
        # Tier 2 signal (franchise pharma vs franchise pharma).
        conf = 75
    if bucket_widened:
        conf -= 10
    if fv_capped:
        conf -= 5
    conf = max(40, min(TIER2_CONFIDENCE_CAP, conf))

    return {
        "fair_value": base,
        "bear_case": bear,
        "base_case": base,
        "bull_case": bull,
        "margin_of_safety": round(mos_pct, 1),
        "buffett_mos_pct": round(buffett_mos, 1) if buffett_mos is not None else None,
        "verdict": _verdict_from_mos(mos_pct),
        "method": method_label,
        "valuation_method": method_label,
        "confidence_score": conf,
        "_meta": {
            "tier": 2,
            "sector": sector,
            "bucket": bucket,
            "bucket_widened": bucket_widened,
            "cohort_size": len(bucket_peers),
            "peer_pe_median": (
                round(peer_pe_median, 2) if peer_pe_median is not None else None
            ),
            "peer_ev_ebitda_median": (
                round(peer_ev_ebitda_median, 2)
                if peer_ev_ebitda_median is not None else None
            ),
            "leg_used": leg_used,
            "fv_capped": fv_capped,
            "eps": round(eps_f, 4),
            "ticker_bucket_inputs": {
                "roce": financials.get("roce"),
                "piotroski": financials.get("piotroski"),
                "market_cap_cr": financials.get("market_cap_cr"),
            },
        },
    }


# ── Caveat helper for service.py wiring ────────────────────────
def tier2_caveat(meta: dict) -> str:
    """Return a one-line `data_issues` caveat for a Tier 2 result.

    Used by service.py to surface a transparent provenance message:
      "Valuation: cohort_pe (Tier 2, Premium pharma bucket, 8 peers,
       peer median P/E 38.2)"
    """
    bucket = (meta.get("bucket") or "").title()
    sector = meta.get("sector") or "sector"
    n = meta.get("cohort_size") or 0
    leg = meta.get("leg_used") or "pe"
    if leg == "ev_ebitda":
        m = meta.get("peer_ev_ebitda_median")
        marker = f"peer median EV/EBITDA {m}" if m is not None else "peer EV/EBITDA"
    else:
        m = meta.get("peer_pe_median")
        marker = f"peer median P/E {m}" if m is not None else "peer P/E"
    widened = " (widened)" if meta.get("bucket_widened") else ""
    return (
        f"Tier 2 cohort: {bucket} {sector} bucket{widened}, "
        f"{n} peers, {marker}"
    )
