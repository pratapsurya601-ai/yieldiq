"""Tests for backend/services/email_service.py.

Focus: the public send_email() wrapper passes the right shape to
SendGrid (subject, plain-text alt, tags, reply-to), and the unsub
token round-trips. We never touch the real network — the SendGrid
client is patched.
"""
from __future__ import annotations

import os
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture(autouse=True)
def _set_api_key(monkeypatch):
    """SendGrid is gated on SENDGRID_API_KEY being non-empty.
    Without this, _send_email short-circuits and returns False."""
    monkeypatch.setenv("SENDGRID_API_KEY", "test-key-not-real")
    yield


def _import_clean():
    """Re-import email_service so the patched SENDGRID_API_KEY env
    is picked up. Module-level constants are read at import time."""
    import importlib
    from backend.services import email_service
    return importlib.reload(email_service)


def test_send_email_passes_tags_and_text(monkeypatch):
    es = _import_clean()
    sent_messages = []

    fake_sg = MagicMock()
    fake_sg.send = MagicMock(return_value=MagicMock(status_code=202))

    class FakeSGClient:
        def __init__(self, _key): pass
        def send(self, msg):
            sent_messages.append(msg)
            return MagicMock(status_code=202)

    with patch("sendgrid.SendGridAPIClient", FakeSGClient):
        ok = es.send_email(
            to_email="user@example.com",
            subject="Hello",
            html="<b>hi</b>",
            text="hi",
            tags=["weekly_digest"],
        )

    assert ok is True
    assert len(sent_messages) == 1
    msg = sent_messages[0]
    # Subject set on the SendGrid Mail object
    assert msg.subject.subject == "Hello"
    # Plain-text alt included for deliverability
    contents = [c.content for c in msg.contents]
    assert any("hi" == c for c in contents)
    assert any("<b>hi</b>" == c for c in contents)
    # Reply-to set so users can reply
    assert msg.reply_to is not None


def test_send_email_returns_false_without_api_key(monkeypatch):
    monkeypatch.delenv("SENDGRID_API_KEY", raising=False)
    es = _import_clean()
    ok = es.send_email("a@b.com", "x", "<p>x</p>")
    assert ok is False


def test_unsubscribe_token_roundtrip(monkeypatch):
    monkeypatch.setenv("JWT_SECRET", "test-secret-for-unsub")
    es = _import_clean()
    url = es._get_unsubscribe_url("user@example.com")
    # Token is the last query-param value
    assert "token=" in url
    token = url.split("token=")[-1]
    assert es.verify_unsubscribe_token("user@example.com", token) is True
    # Wrong email should fail
    assert es.verify_unsubscribe_token("other@example.com", token) is False
    # Tampered token should fail
    assert es.verify_unsubscribe_token("user@example.com", "deadbeef" * 2) is False


def test_welcome_email_tagged_welcome(monkeypatch):
    """The welcome email helper should send with tags=['welcome'] so
    we can separate signup volume from digest volume in SendGrid
    analytics."""
    es = _import_clean()

    captured = {}

    def fake_send(to_email, subject, html_content, text_content=None,
                  tags=None, reply_to=None):
        captured["tags"] = tags
        captured["subject"] = subject
        captured["text"] = text_content
        return True

    monkeypatch.setattr(es, "_send_email", fake_send)
    # Also bypass the unsubscribe-status DB lookup
    monkeypatch.setattr(es, "is_user_unsubscribed", lambda e: False)

    es.send_welcome_email("user@example.com", name="Vinit")
    assert captured["tags"] == ["welcome"]
    assert "Vinit" in captured["subject"]
    # Plain-text alt is present (deliverability)
    assert captured["text"] and "YieldIQ" in captured["text"]
