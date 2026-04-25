"""cron_earnings_reminder.py — Pro-tier earnings reminder source.

Given today's date, finds Pro users whose watchlist tickers have an
earnings call scheduled in the next 24 hours and creates an in-app
notification (type=earnings_reminder) per match.

Tier gating: only "pro" users receive earnings_reminder notifications.
This is enforced via notifications_service.can_receive() so any tier
expansion goes through the same chokepoint as every other event source.

Data source caveat (DOCUMENTED GAP):
    There is no first-class earnings_calendar table in this repo today.
    `corporate_actions` carries SPLIT / BONUS / DIVIDEND with an
    `ex_date` — it does NOT carry earnings call dates. As an interim
    stub we treat any DIVIDEND ex_date in the next 24h as a proxy for
    "earnings event soon" because a board meeting that declares an
    interim dividend is almost always the same meeting that publishes
    quarterly results. This is approximate and over-counts (an ex_date
    is when the share trades cum-/ex-dividend, not when the call
    happens). A future migration that wires NSE/BSE corporate-event
    feeds for "Board Meeting — Earnings" should replace _earnings_dates_for().

Usage (manual / testing — not yet wired into a GH Actions workflow):
    python -m backend.scripts.cron_earnings_reminder
    python -m backend.scripts.cron_earnings_reminder --dry-run

Exit codes:
    0  success (any number of notifications, including zero)
    1  unrecoverable error (DB unreachable, etc.)
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

# Allow `python backend/scripts/cron_earnings_reminder.py` direct invocation.
_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.services import notifications_service as notif_svc  # noqa: E402

logger = logging.getLogger("yieldiq.cron.earnings_reminder")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")


# ── Pro-tier user enumeration ─────────────────────────────────

def _list_pro_users() -> list[dict]:
    """Return [{user_id, email}] for every user currently on the Pro tier.

    Reads from Supabase users_meta. Returns [] on any failure (cron is
    fail-quiet — a one-day skip is preferable to a Sentry storm).
    """
    try:
        from db.supabase_client import get_admin_client  # type: ignore
    except Exception as exc:  # pragma: no cover — env-shape guard
        logger.warning("supabase admin client import failed: %s", exc)
        return []
    try:
        client = get_admin_client()
        if client is None:
            logger.warning("supabase admin client returned None — DATABASE_URL/keys missing?")
            return []
        rows = (
            client.table("users_meta")
            .select("user_id, email, tier")
            .eq("tier", "pro")
            .execute()
        )
        return [
            {"user_id": r["user_id"], "email": r.get("email")}
            for r in (rows.data or [])
            if r.get("user_id")
        ]
    except Exception:
        logger.exception("listing Pro users failed")
        return []


# ── Watchlist enumeration ─────────────────────────────────────

def _watchlist_tickers(user_id: str) -> list[str]:
    """Return the tickers in the user's watchlist (Supabase `watchlist`)."""
    try:
        from db.supabase_client import get_admin_client  # type: ignore
        client = get_admin_client()
        if client is None:
            return []
        rows = (
            client.table("watchlist")
            .select("ticker")
            .eq("user_id", user_id)
            .execute()
        )
        return [r["ticker"] for r in (rows.data or []) if r.get("ticker")]
    except Exception:
        logger.exception("watchlist read failed for user %s", user_id)
        return []


# ── Earnings-date proxy (the documented gap) ──────────────────

def _earnings_dates_for(tickers: list[str], window_start: date, window_end: date) -> dict[str, date]:
    """Return {ticker: ex_date} for any ticker with a corporate-action
    ex_date in [window_start, window_end].

    STUB: see module docstring. Treats DIVIDEND ex_dates as a proxy for
    earnings events because the same board meeting that declares an
    interim dividend usually publishes quarterly results. Over-counts;
    do not rely on this for anything user-billed.
    """
    if not tickers:
        return {}
    try:
        from data_pipeline.db import Session
        from data_pipeline.models import CorporateAction
    except Exception as exc:  # pragma: no cover
        logger.warning("data_pipeline import failed: %s", exc)
        return {}
    if Session is None:
        return {}

    out: dict[str, date] = {}
    db = Session()
    try:
        rows = (
            db.query(CorporateAction.ticker, CorporateAction.ex_date)
            .filter(CorporateAction.ticker.in_(tickers))
            .filter(CorporateAction.action_type.ilike("%DIVIDEND%"))
            .filter(CorporateAction.ex_date >= window_start)
            .filter(CorporateAction.ex_date <= window_end)
            .all()
        )
        for ticker, ex_date in rows:
            # Earliest match wins per ticker.
            if ticker not in out or ex_date < out[ticker]:
                out[ticker] = ex_date
    finally:
        db.close()
    return out


# ── Main loop ─────────────────────────────────────────────────

def run(today: date | None = None, dry_run: bool = False) -> int:
    """Returns the number of notifications created (or that WOULD be
    created in dry-run mode)."""
    today = today or date.today()
    horizon = today + timedelta(days=1)
    logger.info("earnings reminder cron: window %s..%s dry_run=%s", today, horizon, dry_run)

    pro_users = _list_pro_users()
    logger.info("found %d pro-tier users", len(pro_users))

    created = 0
    for user in pro_users:
        uid = user["user_id"]
        # Defence-in-depth: every event source MUST gate via can_receive
        # so a tier matrix change in notifications_service propagates here
        # automatically without code edits.
        if not notif_svc.can_receive("pro", "earnings_reminder"):
            continue
        tickers = _watchlist_tickers(uid)
        if not tickers:
            continue
        upcoming = _earnings_dates_for(tickers, today, horizon)
        for ticker, ex_date in upcoming.items():
            display = ticker.replace(".NS", "").replace(".BO", "")
            title = f"{display} earnings call coming up"
            body = (
                f"{display} has a board action scheduled for {ex_date.isoformat()} "
                f"(within 24h). Quarterly results often land at the same meeting."
            )
            link = f"/analysis/{ticker}"
            metadata = {"ticker": ticker, "ex_date": ex_date.isoformat(), "source": "corporate_actions_proxy"}
            if dry_run:
                logger.info("[DRY-RUN] would notify user=%s ticker=%s", uid, ticker)
                created += 1
                continue
            try:
                notif_svc.create_notification(
                    user_id=uid,
                    type="earnings_reminder",
                    title=title,
                    body=body,
                    link=link,
                    metadata=metadata,
                )
                created += 1
            except Exception:
                logger.exception("create_notification failed for user=%s ticker=%s", uid, ticker)

    logger.info("earnings reminder cron complete — %d notifications %s",
                created, "would be created" if dry_run else "created")
    return created


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                        help="Log intended notifications without inserting.")
    args = parser.parse_args(argv)

    if not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL not set — refusing to run")
        return 1
    try:
        run(dry_run=args.dry_run)
        return 0
    except Exception:
        logger.exception("cron failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
