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


# ── Skip-rules for the live write-hook (Phase 1 task #264) ──────
# Verdicts that mean "the engine could not produce a chartable point".
# We refuse to persist a row when the verdict is one of these even if
# the FV value technically passed the > 0 numeric gate, because the
# value is either a clamp / floor / placeholder and persisting it
# would pollute the per-ticker history that ValuationHistoryChart
# (task #265) renders. Backfills bypass this filter — they have their
# own provenance flag ('snapshot' / 'golden') and the live-hook gate
# only applies to provenance='live'.
NON_CHARTABLE_VERDICTS = frozenset({
    "data_limited",   # bound-clamp tripped; FV is a sentinel, not a model output
    "unavailable",    # collector returned no usable inputs
    "under_review",   # transient quarantine — not a stable historical anchor
})


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


def _previous_fv(ticker: str, today_date, db: Session) -> float | None:
    """Return the most-recent prior fair_value for ticker, or None.

    Caller pattern: the FV-write sanity gate (ROOT CAUSE #12)
    needs the day-1 anchor to compute the |Δ| guard. Pure read,
    swallow errors.
    """
    try:
        prev = (
            db.query(FairValueHistory)
            .filter(
                FairValueHistory.ticker == ticker,
                FairValueHistory.date < today_date,
            )
            .order_by(FairValueHistory.date.desc())
            .first()
        )
        if prev and prev.fair_value:
            return float(prev.fair_value)
    except Exception:
        return None
    return None


def store_today_fair_value(
    ticker: str,
    fv: float,
    price: float,
    mos: float,
    verdict: str,
    wacc: float,
    confidence: int,
    db: Session,
    yieldiq_score: int | None = None,
    grade: str | None = None,
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

    Skip-rules (Phase 1 task #264 — write-hook hardening):
      * fv <= 0 or price <= 0 — degenerate inputs, can't compute MoS.
      * verdict in NON_CHARTABLE_VERDICTS — clamp / sentinel output
        that would pollute the per-ticker chart (task #265).
    Skipped rows DO NOT raise; they log at DEBUG and return cleanly so
    the analyze() caller never sees a difference. Quarantine columns
    on existing rows are NEVER overwritten — the UPDATE branch only
    touches engine-output columns.

    ROOT CAUSE #13 (2026-06-11): ``yieldiq_score`` + ``grade`` are
    now persisted alongside fv/mos so peers_service._cached_score has
    a DB fallback for the peer SCORE column. Both kwargs default to
    None for backward compatibility with the workflow-only call sites
    (snapshot_fv_history / backfill_fair_value_history_monthly) that
    don't have a score to persist — those leave the columns NULL and
    the frontend renders the peer score as `—` until the row is
    re-touched by the live write-hook.

    Write-time sanity gate (ROOT CAUSE #12):
    After all skip-rules pass and BEFORE the upsert, the FV is
    compared against the previous day's row. Daily |Δ| > 25 %
    must be corroborated by a manifest entry / corporate action /
    concall_ai_summary landing on the same date, else the row is
    routed to ``fair_value_history_quarantine`` instead of the
    canonical table. See
    ``backend.services.fair_value_history_writer`` for the policy.
    """
    today = date.today()
    try:
        # ── Gate: numeric inputs ─────────────────────────────────
        if fv is None or price is None or fv <= 0 or price <= 0:
            log.debug(
                "FV history skipped for %s: degenerate inputs (fv=%s, price=%s)",
                ticker, fv, price,
            )
            return

        # ── Gate: verdict is chartable ───────────────────────────
        # Verdicts like 'data_limited' carry clamped FV values that
        # are not real model output; persisting them would corrupt
        # the history chart.
        if verdict in NON_CHARTABLE_VERDICTS:
            log.debug(
                "FV history skipped for %s: non-chartable verdict=%s",
                ticker, verdict,
            )
            return

        # Observability before any mutation
        _warn_if_volatile(ticker, fv, price, today, db)

        # EMA smoothing of persisted value -- cosmetic stabilization
        smoothed_fv = _compute_smoothed_fv(ticker, fv, today, db)
        # Recompute MoS against the smoothed value so chart stats stay consistent
        smoothed_mos = (
            round((smoothed_fv - price) / price * 100, 1) if price > 0 else mos
        )

        # ── Gate: write-time sanity (ROOT CAUSE #12) ──────────────
        # Compare smoothed_fv against the previous day's row.
        # If the |Δ| exceeds 25 % AND no corroborating manifest /
        # corporate action / concall summary lands on today's
        # date, route the row to quarantine instead of polluting
        # the canonical table.
        try:
            from backend.services.fair_value_history_writer import (
                insert_into_quarantine,
                should_persist_fv_row,
            )
            from backend.services.cache_invalidation_manifest import MANIFEST
            prev_fv = _previous_fv(ticker, today, db)
            decision = should_persist_fv_row(
                ticker=ticker,
                today_fv=smoothed_fv,
                prev_fv=prev_fv,
                write_date=today,
                manifest_entries=MANIFEST,
                db_session=db,
            )
        except Exception as exc:
            # Defensive: a gate-import failure must NEVER block writes.
            log.debug("FV writer gate import failed for %s: %s", ticker, exc)
            decision = None

        if decision is not None and not decision.persist:
            log.warning(
                "FV history quarantined for %s: %s",
                ticker, decision.reason,
            )
            insert_into_quarantine(
                db,
                ticker=ticker,
                write_date=today,
                today_fv=round(smoothed_fv, 2),
                prev_fv=decision.prev_fv,
                decision=decision,
                price=round(price, 2),
                mos_pct=smoothed_mos,
                verdict=verdict,
            )
            return

        existing = (
            db.query(FairValueHistory)
            .filter_by(ticker=ticker, date=today)
            .first()
        )
        # ROOT CAUSE #13 (2026-06-11): clamp score to the constraint
        # range so a stray engine value can never tip the row into a
        # CHECK violation that rolls back the whole write.
        score_clamped: int | None = None
        if yieldiq_score is not None:
            try:
                score_clamped = max(0, min(100, int(yieldiq_score)))
            except (TypeError, ValueError):
                score_clamped = None
        grade_clean = grade if (grade and isinstance(grade, str) and len(grade) <= 4) else None

        if existing:
            existing.fair_value = round(smoothed_fv, 2)
            existing.price = round(price, 2)
            existing.mos_pct = smoothed_mos
            existing.verdict = verdict
            existing.wacc = round(wacc, 4)
            existing.confidence = confidence
            # Only overwrite score/grade when the caller provided one —
            # an unscored backfill row should not blank a previously
            # populated value.
            if score_clamped is not None:
                existing.yieldiq_score = score_clamped
            if grade_clean is not None:
                existing.grade = grade_clean
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
                yieldiq_score=score_clamped,
                grade=grade_clean,
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
            # Step B (2026-05-17): derived true Buffett MoS from stored
            # FV/price; the FV history table itself stores upside % only.
            "buffett_mos_pct": (
                round((r.fair_value - r.price) / r.fair_value * 100.0, 2)
                if (r.fair_value and r.fair_value > 0 and r.price and r.price > 0)
                else None
            ),
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
