"""filing_alert_service.py — SCAFFOLDING for filing-driven alerts.

When a quarterly result lands in `sebi_filings_queue` with status
'ingested', we want to notify users who hold or watch that ticker.

This module is the join point between the crawler and the existing
`backend/services/notifications_service.py` pipeline. The actual
dispatch is STUBBED — the real version should:

* Look up watchlist + holdings rows for the ticker.
* For each user, check tier-eligibility via
  `notifications_service.can_receive(user_tier, "model_update")`.
* Queue a 'model_update' notification with metadata
  {ticker, fiscal_period, filing_date, source_url}.
* Dedupe against any notification fired in the last 24h for the same
  (user_id, ticker, fiscal_period) tuple.

Dispatch latency policy (see design doc Q5): batched to the next
07:30 IST mail run rather than fired at midnight, except when the
filing implies a price-moving change > X% (TBD).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Optional

logger = logging.getLogger("yieldiq.filing_alerts")


@dataclass
class FilingAlertResult:
    ticker: str
    fiscal_period: Optional[str]
    notified_user_count: int
    skipped_user_count: int
    dry_run: bool


def _eligible_users_for_ticker(ticker: str, *, conn=None) -> list[dict]:
    """Return [{user_id, tier}, ...] for users with `ticker` in watchlist
    or holdings. STUB — returns []."""
    logger.info("eligible_users_for_ticker STUB ticker=%s", ticker)
    return []


def notify_users_of_new_quarterly(
    ticker: str,
    fiscal_period: Optional[str],
    *,
    source_url: Optional[str] = None,
    dry_run: bool = True,
    conn=None,
) -> FilingAlertResult:
    """Queue 'model_update' notifications for a newly ingested filing.

    SCAFFOLDING: dry_run defaults to True so the wiring can be exercised
    in tests without polluting the notifications table. The crawler
    must explicitly pass dry_run=False to actually fan out — and that
    flag should remain off until follow-up Phase 4 lands.
    """
    ticker_u = (ticker or "").upper().strip()
    if not ticker_u:
        return FilingAlertResult(ticker_u, fiscal_period, 0, 0, dry_run)

    users = _eligible_users_for_ticker(ticker_u, conn=conn)
    notified = 0
    skipped = 0

    for u in users:
        try:
            from backend.services.notifications_service import can_receive
        except Exception as exc:
            logger.warning("notifications_service import failed: %s", exc)
            return FilingAlertResult(ticker_u, fiscal_period, notified, skipped + len(users) - notified, dry_run)

        if not can_receive(u.get("tier", "free"), "model_update"):
            skipped += 1
            continue

        if dry_run:
            logger.info("DRY-RUN would notify user=%s ticker=%s period=%s",
                        u.get("user_id"), ticker_u, fiscal_period)
            notified += 1
            continue

        # Real path:
        #   notifications_service.create_notification(
        #       user_id=u["user_id"], type="model_update",
        #       title=f"{ticker_u} filed {fiscal_period}",
        #       metadata={"ticker": ticker_u, "fiscal_period": fiscal_period,
        #                 "source_url": source_url})
        # Intentionally NOT wired up — see Phase 4 follow-up.
        notified += 1

    logger.info("notify_users_of_new_quarterly ticker=%s period=%s notified=%d skipped=%d dry_run=%s",
                ticker_u, fiscal_period, notified, skipped, dry_run)
    return FilingAlertResult(ticker_u, fiscal_period, notified, skipped, dry_run)
