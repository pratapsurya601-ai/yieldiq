"""Saved DCF scenarios for paid users (Phase-2 of editable-assumptions).

A scenario is a per-user named bundle of DCF override inputs +
the result computed at save time, scoped to one ticker. The user
edits sliders in <SensitivityPanel/>, hits "Save scenario", names it,
and can re-load it later to see what THEIR assumptions said about the
stock at that moment.

Storage:
  * Postgres table ``saved_scenarios`` (see migration 017).
  * In-memory fallback for hermetic tests / local dev without
    DATABASE_URL — same pattern as api_keys_service.

Tier gating happens at the router layer (``require_tier("pro")``);
this module is auth-agnostic — it trusts the caller to have already
verified the user can save.

Caps:
  * MAX_SCENARIOS_PER_USER = 50. Soft limit to keep the per-user
    list query bounded; pricing tiers can raise this later via
    tier_caps once that PR lands.
"""
from __future__ import annotations

import json
import logging
import os
import threading
from datetime import datetime
from typing import Optional

logger = logging.getLogger("yieldiq.saved_scenarios")

MAX_SCENARIOS_PER_USER = 50
MAX_NAME_LEN = 80

# ── In-memory fallback (hermetic tests, local dev without Postgres) ──
_mem_lock = threading.Lock()
_mem_rows: dict[int, dict] = {}
_mem_id_seq = 0


def _next_mem_id() -> int:
    global _mem_id_seq
    _mem_id_seq += 1
    return _mem_id_seq


def _reset_memory_for_tests() -> None:
    """Wipe in-memory state. Tests use this in an autouse fixture."""
    global _mem_id_seq
    with _mem_lock:
        _mem_rows.clear()
        _mem_id_seq = 0


# ── DB plumbing ──────────────────────────────────────────────────────

def _connect():
    """Open a psycopg2 connection. Returns None if DATABASE_URL is
    unset or connect fails — callers must handle the None and fall
    back to the in-memory store."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg2
        return psycopg2.connect(url)
    except Exception as exc:  # pragma: no cover
        logger.debug("saved_scenarios: psycopg2.connect failed (%s) — using memory", exc)
        return None


def _norm_ticker(t: str) -> str:
    t = (t or "").strip().upper()
    if not t:
        raise ValueError("ticker required")
    return t


def _norm_name(n: str) -> str:
    n = (n or "").strip()[:MAX_NAME_LEN]
    if not n:
        raise ValueError("name required")
    return n


# ── Public API ───────────────────────────────────────────────────────

def count_for_user(user_id: str) -> int:
    if not user_id:
        return 0
    conn = _connect()
    if conn is None:
        with _mem_lock:
            return sum(1 for r in _mem_rows.values() if r["user_id"] == user_id)
    try:
        cur = conn.cursor()
        cur.execute("SELECT COUNT(*) FROM saved_scenarios WHERE user_id = %s", (user_id,))
        n = int(cur.fetchone()[0])
        cur.close()
        return n
    finally:
        try:
            conn.close()
        except Exception:
            pass


def save_scenario(
    user_id: str,
    ticker: str,
    name: str,
    assumptions: dict,
    result: dict,
) -> dict:
    """Insert-or-update the (user, ticker, name) scenario.

    If a row already exists with the same name for this user+ticker,
    overwrite assumptions/result/updated_at. This matches the user's
    mental model: "Save with this name" means "make this the current
    version of that scenario", not "create a duplicate".
    """
    if not user_id:
        raise ValueError("user_id required")
    ticker = _norm_ticker(ticker)
    name = _norm_name(name)
    if not isinstance(assumptions, dict) or not isinstance(result, dict):
        raise ValueError("assumptions and result must be JSON-serialisable dicts")

    # Per-user cap check (only on NEW rows — updates are free).
    conn = _connect()
    now = datetime.utcnow()

    if conn is None:
        with _mem_lock:
            existing_id = None
            for rid, r in _mem_rows.items():
                if (r["user_id"] == user_id
                        and r["ticker"] == ticker
                        and r["name"] == name):
                    existing_id = rid
                    break
            if existing_id is None:
                # Cap check
                count = sum(1 for r in _mem_rows.values() if r["user_id"] == user_id)
                if count >= MAX_SCENARIOS_PER_USER:
                    raise ScenarioCapReached(count, MAX_SCENARIOS_PER_USER)
                new_id = _next_mem_id()
                _mem_rows[new_id] = {
                    "id": new_id,
                    "user_id": user_id,
                    "ticker": ticker,
                    "name": name,
                    "assumptions": assumptions,
                    "result": result,
                    "created_at": now,
                    "updated_at": now,
                }
                return _row_to_dict(_mem_rows[new_id])
            else:
                row = _mem_rows[existing_id]
                row["assumptions"] = assumptions
                row["result"] = result
                row["updated_at"] = now
                return _row_to_dict(row)

    try:
        cur = conn.cursor()
        # Check existence first so we can enforce the cap on inserts only.
        cur.execute(
            "SELECT id FROM saved_scenarios WHERE user_id=%s AND ticker=%s AND name=%s",
            (user_id, ticker, name),
        )
        existing = cur.fetchone()
        if existing is None:
            cur.execute(
                "SELECT COUNT(*) FROM saved_scenarios WHERE user_id=%s",
                (user_id,),
            )
            count = int(cur.fetchone()[0])
            if count >= MAX_SCENARIOS_PER_USER:
                cur.close()
                raise ScenarioCapReached(count, MAX_SCENARIOS_PER_USER)

        # Upsert on the unique (user_id, ticker, name) constraint.
        cur.execute(
            """
            INSERT INTO saved_scenarios
                (user_id, ticker, name, assumptions, result, created_at, updated_at)
            VALUES (%s, %s, %s, %s::jsonb, %s::jsonb, NOW(), NOW())
            ON CONFLICT (user_id, ticker, name) DO UPDATE
              SET assumptions = EXCLUDED.assumptions,
                  result = EXCLUDED.result,
                  updated_at = NOW()
            RETURNING id, created_at, updated_at
            """,
            (user_id, ticker, name, json.dumps(assumptions), json.dumps(result)),
        )
        new_id, created_at, updated_at = cur.fetchone()
        conn.commit()
        cur.close()
        return {
            "id": int(new_id),
            "user_id": user_id,
            "ticker": ticker,
            "name": name,
            "assumptions": assumptions,
            "result": result,
            "created_at": created_at.isoformat() if created_at else None,
            "updated_at": updated_at.isoformat() if updated_at else None,
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


def list_scenarios(user_id: str, ticker: Optional[str] = None) -> list[dict]:
    """List a user's saved scenarios. If ``ticker`` is provided, scope
    to that one ticker — the common case for the analysis page."""
    if not user_id:
        return []
    conn = _connect()

    if conn is None:
        with _mem_lock:
            rows = [r for r in _mem_rows.values() if r["user_id"] == user_id]
            if ticker:
                tk = _norm_ticker(ticker)
                rows = [r for r in rows if r["ticker"] == tk]
            rows.sort(key=lambda r: r["updated_at"], reverse=True)
            return [_row_to_dict(r) for r in rows]

    try:
        cur = conn.cursor()
        if ticker:
            cur.execute(
                """
                SELECT id, user_id, ticker, name, assumptions, result,
                       created_at, updated_at
                FROM saved_scenarios
                WHERE user_id=%s AND ticker=%s
                ORDER BY updated_at DESC
                """,
                (user_id, _norm_ticker(ticker)),
            )
        else:
            cur.execute(
                """
                SELECT id, user_id, ticker, name, assumptions, result,
                       created_at, updated_at
                FROM saved_scenarios
                WHERE user_id=%s
                ORDER BY updated_at DESC
                """,
                (user_id,),
            )
        rows = cur.fetchall()
        cur.close()
        return [
            {
                "id": int(r[0]),
                "user_id": r[1],
                "ticker": r[2],
                "name": r[3],
                "assumptions": r[4] if isinstance(r[4], dict) else json.loads(r[4]),
                "result": r[5] if isinstance(r[5], dict) else json.loads(r[5]),
                "created_at": r[6].isoformat() if r[6] else None,
                "updated_at": r[7].isoformat() if r[7] else None,
            }
            for r in rows
        ]
    finally:
        try:
            conn.close()
        except Exception:
            pass


def delete_scenario(user_id: str, scenario_id: int) -> bool:
    """Hard-delete by id, scoped to the calling user. Returns False if
    the row didn't exist or belonged to another user (we don't
    distinguish — both are 404 from the caller's perspective)."""
    if not user_id or not scenario_id:
        return False
    conn = _connect()
    if conn is None:
        with _mem_lock:
            row = _mem_rows.get(scenario_id)
            if not row or row["user_id"] != user_id:
                return False
            _mem_rows.pop(scenario_id, None)
            return True
    try:
        cur = conn.cursor()
        cur.execute(
            "DELETE FROM saved_scenarios WHERE id=%s AND user_id=%s",
            (scenario_id, user_id),
        )
        ok = cur.rowcount > 0
        conn.commit()
        cur.close()
        return ok
    finally:
        try:
            conn.close()
        except Exception:
            pass


# ── Helpers ──────────────────────────────────────────────────────────

def _row_to_dict(r: dict) -> dict:
    return {
        "id": r["id"],
        "user_id": r["user_id"],
        "ticker": r["ticker"],
        "name": r["name"],
        "assumptions": r["assumptions"],
        "result": r["result"],
        "created_at": (r["created_at"].isoformat() + "Z")
                      if r["created_at"] else None,
        "updated_at": (r["updated_at"].isoformat() + "Z")
                      if r["updated_at"] else None,
    }


class ScenarioCapReached(Exception):
    """Raised when a user tries to save beyond MAX_SCENARIOS_PER_USER."""
    def __init__(self, current: int, cap: int):
        super().__init__(f"Scenario cap reached: {current}/{cap}")
        self.current = current
        self.cap = cap
