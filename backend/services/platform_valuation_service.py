"""Platform / Fintech valuation engine — peer-median P/Sales.

Why this exists
───────────────
Indian internet-platform stocks (PAYTM, POLICYBZR, ZOMATO, NAUKRI,
NYKAA, MEESHO, SWIGGY) and fintech distributors (NUVAMA, GROWW,
ANGELONE, MOTILALOFS, 360ONE, CDSL, BSE, MCX) are mis-valued by every
existing engine:

  - DCF: trailing FCF is volatile or negative → collapses to ₹0.x
  - P/B: asset-light businesses → BVPS is tiny, multiplier explosive
  - P/E: many have negative or volatile EPS → undefined or noisy
  - Tier 2 cohort (P/E based): peer P/E undefined for loss-making peers

The Damodaran-standard frame for platform / growth businesses is
peer-median **P/Sales** multiplied by trailing revenue-per-share,
with a growth adjustment when the target's revenue CAGR diverges from
the peer median.

Caller contract
───────────────
compute_platform_fair_value(
    ticker, sector, financials, peers
) -> Optional[dict]

  ``sector`` ∈ {"internet_platform", "fintech_broker"} or the
  human-readable strings ("Internet Platform", "Fintech") — both are
  accepted; we normalise via the sector_relative DIRECT_PEERS key.

  ``financials`` must contain:
    revenue (TTM, in rupees), shares (count), current_price,
    revenue_cagr_3y (optional — used for growth adj)

  ``peers`` is the cohort list — same PeerRecord shape used by
  Tier 2 cohort. Each peer needs ``pe`` OR ``ps`` (preferably ``ps``
  computed from market_metrics + revenue).

Return dict shape mirrors compute_tier2_fair_value:
  fair_value, bear_case, base_case, bull_case, verdict,
  method ("ps_peer_median"), valuation_method, confidence_score,
  _meta with peer_median_ps / growth_adj / ticker_revenue_per_share

Returns None when:
  - sector not platform/fintech
  - < 3 peers have valid P/S
  - target ticker revenue not available

Discipline
──────────
- Confidence capped at 65 (lower than Tier 2's 75 — P/S is noisier
  than P/E because revenue quality varies more across platforms)
- Growth adjustment clamped to [0.6, 1.6] (platform-stock P/S
  multiples are sensitive to growth, but a single year shouldn't
  swing FV by 2×)
"""
from __future__ import annotations

import logging
from statistics import median
from typing import Iterable, Optional

logger = logging.getLogger("yieldiq.platform_valuation")


# ── Sector key normalisation ────────────────────────────────────
_SECTOR_TO_COHORT: dict[str, str] = {
    "internet platform": "internet_platform",
    "internet_platform": "internet_platform",
    "internet": "internet_platform",
    "e-commerce": "internet_platform",
    "ecommerce": "internet_platform",

    "fintech": "fintech_broker",
    "fintech_broker": "fintech_broker",
    "online broker": "fintech_broker",
    "capital markets": "fintech_broker",
    "stock exchanges": "fintech_broker",
}


def _norm_sector(s: Optional[str]) -> Optional[str]:
    if not s:
        return None
    return _SECTOR_TO_COHORT.get(s.strip().lower())


# ── Sanity bands ────────────────────────────────────────────────
# Peer P/S outside this band is data noise (loss-making platform with
# negligible revenue → P/S explodes, or 100% margin business is suspect).
MIN_PEER_PS = 0.5
MAX_PEER_PS = 40.0

# Growth-adjustment clamp
MIN_GROWTH_ADJ = 0.6
MAX_GROWTH_ADJ = 1.6

# Minimum cohort size after self-exclusion + sanity-band filtering.
MIN_PEERS = 3

# Confidence ceiling. Lower than Tier 2's 75 because P/S is noisier
# than P/E. See module docstring.
PLATFORM_CONFIDENCE_CAP = 65


def _verdict_from_mos(mos_pct: float) -> str:
    if mos_pct > 20:
        return "undervalued"
    if mos_pct > -20:
        return "fairly_valued"
    return "overvalued"


def _safe_float(v) -> Optional[float]:
    try:
        return float(v) if v is not None else None
    except (TypeError, ValueError):
        return None


def _peer_ps_values(peers: Iterable[dict], target_ticker: str) -> list[float]:
    """Extract usable P/S values from peers, excluding target itself
    and out-of-band values."""
    target_bare = (target_ticker or "").replace(".NS", "").replace(".BO", "").upper()
    out: list[float] = []
    for p in peers or []:
        if not isinstance(p, dict):
            continue
        p_ticker = (p.get("ticker") or "").upper()
        if p_ticker == target_bare:
            continue
        ps = _safe_float(p.get("ps"))
        if ps is None or ps <= 0:
            # Derive P/S from market_cap_cr / revenue_cr if both present
            mcap = _safe_float(p.get("market_cap_cr"))
            rev_cr = _safe_float(p.get("revenue_cr"))
            if mcap and rev_cr and rev_cr > 0:
                ps = mcap / rev_cr
        if ps is None:
            continue
        if MIN_PEER_PS <= ps <= MAX_PEER_PS:
            out.append(ps)
    return out


def compute_platform_fair_value(
    ticker: str,
    sector: Optional[str],
    financials: dict,
    peers: Iterable[dict],
) -> Optional[dict]:
    """Compute platform fair value via peer-median P/Sales.

    Returns None on insufficient inputs — caller falls through to
    whatever data_limited / safety-net path is configured.
    """
    cohort_key = _norm_sector(sector)
    if cohort_key is None:
        return None

    fin = financials or {}
    revenue = _safe_float(fin.get("revenue") or fin.get("latest_revenue"))
    shares = _safe_float(fin.get("shares"))
    price = _safe_float(fin.get("current_price"))
    if not revenue or revenue <= 0:
        logger.info(
            "platform_valuation: %s — no revenue, returning None",
            ticker,
        )
        return None
    if not shares or shares <= 0:
        return None
    if not price or price <= 0:
        return None

    peer_ps = _peer_ps_values(peers, ticker)
    if len(peer_ps) < MIN_PEERS:
        logger.info(
            "platform_valuation: %s — only %d peers with valid P/S (need >=%d)",
            ticker, len(peer_ps), MIN_PEERS,
        )
        return None

    peer_ps_med = median(peer_ps)

    # Growth adjustment — if target grows faster than peers it deserves
    # higher P/S, slower → lower. Clamped to ±60%.
    target_growth = _safe_float(fin.get("revenue_cagr_3y"))
    peer_growths = [
        _safe_float(p.get("revenue_cagr_3y"))
        for p in peers if isinstance(p, dict)
    ]
    peer_growths = [g for g in peer_growths if g is not None]
    growth_adj = 1.0
    if target_growth is not None and peer_growths:
        peer_growth_med = median(peer_growths)
        if peer_growth_med > 0:
            ratio = (target_growth + 0.001) / (peer_growth_med + 0.001)
            growth_adj = max(MIN_GROWTH_ADJ, min(MAX_GROWTH_ADJ, ratio))

    fair_ps = peer_ps_med * growth_adj
    revenue_per_share = revenue / shares
    base = round(fair_ps * revenue_per_share, 2)
    bear = round(base * 0.75, 2)
    bull = round(base * 1.30, 2)

    mos_pct = ((base - price) / price * 100.0) if price > 0 else 0.0
    buffett_mos = ((base - price) / base * 100.0) if base > 0 else None

    # Confidence — start at floor, add 5 per extra peer above min, cap.
    conf = min(
        PLATFORM_CONFIDENCE_CAP,
        50 + min(15, (len(peer_ps) - MIN_PEERS) * 3),
    )

    return {
        "fair_value": base,
        "margin_of_safety": round(mos_pct, 1),
        "buffett_mos_pct": round(buffett_mos, 1) if buffett_mos is not None else None,
        "verdict": _verdict_from_mos(mos_pct),
        "bear_case": bear,
        "base_case": base,
        "bull_case": bull,
        "method": "ps_peer_median",
        "valuation_method": "ps_peer_median",
        "confidence_score": conf,
        "_meta": {
            "cohort": cohort_key,
            "peer_ps_median": round(peer_ps_med, 2),
            "growth_adj": round(growth_adj, 3),
            "fair_ps": round(fair_ps, 2),
            "revenue_per_share": round(revenue_per_share, 2),
            "n_peers": len(peer_ps),
        },
    }


__all__ = ["compute_platform_fair_value"]
