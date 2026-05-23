# backend/routers/concall.py
# ═══════════════════════════════════════════════════════════════
# Concall (earnings call) analysis endpoints — Pro tier required.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from backend.middleware.auth import get_current_user
from backend.services.concall_service import (
    analyze_transcript,
    save_user_concall,
    get_user_concalls,
)

logger = logging.getLogger("yieldiq.concall")

router = APIRouter(prefix="/api/v1/concall", tags=["concall"])


class AnalyzeRequest(BaseModel):
    transcript: str
    ticker: str = ""
    quarter: str = ""
    save: bool = True


def _require_paid_tier(user: dict) -> None:
    tier = user.get("tier", "free")
    if tier == "free":
        raise HTTPException(
            status_code=402,
            detail="Concall AI summaries require Pro plan (Rs 299/mo). Upgrade to unlock.",
        )


@router.post("/analyze")
async def analyze_concall(req: AnalyzeRequest, user: dict = Depends(get_current_user)):
    """
    Analyze an earnings call transcript using AI.
    Pro/Analyst tier required.

    Returns structured insights:
        executive_summary, financial_highlights, forward_guidance,
        strategic_priorities, q_and_a_themes, concerns_raised, sentiment
    """
    _require_paid_tier(user)

    if not req.transcript or len(req.transcript.strip()) < 200:
        raise HTTPException(status_code=400, detail="Transcript must be at least 200 characters")

    try:
        result = analyze_transcript(req.transcript, req.ticker, req.quarter)
        if result.get("error"):
            raise HTTPException(status_code=400, detail=result["error"])

        # Save to user's library if requested
        if req.save and user.get("email"):
            try:
                save_user_concall(user["email"], result)
            except Exception as e:
                logger.warning(f"Save concall failed: {e}")

        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.warning(f"analyze_concall failed: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail="Concall analysis failed")


@router.get("/library")
async def list_user_concalls(ticker: str = "", user: dict = Depends(get_current_user)):
    """List user's saved concall analyses (optionally filtered by ticker)."""
    _require_paid_tier(user)
    email = user.get("email", "")
    if not email:
        return {"items": []}
    items = get_user_concalls(email, ticker=ticker if ticker else None)
    return {"items": items, "count": len(items)}


# ─────────────────────────────────────────────────────────────────
# Phase G-intel-phase1 (c): public-read structured-signals endpoints
#
# Two endpoints, both no-auth, both read-only against the
# `concall_signals` table populated by the batch extractor
# (extract_concall_signals_batch.py, PR #567).
#
#   1. GET /api/v1/concall/{transcript_id}/signals
#        Returns the signals row linked to a specific transcript_id
#        (column added in migration 059). Useful for the operator
#        review surface and any future per-transcript drilldown.
#
#   2. GET /api/v1/concall/signals/by-ticker/{ticker}/latest
#        Returns the most-recent (by concall_date DESC) signals row
#        for a ticker. This is what the public ConcallSignalsPanel
#        on /analysis/[ticker] consumes.
#
# Both endpoints follow the same withheld-protocol: when
# quality_flag == 'sebi_withheld' on the row, we return
# {signals: null, withheld: true, ...} so the frontend can render a
# neutral "withheld pending review" affordance instead of unsafe
# free text.
# ─────────────────────────────────────────────────────────────────

def _connect_signals():
    """Open a psycopg2 connection for the signals read endpoints.
    Returns None on missing DATABASE_URL or driver-import failure so
    the endpoints can downgrade to a {signals: null} 200 response
    instead of 500-ing the analysis page.
    """
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg2  # type: ignore
        return psycopg2.connect(url)
    except Exception as exc:
        logger.debug("concall signals: psycopg2.connect failed (%s)", exc)
        return None


def _parse_jsonb(value: Any) -> Any:
    """psycopg2 returns JSONB as either dict/list (when the connection
    has the JSON adapter registered) or as a raw JSON string. Normalise
    to the Python object."""
    if value is None:
        return None
    if isinstance(value, (dict, list)):
        return value
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return value


def _row_to_payload(row: tuple) -> dict:
    """Convert a SELECTed row to the public JSON shape.

    Row layout MUST match the SELECT column order in both query sites
    below. Centralised so the two endpoints can't drift.
    """
    (
        signals_id,
        ticker_row,
        fiscal_period,
        concall_date,
        transcript_source,
        guidance_changes,
        capex_commitments,
        margin_commentary,
        management_tone,
        key_quotes,
        extracted_at,
        extractor_version,
        quality_flag,
        transcript_id_row,
    ) = row

    # SEBI-withheld rows return a neutral envelope. We still expose the
    # transcript_id + fiscal_period metadata so the operator review
    # surface can find the row, but the free-text signals are nulled.
    if (quality_flag or "").lower() == "sebi_withheld":
        return {
            "signals": None,
            "withheld": True,
            "ticker": ticker_row,
            "fiscal_period": fiscal_period,
            "concall_date": concall_date.isoformat() if concall_date else None,
            "transcript_id": transcript_id_row,
            "quality_flag": quality_flag,
            "generated_at": extracted_at.isoformat() if extracted_at else None,
        }

    return {
        "signals": {
            "fiscal_period": fiscal_period,
            "concall_date": concall_date.isoformat() if concall_date else None,
            "transcript_source": transcript_source,
            "guidance_changes": _parse_jsonb(guidance_changes) or [],
            "capex_commitments": _parse_jsonb(capex_commitments) or [],
            "margin_commentary": _parse_jsonb(margin_commentary) or [],
            "management_tone": management_tone,
            "key_quotes": _parse_jsonb(key_quotes) or [],
            "extractor_version": extractor_version,
        },
        "withheld": False,
        "ticker": ticker_row,
        "fiscal_period": fiscal_period,
        "transcript_id": transcript_id_row,
        "quality_flag": quality_flag or "ok",
        "generated_at": extracted_at.isoformat() if extracted_at else None,
    }


_SIGNALS_SELECT = (
    "SELECT id, ticker, fiscal_period, concall_date, transcript_source, "
    "guidance_changes, capex_commitments, margin_commentary, "
    "management_tone, key_quotes, extracted_at, extractor_version, "
    "quality_flag, transcript_id FROM concall_signals "
)


def _empty_payload() -> dict:
    return {
        "signals": None,
        "withheld": False,
        "ticker": None,
        "fiscal_period": None,
        "transcript_id": None,
        "quality_flag": None,
        "generated_at": None,
    }


@router.get("/{transcript_id}/signals")
async def get_signals_for_transcript(transcript_id: int):
    """Return the concall_signals row linked to a specific transcript.

    Per-transcript lookup. Most signals are unique per
    (ticker, fiscal_period) but we key the public read on
    transcript_id because that's the stable identifier the operator
    review surface holds. When no row exists, returns a 200 with
    {signals: null} so the caller doesn't need a special 404 path.
    """
    if transcript_id is None or transcript_id <= 0:
        raise HTTPException(status_code=400, detail="transcript_id must be a positive integer")
    conn = _connect_signals()
    if conn is None:
        return _empty_payload()
    try:
        with conn:
            with conn.cursor() as cur:
                cur.execute(
                    _SIGNALS_SELECT
                    + "WHERE transcript_id = %s ORDER BY extracted_at DESC LIMIT 1",
                    (transcript_id,),
                )
                row = cur.fetchone()
        if not row:
            return _empty_payload()
        return _row_to_payload(row)
    except Exception as exc:
        logger.warning("get_signals_for_transcript failed: %s", exc)
        return _empty_payload()
    finally:
        try:
            conn.close()
        except Exception:
            pass


@router.get("/signals/by-ticker/{ticker}/latest")
async def get_latest_signals_for_ticker(ticker: str):
    """Return the most-recent concall_signals row for a ticker.

    Backs the public ConcallSignalsPanel on /analysis/[ticker]. Strips
    any exchange suffix (.NS / .BO) so RELIANCE.NS and plain RELIANCE
    both match — the signals table is keyed by bare ticker. Returns
    {signals: null} when there's no extraction yet.
    """
    raw = (ticker or "").strip().upper()
    if not raw:
        raise HTTPException(status_code=400, detail="ticker required")
    # Strip common exchange suffixes — concall_signals.ticker is stored
    # in the bare form by the extractor batch script.
    bare = raw
    for suffix in (".NS", ".BO"):
        if bare.endswith(suffix):
            bare = bare[: -len(suffix)]
            break
    conn = _connect_signals()
    if conn is None:
        return _empty_payload()
    try:
        with conn:
            with conn.cursor() as cur:
                # Match either the bare ticker or the suffixed form to
                # be defensive against historical writes that included
                # the .NS suffix.
                cur.execute(
                    _SIGNALS_SELECT
                    + "WHERE ticker IN (%s, %s, %s) "
                    "ORDER BY concall_date DESC NULLS LAST, extracted_at DESC LIMIT 1",
                    (bare, f"{bare}.NS", f"{bare}.BO"),
                )
                row = cur.fetchone()
        if not row:
            return _empty_payload()
        return _row_to_payload(row)
    except Exception as exc:
        logger.warning("get_latest_signals_for_ticker(%s) failed: %s", bare, exc)
        return _empty_payload()
    finally:
        try:
            conn.close()
        except Exception:
            pass
