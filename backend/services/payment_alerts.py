# backend/services/payment_alerts.py
# ═══════════════════════════════════════════════════════════════
# Push notification primitive for payment lifecycle events.
#
# Why this exists: tier-grant happens synchronously in
# `POST /api/v1/payments/verify-subscription` (backend/routers/payments.py
# line ~318) and via the webhook handler (backend/routers/payments.py
# L905-L1205) on renewals / cancellations. Until this primitive landed
# the operator had no push surface — paid signups were discoverable only
# by polling the Razorpay dashboard or running a Supabase query. For the
# 4-week content-acquisition experiment where "did a stranger pay?" is
# the one success metric, polling is the failure mode.
#
# Behavior summary:
#   - Pick the loudest available backend (Slack > email > log)
#   - Never raise: the payment flow must not break on alert failure
#   - Log the failure via the structured logger (NOT silent except-pass —
#     CLAUDE.md task #247 history: silent exception swallowing at
#     analysis.py:820 was a real bug because it hid the failure)
#
# Audience: internal-only (operator's Slack / inbox). Emoji are used in
# the Slack-rendered message as chat-UX cues — these are not user-facing
# frontend strings, so the SEBI lint allowlist around them is correct.
# The event messages remain factual descriptions of payment lifecycle
# events; no advice vocabulary even in an internal context.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import os
from typing import Any
from urllib import request as _urlreq
from urllib.error import URLError

logger = logging.getLogger("yieldiq.payments.alerts")


# Public event-type vocabulary. Keep in sync with call sites in
# backend/routers/payments.py.
EVENT_TYPES = ("first_payment", "renewal", "cancellation", "failed")


def _slack_webhook_url() -> str:
    """Resolved at call time (not import time) so tests can monkeypatch
    os.environ without re-importing the module."""
    return os.environ.get("SLACK_WEBHOOK_URL", "").strip()


def _alert_email_to() -> str:
    return os.environ.get("ALERT_EMAIL_TO", "").strip()


def _format_inr(amount_inr: Any) -> str:
    """Render amount as a clean rupee string. Accepts int / float / str.
    Returns '?' if unparseable — we never want a formatting error to
    cascade into a swallowed alert."""
    if amount_inr is None or amount_inr == "":
        return "?"
    try:
        val = float(amount_inr)
    except (TypeError, ValueError):
        return str(amount_inr)
    if val == int(val):
        return f"{int(val):,}"
    return f"{val:,.2f}"


def _format_slack_message(event_type: str, payload: dict) -> str:
    """Render a one-line Slack message. Emoji are intentional chat-UX
    cues — internal channel only, never reaches the SEBI-regulated
    frontend surface."""
    user_email = payload.get("user_email") or "?"
    tier = payload.get("tier") or "?"
    amount = _format_inr(payload.get("amount_inr"))
    payment_id = payload.get("razorpay_payment_id") or "?"
    occurred_at = payload.get("occurred_at") or "?"

    headings = {
        "first_payment": "*New first payment*",
        "renewal": "*Renewal*",
        "cancellation": "*Cancellation*",
        "failed": "*Payment failed*",
    }
    emoji = {
        "first_payment": ":moneybag:",
        "renewal": ":white_check_mark:",
        "cancellation": ":x:",
        "failed": ":warning:",
    }
    heading = headings.get(event_type, f"*Payment event: {event_type}*")
    icon = emoji.get(event_type, ":bell:")
    return (
        f"{icon} {heading} | User: `{user_email}` | Tier: `{tier}` | "
        f"Amount: INR {amount} | Razorpay: `{payment_id}` | {occurred_at}"
    )


def _post_slack(url: str, message: str, timeout: float = 5.0) -> None:
    """POST a Slack-formatted message. Raises on network / non-2xx so
    the outer try/except in notify_payment_event can log it."""
    body = json.dumps({"text": message}).encode("utf-8")
    req = _urlreq.Request(
        url,
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with _urlreq.urlopen(req, timeout=timeout) as resp:
        status = getattr(resp, "status", 200)
        if status < 200 or status >= 300:
            raise URLError(f"Slack webhook returned HTTP {status}")


def _send_email_alert(to_email: str, event_type: str, message: str) -> bool:
    """Fallback channel. Delegates to backend.services.email_service so
    we reuse the verified SendGrid sender and don't open a second SMTP
    code path. Returns True on success."""
    try:
        from backend.services.email_service import send_email
    except Exception as exc:  # noqa: BLE001 — import failures are diagnostic
        logger.error(
            "payment-alert: email_service import failed: %s: %s",
            type(exc).__name__, exc,
        )
        return False

    subject = f"[YieldIQ payment] {event_type}"
    # Plain text body — operator inbox surface. Mirror the Slack line so
    # the same factual content lands wherever the alert routes.
    text_body = message
    html_body = (
        f"<p style=\"font-family:monospace;\">{message}</p>"
    )
    return bool(send_email(
        to_email=to_email,
        subject=subject,
        html=html_body,
        text=text_body,
        tags=["payment_alert", event_type],
    ))


def notify_payment_event(event_type: str, payload: dict) -> None:
    """Non-blocking push notification of payment lifecycle events.

    event_type: 'first_payment' | 'renewal' | 'cancellation' | 'failed'
    payload:    dict containing user_email, tier, amount_inr,
                razorpay_payment_id, occurred_at

    Backend selection:
      - SLACK_WEBHOOK_URL set  → POST to Slack
      - ALERT_EMAIL_TO  set    → send via SendGrid (email_service)
      - neither set            → log at INFO (degraded but visible)

    Never raises. All failures are caught and logged via the structured
    logger so the payment flow is unaffected. NB: this is NOT a silent
    except-pass — see CLAUDE.md task #247 history.
    """
    # Build the structured payload up front so even the log-only fallback
    # captures everything the operator needs.
    message = _format_slack_message(event_type, payload or {})

    slack_url = _slack_webhook_url()
    email_to = _alert_email_to()

    try:
        if slack_url:
            try:
                _post_slack(slack_url, message)
                logger.info(
                    "payment-alert sent via slack: event=%s payment=%s",
                    event_type, (payload or {}).get("razorpay_payment_id"),
                )
                return
            except Exception as slack_exc:  # noqa: BLE001 — fall through to next channel
                logger.error(
                    "payment-alert slack post failed (falling back): %s: %s",
                    type(slack_exc).__name__, slack_exc,
                )

        if email_to:
            ok = _send_email_alert(email_to, event_type, message)
            if ok:
                logger.info(
                    "payment-alert sent via email: event=%s to=%s",
                    event_type, email_to,
                )
                return
            logger.error(
                "payment-alert email send returned False (falling back to log): event=%s",
                event_type,
            )

        # Degraded fallback. Better than silent. Operator can grep for
        # 'payment-alert (log-only)' in Railway logs until SLACK_WEBHOOK_URL
        # or ALERT_EMAIL_TO is set.
        logger.info(
            "payment-alert (log-only): event=%s payload=%s",
            event_type, payload,
        )
    except Exception as exc:  # noqa: BLE001 — final safety net
        # Final safety net. The payment flow has already done its work
        # by the time we get called; an alert failure must never cascade
        # back into a 500 for the user. Log loudly via the structured
        # logger — never silent.
        logger.exception(
            "payment-alert unexpected failure for event=%s: %s: %s",
            event_type, type(exc).__name__, exc,
        )
