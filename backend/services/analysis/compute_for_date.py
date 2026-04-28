# backend/services/analysis/compute_for_date.py
# ═══════════════════════════════════════════════════════════════
# Counterfactual reconstruction entry point for the Performance
# Retrospective (Task 12 Phase 2).
#
# Given a (ticker, as_of_date) pair, return what the CURRENT model
# would say about FV / MoS / score using the price that was live on
# as_of_date. The function exists so scripts/backfill_predictions.py
# can populate model_predictions_history for past dates without
# reimplementing the DCF.
#
# ──────────────────────────────────────────────────────────────────
# IMPORTANT — pragmatic scope (called out explicitly in the PR body)
# ──────────────────────────────────────────────────────────────────
# A *strict* counterfactual would re-run the DCF using ONLY financials
# whose `period_end <= as_of_date`. That requires threading an
# `_as_of_date` parameter through ~12 functions in
# backend/services/analysis/db.py and the screener engines, all of
# which currently fetch "latest" via `ORDER BY period_end DESC LIMIT 1`.
# Doing that safely is a multi-PR refactor and risks regressing the
# live analysis pipeline.
#
# This module therefore ships the SIMPLER variant:
#
#   * Fair value, score, grade, verdict   ← computed against CURRENT
#                                           financials (latest XBRL)
#   * current_price, margin_of_safety_pct ← reprojected against the
#                                           HISTORICAL daily_prices
#                                           close on as_of_date
#
# For a 30-day backfill window the financials snapshot is essentially
# unchanged, so the simpler variant is materially honest. For a 90-day
# or longer window, FY-end results that landed inside the window WILL
# leak into earlier snapshots (look-ahead bias on financials, no
# look-ahead on price). This caveat is documented at the top of the
# public methodology page.
#
# Phase 3 (90d × 3000 stocks rollout) should land the strict variant
# behind a `--strict` flag. The function signature here is stable;
# only the internals change.
# ══════════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date
from typing import Any, Optional

from sqlalchemy import text

logger = logging.getLogger("yieldiq.compute_for_date")


@dataclass
class HistoricalPrediction:
    """One row's worth of model output for (ticker, as_of_date).

    Shape mirrors what model_predictions_history needs to INSERT.
    Fair-value-and-score fields come from the current model run;
    price/mos fields come from the historical close.
    """
    ticker: str
    as_of_date: date
    current_price: float
    fair_value: Optional[float]
    margin_of_safety_pct: Optional[float]
    yieldiq_score: Optional[int]
    grade: Optional[str]
    verdict: Optional[str]
    cache_version: int


def _historical_close(session: Any, ticker: str, as_of_date: date) -> Optional[float]:
    """Look up the closest trading-day close for `ticker` at or before `as_of_date`.

    NSE holidays / weekends mean as_of_date may not have a row in
    daily_prices. We accept the closest prior trading day within a
    7-day window; further back than that we treat the data as missing
    (delisted / data gap — survivorship bias, see methodology doc).

    Strips `.NS` / `.BO` suffix because daily_prices keys on the bare
    NSE symbol (per data_pipeline/models.py:18).
    """
    bare = ticker.replace(".NS", "").replace(".BO", "").upper().strip()
    sql = text(
        """
        SELECT close_price
          FROM daily_prices
         WHERE ticker = :ticker
           AND trade_date <= :as_of
           AND trade_date >= :floor
         ORDER BY trade_date DESC
         LIMIT 1
        """
    )
    from datetime import timedelta
    row = session.execute(
        sql,
        {"ticker": bare, "as_of": as_of_date, "floor": as_of_date - timedelta(days=7)},
    ).fetchone()
    if row is None or row[0] is None:
        return None
    try:
        return float(row[0])
    except (TypeError, ValueError):
        return None


def compute_for_date(
    ticker: str,
    as_of_date: date,
    *,
    session: Any | None = None,
) -> Optional[HistoricalPrediction]:
    """Return the current model's view of `ticker` reprojected onto `as_of_date`.

    Parameters
    ----------
    ticker
        Canonical ticker (with or without `.NS` suffix; both accepted).
    as_of_date
        Historical trading date for the price snapshot.
    session
        SQLAlchemy session against the pipeline DB. If None, the
        function builds one via `_get_pipeline_session` and closes
        it before returning.

    Returns
    -------
    HistoricalPrediction or None
        None when the ticker has no daily_prices row within 7 days of
        `as_of_date` (delisted / data gap) or when the current model
        cannot price it (TickerNotFoundError, validator veto).
    """
    from backend.services.analysis.service import (
        AnalysisService, TickerNotFoundError,
    )
    from backend.services.analysis.db import _get_pipeline_session
    from backend.services.cache_service import CACHE_VERSION

    owned_session = False
    if session is None:
        session = _get_pipeline_session()
        owned_session = True
    if session is None:
        logger.warning(
            "compute_for_date(%s, %s): no DB session available", ticker, as_of_date,
        )
        return None

    try:
        historical_price = _historical_close(session, ticker, as_of_date)
        if historical_price is None or historical_price <= 0:
            logger.info(
                "compute_for_date(%s, %s): no historical price within 7d window",
                ticker, as_of_date,
            )
            return None

        # Run the current full pipeline. We deliberately accept that
        # this uses today's financials snapshot — see module docstring.
        try:
            svc = AnalysisService()
            result = svc.get_full_analysis(ticker)
        except TickerNotFoundError:
            logger.info(
                "compute_for_date(%s, %s): ticker not found by current pipeline",
                ticker, as_of_date,
            )
            return None
        except Exception as exc:
            logger.warning(
                "compute_for_date(%s, %s): pipeline raised %s: %s",
                ticker, as_of_date, type(exc).__name__, exc,
            )
            return None

        valuation = getattr(result, "valuation", None)
        if valuation is None:
            return None

        fair_value = float(getattr(valuation, "fair_value", 0) or 0) or None
        verdict = getattr(valuation, "verdict", None)
        grade = None
        score = None
        try:
            quality = getattr(result, "quality", None)
            if quality is not None:
                grade = getattr(quality, "grade", None)
                score = getattr(quality, "yieldiq_score", None)
        except Exception:
            pass

        # Reproject MoS onto the historical price. Same formula the
        # live pipeline uses (see screener.dcf_engine.margin_of_safety
        # and analysis/service.py:749).
        if fair_value and historical_price > 0:
            mos_pct = round(((fair_value - historical_price) / historical_price) * 100, 2)
        else:
            mos_pct = None

        return HistoricalPrediction(
            ticker=ticker,
            as_of_date=as_of_date,
            current_price=round(historical_price, 2),
            fair_value=round(fair_value, 2) if fair_value else None,
            margin_of_safety_pct=mos_pct,
            yieldiq_score=int(score) if score is not None else None,
            grade=str(grade) if grade else None,
            verdict=str(verdict) if verdict else None,
            cache_version=int(CACHE_VERSION),
        )
    finally:
        if owned_session:
            try:
                session.close()
            except Exception:
                pass
