# backend/services/alerts_service.py
# ═══════════════════════════════════════════════════════════════
# Backend-driven alerts engine.
#
# This service powers the new `user_alerts` table (migration 009).
# It is distinct from the legacy `alert_service.py`, which targets the
# Supabase `price_alerts` table used by the older frontend flow.
#
# Responsibilities:
#   - Fetch latest price + MoS + verdict per ticker.
#   - Decide whether an alert's condition is met.
#   - Fire an email via email_service._send_email.
#   - Update last_checked_at / last_triggered_at / status.
#
# Called by scripts/alerts_evaluator.py (hourly GH Actions cron).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession

logger = logging.getLogger(__name__)

# ── Constants ─────────────────────────────────────────────────
# Don't re-fire an alert that has fired in the last N hours. Keeps a
# flapping ticker from spamming users once every hour.
COOLDOWN_HOURS = 24

# Alert kinds that are "one-shot": once fired, flip status to 'triggered'
# so the evaluator stops checking them. Verdict_change and MoS threshold
# crosses are better modelled as one-shot — user can re-arm from the UI.
ONE_SHOT_KINDS: frozenset[str] = frozenset(
    {"mos_above", "mos_below", "price_above", "price_below", "verdict_change"}
)


@dataclass
class TickerSnapshot:
    """Latest market snapshot for a single ticker."""

    ticker: str
    price: Optional[float]
    mos_pct: Optional[float]
    verdict: Optional[str]


# ── Data fetchers ─────────────────────────────────────────────

def _fetch_snapshots(session: OrmSession, tickers: Iterable[str]) -> dict[str, TickerSnapshot]:
    """Batch-fetch the latest price + MoS + verdict for each ticker.

    Reads:
      - market_metrics (latest trade_date per ticker) for price proxy:
        we fall back to fair_value_history.price which is populated by
        store_today_fair_value() on every analysis hit.
      - fair_value_history (latest date per ticker) for mos_pct + verdict.
    """
    out: dict[str, TickerSnapshot] = {}
    uniq = sorted({(t or "").strip().upper() for t in tickers if t})
    if not uniq:
        return out

    # Import inside the function to avoid hard-binding this module to
    # the data_pipeline package at import time (keeps unit tests light).
    from data_pipeline.models import FairValueHistory

    # fair_value_history carries price, mos_pct, and verdict on one row.
    # Use a DISTINCT ON (ticker) style to take the latest row per ticker.
    try:
        # Portable SQL: subquery the max(date) per ticker, then join.
        from sqlalchemy import func, and_

        subq = (
            session.query(
                FairValueHistory.ticker.label("t"),
                func.max(FairValueHistory.date).label("d"),
            )
            .filter(FairValueHistory.ticker.in_(uniq))
            .group_by(FairValueHistory.ticker)
            .subquery()
        )
        rows = (
            session.query(FairValueHistory)
            .join(
                subq,
                and_(
                    FairValueHistory.ticker == subq.c.t,
                    FairValueHistory.date == subq.c.d,
                ),
            )
            .all()
        )
        for r in rows:
            out[r.ticker] = TickerSnapshot(
                ticker=r.ticker,
                price=float(r.price) if r.price is not None else None,
                mos_pct=float(r.mos_pct) if r.mos_pct is not None else None,
                verdict=r.verdict,
            )
    except Exception as e:
        logger.warning("fair_value_history lookup failed: %s", e)

    # Any ticker without an FV row at all — seed an empty snapshot so
    # the evaluator can still log "skipped: no data".
    for t in uniq:
        out.setdefault(t, TickerSnapshot(ticker=t, price=None, mos_pct=None, verdict=None))
    return out


# ── Condition evaluation ──────────────────────────────────────

def _should_fire(
    kind: str,
    threshold: Optional[float],
    snap: TickerSnapshot,
    previous_verdict: Optional[str],
) -> bool:
    """Return True iff the alert's condition is currently met."""
    if kind == "price_above":
        return snap.price is not None and threshold is not None and snap.price >= threshold
    if kind == "price_below":
        return snap.price is not None and threshold is not None and snap.price <= threshold
    if kind == "mos_above":
        return snap.mos_pct is not None and threshold is not None and snap.mos_pct >= threshold
    if kind == "mos_below":
        return snap.mos_pct is not None and threshold is not None and snap.mos_pct <= threshold
    if kind == "verdict_change":
        # Fire when we have a current verdict AND it differs from the
        # last-seen verdict. On first run previous_verdict is None so we
        # don't fire (avoid a stampede the first time the evaluator runs).
        return bool(
            snap.verdict
            and previous_verdict
            and snap.verdict != previous_verdict
        )
    return False


def _in_cooldown(last_triggered_at: Optional[datetime]) -> bool:
    """True if the alert fired within the last COOLDOWN_HOURS."""
    if last_triggered_at is None:
        return False
    now = datetime.now(timezone.utc)
    # Normalise naive timestamps to UTC — DB returns TIMESTAMPTZ so this
    # is defence-in-depth for SQLite-backed tests.
    if last_triggered_at.tzinfo is None:
        last_triggered_at = last_triggered_at.replace(tzinfo=timezone.utc)
    return now - last_triggered_at < timedelta(hours=COOLDOWN_HOURS)


# ── User-email resolution ─────────────────────────────────────

def _resolve_email(user_id: str) -> Optional[str]:
    """Map user_id -> email via Supabase users_meta.

    Returns None if Supabase isn't configured or the lookup fails;
    the evaluator logs and skips the send in that case.
    """
    try:
        from db.supabase_client import get_admin_client
        client = get_admin_client()
        if client is None:
            return None
        # users_meta.user_id is the Supabase auth UUID (text).
        result = (
            client.table("users_meta")
            .select("email")
            .eq("user_id", user_id)
            .maybe_single()
            .execute()
        )
        if result and result.data:
            return result.data.get("email")
    except Exception as e:
        logger.debug("users_meta email lookup failed for %s: %s", user_id, e)
    return None


# ── Notification dispatch ─────────────────────────────────────

def _render_subject(kind: str, ticker: str, snap: TickerSnapshot, threshold: Optional[float]) -> str:
    display = ticker.replace(".NS", "").replace(".BO", "")
    if kind == "price_above" and threshold is not None:
        return f"YieldIQ Alert: {display} crossed above \u20b9{threshold:.0f}"
    if kind == "price_below" and threshold is not None:
        return f"YieldIQ Alert: {display} dropped below \u20b9{threshold:.0f}"
    if kind == "mos_above" and threshold is not None:
        return f"YieldIQ Alert: {display} MoS above {threshold:.0f}%"
    if kind == "mos_below" and threshold is not None:
        return f"YieldIQ Alert: {display} MoS below {threshold:.0f}%"
    if kind == "verdict_change":
        return f"YieldIQ Alert: {display} verdict changed to {snap.verdict or 'Unknown'}"
    return f"YieldIQ Alert: {display}"


def _render_html(kind: str, ticker: str, snap: TickerSnapshot, threshold: Optional[float]) -> str:
    display = ticker.replace(".NS", "").replace(".BO", "")
    price = f"\u20b9{snap.price:,.2f}" if snap.price is not None else "n/a"
    mos = f"{snap.mos_pct:.1f}%" if snap.mos_pct is not None else "n/a"
    verdict = snap.verdict or "n/a"
    thr = f"{threshold:g}" if threshold is not None else "\u2014"
    return f"""
    <div style="font-family:-apple-system,Segoe UI,Roboto,Arial,sans-serif;
                max-width:560px;margin:0 auto;padding:24px;">
      <h2 style="margin:0 0 8px;color:#0F172A;">{display}: {kind.replace('_',' ')}</h2>
      <p style="color:#475569;margin:0 0 16px;">
        Your alert condition was met. Current snapshot:
      </p>
      <table style="width:100%;border-collapse:collapse;font-size:14px;">
        <tr><td style="padding:6px 0;color:#64748B;">Price</td>
            <td style="text-align:right;font-weight:600;">{price}</td></tr>
        <tr><td style="padding:6px 0;color:#64748B;">MoS</td>
            <td style="text-align:right;font-weight:600;">{mos}</td></tr>
        <tr><td style="padding:6px 0;color:#64748B;">Verdict</td>
            <td style="text-align:right;font-weight:600;">{verdict}</td></tr>
        <tr><td style="padding:6px 0;color:#64748B;">Threshold</td>
            <td style="text-align:right;font-weight:600;">{thr}</td></tr>
      </table>
      <p style="margin-top:24px;">
        <a href="https://yieldiq.in/analysis/{ticker}"
           style="display:inline-block;padding:10px 20px;background:#2563EB;
                  color:#fff;text-decoration:none;border-radius:6px;">
          View full analysis &rarr;
        </a>
      </p>
    </div>
    """


def _send_alert_email(to_email: str, kind: str, ticker: str,
                     snap: TickerSnapshot, threshold: Optional[float]) -> bool:
    try:
        from backend.services.email_service import _send_email
    except Exception as e:
        logger.warning("email_service unavailable: %s", e)
        return False
    subject = _render_subject(kind, ticker, snap, threshold)
    html = _render_html(kind, ticker, snap, threshold)
    try:
        return bool(_send_email(to_email, subject, html))
    except Exception as e:
        logger.error("email send failed for %s: %s", to_email, e)
        return False


# ── Public entry point ────────────────────────────────────────

@dataclass
class EvaluationResult:
    alert_id: int
    user_id: str
    ticker: str
    kind: str
    threshold: Optional[float]
    fired: bool
    reason: str  # 'fired', 'cooldown', 'no_data', 'condition_not_met', 'no_email'


def evaluate_alerts(session: OrmSession, *, dry_run: bool = False) -> list[EvaluationResult]:
    """Run one evaluation pass over all active alerts.

    Args:
      session: a SQLAlchemy session bound to the Postgres engine that
        has the user_alerts + fair_value_history tables.
      dry_run: if True, don't send emails and don't persist
        last_triggered_at / status updates — only last_checked_at is
        still left untouched to keep the run idempotent.

    Returns a list of per-alert EvaluationResult records.
    """
    from backend.models.alerts import UserAlert

    active = (
        session.query(UserAlert)
        .filter(UserAlert.status == "active")
        .all()
    )
    if not active:
        logger.info("evaluate_alerts: no active alerts")
        return []

    # Batch-fetch snapshots once per ticker.
    tickers = {a.ticker for a in active}
    snapshots = _fetch_snapshots(session, tickers)
    now = datetime.now(timezone.utc)

    # Cache previous verdict per ticker — for verdict_change we compare
    # the current fair_value_history verdict against whatever verdict
    # was live at last_checked_at. We use the same snapshot verdict as
    # "current"; the "previous" needs the row from `fair_value_history`
    # at or before last_checked_at.
    previous_verdict_cache: dict[tuple[str, datetime], Optional[str]] = {}

    def _prev_verdict(ticker: str, before: Optional[datetime]) -> Optional[str]:
        if before is None:
            return None
        key = (ticker, before)
        if key in previous_verdict_cache:
            return previous_verdict_cache[key]
        try:
            from data_pipeline.models import FairValueHistory
            row = (
                session.query(FairValueHistory)
                .filter(
                    FairValueHistory.ticker == ticker,
                    FairValueHistory.date <= before.date(),
                )
                .order_by(FairValueHistory.date.desc())
                .first()
            )
            v = row.verdict if row else None
        except Exception:
            v = None
        previous_verdict_cache[key] = v
        return v

    results: list[EvaluationResult] = []
    for alert in active:
        ticker = (alert.ticker or "").strip().upper()
        snap = snapshots.get(ticker) or TickerSnapshot(ticker, None, None, None)
        threshold = float(alert.threshold) if alert.threshold is not None else None

        if snap.price is None and snap.mos_pct is None and snap.verdict is None:
            results.append(EvaluationResult(
                alert.id, alert.user_id, ticker, alert.kind, threshold,
                fired=False, reason="no_data",
            ))
            if not dry_run:
                alert.last_checked_at = now
            continue

        prev_verdict = _prev_verdict(ticker, alert.last_checked_at)
        condition_met = _should_fire(alert.kind, threshold, snap, prev_verdict)

        if not condition_met:
            results.append(EvaluationResult(
                alert.id, alert.user_id, ticker, alert.kind, threshold,
                fired=False, reason="condition_not_met",
            ))
            if not dry_run:
                alert.last_checked_at = now
            continue

        if _in_cooldown(alert.last_triggered_at):
            results.append(EvaluationResult(
                alert.id, alert.user_id, ticker, alert.kind, threshold,
                fired=False, reason="cooldown",
            ))
            if not dry_run:
                alert.last_checked_at = now
            continue

        # Fire!
        sent_ok = False
        if dry_run:
            sent_ok = True
        else:
            email = _resolve_email(alert.user_id) if alert.notify_email else None
            if email:
                sent_ok = _send_alert_email(email, alert.kind, ticker, snap, threshold)
            else:
                # No email on file — still mark triggered so we don't
                # spin on the same alert forever, but note the reason.
                sent_ok = False
                results.append(EvaluationResult(
                    alert.id, alert.user_id, ticker, alert.kind, threshold,
                    fired=False, reason="no_email",
                ))
                alert.last_checked_at = now
                continue

        results.append(EvaluationResult(
            alert.id, alert.user_id, ticker, alert.kind, threshold,
            fired=True, reason="fired" if sent_ok else "send_failed",
        ))

        if not dry_run:
            alert.last_checked_at = now
            if sent_ok:
                alert.last_triggered_at = now
                if alert.kind in ONE_SHOT_KINDS:
                    alert.status = "triggered"

    if not dry_run:
        session.commit()
    return results
