# backend/services/concall_intel_service.py
# ===============================================================
# Concall INTELLIGENCE -- structured-signal extraction from earnings
# call transcripts using the Claude (Anthropic) API.
#
# This is DISTINCT from backend/services/concall_service.py which
# returns a free-text retail-investor TL;DR via Groq/Llama. Intel
# returns STRUCTURED, machine-queryable signals that downstream
# analytics (alerts, percentile cohorts, retrospective backtests)
# can consume.
#
# Phase 0 (current): scaffold only. extract_concall_signals() raises
# NotImplementedError unless an `anthropic_client` is injected (used
# by the unit test with a mock). No live LLM calls in this phase.
# No anthropic SDK in requirements.txt yet -- added in Phase 1.
#
# Phase 1 (later session): wire real Anthropic client, prompt cache
# the system prompt + tool schema, add a router, add the worker
# job that pulls unextracted concall PDFs.
# ===============================================================
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

logger = logging.getLogger("yieldiq.concall_intel")

EXTRACTOR_VERSION = "concall-intel-v0-scaffold"

# -- JSON shape returned by the LLM (and stored in concall_signals) --
# {
#   "fiscal_period":     "Q1FY26",                  # str, e.g. "Q3FY25"
#   "concall_date":      "2026-04-25",              # ISO date str
#   "transcript_source": "nse_pdf|user_paste|...",  # provenance tag
#   "guidance_changes": [
#     {"metric": "revenue_growth_fy26",
#      "previous": "12-15%",
#      "new":      "14-16%",
#      "direction": "raised|lowered|reaffirmed",
#      "quote": "..."}
#   ],
#   "capex_commitments": [
#     {"amount_cr": 1200, "horizon": "FY26-FY28",
#      "purpose": "new fab in Sanand", "quote": "..."}
#   ],
#   "margin_commentary": [
#     {"segment": "consumer",
#      "direction": "expansion|contraction|stable",
#      "drivers": ["RM tailwind", "premiumisation"],
#      "quote": "..."}
#   ],
#   "management_tone":  "bullish|neutral|cautious|defensive",
#   "key_quotes": [
#     {"speaker": "CFO", "topic": "working capital", "quote": "..."}
#   ]
# }


def extract_concall_signals(
    ticker: str,
    transcript_text: str,
    anthropic_client: Optional[Any] = None,
) -> dict:
    """Extract structured signals from an earnings call transcript.

    Phase-0 scaffold. The real implementation (Phase 1) will:
      1. Build a prompt with the schema spec embedded.
      2. Call ``anthropic_client.messages.create(...)`` with
         tool-use forcing the JSON schema below.
      3. Parse + validate the tool-use payload.
      4. Return the dict in the shape documented at the top of
         this module.

    Args:
        ticker: NSE/BSE ticker symbol (e.g. "TCS", "RELIANCE").
        transcript_text: Full earnings call transcript text.
        anthropic_client: An anthropic.Anthropic-compatible client.
            If None, the call raises NotImplementedError. Tests
            inject a Mock that returns a stubbed messages.create
            response.

    Returns:
        dict with keys: fiscal_period, concall_date,
        transcript_source, guidance_changes, capex_commitments,
        margin_commentary, management_tone, key_quotes.

    Raises:
        NotImplementedError: if no anthropic_client is supplied
        (Phase-0 guard so we never silently hit the live API
        from a code path that forgot to wire it).
        ValueError: if the LLM response cannot be parsed as the
        expected schema.
    """
    if anthropic_client is None:
        raise NotImplementedError(
            "concall_intel_service.extract_concall_signals: live "
            "Anthropic client wiring is a Phase-1 task. Inject a "
            "client (or a mock in tests) to use the parsing path."
        )

    if not ticker or not isinstance(ticker, str):
        raise ValueError("ticker must be a non-empty string")
    if not transcript_text or len(transcript_text.strip()) < 200:
        raise ValueError(
            "transcript_text too short (<200 chars) -- pass a full "
            "transcript to extract meaningful signals."
        )

    # Phase-0 minimal parsing path (exercised by the mocked test).
    # The mock client should return an object with a .content list
    # whose first item has a .text attribute containing JSON. This
    # mirrors the basic anthropic SDK response shape so swapping in
    # the real client in Phase 1 is a small change.
    try:
        response = anthropic_client.messages.create(
            model="claude-opus-4-7",
            max_tokens=4096,
            messages=[
                {
                    "role": "user",
                    "content": (
                        f"Extract structured concall signals for {ticker}.\n\n"
                        f"Transcript:\n{transcript_text}\n\n"
                        "Respond with a single JSON object matching the "
                        "schema documented in concall_intel_service.py."
                    ),
                }
            ],
        )
    except Exception as exc:  # pragma: no cover (Phase-1 wires real retry)
        logger.warning("anthropic_client.messages.create failed: %s", exc)
        raise

    try:
        raw_text = response.content[0].text
    except (AttributeError, IndexError) as exc:
        raise ValueError(
            f"unexpected anthropic response shape: {exc}"
        ) from exc

    try:
        signals = json.loads(raw_text)
    except json.JSONDecodeError as exc:
        raise ValueError(
            f"LLM did not return valid JSON: {exc}"
        ) from exc

    if not isinstance(signals, dict):
        raise ValueError("LLM JSON root must be an object")

    signals.setdefault("extractor_version", EXTRACTOR_VERSION)
    return signals


# -- DB persistence ----------------------------------------------

def _connect():
    """Open a psycopg2 connection. Returns None if DATABASE_URL is
    unset or the connect fails -- callers must handle the None.
    Same pattern as backend/services/api_keys_service.py."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg2  # type: ignore
        return psycopg2.connect(url)
    except Exception as exc:
        logger.debug("concall_intel: psycopg2.connect failed (%s)", exc)
        return None


def save_signals(ticker: str, fiscal_period: str, signals: dict) -> bool:
    """UPSERT a concall_signals row for (ticker, fiscal_period).

    Returns True on success, False if the DB is unreachable or the
    insert fails. Does NOT raise on DB errors -- callers can decide
    whether to retry.

    The signals dict is expected to match the schema documented in
    extract_concall_signals.
    """
    if not ticker or not fiscal_period:
        raise ValueError("ticker and fiscal_period are required")
    if not isinstance(signals, dict):
        raise ValueError("signals must be a dict")

    conn = _connect()
    if conn is None:
        logger.info(
            "save_signals: no DATABASE_URL -- skipping persist for %s %s",
            ticker, fiscal_period,
        )
        return False

    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    INSERT INTO concall_signals (
                        ticker, fiscal_period, concall_date,
                        transcript_source, guidance_changes,
                        capex_commitments, margin_commentary,
                        management_tone, key_quotes, extractor_version
                    ) VALUES (
                        %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
                    )
                    ON CONFLICT (ticker, fiscal_period) DO UPDATE SET
                        concall_date      = EXCLUDED.concall_date,
                        transcript_source = EXCLUDED.transcript_source,
                        guidance_changes  = EXCLUDED.guidance_changes,
                        capex_commitments = EXCLUDED.capex_commitments,
                        margin_commentary = EXCLUDED.margin_commentary,
                        management_tone   = EXCLUDED.management_tone,
                        key_quotes        = EXCLUDED.key_quotes,
                        extracted_at      = now(),
                        extractor_version = EXCLUDED.extractor_version
                    """,
                    (
                        ticker,
                        fiscal_period,
                        signals.get("concall_date"),
                        signals.get("transcript_source"),
                        json.dumps(signals.get("guidance_changes") or []),
                        json.dumps(signals.get("capex_commitments") or []),
                        json.dumps(signals.get("margin_commentary") or []),
                        signals.get("management_tone"),
                        json.dumps(signals.get("key_quotes") or []),
                        signals.get("extractor_version", EXTRACTOR_VERSION),
                    ),
                )
        return True
    except Exception as exc:
        logger.warning("save_signals UPSERT failed: %s", exc)
        return False
    finally:
        try:
            conn.close()
        except Exception:
            pass
