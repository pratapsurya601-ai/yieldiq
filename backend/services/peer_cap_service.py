# backend/services/peer_cap_service.py
# ═══════════════════════════════════════════════════════════════
# Peer-multiple sanity ceiling for DCF Fair Value.
#
# Motivation (2026-04-28 launch audit, outlier-7):
#   The DCF model can blow past plausible valuations on small-cap
#   names with thin coverage data — e.g. JUSTDIAL showed 91% MoS,
#   EMAMILTD 82%. The DCF output is internally consistent, but a
#   1-line sanity check against sector peers tells you the displayed
#   FV would price the stock at 5–10× the median P/E of comparable
#   businesses. That is almost never a mispricing — it's a model
#   miscalibration.
#
# Idea: when DCF says the stock is worth >1.5× peer-median multiples,
# cap displayed FV at 1.5× peer-implied. The 1.5× headroom preserves
# legitimate undervaluation calls while clipping the implausible tail.
#
# Caller pattern (backend/services/analysis/service.py, after the
# moat-adjusted `iv` is settled but before mos_pct recompute):
#
#     from backend.services.peer_cap_service import compute_peer_cap
#     pc = compute_peer_cap(ticker)  # cheap; returns None on error
#     fair_value_source = "dcf"
#     peer_cap_details = None
#     if pc and pc.get("peer_fv", 0) > 0 and 1.5 * pc["peer_fv"] < iv:
#         peer_cap_details = {
#             "uncapped_fv": float(iv),
#             "peer_fv": float(pc["peer_fv"]),
#             "ceiling_fv": float(1.5 * pc["peer_fv"]),
#             "method": pc["method"],
#             "n_peers": pc["n_peers"],
#             "median_pe": pc.get("median_pe"),
#             "median_ev_ebitda": pc.get("median_ev_ebitda"),
#             "median_pb": pc.get("median_pb"),
#         }
#         iv = round(1.5 * pc["peer_fv"], 2)
#         fair_value_source = "peer_capped"
#
# Schema notes:
#   - `stocks` table has `sector` + `industry` (yfinance taxonomy:
#     "Financial Services", "Technology", etc). We use `industry`
#     for tighter peers when populated, falling back to `sector`.
#   - `ratio_history` carries the latest pe_ratio / pb_ratio /
#     ev_ebitda / market_cap_cr per ticker.
#   - "Liquid" = market_cap_cr > 500 (i.e. ₹500 Cr).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from statistics import median
from typing import Optional

logger = logging.getLogger("yieldiq.peer_cap")


def should_skip_peer_cap(ticker: str) -> bool:
    """Bellwether allowlist: trust the explicit model, not the peer
    cohort ceiling. For these tickers the DCF / RIM / bank-P/B
    model already encodes the right narrative (super-stable consumer
    bellwethers, tier-1 private banks with reset COE) and the peer
    cohort median tends to under-price them due to the long tail
    of weaker comps. Empirically, applying peer_cap to TITAN /
    HDFCBANK was overriding the bcc591d super-cyclical exclusion
    and bank COE reset — so the explicit model wins here.

    Imports deferred to avoid a circular import:
    backend.services.analysis.__init__ imports service.py, which
    imports this module at top level."""
    if not ticker:
        return False
    try:
        from backend.services.analysis.constants import (
            NEVER_SUPER_CYCLICAL,
            is_top_private_bank,
        )
    except Exception:
        return False
    bare = ticker.replace(".NS", "").replace(".BO", "").upper()
    if bare in NEVER_SUPER_CYCLICAL:
        return True
    if is_top_private_bank(bare):
        return True
    return False

# Threshold: peers must have market_cap_cr above this floor (in ₹ crore)
# to be considered "liquid". Smaller names have noisier multiples and
# thinner public data, which would defeat the purpose of the cap.
_MIN_PEER_MCAP_CR = 500.0

# Minimum number of liquid peers needed to compute a meaningful
# median. Below this, return None and the caller leaves DCF FV
# untouched (no false-confidence cap from a 1-peer sample).
_MIN_PEERS = 3

# Sector strings (yfinance taxonomy in the `stocks` table) that
# route to a P/B-based cap rather than P/E + EV/EBITDA. Banks and
# NBFCs don't have meaningful EBITDA, and their P/E is often
# distorted by provisioning cycles, so book value is the more
# stable comparable.
_BANK_LIKE_SECTORS = {"Financial Services"}


def _safe_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        f = float(v)
        if f != f:  # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _get_session():
    """Resolve a DB session via the same path as analysis/db.py.
    Returns None if the data pipeline / DB is unavailable."""
    try:
        from data_pipeline.db import Session as PipelineSession
        if PipelineSession is None:
            return None
        return PipelineSession()
    except Exception as exc:
        logger.debug("peer_cap: session unavailable: %s", exc)
        return None


def _fetch_target_classification(session, db_ticker: str) -> Optional[dict]:
    """Pull the target ticker's sector + industry from `stocks`."""
    from sqlalchemy import text
    row = session.execute(text("""
        SELECT sector, industry
        FROM stocks
        WHERE ticker = :t
        LIMIT 1
    """), {"t": db_ticker}).mappings().first()
    if not row:
        return None
    return {
        "sector": row.get("sector"),
        "industry": row.get("industry"),
    }


def _fetch_target_multiples(session, db_ticker: str) -> Optional[dict]:
    """Latest pe_ratio / pb_ratio / ev_ebitda + market_cap_cr for the
    target. Returns ``None`` if ratio_history has no row.

    We use ratio-against-ratio (peer_median_pe / target_pe) ×
    target_price to derive peer-implied FV. This avoids any
    unit-mismatch landmines between PAT (₹ crore) and
    shares_outstanding (lakh on some tickers, crore on others, raw
    count on yet others). The ratio_history pipeline already
    normalised those when computing pe_ratio and pb_ratio.
    """
    from sqlalchemy import text
    row = session.execute(text("""
        SELECT pe_ratio, pb_ratio, ev_ebitda, market_cap_cr
        FROM ratio_history
        WHERE ticker = :t
          AND period_type = 'annual'
          AND period_end IS NOT NULL
        ORDER BY period_end DESC
        LIMIT 1
    """), {"t": db_ticker}).mappings().first()
    if not row:
        return None
    return {
        "pe_ratio": _safe_float(row.get("pe_ratio")),
        "pb_ratio": _safe_float(row.get("pb_ratio")),
        "ev_ebitda": _safe_float(row.get("ev_ebitda")),
        "market_cap_cr": _safe_float(row.get("market_cap_cr")),
    }


def _fetch_target_price(session, db_ticker: str) -> Optional[float]:
    """Latest live-ish price for the target. Used as the anchor for
    converting (peer_median_multiple / target_multiple) into a rupee
    fair value: peer_implied_fv = price × (peer_median / target)."""
    from sqlalchemy import text
    # Prefer the freshest close from `daily_prices` (NSE EOD). Falls
    # through to None on miss — caller bails out gracefully.
    try:
        row = session.execute(text("""
            SELECT close_price FROM daily_prices
            WHERE ticker = :t
            ORDER BY trade_date DESC
            LIMIT 1
        """), {"t": db_ticker}).mappings().first()
        if row and row.get("close_price") is not None:
            return _safe_float(row.get("close_price"))
    except Exception:
        # Some sessions abort on a failed query; rollback so the
        # caller's subsequent peer-multiples query still works.
        try:
            session.rollback()
        except Exception:
            pass
    return None


def _fetch_peer_multiples(
    session, db_ticker: str, sector: Optional[str], industry: Optional[str]
) -> list[dict]:
    """Pull pe / pb / ev_ebitda for liquid sector/industry peers.

    Joins `stocks` (for sector/industry classification) with the
    most-recent `ratio_history` row per ticker. Excludes the target
    itself. Filters: market_cap_cr > 500, and at least one of
    pe/pb/ev_ebitda non-null.

    Strategy: prefer the tighter `industry` match when populated;
    if that returns < _MIN_PEERS, broaden to `sector`.
    """
    from sqlalchemy import text

    def _query(filter_sql: str, params: dict) -> list[dict]:
        # Window-function approach: pick the most recent ratio_history
        # row per peer ticker, then filter on liquidity + sector match.
        sql = f"""
            WITH latest_rh AS (
                SELECT
                    ticker, pe_ratio, pb_ratio, ev_ebitda, market_cap_cr,
                    ROW_NUMBER() OVER (
                        PARTITION BY ticker
                        ORDER BY period_end DESC
                    ) AS rn
                FROM ratio_history
                WHERE period_type = 'annual'
            )
            SELECT s.ticker, s.sector, s.industry,
                   r.pe_ratio, r.pb_ratio, r.ev_ebitda, r.market_cap_cr
            FROM stocks s
            JOIN latest_rh r ON r.ticker = s.ticker AND r.rn = 1
            WHERE s.ticker <> :self_t
              AND r.market_cap_cr IS NOT NULL
              AND r.market_cap_cr > :mcap_floor
              AND ({filter_sql})
        """
        rows = session.execute(text(sql), {**params, "self_t": db_ticker, "mcap_floor": _MIN_PEER_MCAP_CR}).mappings().all()
        return [dict(r) for r in rows]

    peers: list[dict] = []
    if industry:
        peers = _query("s.industry = :ind", {"ind": industry})
    if len(peers) < _MIN_PEERS and sector:
        peers = _query("s.sector = :sec", {"sec": sector})
    return peers


def _median_or_none(values: list[float], lo: float, hi: float) -> Optional[float]:
    """Median of `values` with sanity bounds. Filters out the
    garbage-data tail in `ratio_history.pe_ratio` (HCLTECH/TECHM/
    WIPRO show normalised values < 1 instead of true P/E ~25, a
    known upstream pipeline issue). `lo`/`hi` clip those out so the
    median doesn't get dragged into bizarro territory.

    Returns None when fewer than _MIN_PEERS values survive — caller
    interprets that as "not enough comparable data, no cap".
    """
    cleaned = [v for v in values if v is not None and lo <= v <= hi]
    if len(cleaned) < _MIN_PEERS:
        return None
    return float(median(cleaned))


# Sanity ranges for ratio_history multiples. A real-world Indian
# equity P/E sits in roughly [3, 200]; the upstream pipeline emits
# values in [0.1, 0.5] for ~30% of IT-services tickers (a
# normalised score, not a true ratio). Filtering them out is the
# only way to get a meaningful peer median without rebuilding the
# upstream parser.
_PE_RANGE = (3.0, 250.0)
_EV_EBITDA_RANGE = (1.0, 100.0)
_PB_RANGE = (0.2, 50.0)


def compute_peer_cap(ticker: str) -> Optional[dict]:
    """Compute a peer-multiple-implied fair value for `ticker`.

    Returns None when:
      - DB is unreachable
      - target ticker not in `stocks` table
      - target has no usable EPS / BVPS data
      - fewer than _MIN_PEERS liquid peers in industry/sector
      - none of P/E or EV/EBITDA (or P/B for banks) survive median

    On success returns:
        {
          "peer_fv": float,           # rupees per share
          "method": "min(pe,ev_ebitda)" | "pe_only" | "ev_ebitda_only" | "pb",
          "n_peers": int,
          "sector": str | None,
          "industry": str | None,
          "median_pe": float | None,
          "median_ev_ebitda": float | None,
          "median_pb": float | None,
          "is_bank": bool,
        }
    """
    # Bellwether allowlist: skip peer-cap entirely so the explicit
    # DCF / RIM / bank-P/B model wins. Returning None here means the
    # caller leaves `iv` untouched (no ceiling applied).
    if should_skip_peer_cap(ticker):
        logger.info(
            "peer_cap.bypass ticker=%s reason=bellwether_allowlist", ticker,
        )
        return None
    db_ticker = ticker.replace(".NS", "").replace(".BO", "")
    session = _get_session()
    if session is None:
        return None
    try:
        cls = _fetch_target_classification(session, db_ticker)
        if not cls:
            logger.info("peer_cap: %s not found in stocks table", db_ticker)
            return None
        sector = cls.get("sector")
        industry = cls.get("industry")
        is_bank = sector in _BANK_LIKE_SECTORS

        target = _fetch_target_multiples(session, db_ticker)
        if not target:
            logger.info("peer_cap: %s no ratio_history row", db_ticker)
            return None
        target_price = _fetch_target_price(session, db_ticker)

        peers = _fetch_peer_multiples(session, db_ticker, sector, industry)
        if len(peers) < _MIN_PEERS:
            logger.info(
                "peer_cap: %s only %d liquid peers (sector=%s industry=%s) — skip",
                db_ticker, len(peers), sector, industry,
            )
            return None

        med_pe = _median_or_none(
            [_safe_float(p.get("pe_ratio")) for p in peers], *_PE_RANGE,
        )
        med_pb = _median_or_none(
            [_safe_float(p.get("pb_ratio")) for p in peers], *_PB_RANGE,
        )
        med_ev_ebitda = _median_or_none(
            [_safe_float(p.get("ev_ebitda")) for p in peers], *_EV_EBITDA_RANGE,
        )

        # Anchor price: prefer live price; fall back to deriving from
        # target's own multiples — though if both are missing we bail.
        if target_price is None or target_price <= 0:
            logger.info("peer_cap: %s no anchor price — skip", db_ticker)
            return None

        def _ratio_fv(
            peer_med: Optional[float],
            target_mult: Optional[float],
            bounds: tuple[float, float],
        ) -> Optional[float]:
            """peer_implied_fv = target_price × (peer_med / target_mult).
            Returns None when either input is missing or out of the
            sanity range — same filter we apply to peers, otherwise
            a corrupted target multiple would make the ratio meaningless."""
            if peer_med is None or target_mult is None:
                return None
            lo, hi = bounds
            if not (lo <= target_mult <= hi):
                return None
            if peer_med <= 0 or target_mult <= 0:
                return None
            return target_price * (peer_med / target_mult)

        if is_bank:
            # Bank/financial path: use P/B only.
            peer_fv = _ratio_fv(med_pb, target.get("pb_ratio"), _PB_RANGE)
            if peer_fv is None or peer_fv <= 0:
                return None
            return {
                "peer_fv": float(peer_fv),
                "method": "pb",
                "n_peers": len(peers),
                "sector": sector,
                "industry": industry,
                "median_pe": med_pe,
                "median_ev_ebitda": med_ev_ebitda,
                "median_pb": med_pb,
                "is_bank": True,
            }

        # Non-bank: lower of P/E-implied and EV/EBITDA-implied.
        candidates: list[tuple[str, float]] = []
        pe_fv = _ratio_fv(med_pe, target.get("pe_ratio"), _PE_RANGE)
        if pe_fv is not None:
            candidates.append(("pe", pe_fv))
        eb_fv = _ratio_fv(med_ev_ebitda, target.get("ev_ebitda"), _EV_EBITDA_RANGE)
        if eb_fv is not None:
            candidates.append(("ev_ebitda", eb_fv))

        if not candidates:
            return None

        # "lower of" — the more conservative ceiling.
        candidates.sort(key=lambda kv: kv[1])
        peer_fv = candidates[0][1]
        if len(candidates) >= 2:
            method = "min(pe,ev_ebitda)"
        else:
            method = f"{candidates[0][0]}_only"

        return {
            "peer_fv": float(peer_fv),
            "method": method,
            "n_peers": len(peers),
            "sector": sector,
            "industry": industry,
            "median_pe": med_pe,
            "median_ev_ebitda": med_ev_ebitda,
            "median_pb": med_pb,
            "is_bank": False,
        }
    except Exception as exc:
        logger.exception("peer_cap: %s failed: %s", ticker, exc)
        return None
    finally:
        try:
            session.close()
        except Exception:
            pass
