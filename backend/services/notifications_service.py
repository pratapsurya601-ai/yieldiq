"""In-app notification system. Notifications are typed events surfaced
to the user via the bell icon in the nav. Cost: ₹0 per message (vs
SendGrid's per-email cost). Latency: 60s (frontend polls /unread-count).

Schema lives in `data_pipeline/migrations/015_create_notifications_table.sql`.
DB connection reuses the same SQLAlchemy engine the rest of the backend
uses (data_pipeline.db.engine), through the raw psycopg2 cursor for the
JSONB metadata column.

Tier-gating policy:
    * `create_notification` does NOT enforce tier — it trusts the caller.
    * Cron / event sources call `can_receive(user_tier, type)` BEFORE
      `create_notification`. This keeps the service module thin and
      makes the gating policy testable in isolation.
"""
from __future__ import annotations

import json
import logging
from typing import Optional, Literal

logger = logging.getLogger("yieldiq.notifications")

NotificationType = Literal[
    "alert_fired",        # user's price/score alert triggered (free+)
    "portfolio_event",    # holding moved >5%, dividend declared, etc. (analyst+)
    "earnings_reminder",  # earnings call scheduled in next 24h on watchlist (pro)
    "market_event",       # sector/index swing or news (pro)
    "model_update",       # FV revised on a watched ticker (pro)
    "system",             # plan upgrade confirmed, payment receipt, etc. (all)
]

# Tier → which notification types that tier is permitted to receive.
# Caller is expected to call `can_receive(tier, type)` before insert.
TIER_ALLOWED_TYPES: dict[str, set[str]] = {
    "free": {"alert_fired", "system"},
    "analyst": {"alert_fired", "portfolio_event", "system"},
    "pro": {
        "alert_fired",
        "portfolio_event",
        "earnings_reminder",
        "market_event",
        "model_update",
        "system",
    },
}


def can_receive(tier: str, type: str) -> bool:
    """Return True iff `tier` is permitted to receive notifications of `type`.

    Unknown tiers fall through to the most-restrictive ("free") set so an
    auth bug or new tier name can't accidentally surface Pro-only
    notifications to free users.
    """
    allowed = TIER_ALLOWED_TYPES.get(tier, TIER_ALLOWED_TYPES["free"])
    return type in allowed


# ── DB helpers ────────────────────────────────────────────────

def _get_raw_cursor():
    """Yield a raw psycopg2 cursor + connection from the pipeline engine.

    Returns (conn, cursor). Caller MUST close both. Returns (None, None)
    if DATABASE_URL is not configured (allows tests / dev to no-op).
    """
    try:
        from data_pipeline.db import engine
    except Exception as exc:
        logger.warning("notifications_service: pipeline engine import failed: %s", exc)
        return None, None
    if engine is None:
        return None, None
    conn = engine.raw_connection()
    cur = conn.cursor()
    return conn, cur


def _row_to_dict(row: tuple) -> dict:
    """Convert a SELECT row to the dict shape the API returns."""
    (id_, type_, title, body, link, metadata, created_at, read_at) = row
    if isinstance(metadata, str):
        try:
            metadata = json.loads(metadata)
        except (TypeError, ValueError):
            metadata = {}
    return {
        "id": int(id_),
        "type": type_,
        "title": title,
        "body": body,
        "link": link,
        "metadata": metadata or {},
        "created_at": created_at.isoformat() if created_at else None,
        "read_at": read_at.isoformat() if read_at else None,
    }


# ── Public API ────────────────────────────────────────────────

def create_notification(
    *,
    user_id: str,
    type: NotificationType,
    title: str,
    body: Optional[str] = None,
    link: Optional[str] = None,
    metadata: Optional[dict] = None,
) -> int:
    """Insert a notification. Returns the new row id.

    Caller is responsible for tier-checking before invoking — this
    function trusts the caller. Caps message size to keep UI tidy.
    """
    title = (title or "")[:120]
    body = (body or "")[:1000] if body else None
    link = (link or "")[:500] if link else None
    metadata = metadata or {}

    conn, cur = _get_raw_cursor()
    if conn is None or cur is None:
        logger.warning(
            "notifications_service.create_notification: DB unavailable, dropping "
            "notification (user=%s type=%s)", user_id, type,
        )
        return 0
    try:
        cur.execute(
            """
            INSERT INTO notifications (user_id, type, title, body, link, metadata)
            VALUES (%s, %s, %s, %s, %s, %s::jsonb)
            RETURNING id
            """,
            (user_id, type, title, body, link, json.dumps(metadata)),
        )
        new_id = cur.fetchone()[0]
        conn.commit()
        return int(new_id)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception(
            "notifications_service.create_notification failed (user=%s type=%s)",
            user_id, type,
        )
        raise
    finally:
        try:
            cur.close()
        finally:
            conn.close()


def list_unread(user_id: str, limit: int = 50) -> list[dict]:
    """Return user's unread notifications, newest first. Capped at 50
    so the bell-drawer stays small."""
    limit = max(1, min(int(limit or 50), 50))
    conn, cur = _get_raw_cursor()
    if conn is None or cur is None:
        return []
    try:
        cur.execute(
            """
            SELECT id, type, title, body, link, metadata, created_at, read_at
              FROM notifications
             WHERE user_id = %s AND read_at IS NULL
             ORDER BY created_at DESC
             LIMIT %s
            """,
            (user_id, limit),
        )
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        try:
            cur.close()
        finally:
            conn.close()


def list_recent(user_id: str, limit: int = 50) -> list[dict]:
    """Return user's recent notifications (read + unread), newest first."""
    limit = max(1, min(int(limit or 50), 50))
    conn, cur = _get_raw_cursor()
    if conn is None or cur is None:
        return []
    try:
        cur.execute(
            """
            SELECT id, type, title, body, link, metadata, created_at, read_at
              FROM notifications
             WHERE user_id = %s
             ORDER BY created_at DESC
             LIMIT %s
            """,
            (user_id, limit),
        )
        return [_row_to_dict(r) for r in cur.fetchall()]
    finally:
        try:
            cur.close()
        finally:
            conn.close()


def mark_read(user_id: str, notification_id: int) -> bool:
    """Mark a single notification as read. Returns True if updated.

    user_id is part of the WHERE clause so a user can never mark another
    user's notifications as read.
    """
    conn, cur = _get_raw_cursor()
    if conn is None or cur is None:
        return False
    try:
        cur.execute(
            """
            UPDATE notifications
               SET read_at = NOW()
             WHERE id = %s AND user_id = %s AND read_at IS NULL
            """,
            (int(notification_id), user_id),
        )
        updated = cur.rowcount or 0
        conn.commit()
        return updated > 0
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("notifications_service.mark_read failed")
        return False
    finally:
        try:
            cur.close()
        finally:
            conn.close()


def mark_all_read(user_id: str) -> int:
    """Mark all unread notifications as read. Returns count."""
    conn, cur = _get_raw_cursor()
    if conn is None or cur is None:
        return 0
    try:
        cur.execute(
            """
            UPDATE notifications
               SET read_at = NOW()
             WHERE user_id = %s AND read_at IS NULL
            """,
            (user_id,),
        )
        updated = cur.rowcount or 0
        conn.commit()
        return int(updated)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("notifications_service.mark_all_read failed")
        return 0
    finally:
        try:
            cur.close()
        finally:
            conn.close()


def unread_count(user_id: str) -> int:
    """Cheap count for the bell badge. Uses the partial index
    `idx_notif_user_unread`.

    This endpoint is polled every 60s per active session, so the index
    is what makes it cheap — DO NOT add filters that bypass the partial
    predicate (`WHERE read_at IS NULL`).
    """
    conn, cur = _get_raw_cursor()
    if conn is None or cur is None:
        return 0
    try:
        cur.execute(
            """
            SELECT COUNT(*) FROM notifications
             WHERE user_id = %s AND read_at IS NULL
            """,
            (user_id,),
        )
        row = cur.fetchone()
        return int(row[0]) if row else 0
    finally:
        try:
            cur.close()
        finally:
            conn.close()
