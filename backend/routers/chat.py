# backend/routers/chat.py
# ═══════════════════════════════════════════════════════════════
# T6.2 Phase A (2026-06-10) — multi-turn streaming chat router.
#
#   POST /api/v1/analysis/{ticker}/chat   (Server-Sent Events stream)
#
# Body shape:
#   {
#     "messages": [{"role": "user"|"assistant", "content": "..."}, ...],
#     "ticker": "HDFCBANK.NS"
#   }
#
# Wire shape: text/event-stream with JSON-encoded payloads of the
# form ``{"delta": "<token-chunk>", "done": false}``. A terminal
# event ``{"delta": "", "done": true}`` marks completion.
#
# This is the streaming sibling of the single-shot R4 ``ai_explain``
# endpoint. It reuses the same Anthropic wiring (lazy import,
# ANTHROPIC_API_KEY env var, claude-sonnet-4-5 by default) and the
# same SEBI-strict register — the system prompt forbids the advisory
# vocab list, and we filter each assembled delta-window through the
# shared sebi banned-vocab guard before forwarding to the client.
#
# The system prompt includes a compact summary of the cached
# AnalysisResponse so multi-turn questions can reference the model's
# actual numbers (fair value, MoS, WACC, scenarios) without
# re-running the engine. The same ``ai_explain_service`` context
# builder is reused so the chat answer text and the preset answer
# text reference the same numbers.
#
# Free-tier rate-limit: chat counts against the shared 5/day analyse
# counter (same as ``ai_explain``) so a single user cannot grind the
# LLM budget through repeated chat turns.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import asyncio
import json
import logging
import os
import re
from typing import Any, AsyncIterator, Iterable, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field

from backend.middleware.auth import get_current_user
from backend.middleware.rate_limit import rate_limiter, clamped_used
from backend.services.analysis_service import (
    AnalysisService,
    TickerNotFoundError,
)
from backend.services import ai_explain_service as explain_svc

logger = logging.getLogger("yieldiq.chat")

router = APIRouter(prefix="/api/v1/analysis", tags=["chat"])

_analysis = AnalysisService()

# Caps. Chat is multi-turn so we keep these tight: a long thread is
# expensive and the user can always start a new one.
_MAX_MESSAGES = 30
_MAX_TURN_CHARS = 4000
_MAX_TOKENS = 800
_DEFAULT_MODEL = explain_svc.DEFAULT_ANTHROPIC_MODEL

_BANNED_RE = explain_svc._BANNED_RE  # canonical SEBI vocab regex


# ── Request shape ───────────────────────────────────────────────

class ChatMessage(BaseModel):
    role: str = Field(..., description="'user' or 'assistant'")
    content: str = Field(..., max_length=_MAX_TURN_CHARS)


class ChatRequest(BaseModel):
    ticker: str = Field(..., min_length=1, max_length=24)
    messages: list[ChatMessage] = Field(default_factory=list)


# ── System-prompt assembly ──────────────────────────────────────

# A long, stable prefix that is cheap to prompt-cache. The
# observational-vocab constraint is the same one ``ai_explain``
# enforces; we inline the banned list verbatim so a curious user
# inspecting the system prompt sees the constraint, and the model
# does not need to chase a cross-reference at inference time.
_SYSTEM_PROMPT_BASE = (
    "You are a careful Indian-equities valuation analyst chatting "
    "with a retail investor about ONE specific stock. Stay strictly "
    "observational and descriptive — describe what the YieldIQ model "
    "SEES; never instruct the reader to act.\n\n"
    "HARD CONSTRAINTS (SEBI IA Regulations 2013 — non-negotiable):\n"
    "* You MUST NOT use any of these words, in any form: buy, sell, "
    "hold, recommend, recommendation, accumulate, outperform, "
    "underperform, should, appears, concern, strength, weakness, "
    "expensive, cheap, undervalued, overvalued, attractive, poor, "
    "strong, weak, investable, investability.\n"
    "* Use descriptive vocabulary: 'MoS', 'composite IV gap', "
    "'sector cohort percentile', 'fair-value reference', 'scenario "
    "range', 'WACC sensitivity', etc.\n"
    "* Cite numbers from the analysis context VERBATIM. Do not invent "
    "metrics that are not in the context block.\n"
    "* Stay on the stock named in the context. If the user asks about "
    "a different ticker, redirect them to open that ticker's page.\n"
    "* Keep replies to 2-4 short paragraphs unless the user asks for "
    "more depth. Plain prose; no markdown bold/italic.\n"
    "* No 'in conclusion' / 'overall' / 'in summary'.\n"
)


def _fmt_money(v: Optional[float]) -> str:
    return "n/a" if v is None else f"Rs {v:,.0f}"


def _fmt_pct(v: Optional[float], dp: int = 1) -> str:
    return "n/a" if v is None else f"{v:.{dp}f}%"


def build_system_prompt(analysis_payload: dict, ticker: str) -> str:
    """Stitch the base SEBI prompt with a compact analysis context.

    Reuses ``ai_explain_service.build_context_from_analysis`` so the
    chat surface and the preset-card surface always see the same
    numbers (single source of truth).
    """
    ctx = explain_svc.build_context_from_analysis(
        analysis_payload, ticker, "chat",
    )
    lines: list[str] = [
        "CONTEXT — current YieldIQ analysis for this ticker:",
        f"Stock: {ctx.company_name} ({ctx.ticker})",
        f"Sector: {ctx.sector or 'n/a'}",
        f"Model verdict: {ctx.verdict_display}",
        f"Current price: {_fmt_money(ctx.current_price)}",
        (
            f"Fair-value reference: {_fmt_money(ctx.fair_value)} "
            f"(MoS {_fmt_pct(ctx.mos_pct)})"
        ),
        (
            f"Scenario range: bear {_fmt_money(ctx.bear_case)} / "
            f"base {_fmt_money(ctx.base_case)} / "
            f"bull {_fmt_money(ctx.bull_case)}"
        ),
        (
            f"DCF inputs: WACC {_fmt_pct(ctx.wacc_pct)}, "
            f"FCF growth {_fmt_pct(ctx.fcf_growth_pct)}, "
            f"terminal {_fmt_pct(ctx.terminal_growth_pct)}"
        ),
    ]
    if ctx.moat_label:
        moat = f"Moat: {ctx.moat_label}"
        if ctx.moat_score is not None:
            moat += f" (sub-score {ctx.moat_score:.0f})"
        lines.append(moat)
    if ctx.confidence_pct is not None:
        lines.append(f"Model confidence: {ctx.confidence_pct}%")
    if ctx.sector_medians:
        lines.append(f"Sector medians: {ctx.sector_medians}")

    return _SYSTEM_PROMPT_BASE + "\n" + "\n".join(lines) + "\n"


# ── Streaming helpers ───────────────────────────────────────────

def _sse_event(payload: dict) -> bytes:
    """Encode a single SSE event line. UTF-8 bytes for StreamingResponse."""
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n".encode("utf-8")


def _coerce_messages(msgs: Iterable[ChatMessage]) -> list[dict[str, str]]:
    """Validate + coerce the wire-shape messages into Anthropic format.

    Drops empty turns. Rejects unknown roles. Enforces strict
    alternation is NOT required — Anthropic accepts any sequence —
    but we cap the total at ``_MAX_MESSAGES`` to keep token cost
    bounded. The most-recent ``_MAX_MESSAGES`` turns are kept.
    """
    out: list[dict[str, str]] = []
    for m in msgs:
        role = (m.role or "").strip().lower()
        content = (m.content or "").strip()
        if role not in ("user", "assistant"):
            raise HTTPException(
                status_code=400,
                detail=f"unknown role: {m.role!r}",
            )
        if not content:
            continue
        out.append({"role": role, "content": content})
    if not out:
        raise HTTPException(
            status_code=400, detail="at least one user message required",
        )
    if out[-1]["role"] != "user":
        raise HTTPException(
            status_code=400,
            detail="last message must have role='user'",
        )
    return out[-_MAX_MESSAGES:]


def _strip_banned(text: str) -> str:
    """Replace any SEBI-banned token with 'rated' (same logic as ai_explain).

    Applied per delta window before forwarding to the client. This is
    a defence-in-depth on top of the system-prompt constraint — the
    model occasionally lapses into advisory vocab and we MUST never
    let it reach the user.
    """
    if not text:
        return text
    return _BANNED_RE.sub("rated", text)


# ── Anthropic streaming dispatch ────────────────────────────────

def _build_anthropic_client() -> Optional[Any]:
    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return None
    try:
        from anthropic import Anthropic
        return Anthropic(api_key=api_key)
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning("anthropic client init failed: %s", exc)
        return None


def _deterministic_fallback(messages: list[dict[str, str]], ctx_dict: dict, ticker: str) -> str:
    """When no Claude client is available, hand back a SEBI-safe template
    that quotes the analysis numbers and acknowledges the user's last
    question without inventing facts.
    """
    last_user = next(
        (m["content"] for m in reversed(messages) if m["role"] == "user"),
        "",
    )
    ctx = explain_svc.build_context_from_analysis(ctx_dict, ticker, "chat")
    body = (
        f"You asked: \"{last_user[:160]}\". The YieldIQ model currently "
        f"reads {ctx.company_name or ticker} at a fair-value reference "
        f"of {_fmt_money(ctx.fair_value)} with MoS {_fmt_pct(ctx.mos_pct)} "
        f"versus the live quote of {_fmt_money(ctx.current_price)}.\n\n"
        f"The DCF inputs behind that number are WACC "
        f"{_fmt_pct(ctx.wacc_pct)}, FCF growth "
        f"{_fmt_pct(ctx.fcf_growth_pct)}, and terminal "
        f"{_fmt_pct(ctx.terminal_growth_pct)}. The scenario fan runs "
        f"bear {_fmt_money(ctx.bear_case)} / base "
        f"{_fmt_money(ctx.base_case)} / bull {_fmt_money(ctx.bull_case)}.\n\n"
        f"This is a deterministic fallback because the live AI backend "
        f"is unavailable. Reload to retry the streaming path."
    )
    return _strip_banned(body)


async def _stream_anthropic(
    client: Any,
    system_prompt: str,
    messages: list[dict[str, str]],
    model: str,
) -> AsyncIterator[str]:
    """Yield raw text deltas from an Anthropic streaming response.

    Runs the blocking SDK iterator on a worker thread so the event-
    loop stays responsive. Each yielded chunk is the raw model
    output — the caller is responsible for SEBI-filtering before it
    reaches the client.
    """
    # The Anthropic streaming context manager is synchronous; run it
    # in a thread and bridge chunks back via an asyncio.Queue.
    queue: asyncio.Queue[Optional[str]] = asyncio.Queue()

    def worker() -> None:
        try:
            with client.messages.stream(
                model=model,
                max_tokens=_MAX_TOKENS,
                system=[{
                    "type": "text",
                    "text": system_prompt,
                    "cache_control": {"type": "ephemeral"},
                }],
                messages=messages,
            ) as stream:
                for text in stream.text_stream:
                    if text:
                        # asyncio.Queue.put_nowait is thread-safe for a
                        # single producer because it is just dict-append
                        # under the hood, but we use loop.call_soon_threadsafe
                        # to be strictly correct.
                        asyncio.run_coroutine_threadsafe(
                            queue.put(text), loop,
                        )
        except Exception as exc:
            logger.warning("anthropic stream failed: %s", exc)
        finally:
            asyncio.run_coroutine_threadsafe(queue.put(None), loop)

    loop = asyncio.get_running_loop()
    fut = loop.run_in_executor(None, worker)

    try:
        while True:
            chunk = await queue.get()
            if chunk is None:
                break
            yield chunk
    finally:
        await fut


# ── Endpoint ────────────────────────────────────────────────────

@router.post("/{ticker}/chat")
async def chat_stream(
    ticker: str,
    body: ChatRequest,
    user: dict = Depends(get_current_user),
) -> StreamingResponse:
    """Stream a SEBI-filtered chat reply for the given ticker."""
    norm_ticker = (ticker or "").upper().strip()
    if not norm_ticker:
        raise HTTPException(status_code=400, detail="ticker required")
    if (body.ticker or "").upper().strip() != norm_ticker:
        # The body ticker must match the path. Mismatched values
        # historically caused cross-stock context leaks in v6 -- fail
        # fast rather than guess.
        raise HTTPException(
            status_code=400,
            detail="body.ticker must match path ticker",
        )

    messages = _coerce_messages(body.messages)

    # Tier-gate against the same daily counter as analyze() / ai_explain.
    user_tier = (user.get("tier") or "free").lower()
    user_id = str(
        user.get("id") or user.get("user_id") or user.get("email") or "anon"
    )
    allowed, used, limit = rate_limiter.check_and_increment(
        user_id=user_id, tier=user_tier,
    )
    if not allowed:
        raise HTTPException(
            status_code=429,
            detail={
                "error": "Daily analysis limit reached",
                "used": clamped_used(used, limit),
                "limit": limit,
                "tier": user_tier,
            },
        )

    # Load the cached analyze() payload so the system prompt can
    # quote real numbers. We use to_thread because get_full_analysis
    # is sync; on a cache hit this is sub-millisecond.
    try:
        analysis = await asyncio.to_thread(
            _analysis.get_full_analysis, norm_ticker,
        )
    except TickerNotFoundError:
        raise HTTPException(
            status_code=404,
            detail={"error": "Ticker not found", "ticker": norm_ticker},
        )
    except Exception as exc:  # pragma: no cover — defensive
        logger.warning(
            "chat: get_full_analysis failed for %s: %s", norm_ticker, exc,
        )
        raise HTTPException(
            status_code=503,
            detail={"error": "analysis_unavailable", "retry_after": 30},
        )

    payload = explain_svc.build_context_from_analysis(
        # Reuse the same dict-coerce path the R4 router uses.
        getattr(analysis, "model_dump", lambda: dict(vars(analysis)))(),
        norm_ticker,
        "chat",
    )
    payload_dict = (
        analysis.model_dump()
        if hasattr(analysis, "model_dump")
        else dict(vars(analysis))
    )

    system_prompt = build_system_prompt(payload_dict, norm_ticker)

    client = _build_anthropic_client()

    async def event_source() -> AsyncIterator[bytes]:
        """Async generator yielding SSE-encoded chunks."""
        # Header event: lets the client confirm the stream opened.
        yield _sse_event({"delta": "", "done": False, "event": "open"})

        if client is None:
            text = _deterministic_fallback(messages, payload_dict, norm_ticker)
            # Defence-in-depth: scrub each chunk before forwarding even
            # though _deterministic_fallback already scrubs the full
            # string. A future regression in the template path must NOT
            # be able to leak banned vocab through SSE.
            for chunk in _chunked(text, 80):
                yield _sse_event({
                    "delta": _strip_banned(chunk),
                    "done": False,
                    "source": "template",
                })
            yield _sse_event({"delta": "", "done": True, "source": "template"})
            return

        try:
            async for raw in _stream_anthropic(
                client, system_prompt, messages, _DEFAULT_MODEL,
            ):
                safe = _strip_banned(raw)
                if safe:
                    yield _sse_event({"delta": safe, "done": False})
            yield _sse_event({"delta": "", "done": True, "source": "llm"})
        except Exception as exc:
            logger.warning(
                "chat: stream errored for %s: %s", norm_ticker, exc,
            )
            yield _sse_event({
                "delta": "",
                "done": True,
                "error": "stream_failed",
            })

    return StreamingResponse(
        event_source(),
        media_type="text/event-stream",
        headers={
            # Disable proxy buffering so chunks reach the client live.
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


def _chunked(text: str, size: int) -> list[str]:
    """Split a string into ``size``-char chunks (no word-boundary care)."""
    return [text[i:i + size] for i in range(0, len(text), size)] or [""]
