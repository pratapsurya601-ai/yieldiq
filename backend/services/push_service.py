# backend/services/push_service.py
# ═══════════════════════════════════════════════════════════════
# Web Push (PWA) delivery — Day-98.
#
# Lifts mobile retention by reaching the user when an alert condition
# crosses (e.g. MoS for a watchlist stock crosses their threshold),
# without depending on the user opening email. Used as an additional
# channel by backend.services.alerts_service when:
#
#     user_alerts.notify_push = TRUE
#     AND >=1 row exists in push_subscriptions for (user_id)
#
# Email is still sent in parallel (no behaviour change for users who
# haven't opted in to push).
#
# VAPID configuration is read from env:
#   VAPID_PRIVATE_KEY    -- backend-only; base64url-encoded EC private key
#   VAPID_PUBLIC_KEY     -- mirror of NEXT_PUBLIC_VAPID_PUBLIC_KEY (frontend)
#   VAPID_SUBJECT        -- "mailto:ops@yieldiq.in" (push services require it)
#
# pywebpush import is *lazy* so the module loads even when the library
# (which depends on the `cryptography` wheel) is unavailable in CI.
# In that case send_push() is a no-op that logs the intended payload.
#
# SEBI vocabulary: keep all generated copy informational ("crossed your
# alert threshold"), never directive ("buy"/"sell"/"recommend"/...).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import os
from typing import Optional

from sqlalchemy.orm import Session as OrmSession

logger = logging.getLogger(__name__)


# ── Copy templates (SEBI-safe — informational only) ──────────────
#
# Centralised so the tests can assert no banned tokens appear here.
TEST_NOTIFICATION_TITLE = "YieldIQ"
TEST_NOTIFICATION_BODY = "Notifications enabled for your watchlist alerts"


def render_alert_copy(ticker: str, kind: str, threshold: Optional[float]) -> tuple[str, str]:
    """Render a (title, body) pair for an alert-fired push.

    Informational only — never directive. Examples:
      title: "RELIANCE alert"
      body:  "Crossed your MoS threshold of 25%"
    """
    display = (ticker or "").replace(".NS", "").replace(".BO", "").upper()
    title = f"{display} alert"
    if kind == "price_above" and threshold is not None:
        body = f"Crossed above your price threshold of ₹{threshold:.0f}"
    elif kind == "price_below" and threshold is not None:
        body = f"Dropped below your price threshold of ₹{threshold:.0f}"
    elif kind == "mos_above" and threshold is not None:
        body = f"Crossed your MoS threshold of {threshold:.0f}%"
    elif kind == "mos_below" and threshold is not None:
        body = f"MoS fell below your threshold of {threshold:.0f}%"
    elif kind == "verdict_change":
        body = f"Verdict changed since your last check"
    else:
        body = "Crossed your alert threshold"
    return title, body


# ── VAPID config ────────────────────────────────────────────────

def _vapid_claims() -> dict:
    return {
        "sub": os.environ.get("VAPID_SUBJECT", "mailto:ops@yieldiq.in"),
    }


def _vapid_private_key() -> Optional[str]:
    return os.environ.get("VAPID_PRIVATE_KEY") or None


# ── Subscription storage ────────────────────────────────────────

def upsert_subscription(
    session: OrmSession,
    *,
    user_id: str,
    endpoint: str,
    p256dh: str,
    auth: str,
    user_agent: Optional[str] = None,
) -> dict:
    """Insert or update a push subscription for (user_id, endpoint).

    `endpoint` is unique across the table — the same browser
    re-subscribing simply refreshes the row. Returns the to_dict()
    of the persisted row.
    """
    from backend.models.push_subscription import PushSubscription

    existing = (
        session.query(PushSubscription)
        .filter(PushSubscription.endpoint == endpoint)
        .one_or_none()
    )
    if existing:
        existing.user_id = user_id
        existing.p256dh = p256dh
        existing.auth = auth
        existing.user_agent = user_agent
        session.commit()
        return existing.to_dict()

    row = PushSubscription(
        user_id=user_id,
        endpoint=endpoint,
        p256dh=p256dh,
        auth=auth,
        user_agent=user_agent,
    )
    session.add(row)
    session.commit()
    return row.to_dict()


def list_subscriptions(session: OrmSession, user_id: str) -> list[dict]:
    from backend.models.push_subscription import PushSubscription

    rows = (
        session.query(PushSubscription)
        .filter(PushSubscription.user_id == user_id)
        .all()
    )
    return [r.to_dict() for r in rows]


# ── Send ────────────────────────────────────────────────────────

def _send_to_endpoint(
    *,
    endpoint: str,
    p256dh: str,
    auth: str,
    payload: dict,
) -> bool:
    """Attempt a single Web Push delivery. Returns True on apparent success.

    pywebpush is imported lazily. If the import fails (e.g. cryptography
    wheel missing in the current environment) we log the would-be
    delivery and return False so the caller can degrade gracefully.
    """
    private_key = _vapid_private_key()
    if not private_key:
        logger.info("push: VAPID_PRIVATE_KEY unset — would send %s", payload.get("title"))
        return False

    try:
        from pywebpush import WebPushException, webpush  # type: ignore
    except Exception as e:  # pragma: no cover - depends on host env
        logger.warning("push: pywebpush import failed (%s) — would send %s", e, payload)
        return False

    try:
        webpush(
            subscription_info={
                "endpoint": endpoint,
                "keys": {"p256dh": p256dh, "auth": auth},
            },
            data=json.dumps(payload),
            vapid_private_key=private_key,
            vapid_claims=_vapid_claims(),
        )
        return True
    except WebPushException as e:  # pragma: no cover - needs live push service
        logger.warning("push: WebPushException for %s: %s", endpoint[:60], e)
        return False
    except Exception as e:  # pragma: no cover
        logger.error("push: unexpected error for %s: %s", endpoint[:60], e)
        return False


def send_push(
    session: OrmSession,
    *,
    user_id: str,
    title: str,
    body: str,
    url: Optional[str] = None,
) -> int:
    """Send a push to every registered subscription for the user.

    Returns the number of subscriptions that accepted the payload.
    Never raises — failures degrade silently so the caller (alerts
    evaluator) can move on to the next alert.
    """
    subs = list_subscriptions(session, user_id)
    if not subs:
        return 0

    from backend.models.push_subscription import PushSubscription

    payload = {"title": title, "body": body, "url": url or "/"}
    delivered = 0
    for sub_dict in subs:
        # We need p256dh + auth — re-fetch the ORM row (to_dict() omits
        # secrets by design so they don't leak into logs).
        row = (
            session.query(PushSubscription)
            .filter(PushSubscription.id == sub_dict["id"])
            .one_or_none()
        )
        if not row:
            continue
        if _send_to_endpoint(
            endpoint=row.endpoint,
            p256dh=row.p256dh,
            auth=row.auth,
            payload=payload,
        ):
            delivered += 1
    return delivered
