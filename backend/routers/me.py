# backend/routers/me.py
# ═══════════════════════════════════════════════════════════════
# Phase 4 manifesto (Paradigm 11) — Memory Lane.
#
# Per-user, per-ticker personal history layer. Two endpoints, table =
# user_ticker_visits (migration 066):
#
#   POST /api/v1/me/ticker-visit/{ticker}    — upsert visit (auth required)
#   GET  /api/v1/me/memory-lane/{ticker}     — fetch personal history payload
#   PUT  /api/v1/me/memory-lane/{ticker}/note — save user note (debounced
#                                               auto-save from frontend)
#
# SEBI safety: copy/labels are descriptive ("you first analyzed this 47
# days ago"), never advisory. The component renders only for users with a
# prior visit; anon and first-time visitors get 204 / null.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Response
from pydantic import BaseModel, Field

_PROJECT_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from backend.middleware.auth import get_current_user

logger = logging.getLogger("yieldiq.memory_lane")

router = APIRouter(prefix="/api/v1/me", tags=["me"])


# ─────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────
def _norm_visit_ticker(ticker: str) -> str:
    """Strip exchange suffix so HDFCBANK and HDFCBANK.NS share a row.

    Mirrors backend/routers/public.py::_norm_sentiment_ticker so the two
    user-keyed tables (votes + visits) aggregate the same way.
    """
    t = (ticker or "").upper().strip()
    for suf in (".NS", ".BO", ".BSE", ".NSE"):
        if t.endswith(suf):
            t = t[: -len(suf)]
    return t


def _pg_conn():
    """Open a psycopg2 connection or raise 503. Mirrors sentiment pattern."""
    import psycopg2
    url = os.environ.get("DATABASE_URL")
    if not url:
        raise HTTPException(status_code=503, detail="DB unavailable")
    try:
        return psycopg2.connect(url)
    except Exception as exc:
        logger.warning("memory_lane DB connect failed: %s", exc)
        raise HTTPException(status_code=503, detail="DB unavailable") from exc


def _fetch_current_snapshot(ticker_bare: str) -> dict:
    """Pull current price/FV/verdict for the canonical (suffix-bearing) ticker.

    Tries each common Indian suffix because analysis_cache keys on the
    suffixed form (e.g. HDFCBANK.NS). Returns {} on miss — callers handle
    gracefully.
    """
    try:
        from backend.services.analysis_cache_service import get_cached
    except Exception as exc:
        logger.warning("memory_lane: cache import failed: %s", exc)
        return {}

    for suffix in (".NS", ".BO", ""):
        candidate = f"{ticker_bare}{suffix}"
        try:
            payload = get_cached(
                candidate,
                max_age_hours=24,
                fields_needed=["fair_value", "current_price", "verdict"],
            )
        except Exception:
            payload = None
        if not payload:
            continue
        val = (payload or {}).get("valuation") or {}
        price = val.get("current_price")
        fv = val.get("fair_value")
        verdict = val.get("verdict")
        # Cast numerics defensively (cache sometimes stringifies).
        try:
            price = float(price) if price is not None else None
        except (TypeError, ValueError):
            price = None
        try:
            fv = float(fv) if fv is not None else None
        except (TypeError, ValueError):
            fv = None
        return {
            "current_price": price,
            "current_fair_value": fv,
            "current_verdict": verdict,
        }
    return {}


def _days_between(then: datetime, now: Optional[datetime] = None) -> int:
    """UTC day difference, floor at 0 (never report 'visited tomorrow')."""
    n = now or datetime.now(timezone.utc)
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    delta = n - then
    return max(0, int(delta.total_seconds() // 86400))


def _pct_delta(old: Optional[float], new: Optional[float]) -> Optional[float]:
    """((new - old) / old) * 100, rounded to 1dp. None if either side missing
    or old is non-positive (avoid divide-by-zero and silly negatives)."""
    if old is None or new is None:
        return None
    try:
        old_f = float(old)
        new_f = float(new)
    except (TypeError, ValueError):
        return None
    if old_f <= 0:
        return None
    return round(((new_f - old_f) / old_f) * 100.0, 1)


def _hypothetical_10k(
    price_then: Optional[float],
    price_now: Optional[float],
) -> Optional[float]:
    """Value today of ₹10,000 bought at price_then. None if math undefined."""
    if price_then is None or price_now is None:
        return None
    try:
        pt = float(price_then)
        pn = float(price_now)
    except (TypeError, ValueError):
        return None
    if pt <= 0:
        return None
    return round((10000.0 * pn) / pt, 0)


# ─────────────────────────────────────────────────────────────────
# Models
# ─────────────────────────────────────────────────────────────────
class NoteRequest(BaseModel):
    note: Optional[str] = Field(
        default=None,
        max_length=2000,
        description="Free-form personal note (auto-saved). Max 2000 chars.",
    )


# ─────────────────────────────────────────────────────────────────
# POST /me/ticker-visit/{ticker}
# ─────────────────────────────────────────────────────────────────
@router.post("/ticker-visit/{ticker}")
async def post_ticker_visit(
    ticker: str,
    user: dict = Depends(get_current_user),
):
    """Upsert a visit. On first insert, snapshot current price/FV/verdict.

    On subsequent visits, only ``last_visited_at`` + ``visit_count`` are
    bumped — the snapshot is preserved so the user's personal baseline
    doesn't drift each time they reopen the page.

    Returns ``{"ok": True, "first_visit": bool}`` so the frontend can
    invalidate its ``GET /memory-lane`` query on the very first visit
    (the component appears) without re-fetching on later visits.
    """
    ticker_bare = _norm_visit_ticker(ticker)
    if not ticker_bare:
        raise HTTPException(status_code=400, detail="ticker required")
    user_id = str(user.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="user_id required")

    snapshot = _fetch_current_snapshot(ticker_bare)

    conn = _pg_conn()
    try:
        cur = conn.cursor()
        # ON CONFLICT updates only the visit counters; the snapshot
        # columns are NOT overwritten so they remain anchored to the
        # FIRST visit forever.
        cur.execute(
            """
            INSERT INTO user_ticker_visits (
                user_id, ticker,
                first_visited_at, last_visited_at, visit_count,
                price_at_first_visit, fair_value_at_first_visit,
                verdict_at_first_visit
            ) VALUES (
                %s, %s, now(), now(), 1, %s, %s, %s
            )
            ON CONFLICT (user_id, ticker)
            DO UPDATE SET
                last_visited_at = now(),
                visit_count = user_ticker_visits.visit_count + 1
            RETURNING (xmax = 0) AS inserted
            """,
            (
                user_id,
                ticker_bare,
                snapshot.get("current_price"),
                snapshot.get("current_fair_value"),
                snapshot.get("current_verdict"),
            ),
        )
        row = cur.fetchone()
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("memory_lane visit upsert failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to record visit") from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass

    first_visit = bool(row[0]) if row else False
    return {"ok": True, "first_visit": first_visit}


# ─────────────────────────────────────────────────────────────────
# GET /me/memory-lane/{ticker}
# ─────────────────────────────────────────────────────────────────
@router.get("/memory-lane/{ticker}")
async def get_memory_lane(
    ticker: str,
    response: Response,
    user: dict = Depends(get_current_user),
):
    """Return the personal Memory Lane payload for ``ticker``.

    204 No Content if the signed-in user has never visited this ticker
    (the frontend renders nothing in that case).
    """
    ticker_bare = _norm_visit_ticker(ticker)
    if not ticker_bare:
        raise HTTPException(status_code=400, detail="ticker required")
    user_id = str(user.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="user_id required")

    conn = _pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT
                first_visited_at,
                last_visited_at,
                visit_count,
                price_at_first_visit,
                fair_value_at_first_visit,
                verdict_at_first_visit,
                user_note
            FROM user_ticker_visits
            WHERE user_id = %s AND ticker = %s
            """,
            (user_id, ticker_bare),
        )
        row = cur.fetchone()
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if row is None:
        # 204 — frontend treats as "no memory yet, hide the component".
        response.status_code = 204
        return None

    (
        first_visited_at,
        last_visited_at,
        visit_count,
        price_then,
        fv_then,
        verdict_then,
        user_note,
    ) = row

    current = _fetch_current_snapshot(ticker_bare)
    current_price = current.get("current_price")
    current_fv = current.get("current_fair_value")
    current_verdict = current.get("current_verdict")

    # Cast snapshot numerics — psycopg2 hands NUMERIC back as Decimal.
    def _f(v):
        if v is None:
            return None
        try:
            return float(v)
        except (TypeError, ValueError):
            return None

    price_then_f = _f(price_then)
    fv_then_f = _f(fv_then)

    return {
        "ticker": f"{ticker_bare}.NS",  # canonical display form
        "ticker_bare": ticker_bare,
        "first_visited_at": (
            first_visited_at.isoformat() if first_visited_at else None
        ),
        "last_visited_at": (
            last_visited_at.isoformat() if last_visited_at else None
        ),
        "days_ago": _days_between(first_visited_at) if first_visited_at else 0,
        "visit_count": int(visit_count or 0),
        "price_at_first_visit": price_then_f,
        "fair_value_at_first_visit": fv_then_f,
        "verdict_at_first_visit": verdict_then,
        "current_price": current_price,
        "current_fair_value": current_fv,
        "current_verdict": current_verdict,
        "price_delta_pct": _pct_delta(price_then_f, current_price),
        "fv_delta_pct": _pct_delta(fv_then_f, current_fv),
        "hypothetical_10k_value": _hypothetical_10k(price_then_f, current_price),
        "user_note": user_note,
    }


# ─────────────────────────────────────────────────────────────────
# PUT /me/memory-lane/{ticker}/note
# ─────────────────────────────────────────────────────────────────
@router.put("/memory-lane/{ticker}/note")
async def put_memory_lane_note(
    ticker: str,
    body: NoteRequest,
    user: dict = Depends(get_current_user),
):
    """Save (or clear) the user's note for ``ticker``.

    Requires a prior visit — returns 404 if the user has never opened
    this ticker. The frontend debounces this call by 1s after typing
    stops; treat repeated overwrites as idempotent.
    """
    ticker_bare = _norm_visit_ticker(ticker)
    if not ticker_bare:
        raise HTTPException(status_code=400, detail="ticker required")
    user_id = str(user.get("user_id") or "").strip()
    if not user_id:
        raise HTTPException(status_code=401, detail="user_id required")

    note = body.note
    if note is not None:
        note = note.strip() or None  # empty string clears the note

    conn = _pg_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE user_ticker_visits
            SET user_note = %s
            WHERE user_id = %s AND ticker = %s
            RETURNING id
            """,
            (note, user_id, ticker_bare),
        )
        row = cur.fetchone()
        conn.commit()
    except Exception as exc:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("memory_lane note save failed: %s", exc)
        raise HTTPException(status_code=500, detail="Failed to save note") from exc
    finally:
        try:
            conn.close()
        except Exception:
            pass

    if row is None:
        raise HTTPException(
            status_code=404,
            detail="No visit record yet — open the page once to start a memory.",
        )
    return {"ok": True, "user_note": note}
