# backend/services/retrospective_service.py
# ═══════════════════════════════════════════════════════════════
# Performance Retrospective service — SCAFFOLDING.
#
# This module backs Task 12 (public Performance Retrospective). It
# is intentionally lightweight: the full implementation requires
# ~1 week of backfill + analyst review. What lives here is the
# stable interface the rest of the platform can lean on while the
# heavy lifting (90 days of recomputed predictions, public page
# polish) lands in follow-up PRs.
#
# Surface
# -------
#   record_daily_predictions(date)            — snapshot live cache to history
#   compute_outcome(prediction_id, outcome_date)
#                                              — fill one outcome row
#   compute_outcomes_for_window(prediction_id, windows=[30,60,90,180,365])
#                                              — batch wrapper
#   summarize_for_period(start, end, ...)     — what the public page reads
#
# Storage
# -------
# Reads/writes the two tables introduced in migration 019:
#   * model_predictions_history
#   * prediction_outcomes
#
# Methodology questions and SEBI posture live in
# docs/performance_retrospective_design.md — read that first.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import statistics
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Iterable, Optional, Sequence

logger = logging.getLogger("yieldiq.retrospective")

# Default outcome windows in trading days-from-prediction. We keep
# 30/60/90 for the "headline" public number, 180/365 for medium-term
# follow-up. The public page defaults to 90 because that's the longest
# window that lets us publish quarterly without lag.
DEFAULT_WINDOWS: tuple[int, ...] = (30, 60, 90, 180, 365)

# Default Margin-of-Safety threshold for "the model called this
# undervalued". 30% mirrors the verdict-band cutoff used elsewhere
# in the analysis pipeline (see analysis_service._verdict_for_mos).
DEFAULT_MOS_THRESHOLD = 30.0

# Default benchmark for the "vs Nifty" comparison. Nifty 500 is a
# better cross-cap match for our 3000-stock universe than Nifty 50,
# but the choice is debated — see design doc open question #3.
DEFAULT_BENCHMARK_TICKER = "NIFTY500.NS"


@dataclass
class PredictionRecord:
    """In-memory representation of one row from model_predictions_history."""
    id: int
    ticker: str
    prediction_date: date
    current_price: float
    fair_value: Optional[float]
    margin_of_safety_pct: Optional[float]
    yieldiq_score: Optional[int]
    grade: Optional[str]
    verdict: Optional[str]
    cache_version_at_prediction: int


# ─────────────────────────────────────────────────────────────────
# Snapshot writer
# ─────────────────────────────────────────────────────────────────

def record_daily_predictions(
    snapshot_date: date,
    *,
    session: Any | None = None,
    cache_version: Optional[int] = None,
) -> int:
    """Snapshot today's analysis_cache + price into model_predictions_history.

    Cron-driven (intended schedule: 19:30 IST after daily_prices ETL).
    Returns number of rows written.

    Implementation sketch (NOT executed in scaffolding PR):
        SELECT a.ticker, a.fair_value, a.margin_of_safety_pct,
               a.yieldiq_score, a.grade, a.verdict, a.cache_version,
               dp.close AS current_price
          FROM analysis_cache a
          JOIN daily_prices dp
            ON dp.ticker = a.ticker AND dp.date = :snapshot_date
         WHERE a.cache_version = :live_cache_version

        INSERT INTO model_predictions_history (...)
        VALUES (...)
        ON CONFLICT (ticker, prediction_date) DO NOTHING;

    The ON CONFLICT clause makes daily re-runs idempotent — important
    because the cron will retry on transient Aiven blips.
    """
    if session is None:
        # TODO(task12-phase2): wire real DB session via
        #   backend.services.analysis_service._get_pipeline_session
        # and the live CACHE_VERSION constant. Stubbed for the
        # scaffolding PR so unit tests don't need a database.
        logger.warning(
            "record_daily_predictions called without session; "
            "scaffolding stub returning 0 rows. snapshot_date=%s",
            snapshot_date,
        )
        return 0

    raise NotImplementedError(
        "record_daily_predictions full implementation lands in Task 12 Phase 2. "
        "See backend/services/retrospective_service.py docstring for SQL sketch."
    )


# ─────────────────────────────────────────────────────────────────
# Outcome computation
# ─────────────────────────────────────────────────────────────────

def compute_outcome(
    prediction_id: int,
    outcome_date: date,
    *,
    session: Any | None = None,
) -> Optional[dict]:
    """Fill one (prediction, outcome_date) row in prediction_outcomes.

    Reads the close from daily_prices on outcome_date, divides against
    the prediction's stored current_price, upserts return_pct.

    Returns the upserted row as a dict, or None if the price was
    missing (suspended / delisted — survivorship bias matters here,
    see design doc).
    """
    if session is None:
        logger.warning(
            "compute_outcome called without session; "
            "scaffolding stub returning None. prediction_id=%s outcome_date=%s",
            prediction_id, outcome_date,
        )
        return None

    raise NotImplementedError(
        "compute_outcome full implementation lands in Task 12 Phase 2."
    )


def compute_outcomes_for_window(
    prediction_id: int,
    prediction_date: date,
    *,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    session: Any | None = None,
) -> list[dict]:
    """Batch wrapper: compute_outcome for each (prediction, t+window) pair.

    Skips windows whose outcome_date is in the future. Used by both
    the daily cron (catching up t+30 etc. for old predictions) and
    the backfill script.
    """
    today = date.today()
    written: list[dict] = []
    for w in windows:
        outcome_date = prediction_date + timedelta(days=w)
        if outcome_date > today:
            # Future window — outcome doesn't exist yet, skip silently.
            continue
        row = compute_outcome(prediction_id, outcome_date, session=session)
        if row is not None:
            written.append(row)
    return written


# ─────────────────────────────────────────────────────────────────
# Summary — the function the public page actually reads
# ─────────────────────────────────────────────────────────────────

def summarize_for_period(
    start_date: date,
    end_date: date,
    *,
    mos_threshold: float = DEFAULT_MOS_THRESHOLD,
    window: int = 90,
    benchmark_ticker: str = DEFAULT_BENCHMARK_TICKER,
    predictions: Optional[Iterable[dict]] = None,
    benchmark_return_pct: Optional[float] = None,
) -> dict:
    """Aggregate retrospective stats for a [start_date, end_date] period.

    Returned dict shape (this is the public-page contract):

        {
          "period":        {"start": "...", "end": "...", "label": "Q1FY26"},
          "window_days":   90,
          "mos_threshold": 30.0,
          "n_predictions": 47,
          "mean_return":   12.4,
          "median_return": 9.8,
          "hit_rate":      0.638,        # share with return > 0
          "outperform_rate": 0.553,      # share that beat benchmark
          "benchmark":     {
              "ticker": "NIFTY500.NS",
              "return_pct": 6.2,
          },
          "winners":       [{"ticker": "...", "return_pct": ...}, ...],  # top 5
          "losers":        [{"ticker": "...", "return_pct": ...}, ...],  # bottom 5
        }

    Parameters
    ----------
    predictions
        Optional iterable of dicts with keys:
            ticker, prediction_date, margin_of_safety_pct, return_pct
        If supplied, no DB hit — used for tests and fixture-driven
        rendering. If None, the function would query the joined
        history+outcomes view (raises NotImplementedError in scaffolding).
    benchmark_return_pct
        Pre-computed Nifty (or whichever) return for the same window.
        Required when ``predictions`` is supplied; otherwise the
        function would compute it from daily_prices.
    """
    if predictions is None:
        # TODO(task12-phase2): SQL like
        #   SELECT h.ticker, h.prediction_date, h.margin_of_safety_pct,
        #          o.return_pct
        #     FROM model_predictions_history h
        #     JOIN prediction_outcomes o ON o.prediction_id = h.id
        #    WHERE h.prediction_date BETWEEN :start AND :end
        #      AND o.outcome_date = h.prediction_date + :window
        #      AND h.margin_of_safety_pct >= :mos_threshold;
        raise NotImplementedError(
            "summarize_for_period needs DB wiring; pass predictions=... for now."
        )

    if benchmark_return_pct is None:
        raise ValueError(
            "benchmark_return_pct must be supplied when predictions is given"
        )

    qualifying = [
        p for p in predictions
        if p.get("margin_of_safety_pct") is not None
        and float(p["margin_of_safety_pct"]) >= mos_threshold
        and p.get("return_pct") is not None
    ]

    n = len(qualifying)
    if n == 0:
        return {
            "period": {
                "start": start_date.isoformat(),
                "end":   end_date.isoformat(),
                "label": _period_label(start_date, end_date),
            },
            "window_days": window,
            "mos_threshold": mos_threshold,
            "n_predictions": 0,
            "mean_return": None,
            "median_return": None,
            "hit_rate": None,
            "outperform_rate": None,
            "benchmark": {
                "ticker": benchmark_ticker,
                "return_pct": benchmark_return_pct,
            },
            "winners": [],
            "losers": [],
        }

    returns = [float(p["return_pct"]) for p in qualifying]
    hits = sum(1 for r in returns if r > 0)
    outperformers = sum(1 for r in returns if r > benchmark_return_pct)

    # Sort once, slice from both ends.
    sorted_by_return = sorted(
        qualifying, key=lambda p: float(p["return_pct"]), reverse=True,
    )
    winners = [
        {"ticker": p["ticker"], "return_pct": round(float(p["return_pct"]), 2)}
        for p in sorted_by_return[:5]
    ]
    losers = [
        {"ticker": p["ticker"], "return_pct": round(float(p["return_pct"]), 2)}
        for p in sorted_by_return[-5:][::-1]
    ]

    return {
        "period": {
            "start": start_date.isoformat(),
            "end":   end_date.isoformat(),
            "label": _period_label(start_date, end_date),
        },
        "window_days": window,
        "mos_threshold": mos_threshold,
        "n_predictions": n,
        "mean_return":   round(statistics.fmean(returns), 2),
        "median_return": round(statistics.median(returns), 2),
        "hit_rate":         round(hits / n, 4),
        "outperform_rate":  round(outperformers / n, 4),
        "benchmark": {
            "ticker": benchmark_ticker,
            "return_pct": round(float(benchmark_return_pct), 2),
        },
        "winners": winners,
        "losers": losers,
    }


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────

def _period_label(start_date: date, end_date: date) -> str:
    """Best-effort 'Q1FY26' / 'Q4FY25' style label.

    Indian fiscal year runs Apr–Mar, so:
        Apr–Jun = Q1, Jul–Sep = Q2, Oct–Dec = Q3, Jan–Mar = Q4
    FY label is the calendar year of the END of the fiscal year, so
    Apr 2025 – Mar 2026 = FY26.
    """
    # If the range doesn't sit cleanly inside one quarter, fall back
    # to ISO dates rather than mislabel.
    s, e = start_date, end_date
    if s.year != e.year and not (s.month >= 10 and e.month <= 3 and e.year == s.year + 1):
        return f"{s.isoformat()}–{e.isoformat()}"

    month = s.month
    if 4 <= month <= 6:
        q = 1; fy_year = s.year + 1
    elif 7 <= month <= 9:
        q = 2; fy_year = s.year + 1
    elif 10 <= month <= 12:
        q = 3; fy_year = s.year + 1
    else:                              # Jan–Mar
        q = 4; fy_year = s.year

    return f"Q{q}FY{fy_year % 100:02d}"
