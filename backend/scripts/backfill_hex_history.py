#!/usr/bin/env python3
# backend/scripts/backfill_hex_history.py
# ═══════════════════════════════════════════════════════════════
# One-off / weekly backfill of the hex_history table.
#
# CLI:
#     python backfill_hex_history.py [--limit 500] [--ticker RELIANCE.NS]
#                                    [--quarters 12] [--throttle 0.05]
#
# Runs in GitHub Actions (see .github/workflows/hex_history_weekly.yml).
# NEVER run this at request time on Railway — it's 500 × 12 ≈ 6k
# snapshots and the single worker would starve.
#
# Idempotent: ON CONFLICT UPDATE in the inner upsert.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Repo root on path so `backend.*` and `data_pipeline.*` import cleanly.
_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("backfill_hex_history")


def _load_top_tickers(limit: int) -> list[str]:
    """Top N NSE tickers by market_cap_cr, matching cache_warmup style."""
    try:
        from sqlalchemy import text  # type: ignore
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:
        log.error("cannot import pipeline DB: %s", exc)
        return []
    sess = Session()
    try:
        # DISTINCT ON (ticker) dedupes cross-listing rows. Without it,
        # dual-listed tickers (NSE+BSE, e.g. BPCL) appear twice in the
        # backfill queue. See design note in backend/routers/screener.py.
        rows = sess.execute(
            text(
                """
                SELECT ticker FROM (
                    SELECT DISTINCT ON (ticker) ticker, market_cap_cr
                    FROM market_metrics
                    WHERE market_cap_cr IS NOT NULL
                    ORDER BY ticker, trade_date DESC
                ) t
                ORDER BY market_cap_cr DESC
                LIMIT :lim
                """
            ),
            {"lim": limit},
        ).fetchall()
        out = []
        for r in rows:
            t = r[0]
            if not t:
                continue
            if not (t.endswith(".NS") or t.endswith(".BO")):
                t = f"{t}.NS"
            out.append(t)
        return out
    finally:
        try:
            sess.close()
        except Exception:
            pass


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Backfill hex_history for top-N tickers × N quarters"
    )
    parser.add_argument("--limit", type=int, default=500,
                        help="How many top tickers to backfill (default 500)")
    parser.add_argument("--ticker", type=str, default=None,
                        help="Backfill a single ticker (overrides --limit)")
    parser.add_argument("--quarters", type=int, default=12,
                        help="Number of quarters per ticker (default 12)")
    parser.add_argument("--throttle", type=float, default=0.05,
                        help="Sleep between tickers, seconds (default 0.05)")
    args = parser.parse_args()

    # Import here so path setup has taken effect
    from backend.services.hex_history_service import (
        compute_and_store_all_history,
    )

    if args.ticker:
        tickers = [args.ticker]
    else:
        tickers = _load_top_tickers(args.limit)
    if not tickers:
        log.error("No tickers loaded. Exiting.")
        return 1

    log.info("Backfilling %d tickers × %d quarters (throttle=%.2fs)",
             len(tickers), args.quarters, args.throttle)

    t0 = time.perf_counter()
    ok = 0
    empty = 0
    errors = 0
    total_rows = 0

    for idx, tk in enumerate(tickers, start=1):
        try:
            stored = compute_and_store_all_history(tk, quarters=args.quarters)
            total_rows += stored
            if stored > 0:
                ok += 1
            else:
                empty += 1
        except Exception as exc:
            # Should never happen — service is never-raise — but guard anyway
            errors += 1
            log.warning("backfill error %s: %s", tk, exc)

        if idx % 10 == 0:
            elapsed = time.perf_counter() - t0
            rate = idx / max(elapsed, 1e-3)
            eta = (len(tickers) - idx) / max(rate, 1e-3)
            log.info("  [%d/%d] ok=%d empty=%d err=%d rows=%d  rate=%.1f tk/s  eta=%.0fs",
                     idx, len(tickers), ok, empty, errors, total_rows, rate, eta)

        if args.throttle > 0:
            time.sleep(args.throttle)

    elapsed = time.perf_counter() - t0
    log.info(
        "DONE in %.1fs — tickers: %d ok / %d empty / %d error — rows upserted: %d",
        elapsed, ok, empty, errors, total_rows,
    )
    # Tolerate per-ticker failures; exit 0 unless everything failed
    if ok == 0 and empty == 0:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
