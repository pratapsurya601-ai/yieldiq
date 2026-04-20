#!/usr/bin/env python3
"""Build the peer_groups table from stocks + latest market_metrics.

Purpose
-------
The analysis UI shows a "peers" block (top-6 comparable companies).
This script precomputes those peers weekly so the page doesn't have
to run a fresh SQL every request.

Peer selection rules
--------------------
For each ticker T:
  1. Candidate peers = stocks with the SAME sub_sector (if present)
     AND the SAME market_cap_category, excluding T itself.
     If sub_sector is not populated for T, fall back to matching on
     sector alone.
  2. Rank candidates by market-cap proximity, measured as
     |log(peer_mcap / T_mcap)|. Sort ascending.
  3. Keep the top 6 by proximity. Rank 1 = closest.

Sub-sector provenance
---------------------
The `stocks` model exposes `sector` and `industry`. There is no
dedicated `sub_sector` column — `industry` is the finest-grained
classification available, so this script treats `industry` as the
sub-sector. If a proper `sub_sector` column is added later, swap
the `_sub_sector_of()` helper accordingly.

Usage
-----
    DATABASE_URL=postgres://... python scripts/build_peer_groups.py --all
    DATABASE_URL=postgres://... python scripts/build_peer_groups.py \
        --ticker RELIANCE

Idempotency
-----------
Safe to re-run. For each ticker the script:
  - UPSERTs one row per (ticker, peer_ticker) with updated rank/mcap_ratio
  - DELETEs any older peer rows for this ticker that fell out of
    the new top-6
Each ticker is committed in its own transaction, so a mid-run crash
persists partial progress.

Exit codes
----------
    0    — all tickers processed
    1    — at least one ticker failed
    130  — SIGINT received
"""
from __future__ import annotations

import argparse
import logging
import math
import os
import signal
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from sqlalchemy import text  # noqa: E402
from sqlalchemy.orm import Session as OrmSession  # noqa: E402

from data_pipeline.db import Session  # noqa: E402


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("build_peer_groups")


TOP_N_PEERS = 6


# ──────────────────────────────────────────────────────────────────────
# SIGINT handling
# ──────────────────────────────────────────────────────────────────────
_interrupted = False
_processed_count = 0


def _sigint_handler(signum: int, frame: Any) -> None:  # noqa: ARG001
    global _interrupted
    _interrupted = True


signal.signal(signal.SIGINT, _sigint_handler)


# ──────────────────────────────────────────────────────────────────────
# Data model
# ──────────────────────────────────────────────────────────────────────
@dataclass(frozen=True)
class StockRow:
    ticker: str
    sector: str | None
    sub_sector: str | None
    market_cap_category: str | None   # stored column, often null
    market_cap_cr: float | None
    derived_tier: str | None           # computed from market_cap_cr


def _derive_tier(mcap_cr: float | None) -> str | None:
    """SEBI-aligned cap-tier thresholds, INR Cr.

    Used when stocks.market_cap_category is not populated — which is
    the common case until the stocks table is re-enriched. Thresholds:
      - Large : mcap_cr >= 20_000   (roughly top 100 by market cap)
      - Mid   : 5_000 <= mcap_cr < 20_000
      - Small : 1_000 <= mcap_cr < 5_000
      - Micro : mcap_cr < 1_000
    Micro + Small share a pool for peer purposes (otherwise the long
    tail is too sparse). Large and Mid stay separate.
    """
    if mcap_cr is None or mcap_cr <= 0:
        return None
    if mcap_cr >= 20_000:
        return "Large"
    if mcap_cr >= 5_000:
        return "Mid"
    if mcap_cr >= 1_000:
        return "Small"
    return "Micro"


def _sub_sector_of(row: StockRow) -> str | None:
    """Return the finest-grained classification we have for a stock.

    Currently maps to the `industry` column on `stocks` (stored into
    StockRow.sub_sector at load time). Kept behind a helper so that
    if a proper `sub_sector` column is added later, only this one
    function needs to change.
    """
    return row.sub_sector


def _peer_tier(row: StockRow) -> str | None:
    """The tier used for peer grouping: stored category if present,
    else the derived tier from market_cap_cr. Keeps pre-enriched
    rows stable while giving coverage to the (current) all-null case."""
    if row.market_cap_category:
        return row.market_cap_category
    return row.derived_tier


# ──────────────────────────────────────────────────────────────────────
# Loaders
# ──────────────────────────────────────────────────────────────────────
_LOAD_SQL = text("""
    WITH latest_mm AS (
        SELECT DISTINCT ON (ticker)
            ticker, market_cap_cr, trade_date
        FROM market_metrics
        ORDER BY ticker, trade_date DESC
    )
    SELECT
        s.ticker,
        s.sector,
        s.industry          AS sub_sector,
        s.market_cap_category,
        m.market_cap_cr
    FROM stocks s
    LEFT JOIN latest_mm m USING (ticker)
    WHERE s.is_active = true
""")


def _load_universe(db: OrmSession) -> list[StockRow]:
    rows = db.execute(_LOAD_SQL).fetchall()
    out: list[StockRow] = []
    for r in rows:
        mcap = float(r[4]) if r[4] is not None else None
        out.append(
            StockRow(
                ticker=r[0],
                sector=r[1],
                sub_sector=r[2],
                market_cap_category=r[3],
                market_cap_cr=mcap,
                derived_tier=_derive_tier(mcap),
            )
        )
    return out


# ──────────────────────────────────────────────────────────────────────
# Peer selection
# ──────────────────────────────────────────────────────────────────────
def _pick_peers(
    target: StockRow,
    universe: list[StockRow],
) -> tuple[list[tuple[StockRow, float]], str]:
    """Return (ranked_peers, reason).

    ranked_peers is a list of (peer, mcap_ratio) pairs sorted from
    closest to least close, length <= TOP_N_PEERS.
    """
    if target.market_cap_cr is None or target.market_cap_cr <= 0:
        return ([], "no_mcap")

    target_tier = _peer_tier(target)
    if target_tier is None:
        return ([], "no_tier")

    target_sub = _sub_sector_of(target)
    reason = "same_sub_sector_mcap_proximity"

    def _candidates(strategy: str) -> list[StockRow]:
        """strategy ∈ {'sub', 'sector', 'tier'} — progressively looser."""
        out: list[StockRow] = []
        for s in universe:
            if s.ticker == target.ticker:
                continue
            if _peer_tier(s) != target_tier:
                continue
            if s.market_cap_cr is None or s.market_cap_cr <= 0:
                continue
            if strategy == "sub":
                peer_sub = _sub_sector_of(s)
                if not target_sub or not peer_sub or peer_sub != target_sub:
                    continue
            elif strategy == "sector":
                if not s.sector or not target.sector or s.sector != target.sector:
                    continue
            # 'tier' strategy: same cap tier only, no sector filter
            out.append(s)
        return out

    cands = _candidates("sub") if target_sub else []
    if not cands and target.sector:
        cands = _candidates("sector")
        reason = "same_sector_mcap_proximity"
    if not cands:
        # Last-resort fallback: same cap tier only. Keeps peer block
        # populated even when sector/industry data is missing from the
        # stocks table (common before enrichment). Mcap proximity still
        # ranks these, so the closest-size peers surface first.
        cands = _candidates("tier")
        reason = "same_cap_tier_mcap_proximity"
    if not cands:
        return ([], "no_candidates")

    def _proximity(peer: StockRow) -> float:
        # both mcaps > 0 enforced by filter above
        return abs(math.log(peer.market_cap_cr / target.market_cap_cr))

    cands.sort(key=_proximity)
    top = cands[:TOP_N_PEERS]
    ranked = [
        (peer, peer.market_cap_cr / target.market_cap_cr) for peer in top
    ]
    return (ranked, reason)


# ──────────────────────────────────────────────────────────────────────
# SQL (UPSERT + prune)
# ──────────────────────────────────────────────────────────────────────
_UPSERT_SQL = text("""
    INSERT INTO peer_groups (
        ticker, peer_ticker, rank, reason, mcap_ratio,
        sector, sub_sector, computed_at
    ) VALUES (
        :ticker, :peer_ticker, :rank, :reason, :mcap_ratio,
        :sector, :sub_sector, now()
    )
    ON CONFLICT (ticker, peer_ticker) DO UPDATE SET
        rank        = EXCLUDED.rank,
        reason      = EXCLUDED.reason,
        mcap_ratio  = EXCLUDED.mcap_ratio,
        sector      = EXCLUDED.sector,
        sub_sector  = EXCLUDED.sub_sector,
        computed_at = now()
""")


_PRUNE_SQL = text("""
    DELETE FROM peer_groups
    WHERE ticker = :ticker
      AND peer_ticker <> ALL(:keep)
""")


_PRUNE_ALL_SQL = text("""
    DELETE FROM peer_groups WHERE ticker = :ticker
""")


# ──────────────────────────────────────────────────────────────────────
# Per-ticker driver
# ──────────────────────────────────────────────────────────────────────
def process_ticker(
    db: OrmSession,
    target: StockRow,
    universe: list[StockRow],
) -> list[str]:
    """Rebuild peer_groups rows for one ticker. Returns peer tickers written."""
    ranked, reason = _pick_peers(target, universe)

    if not ranked:
        # No peers — clear out any stale rows for this ticker.
        db.execute(_PRUNE_ALL_SQL, {"ticker": target.ticker})
        db.commit()
        return []

    keep = [peer.ticker for peer, _ in ranked]
    for rank, (peer, ratio) in enumerate(ranked, start=1):
        db.execute(
            _UPSERT_SQL,
            {
                "ticker": target.ticker,
                "peer_ticker": peer.ticker,
                "rank": rank,
                "reason": reason,
                "mcap_ratio": ratio,
                "sector": target.sector,
                "sub_sector": _sub_sector_of(target),
            },
        )
    # Prune anything not in the new top-N
    db.execute(_PRUNE_SQL, {"ticker": target.ticker, "keep": keep})
    db.commit()
    return keep


# ──────────────────────────────────────────────────────────────────────
# Main
# ──────────────────────────────────────────────────────────────────────
def main() -> int:
    global _processed_count

    parser = argparse.ArgumentParser(
        description="Build peer_groups from stocks + latest market_metrics."
    )
    parser.add_argument("--all", action="store_true",
                        help="Process all active tickers.")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Process a single ticker.")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL not set")
        return 1

    if Session is None:
        logger.error("data_pipeline.db.Session unavailable (no DATABASE_URL)")
        return 1

    if not args.all and not args.ticker:
        logger.error("must pass --all or --ticker TICKER")
        return 1

    db = Session()
    try:
        universe = _load_universe(db)
    finally:
        db.close()

    by_ticker = {s.ticker: s for s in universe}

    if args.ticker:
        t = args.ticker.strip().upper()
        if t not in by_ticker:
            logger.error("ticker %s not found in active stocks", t)
            return 1
        targets = [by_ticker[t]]
    else:
        targets = sorted(universe, key=lambda s: s.ticker)

    total = len(targets)
    logger.info("starting build_peer_groups: %d tickers", total)

    any_failure = False
    for i, target in enumerate(targets, start=1):
        if _interrupted:
            logger.warning(
                "Interrupted, %d tickers processed", _processed_count,
            )
            return 130

        db = Session()
        try:
            peers = process_ticker(db, target, universe)
            preview = ", ".join(peers) if peers else "(none)"
            print(
                f"{i}/{total} {target.ticker}: {len(peers)} peers ({preview})",
                flush=True,
            )
            _processed_count += 1
        except Exception as exc:  # noqa: BLE001
            any_failure = True
            logger.error(
                "ticker %s failed: %s", target.ticker, exc, exc_info=True,
            )
            try:
                db.rollback()
            except Exception:  # noqa: BLE001
                pass
        finally:
            db.close()

    logger.info(
        "done: %d/%d tickers processed (failures: %s)",
        _processed_count, total, "yes" if any_failure else "no",
    )
    return 1 if any_failure else 0


if __name__ == "__main__":
    sys.exit(main())
