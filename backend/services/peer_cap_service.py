"""Peer-multiple sanity gate for DCF fair value.

Caps the DCF FV at 1.5× the peer P/E-implied FV when DCF disagrees
with peer multiples. Down-only: a stock can never get *raised* above
DCF by this gate. Rationale: legitimate premium-to-peers happens, but
50%+ above peer median almost always indicates an over-optimistic
DCF assumption (e.g. EMAMILTD's +82% MoS vs HUL/Dabur/Marico trading
at much tighter multiples).

EV/EBITDA branch is deliberately omitted from v1 — see PR notes.
The unit conversion (Cr ↔ ₹ ↔ shares-in-lakhs) is a known landmine
in this codebase and a wrong conversion would silently produce
garbage clamps. P/E is per-share × per-share, no unit risk.
Follow-up PR adds EV/EBITDA with its own canary diff.

Peer scope resolution:
  1. Industry peers with market_cap_cr ≥ MIN_MCAP_CR, ≥ MIN_PEERS rows.
  2. Else sector peers with same filter.
  3. Else no cap (fair_value_source = "dcf_no_peer_data").

Outputs at the boundary:
  - capped_fv: float — the FV to display/persist.
  - source: "dcf" | "peer_capped" | "dcf_no_peer_data".
  - details: dict for transparency (peer_count, scope, median_pe,
    pe_implied_fv) — exposed via ValuationOutput.peer_cap_details.
"""
from __future__ import annotations

import logging
import statistics
import time
from dataclasses import dataclass, field, asdict
from typing import Optional

logger = logging.getLogger("yieldiq.peer_cap")

# ── Tunables ──────────────────────────────────────────────────
# Bumping any of these forces a CACHE_VERSION bump + canary diff.

# A stock can deserve a premium to peers, but rarely 50%+. This is
# the headroom multiplier above peer-median P/E-implied FV.
PEER_CAP_MULTIPLIER = 1.5

# Minimum number of liquid peers required to trust the median.
# Below this, fall back to sector; below this at sector, skip cap.
MIN_PEERS = 5

# Liquidity floor — exclude micro-caps from the median, they trade on
# different multiples than mid/large caps in the same industry.
# ₹500 Cr ≈ small-cap floor for Indian markets.
MIN_MCAP_CR = 500.0

# Sanity bounds on peer P/E — any value outside these is almost
# certainly stale / data-quality garbage and would distort the median.
PE_MIN = 3.0
PE_MAX = 200.0

# Median TTL — recompute peer medians no more than once per hour.
# Industry composition is stable; this is just to avoid a DB roundtrip
# on every analysis call.
_MEDIAN_TTL_SEC = 3600
_median_cache: dict[str, tuple[float, "PeerScope"]] = {}


@dataclass
class PeerScope:
    """Resolved peer set + median. Cached per (industry|sector, scope_kind)."""
    scope: str  # "industry" | "sector" | "none"
    label: str  # e.g. "Personal Care" or "Consumer Staples"
    peer_count: int
    median_pe: Optional[float]


@dataclass
class PeerCapResult:
    """Outcome of applying the peer-cap gate. Always returned, never
    raises — failures degrade to source='dcf_no_peer_data' with the
    raw DCF FV passed through unchanged."""
    capped_fv: float
    source: str  # "dcf" | "peer_capped" | "dcf_no_peer_data"
    details: dict = field(default_factory=dict)


def _resolve_peer_scope(
    ticker: str,
    industry: Optional[str],
    sector: Optional[str],
    db,
) -> PeerScope:
    """Find the tightest valid peer set: industry first, sector fallback."""
    if db is None:
        return PeerScope("none", "", 0, None)

    # In-memory cache by (scope_label) — stable across tickers in the
    # same industry, so EMAMILTD and DABUR share a lookup.
    for scope_kind, label in (("industry", industry), ("sector", sector)):
        if not label:
            continue
        cache_key = f"{scope_kind}:{label}"
        cached = _median_cache.get(cache_key)
        if cached and (time.time() - cached[0]) < _MEDIAN_TTL_SEC:
            scope = cached[1]
            if scope.peer_count >= MIN_PEERS and scope.median_pe is not None:
                return scope

        scope = _query_median_pe(ticker, scope_kind, label, db)
        _median_cache[cache_key] = (time.time(), scope)
        if scope.peer_count >= MIN_PEERS and scope.median_pe is not None:
            return scope

    return PeerScope("none", "", 0, None)


def _query_median_pe(exclude_ticker: str, scope_kind: str, label: str, db) -> PeerScope:
    """Query median P/E across liquid peers in the given industry/sector.

    Uses the latest MarketMetrics row per peer (within 30 days).
    Skips micro-caps and stale/garbage P/E values.
    """
    try:
        from data_pipeline.models import Stock, MarketMetrics
        from sqlalchemy import desc
        from datetime import date, timedelta

        col = Stock.industry if scope_kind == "industry" else Stock.sector
        peer_tickers = [
            t for (t,) in db.query(Stock.ticker)
            .filter(col == label, Stock.ticker != exclude_ticker, Stock.is_active.is_(True))
            .all()
        ]
        if len(peer_tickers) < MIN_PEERS:
            return PeerScope(scope_kind, label, 0, None)

        cutoff = date.today() - timedelta(days=30)
        # Latest metrics per peer — group via subquery would be cleaner,
        # but the row count here is small (industry rarely > 50 names).
        pe_values: list[float] = []
        for peer in peer_tickers:
            mm = (
                db.query(MarketMetrics)
                .filter(
                    MarketMetrics.ticker == peer,
                    MarketMetrics.trade_date >= cutoff,
                )
                .order_by(desc(MarketMetrics.trade_date))
                .first()
            )
            if mm is None:
                continue
            mcap = float(mm.market_cap_cr or 0)
            if mcap < MIN_MCAP_CR:
                continue
            pe = mm.pe_ratio
            if pe is None:
                continue
            try:
                pe_f = float(pe)
            except (TypeError, ValueError):
                continue
            if not (PE_MIN <= pe_f <= PE_MAX):
                continue
            pe_values.append(pe_f)

        if len(pe_values) < MIN_PEERS:
            return PeerScope(scope_kind, label, len(pe_values), None)

        return PeerScope(scope_kind, label, len(pe_values), statistics.median(pe_values))
    except Exception as exc:
        logger.warning("peer_cap median query failed (%s=%s): %s", scope_kind, label, exc)
        return PeerScope("none", label or "", 0, None)


def apply_peer_cap(
    ticker: str,
    dcf_fv: float,
    eps_ttm: Optional[float],
    industry: Optional[str],
    sector: Optional[str],
    db,
) -> PeerCapResult:
    """Apply the peer-cap gate to a DCF fair value.

    Args:
      ticker: e.g. "EMAMILTD"
      dcf_fv: per-share FV from DCF (₹).
      eps_ttm: trailing-12m EPS (₹/share). None or ≤0 → skip cap.
      industry, sector: stock's classification from Stocks table.
      db: SQLAlchemy session for MarketMetrics + Stocks lookups.

    Returns: PeerCapResult — never raises. Failure modes pass through
    the raw DCF FV with source='dcf_no_peer_data'.
    """
    if dcf_fv is None or dcf_fv <= 0:
        return PeerCapResult(dcf_fv, "dcf", {"reason": "non_positive_dcf"})

    if eps_ttm is None or eps_ttm <= 0:
        # Loss-making or missing EPS — no P/E baseline. Cap can't fire.
        # NOTE: this is exactly when EV/EBITDA would help. Follow-up PR.
        return PeerCapResult(dcf_fv, "dcf_no_peer_data", {"reason": "non_positive_eps"})

    scope = _resolve_peer_scope(ticker, industry, sector, db)
    if scope.median_pe is None or scope.peer_count < MIN_PEERS:
        return PeerCapResult(dcf_fv, "dcf_no_peer_data", {
            "reason": "insufficient_peers",
            "industry": industry,
            "sector": sector,
            "peer_count_seen": scope.peer_count,
        })

    pe_implied_fv = float(eps_ttm) * float(scope.median_pe)
    cap = PEER_CAP_MULTIPLIER * pe_implied_fv

    if dcf_fv <= cap:
        return PeerCapResult(dcf_fv, "dcf", {
            "scope": scope.scope,
            "label": scope.label,
            "peer_count": scope.peer_count,
            "median_pe": round(scope.median_pe, 2),
            "pe_implied_fv": round(pe_implied_fv, 2),
            "cap": round(cap, 2),
            "fired": False,
        })

    return PeerCapResult(round(cap, 2), "peer_capped", {
        "scope": scope.scope,
        "label": scope.label,
        "peer_count": scope.peer_count,
        "median_pe": round(scope.median_pe, 2),
        "pe_implied_fv": round(pe_implied_fv, 2),
        "cap": round(cap, 2),
        "raw_dcf_fv": round(float(dcf_fv), 2),
        "fired": True,
    })
