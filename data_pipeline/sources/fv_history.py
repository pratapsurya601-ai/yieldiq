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

    Called after every successful analysis. Never raises —
    the caller always wraps this in try/except so a DB hiccup
    can never break the analysis response.
    """
    today = date.today()
    try:
        existing = (
            db.query(FairValueHistory)
            .filter_by(ticker=ticker, date=today)
            .first()
        )
        if existing:
            existing.fair_value = round(fv, 2)
            existing.price = round(price, 2)
            existing.mos_pct = round(mos, 1)
            existing.verdict = verdict
            existing.wacc = round(wacc, 4)
            existing.confidence = confidence
            existing.updated_at = datetime.utcnow()
        else:
            db.add(FairValueHistory(
                ticker=ticker,
                date=today,
                fair_value=round(fv, 2),
                price=round(price, 2),
                mos_pct=round(mos, 1),
                verdict=verdict,
                wacc=round(wacc, 4),
                confidence=confidence,
            ))
        db.commit()
        log.debug(
            "FV history stored: %s FV=%.2f Price=%.2f MoS=%.1f%%",
            ticker, fv, price, mos,
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
