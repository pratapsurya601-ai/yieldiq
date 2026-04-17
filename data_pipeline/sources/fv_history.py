# data_pipeline/sources/fv_history.py
"""
Fair value history — forward-fill mechanism.

Called after every successful analysis to build up a per-day
history of YieldIQ fair value estimates alongside the market
price. No retroactive backfill — history grows forward from
the first day a ticker is analysed.
"""
from __future__ import annotations

import logging
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from data_pipeline.models import FairValueHistory

log = logging.getLogger("yieldiq.fv_history")


def _compute_smoothed_fv(
    ticker: str,
    today_fv: float,
    today_date,
    db: Session,
) -> float:
    """
    3-day EMA smoothing. Blends today's raw FV with the last two
    persisted days using weights 0.5/0.3/0.2. Absorbs residual noise
    from small yfinance input revisions. Cosmetic stabilization for
    the history chart -- live /og-data still returns raw FV.
    Returns today_fv unchanged if we have <2 historical rows.
    """
    try:
        prev = (
            db.query(FairValueHistory)
            .filter(
                FairValueHistory.ticker == ticker,
                FairValueHistory.date < today_date,
            )
            .order_by(FairValueHistory.date.desc())
            .limit(2)
            .all()
        )
        if len(prev) >= 2 and prev[0].fair_value and prev[1].fair_value:
            y1, y2 = float(prev[0].fair_value), float(prev[1].fair_value)
            return 0.5 * today_fv + 0.3 * y1 + 0.2 * y2
        if len(prev) == 1 and prev[0].fair_value:
            y1 = float(prev[0].fair_value)
            return 0.6 * today_fv + 0.4 * y1
    except Exception:
        pass
    return today_fv


def _warn_if_volatile(
    ticker: str,
    today_fv: float,
    today_price: float,
    today_date,
    db: Session,
) -> None:
    """
    Observability: log WARN when fair value swings >15% day-over-day
    while market price barely moved (<3%). Signals a DCF internal
    threshold flip (candidate switching, growth-branch toggle) rather
    than a legitimate business-reason revaluation.
    """
    try:
        yday = (
            db.query(FairValueHistory)
            .filter(
                FairValueHistory.ticker == ticker,
                FairValueHistory.date < today_date,
            )
            .order_by(FairValueHistory.date.desc())
            .first()
        )
        if not yday or not yday.fair_value or not yday.price:
            return
        y_fv, y_px = float(yday.fair_value), float(yday.price)
        if y_fv <= 0 or y_px <= 0:
            return
        fv_drift = abs(today_fv - y_fv) / y_fv
        px_drift = abs(today_price - y_px) / y_px
        if fv_drift > 0.15 and px_drift < 0.03:
            log.warning(
                "DCF_VOLATILITY: %s FV %.2f->%.2f (%.1f%% drift) "
                "price %.2f->%.2f (%.1f%%) -- potential candidate switch "
                "or growth-branch toggle",
                ticker, y_fv, today_fv, fv_drift * 100,
                y_px, today_price, px_drift * 100,
            )
    except Exception:
        pass


def store_today_fair_value(
    ticker: str,
    fv: float,
    price: float,
    mos: float,
    verdict: str,
    wacc: float,
    confidence: int,
    db: Session,
) -> None:
    """
    Upsert today's fair value estimate for ``ticker``.

    Called after every successful analysis. Never raises --
    the caller always wraps this in try/except so a DB hiccup
    can never break the analysis response.

    Applies 3-day EMA smoothing to the PERSISTED value (live
    /og-data still returns the raw FV from analysis_service).
    Also emits DCF_VOLATILITY WARN when FV drift is suspiciously
    high vs price drift.
    """
    today = date.today()
    try:
        # Observability before any mutation
        _warn_if_volatile(ticker, fv, price, today, db)

        # EMA smoothing of persisted value -- cosmetic stabilization
        smoothed_fv = _compute_smoothed_fv(ticker, fv, today, db)
        # Recompute MoS against the smoothed value so chart stats stay consistent
        smoothed_mos = (
            round((smoothed_fv - price) / price * 100, 1) if price > 0 else mos
        )

        existing = (
            db.query(FairValueHistory)
            .filter_by(ticker=ticker, date=today)
            .first()
        )
        if existing:
            existing.fair_value = round(smoothed_fv, 2)
            existing.price = round(price, 2)
            existing.mos_pct = smoothed_mos
            existing.verdict = verdict
            existing.wacc = round(wacc, 4)
            existing.confidence = confidence
            existing.updated_at = datetime.utcnow()
        else:
            db.add(FairValueHistory(
                ticker=ticker,
                date=today,
                fair_value=round(smoothed_fv, 2),
                price=round(price, 2),
                mos_pct=smoothed_mos,
                verdict=verdict,
                wacc=round(wacc, 4),
                confidence=confidence,
            ))
        db.commit()
        log.debug(
            "FV history stored: %s raw_fv=%.2f smoothed_fv=%.2f price=%.2f",
            ticker, fv, smoothed_fv, price,
        )
    except Exception as exc:
        log.warning("store_today_fair_value failed for %s: %s", ticker, exc)
        try:
            db.rollback()
        except Exception:
            pass


def get_fv_history(
    ticker: str,
    db: Session,
    years: int = 3,
) -> list[dict]:
    """Return chronological FV history for ``ticker`` covering ``years`` years."""
    cutoff = date.today() - timedelta(days=years * 365)
    rows = (
        db.query(FairValueHistory)
        .filter(
            FairValueHistory.ticker == ticker,
            FairValueHistory.date >= cutoff,
        )
        .order_by(FairValueHistory.date.asc())
        .all()
    )
    return [
        {
            "date": r.date.isoformat(),
            "fair_value": r.fair_value,
            "price": r.price,
            "mos_pct": r.mos_pct,
            "verdict": r.verdict,
        }
        for r in rows
    ]


def get_fv_history_summary(
    ticker: str,
    db: Session,
    years: int = 3,
) -> dict:
    """Aggregate stats used by the chart caption."""
    rows = get_fv_history(ticker, db, years)
    if not rows:
        return {
            "has_data": False,
            "data_start_date": None,
            "total_points": 0,
            "pct_undervalued": None,
            "pct_overvalued": None,
        }
    total = len(rows)
    undervalued = sum(1 for r in rows if r["price"] < r["fair_value"])
    return {
        "has_data": True,
        "data_start_date": rows[0]["date"],
        "total_points": total,
        "pct_undervalued": round(undervalued / total * 100),
        "pct_overvalued": round((total - undervalued) / total * 100),
    }
