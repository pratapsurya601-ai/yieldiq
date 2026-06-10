"""Chat router — endpoint shape + SSE streaming format tests.

Covers ``backend/routers/chat.py``. The endpoint is the streaming
sibling of ``ai_explain``; these tests pin the wire contract so a
future drive-by edit cannot silently break the frontend's stream
assembler.

What we pin:
  1. Request validation: missing user message -> 400. Body-ticker
     mismatch with path -> 400. Unknown role -> 400.
  2. SSE shape: response Content-Type is ``text/event-stream``, each
     line is ``data: <json>\\n\\n`` with ``{delta, done}`` keys, the
     stream ALWAYS ends with a ``done: true`` event.
  3. SEBI defence-in-depth: a model that returns banned vocab is
     scrubbed before reaching the wire (the ``_strip_banned`` helper
     called on each delta replaces banned tokens with 'rated').
  4. System-prompt context: ``build_system_prompt`` includes the
     ticker name and the model's fair-value / MoS numbers verbatim,
     so multi-turn questions can reference them.
"""
from __future__ import annotations

import json
import re
from typing import Iterator
from unittest.mock import patch

import pytest
from fastapi.testclient import TestClient


# ── Helpers ─────────────────────────────────────────────────────

def _parse_sse_events(body: bytes | str) -> list[dict]:
    """Parse the raw SSE body into a list of decoded JSON event dicts.

    Tolerant to multi-event payloads separated by blank lines and to
    ``data:`` lines split inside an event block (we only ever emit
    one ``data:`` line per event so the simple split is enough).
    """
    text = body.decode("utf-8") if isinstance(body, bytes) else body
    events: list[dict] = []
    for block in text.split("\n\n"):
        block = block.strip()
        if not block:
            continue
        for line in block.splitlines():
            if line.startswith("data:"):
                payload = line[len("data:"):].strip()
                if not payload:
                    continue
                try:
                    events.append(json.loads(payload))
                except json.JSONDecodeError:
                    pass
    return events


@pytest.fixture
def client():
    """TestClient with the auth dependency overridden so the chat
    endpoint is reachable in tests. The chat router depends on
    backend.middleware.auth.get_current_user; we substitute a Pro-tier
    user so the rate-limiter never blocks during the test run.
    """
    from backend.main import app
    from backend.middleware import auth as auth_middleware

    def _fake_user():
        return {
            "id": "test-user-1",
            "email": "test@yieldiq.test",
            "tier": "pro",
        }

    app.dependency_overrides[auth_middleware.get_current_user] = _fake_user
    try:
        yield TestClient(app)
    finally:
        app.dependency_overrides.pop(auth_middleware.get_current_user, None)


# A stub AnalysisService.get_full_analysis return value. We mock the
# instance attached to backend.routers.chat (and ai_explain).
class _StubAnalysis:
    def model_dump(self) -> dict:
        return {
            "company": {"company_name": "HDFC Bank Ltd", "sector": "Banks"},
            "valuation": {
                "verdict": "undervalued",
                "current_price": 747.0,
                "fair_value": 1146.0,
                "margin_of_safety": 53.4,
                "wacc": 0.098,
                "terminal_growth": 0.03,
                "fcf_growth_rate": 0.08,
                "confidence_score": 90,
            },
            "scenarios": {
                "bear": {"iv": 955.0},
                "base": {"iv": 1146.0},
                "bull": {"iv": 1320.0},
            },
            "quality": {"moat": "Wide", "moat_score": 72.0},
        }


# ── 1. Request validation ───────────────────────────────────────

class TestValidation:
    def test_empty_messages_returns_400(self, client):
        with patch(
            "backend.routers.chat._analysis.get_full_analysis",
            return_value=_StubAnalysis(),
        ):
            r = client.post(
                "/api/v1/analysis/HDFCBANK.NS/chat",
                json={"ticker": "HDFCBANK.NS", "messages": []},
            )
        assert r.status_code == 400

    def test_body_ticker_must_match_path(self, client):
        with patch(
            "backend.routers.chat._analysis.get_full_analysis",
            return_value=_StubAnalysis(),
        ):
            r = client.post(
                "/api/v1/analysis/HDFCBANK.NS/chat",
                json={
                    "ticker": "INFY.NS",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )
        assert r.status_code == 400

    def test_unknown_role_rejected(self, client):
        with patch(
            "backend.routers.chat._analysis.get_full_analysis",
            return_value=_StubAnalysis(),
        ):
            r = client.post(
                "/api/v1/analysis/HDFCBANK.NS/chat",
                json={
                    "ticker": "HDFCBANK.NS",
                    "messages": [{"role": "system", "content": "Hi"}],
                },
            )
        assert r.status_code == 400

    def test_last_message_must_be_user(self, client):
        with patch(
            "backend.routers.chat._analysis.get_full_analysis",
            return_value=_StubAnalysis(),
        ):
            r = client.post(
                "/api/v1/analysis/HDFCBANK.NS/chat",
                json={
                    "ticker": "HDFCBANK.NS",
                    "messages": [
                        {"role": "user", "content": "Tell me about it."},
                        {"role": "assistant", "content": "Sure."},
                    ],
                },
            )
        assert r.status_code == 400


# ── 2. SSE stream shape (template-fallback path) ────────────────

class TestSSEShape:
    def test_template_fallback_emits_done_true(self, client, monkeypatch):
        """No Claude client => deterministic template stream that
        still ends with done:true."""
        # Force the no-LLM path by ensuring no anthropic client.
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        with patch(
            "backend.routers.chat._analysis.get_full_analysis",
            return_value=_StubAnalysis(),
        ):
            r = client.post(
                "/api/v1/analysis/HDFCBANK.NS/chat",
                json={
                    "ticker": "HDFCBANK.NS",
                    "messages": [
                        {"role": "user", "content": "Walk me through MoS."},
                    ],
                },
            )
        assert r.status_code == 200
        assert r.headers["content-type"].startswith("text/event-stream")

        events = _parse_sse_events(r.content)
        assert events, "stream must yield at least one event"
        assert events[-1]["done"] is True
        # Every event must have the {delta, done} shape.
        for ev in events:
            assert "delta" in ev
            assert "done" in ev
        # At least one non-empty delta carries the template text.
        joined = "".join(ev.get("delta", "") for ev in events)
        assert "fair-value reference" in joined.lower() or "fair value" in joined.lower()

    def test_template_path_quotes_analysis_numbers(self, client, monkeypatch):
        """The deterministic template MUST quote the cached fair-
        value / MoS numbers so the user sees consistent figures."""
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        with patch(
            "backend.routers.chat._analysis.get_full_analysis",
            return_value=_StubAnalysis(),
        ):
            r = client.post(
                "/api/v1/analysis/HDFCBANK.NS/chat",
                json={
                    "ticker": "HDFCBANK.NS",
                    "messages": [
                        {"role": "user", "content": "Why this verdict?"},
                    ],
                },
            )
        joined = "".join(
            ev.get("delta", "") for ev in _parse_sse_events(r.content)
        )
        # MoS 53.4% and FV Rs 1,146 from the stub above.
        assert "1,146" in joined
        assert "53.4" in joined


# ── 3. SEBI defence-in-depth ────────────────────────────────────

class TestSEBIFilter:
    def test_strip_banned_replaces_advisory_vocab(self):
        from backend.routers.chat import _strip_banned

        dirty = (
            "The model finds this name "
            + "u" + "ndervalued and investors "
            + "sh" + "ould " + "b" + "uy."
        )
        clean = _strip_banned(dirty)
        # No banned tokens remain (case-insensitive).
        assert not re.search(
            r"\b(buy|sell|hold|should|undervalued|overvalued|recommend)\b",
            clean,
            re.IGNORECASE,
        )

    def test_chat_stream_scrubs_banned_deltas(self, client, monkeypatch):
        """Even if the model (here: our template fallback) emits banned
        vocab, no SSE delta forwarded to the client may contain it."""
        # Patch _deterministic_fallback to return adversarial text.
        adversarial = (
            "This stock " + "ap" + "pears " + "u" + "ndervalued. You "
            + "sh" + "ould " + "b" + "uy now."
        )
        monkeypatch.setenv("ANTHROPIC_API_KEY", "")
        with patch(
            "backend.routers.chat._deterministic_fallback",
            return_value=adversarial,
        ), patch(
            "backend.routers.chat._analysis.get_full_analysis",
            return_value=_StubAnalysis(),
        ):
            r = client.post(
                "/api/v1/analysis/HDFCBANK.NS/chat",
                json={
                    "ticker": "HDFCBANK.NS",
                    "messages": [{"role": "user", "content": "Hi"}],
                },
            )

        joined = "".join(
            ev.get("delta", "") for ev in _parse_sse_events(r.content)
        ).lower()
        banned_fragments = [
            "b" + "uy",
            "s" + "ell",
            "h" + "old",
            "sh" + "ould",
            "u" + "ndervalued",
            "ov" + "ervalued",
            "ap" + "pears",
            "rec" + "ommend",
        ]
        for word in banned_fragments:
            assert not re.search(rf"\b{word}\b", joined), (
                f"banned token leaked through: {word!r}"
            )


# ── 4. System-prompt context assembly ───────────────────────────

class TestSystemPrompt:
    def test_system_prompt_includes_ticker_and_numbers(self):
        from backend.routers.chat import build_system_prompt

        prompt = build_system_prompt(
            _StubAnalysis().model_dump(), "HDFCBANK.NS",
        )
        # SEBI guard is present.
        assert "MUST NOT use any of these words" in prompt
        # Numbers from the stub are quoted verbatim.
        assert "HDFCBANK.NS" in prompt
        assert "HDFC Bank Ltd" in prompt
        assert "Rs 1,146" in prompt
        assert "53.4" in prompt
        # No banned vocab leaks INTO the system prompt itself.
        from backend.services import ai_explain_service as svc
        assert svc._find_banned(prompt.replace("MUST NOT use any of these words, in any form: buy, sell, hold, recommend, recommendation, accumulate, outperform, underperform, should, appears, concern, strength, weakness, expensive, cheap, undervalued, overvalued, attractive, poor, strong, weak, investable, investability.", "")) is None
