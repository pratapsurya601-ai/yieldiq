"""Tests for backend.services.payment_alerts.notify_payment_event.

Covers the four behavior assertions from the spec:
  1. SLACK_WEBHOOK_URL set     → Slack POST fires
  2. ALERT_EMAIL_TO only       → email send fires
  3. Neither set               → INFO log only (no exceptions)
  4. Slack POST raises         → payment flow unaffected; structured log
Plus a fifth: rendered message contains user_email, tier, amount,
payment_id.
"""
from __future__ import annotations

import logging
from unittest.mock import patch, MagicMock

import pytest

from backend.services import payment_alerts


# ── Fixture: known-good payload ────────────────────────────────


@pytest.fixture
def sample_payload():
    return {
        "user_email": "stranger@example.com",
        "tier": "analyst",
        "amount_inr": 999,
        "razorpay_payment_id": "pay_TEST123",
        "occurred_at": "2026-06-04T10:00:00+00:00",
    }


# ── 1. Slack path ──────────────────────────────────────────────


def test_slack_post_fires_when_webhook_url_set(monkeypatch, sample_payload):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/T/B/X")
    monkeypatch.delenv("ALERT_EMAIL_TO", raising=False)

    with patch.object(payment_alerts, "_post_slack") as mock_slack, \
         patch.object(payment_alerts, "_send_email_alert") as mock_email:
        payment_alerts.notify_payment_event("first_payment", sample_payload)

    assert mock_slack.call_count == 1, "Slack POST should fire once"
    mock_email.assert_not_called()
    # The URL and rendered message should reach the slack poster.
    call_args = mock_slack.call_args
    assert call_args.args[0] == "https://hooks.slack.example/T/B/X"
    assert "stranger@example.com" in call_args.args[1]


# ── 2. Email fallback ──────────────────────────────────────────


def test_email_fires_when_only_email_set(monkeypatch, sample_payload):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.setenv("ALERT_EMAIL_TO", "ops@yieldiq.in")

    with patch.object(payment_alerts, "_post_slack") as mock_slack, \
         patch.object(payment_alerts, "_send_email_alert", return_value=True) as mock_email:
        payment_alerts.notify_payment_event("first_payment", sample_payload)

    mock_slack.assert_not_called()
    assert mock_email.call_count == 1
    # Email helper called with the right recipient + event_type.
    call_args = mock_email.call_args
    assert call_args.args[0] == "ops@yieldiq.in"
    assert call_args.args[1] == "first_payment"


# ── 3. Log-only degraded fallback ──────────────────────────────


def test_log_only_when_neither_env_set(monkeypatch, sample_payload, caplog):
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("ALERT_EMAIL_TO", raising=False)

    with patch.object(payment_alerts, "_post_slack") as mock_slack, \
         patch.object(payment_alerts, "_send_email_alert") as mock_email, \
         caplog.at_level(logging.INFO, logger="yieldiq.payments.alerts"):
        payment_alerts.notify_payment_event("first_payment", sample_payload)

    mock_slack.assert_not_called()
    mock_email.assert_not_called()
    # Degraded fallback line must be visible.
    log_msgs = [r.getMessage() for r in caplog.records]
    assert any("payment-alert (log-only)" in m for m in log_msgs), \
        f"Expected degraded log line; got {log_msgs!r}"


# ── 4. Slack failure does NOT bubble to caller ─────────────────


def test_slack_failure_does_not_raise_and_logs_error(monkeypatch, sample_payload, caplog):
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/T/B/X")
    monkeypatch.delenv("ALERT_EMAIL_TO", raising=False)

    def _boom(*a, **kw):
        raise RuntimeError("network is down")

    with patch.object(payment_alerts, "_post_slack", side_effect=_boom), \
         caplog.at_level(logging.ERROR, logger="yieldiq.payments.alerts"):
        # The whole point: this MUST NOT raise. Caller is the payment
        # flow and a stranger has already paid us money.
        payment_alerts.notify_payment_event("first_payment", sample_payload)

    # Failure was logged via the structured logger (NOT silent).
    error_msgs = [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]
    assert any("slack post failed" in m for m in error_msgs), \
        f"Expected structured error log; got {error_msgs!r}"


def test_slack_failure_falls_through_to_email(monkeypatch, sample_payload):
    """Bonus: when Slack fails AND email is configured, email should fire."""
    monkeypatch.setenv("SLACK_WEBHOOK_URL", "https://hooks.slack.example/T/B/X")
    monkeypatch.setenv("ALERT_EMAIL_TO", "ops@yieldiq.in")

    with patch.object(payment_alerts, "_post_slack", side_effect=RuntimeError("down")), \
         patch.object(payment_alerts, "_send_email_alert", return_value=True) as mock_email:
        payment_alerts.notify_payment_event("first_payment", sample_payload)

    assert mock_email.call_count == 1


# ── 5. Rendered message contains the operator-relevant fields ──


def test_rendered_message_contains_required_fields(sample_payload):
    msg = payment_alerts._format_slack_message("first_payment", sample_payload)
    assert "stranger@example.com" in msg
    assert "analyst" in msg
    # amount: rendered as INR 999 (no decimal for clean integers)
    assert "999" in msg
    assert "pay_TEST123" in msg


def test_event_types_render_distinct_headings(sample_payload):
    headings = {
        "first_payment": "New first payment",
        "renewal": "Renewal",
        "cancellation": "Cancellation",
        "failed": "Payment failed",
    }
    for evt, expected in headings.items():
        msg = payment_alerts._format_slack_message(evt, sample_payload)
        assert expected in msg, f"event_type={evt}: missing heading {expected!r} in {msg!r}"


# ── 6. Public function never raises on garbage payload ─────────


def test_notify_never_raises_on_bad_payload(monkeypatch):
    """Defensive: the caller is the payment hot path. Even a malformed
    payload (missing fields, None values) must not raise."""
    monkeypatch.delenv("SLACK_WEBHOOK_URL", raising=False)
    monkeypatch.delenv("ALERT_EMAIL_TO", raising=False)
    # Should not raise on any of these.
    payment_alerts.notify_payment_event("first_payment", {})
    payment_alerts.notify_payment_event("first_payment", {"amount_inr": "not-a-number"})
    payment_alerts.notify_payment_event("first_payment", None)  # type: ignore[arg-type]
