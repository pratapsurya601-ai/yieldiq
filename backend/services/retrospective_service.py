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
    # Phase 2 implementation: pulls today's analysis_cache rows and
    # joins them against daily_prices for snapshot_date, then UPSERTs
    # into model_predictions_history. Keeps cache_version in the row so
    # later audits can quarantine buggy-cohort predictions.
    from sqlalchemy import text

    if session is None:
        try:
            from backend.services.analysis.db import _get_pipeline_session
            session = _get_pipeline_session()
        except Exception:
            session = None
    if session is None:
        logger.warning(
            "record_daily_predictions: no DB session — returning 0. snapshot_date=%s",
            snapshot_date,
        )
        return 0

    if cache_version is None:
        try:
            from backend.services.cache_service import CACHE_VERSION as _CV
            cache_version = int(_CV)
        except Exception:
            cache_version = 0

    sql = text(
        """
        WITH live AS (
            SELECT a.ticker,
                   a.payload->'valuation'->>'fair_value'              AS fair_value,
                   a.payload->'valuation'->>'margin_of_safety_display' AS mos_pct,
                   a.payload->'valuation'->>'verdict'                  AS verdict,
                   a.payload->'quality'->>'yieldiq_score'              AS yieldiq_score,
                   a.payload->'quality'->>'grade'                      AS grade,
                   a.cache_version
              FROM analysis_cache a
             WHERE a.cache_version = :cv
        ),
        priced AS (
            SELECT live.*, dp.close_price
              FROM live
              JOIN daily_prices dp
                ON dp.ticker = REPLACE(REPLACE(live.ticker, '.NS', ''), '.BO', '')
               AND dp.trade_date = :d
        )
        INSERT INTO model_predictions_history (
            ticker, prediction_date, current_price, fair_value,
            margin_of_safety_pct, yieldiq_score, grade, verdict,
            cache_version_at_prediction
        )
        SELECT ticker, :d, close_price,
               NULLIF(fair_value, '')::NUMERIC,
               NULLIF(mos_pct, '')::NUMERIC,
               NULLIF(yieldiq_score, '')::INT,
               grade, verdict, cache_version
          FROM priced
         WHERE close_price IS NOT NULL
        ON CONFLICT (ticker, prediction_date) DO NOTHING
        """
    )
    try:
        result = session.execute(sql, {"cv": cache_version, "d": snapshot_date})
        session.commit()
        return int(result.rowcount or 0)
    except Exception as exc:
        session.rollback()
        logger.warning("record_daily_predictions failed: %s: %s",
                       type(exc).__name__, exc)
        return 0


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
    from sqlalchemy import text

    if session is None:
        try:
            from backend.services.analysis.db import _get_pipeline_session
            session = _get_pipeline_session()
        except Exception:
            session = None
    if session is None:
        logger.warning(
            "compute_outcome: no DB session, returning None (id=%s, date=%s)",
            prediction_id, outcome_date,
        )
        return None

    pred = session.execute(
        text(
            "SELECT ticker, current_price FROM model_predictions_history "
            "WHERE id = :id"
        ),
        {"id": prediction_id},
    ).fetchone()
    if pred is None or pred[1] is None or float(pred[1]) <= 0:
        return None
    ticker, cmp_price = pred[0], float(pred[1])
    bare = ticker.replace(".NS", "").replace(".BO", "").upper().strip()

    px = session.execute(
        text(
            "SELECT close_price FROM daily_prices "
            "WHERE ticker = :t AND trade_date <= :d "
            "  AND trade_date >= :floor "
            "ORDER BY trade_date DESC LIMIT 1"
        ),
        {"t": bare, "d": outcome_date,
         "floor": outcome_date - timedelta(days=7)},
    ).fetchone()
    if px is None or px[0] is None:
        return None
    outcome_price = float(px[0])
    return_pct = round(((outcome_price - cmp_price) / cmp_price) * 100, 2)

    try:
        session.execute(
            text(
                "INSERT INTO prediction_outcomes "
                "(prediction_id, outcome_date, outcome_price, return_pct) "
                "VALUES (:id, :d, :p, :r) "
                "ON CONFLICT (prediction_id, outcome_date) DO UPDATE "
                "SET outcome_price = EXCLUDED.outcome_price, "
                "    return_pct = EXCLUDED.return_pct, "
                "    computed_at = NOW()"
            ),
            {"id": prediction_id, "d": outcome_date,
             "p": round(outcome_price, 2), "r": return_pct},
        )
        session.commit()
    except Exception as exc:
        session.rollback()
        logger.warning("compute_outcome upsert failed (id=%s): %s",
                       prediction_id, exc)
        return None

    return {
        "prediction_id": prediction_id,
        "outcome_date": outcome_date.isoformat(),
        "outcome_price": round(outcome_price, 2),
        "return_pct": return_pct,
    }


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
        # DB-backed path. Joins model_predictions_history against
        # prediction_outcomes on the requested window. We tolerate
        # outcome_date drift of ±3 days because daily_prices is sparse
        # over weekends/holidays — the writer in compute_outcomes.py
        # already coalesces to the closest prior trading day, so the
        # exact addition can fall outside the table.
        from sqlalchemy import text
        try:
            from backend.services.analysis.db import _get_pipeline_session
            sess = _get_pipeline_session()
        except Exception:
            sess = None
        if sess is None:
            return _empty_summary(start_date, end_date, window,
                                  mos_threshold, benchmark_ticker,
                                  benchmark_return_pct)
        try:
            rows = sess.execute(
                text(
                    """
                    SELECT h.ticker, h.prediction_date,
                           h.margin_of_safety_pct, o.return_pct
                      FROM model_predictions_history h
                      JOIN prediction_outcomes o ON o.prediction_id = h.id
                     WHERE h.prediction_date BETWEEN :s AND :e
                       AND h.margin_of_safety_pct >= :mos
                       AND o.outcome_date BETWEEN
                           h.prediction_date + (:w - 3) * INTERVAL '1 day'
                       AND h.prediction_date + (:w + 3) * INTERVAL '1 day'
                    """
                ),
                {"s": start_date, "e": end_date,
                 "mos": mos_threshold, "w": window},
            ).fetchall()
        finally:
            try:
                sess.close()
            except Exception:
                pass
        predictions = [
            {
                "ticker": r[0],
                "prediction_date": r[1].isoformat() if hasattr(r[1], "isoformat") else r[1],
                "margin_of_safety_pct": float(r[2]) if r[2] is not None else None,
                "return_pct": float(r[3]) if r[3] is not None else None,
            }
            for r in rows
        ]
        if benchmark_return_pct is None:
            benchmark_return_pct = _fetch_benchmark_return(
                benchmark_ticker, start_date, end_date, window,
            )

    if benchmark_return_pct is None:
        # Try DB-backed lookup; fall back to 0.0 so the summary still
        # renders (rate fields use a 0% benchmark — the public page
        # surfaces this with a "benchmark unavailable" footnote).
        bench = _fetch_benchmark_return(
            benchmark_ticker, start_date, end_date, window,
        )
        benchmark_return_pct = 0.0 if bench is None else bench

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

def _empty_summary(start_date, end_date, window, mos_threshold,
                   benchmark_ticker, benchmark_return_pct):
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
            "return_pct": benchmark_return_pct if benchmark_return_pct is not None else 0.0,
        },
        "winners": [],
        "losers": [],
    }


def _fetch_benchmark_return(benchmark_ticker, start_date, end_date, window):
    """Compute the benchmark return for the period midpoint + window."""
    try:
        from sqlalchemy import text
        from backend.services.analysis.db import _get_pipeline_session
        sess = _get_pipeline_session()
        if sess is None:
            return None
        try:
            mid = start_date + (end_date - start_date) / 2
            outcome = mid + timedelta(days=window)
            bare = benchmark_ticker.replace(".NS", "").replace(".BO", "")
            start_px = sess.execute(
                text("SELECT close_price FROM daily_prices "
                     "WHERE ticker = :t AND trade_date <= :d "
                     "  AND trade_date >= :floor "
                     "ORDER BY trade_date DESC LIMIT 1"),
                {"t": bare, "d": mid, "floor": mid - timedelta(days=10)},
            ).fetchone()
            end_px = sess.execute(
                text("SELECT close_price FROM daily_prices "
                     "WHERE ticker = :t AND trade_date <= :d "
                     "  AND trade_date >= :floor "
                     "ORDER BY trade_date DESC LIMIT 1"),
                {"t": bare, "d": outcome, "floor": outcome - timedelta(days=10)},
            ).fetchone()
            if not start_px or not end_px:
                return None
            sp, ep = float(start_px[0]), float(end_px[0])
            if sp <= 0:
                return None
            return round(((ep - sp) / sp) * 100, 2)
        finally:
            try:
                sess.close()
            except Exception:
                pass
    except Exception as exc:
        logger.warning("benchmark fetch failed: %s", exc)
        return None


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
