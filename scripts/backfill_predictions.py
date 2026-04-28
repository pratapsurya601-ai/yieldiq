#!/usr/bin/env python3
# scripts/backfill_predictions.py
# ═══════════════════════════════════════════════════════════════
# Backfill model_predictions_history for the last N days (default 90).
#
# SCAFFOLDING ONLY — running this for real requires:
#   1. analysis_service.compute_for_date(ticker, date) to exist (it
#      does NOT yet; today's analysis_service only computes against
#      the latest available data).
#   2. A decision on the methodology question (counterfactual vs
#      reconstructed historical model — see design doc, recommendation
#      below).
#   3. ~6h of compute against the prod Aiven Postgres + DuckDB caches.
#
# DO NOT EXECUTE WITHOUT REVIEW. The harness wiring is here so a
# follow-up PR can fill the TODO and ship.
#
# ───────────────────────────────────────────────────────────────
# Methodology — open question, our recommended answer
# ───────────────────────────────────────────────────────────────
# We have two honest options for "what was our Q1FY26 prediction
# on TICKER X?":
#
#   (A) Counterfactual: run the CURRENT model (cache_version 66,
#       post-_normalize_pct fix) against the financials and prices
#       that were available AS OF prediction_date, using the
#       point-in-time price for current_price. Reports "what would
#       today's model have said back then?".
#
#   (B) Reconstruction: replay the model that was actually live on
#       prediction_date (versions 32 → 65 in the relevant window).
#       Reports "what did we actually publish back then?".
#
# Recommendation: (A) Counterfactual, because:
#
#   • (B) requires the bugs as well. The _normalize_pct double-percent
#     bug (fix landed PR #126, cache_version 66) was systematically
#     wrong. Publishing those numbers as our retrospective record is
#     misleading — they were never seen by users of the corrected
#     code paths.
#
#   • (A) tests the model we're publishing, against data the model
#     could not have peeked at. That's the question users actually
#     care about: "is the thing you're shipping today any good?"
#
#   • Strict point-in-time discipline (no look-ahead in financials,
#     no look-ahead in price) prevents (A) from becoming overfitting
#     theatre. The backfill must use as-of snapshots, not live tables.
#
# This decision is documented in docs/performance_retrospective_design.md
# and is open for revision during Phase 2 review.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta
from typing import Iterable

logger = logging.getLogger("yieldiq.backfill_predictions")


def _daterange(start: date, end: date) -> Iterable[date]:
    """Yield each calendar date in [start, end] inclusive."""
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def _is_trading_day(d: date) -> bool:
    """Coarse trading-day filter. Excludes Sat/Sun.

    NOTE: does not exclude NSE holidays. Prod backfill should join
    against the trading_calendar table (or daily_prices itself, which
    is empty on holidays) rather than rely on this stub.
    """
    return d.weekday() < 5


def backfill_for_date(
    target_date: date,
    *,
    universe: list[str] | None = None,
    dry_run: bool = True,
) -> int:
    """Recompute every covered ticker's prediction as-of target_date.

    Returns the number of rows that WOULD be written (or were written
    when dry_run=False — but see the giant TODO below).
    """
    if universe is None:
        # TODO(task12-phase2): pull from
        #   backend.services.ticker_search.INDIAN_STOCKS
        # filtered to the paid-tier analysis universe. Open question:
        # do we include free-tier stocks too? See design doc Q5.
        universe = []

    written = 0
    for ticker in universe:
        # ─── THE STUB ────────────────────────────────────────────
        # We need an analysis_service entry point that accepts a
        # ticker AND a snapshot date and returns the model output
        # using ONLY data that was available on/before that date.
        #
        # Today's compute pipeline (backend.services.analysis_service.
        # compute_analysis) reads "latest" from analysis_cache /
        # company_financials / market_metrics — there is no point-
        # in-time variant.
        #
        # The follow-up PR introducing this function should:
        #   1. Take ticker, as_of_date.
        #   2. Read company_financials WHERE period_end <= as_of_date.
        #   3. Read daily_prices WHERE date <= as_of_date for the
        #      trailing window the DCF needs.
        #   4. Run the same DCF + Prism computation as the live path.
        #   5. Return an AnalysisResponse identical in shape to the
        #      live one.
        #
        # The retrospective_service.record_daily_predictions caller
        # would then INSERT the result into model_predictions_history.
        # ────────────────────────────────────────────────────────
        # TODO: result = analysis_service.compute_for_date(ticker, target_date)
        # TODO: retrospective_service.record_one_prediction(result, target_date)
        if dry_run:
            logger.debug("DRY-RUN backfill %s @ %s", ticker, target_date)
        else:
            raise NotImplementedError(
                "backfill_predictions cannot run for real until "
                "analysis_service.compute_for_date is implemented. "
                "See docstring at top of this file."
            )
        written += 1

    return written


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--days", type=int, default=90,
        help="Backfill window in calendar days ending today (default: 90).",
    )
    parser.add_argument(
        "--end-date", type=str, default=None,
        help="ISO date for the END of the window (default: today).",
    )
    parser.add_argument(
        "--dry-run", action="store_true", default=True,
        help="Do not write anything; just log the plan. Default: True.",
    )
    parser.add_argument(
        "--no-dry-run", dest="dry_run", action="store_false",
        help="Actually write to model_predictions_history. Will refuse "
             "until the analysis_service.compute_for_date stub is filled.",
    )
    parser.add_argument(
        "--verbose", action="store_true",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    end = date.fromisoformat(args.end_date) if args.end_date else date.today()
    start = end - timedelta(days=args.days)

    logger.info(
        "Backfill plan: %s → %s (%d days), dry_run=%s",
        start, end, args.days, args.dry_run,
    )

    total_planned = 0
    for d in _daterange(start, end):
        if not _is_trading_day(d):
            continue
        try:
            total_planned += backfill_for_date(d, dry_run=args.dry_run)
        except NotImplementedError as e:
            logger.error("Halting: %s", e)
            return 2

    logger.info("Backfill complete (or planned): %d rows", total_planned)
    return 0


if __name__ == "__main__":
    sys.exit(main())
