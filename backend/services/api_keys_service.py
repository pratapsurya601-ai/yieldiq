"""API key system for Pro-tier programmatic access (100 req/day per key).

Security:
  * Raw keys are SHOWN ONCE to the user at creation, NEVER stored.
  * Storage is SHA-256 of the raw key. Lookup re-hashes the presented
    key and matches.
  * Format: ``yk_<32-char base32>``. The ``yk_`` prefix lets users (and
    us, in logs) identify the key as a YieldIQ API key at a glance.
  * First ~10 chars of the key (e.g. ``yk_a1b2cd``) are stored in
    cleartext so the user can identify their own keys in the UI list
    without us ever needing the raw value.

Rate limit: 100 req/day per KEY (not per user — a Pro user can create
N keys × 100 each, by design). Lifetime cap on key creation (default 5
active keys per Pro user) is enforced in the management router; the
plan is to swap that constant for a tier_caps lookup once the
tier-caps PR lands.

Concurrency: ``check_and_increment_quota`` uses the same atomic
UPSERT-with-guard pattern as ``backend/middleware/rate_limit.py`` so
the per-key daily cap is real even when N concurrent requests land on
the boundary. Local dev (no DATABASE_URL) falls back to an in-memory
counter — not durable, but correct for tests / single-process dev.

Logging discipline:
  * NEVER log raw keys.
  * Log ``key_id`` or ``key_prefix`` when you need to identify a key
    in operational output.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import string
import threading
from collections import defaultdict
from datetime import date, datetime
from typing import Optional

logger = logging.getLogger("yieldiq.api_keys")

# ── Constants ────────────────────────────────────────────────────────
RAW_KEY_PREFIX = "yk_"
RAW_KEY_BODY_LEN = 32
RAW_KEY_TOTAL_LEN = len(RAW_KEY_PREFIX) + RAW_KEY_BODY_LEN  # 35
KEY_PREFIX_STORED_LEN = 10  # 'yk_' + 7 body chars — what's shown in the UI
DAILY_REQUEST_CAP = 100

# Per-user lifetime cap on active keys. TODO: swap for `tier_caps.cap_for(...)`
# when that PR lands so the limit is configurable per-tier instead of hardcoded.
DEFAULT_ACTIVE_KEY_CAP = 5


# ── In-memory fallback storage (no DATABASE_URL, e.g. local tests) ───
# These are deliberately simple — they exist purely to keep the test
# suite hermetic and to make local dev work without spinning up Postgres.
# Production uses the DB path below.
_mem_lock = threading.Lock()
_mem_keys: dict[int, dict] = {}              # id -> row dict
_mem_hash_index: dict[str, int] = {}         # key_hash -> id
_mem_usage: dict[tuple[int, str], int] = defaultdict(int)  # (id, date_iso) -> count
_mem_id_seq = 0


def _next_mem_id() -> int:
    global _mem_id_seq
    _mem_id_seq += 1
    return _mem_id_seq


# ── DB plumbing (psycopg2 via DATABASE_URL) ──────────────────────────

def _connect():
    """Open a psycopg2 connection. Returns None if DATABASE_URL is unset
    or the connect fails — callers must handle the None and fall back to
    the in-memory store."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg2
        return psycopg2.connect(url)
    except Exception as exc:  # pragma: no cover - exercised via fallback
        logger.debug("api_keys: psycopg2.connect failed (%s) — using memory", exc)
        return None


# ── Key generation + hashing ─────────────────────────────────────────

def _generate_raw_key() -> str:
    """Generate a fresh raw API key. Format: ``yk_<32 base32-ish chars>``.

    We use lowercase a-z + 0-9 (36-char alphabet) for human-readability
    when copy/pasting. ``secrets.choice`` provides cryptographic-grade
    randomness suitable for bearer tokens.
    """
    alphabet = string.ascii_lowercase + string.digits
    body = "".join(secrets.choice(alphabet) for _ in range(RAW_KEY_BODY_LEN))
    return f"{RAW_KEY_PREFIX}{body}"


def _hash(raw: str) -> str:
    """SHA-256 hex digest of the raw key. 64 chars."""
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ── Public API ───────────────────────────────────────────────────────

def create_key(user_id: str, label: str) -> dict:
    """Create a new key.

    Returns a dict with keys: ``raw`` (the cleartext key — only chance
    to capture it), ``prefix`` (cleartext identifier shown in UI),
    ``id`` (BIGINT row id), ``label``, ``created_at``.
    """
    if not user_id:
        raise ValueError("user_id required")
    label = (label or "Untitled").strip()[:80] or "Untitled"

    raw = _generate_raw_key()
    key_hash = _hash(raw)
    prefix = raw[:KEY_PREFIX_STORED_LEN]

    conn = _connect()
    if conn is None:
        with _mem_lock:
            new_id = _next_mem_id()
            row = {
                "id": new_id,
                "user_id": user_id,
                "key_hash": key_hash,
                "key_prefix": prefix,
                "label": label,
                "created_at": datetime.utcnow(),
                "last_used_at": None,
                "revoked_at": None,
            }
            _mem_keys[new_id] = row
            _mem_hash_index[key_hash] = new_id
        logger.info(
            "api_keys: created key id=%s prefix=%s for user=%s (memory)",
            new_id, prefix, user_id,
        )
        return {
            "raw": raw,
            "prefix": prefix,
            "id": new_id,
            "label": label,
            "created_at": row["created_at"].isoformat() + "Z",
        }

    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO api_keys (user_id, key_hash, key_prefix, label)
            VALUES (%s, %s, %s, %s)
            RETURNING id, created_at
            """,
            (user_id, key_hash, prefix, label),
        )
        new_id, created_at = cur.fetchone()
        conn.commit()
        cur.close()
        logger.info(
            "api_keys: created key id=%s prefix=%s for user=%s",
            new_id, prefix, user_id,
        )
        return {
            "raw": raw,
            "prefix": prefix,
            "id": int(new_id),
            "label": label,
            "created_at": created_at.isoformat() if created_at else None,
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass


def list_keys(user_id: str) -> list[dict]:
    """List a user's active (non-revoked) keys. NEVER returns raw key."""
    if not user_id:
        return []
    conn = _connect()
    if conn is None:
        with _mem_lock:
            rows = [
                {
                    "id": r["id"],
                    "key_prefix": r["key_prefix"],
                    "label": r["label"],
                    "created_at": (r["created_at"].isoformat() + "Z")
                                  if r["created_at"] else None,
                    "last_used_at": (r["last_used_at"].isoformat() + "Z")
                                     if r["last_used_at"] else None,
                }
                for r in _mem_keys.values()
                if r["user_id"] == user_id and r["revoked_at"] is None
            ]
        rows.sort(key=lambda x: x["created_at"] or "", reverse=True)
        return rows

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, key_prefix, label, created_at, last_used_at
              FROM api_keys
             WHERE user_id = %s AND revoked_at IS NULL
             ORDER BY created_at DESC
            """,
            (user_id,),
        )
        out = []
        for row in cur.fetchall():
            out.append({
                "id": int(row[0]),
                "key_prefix": row[1],
                "label": row[2],
                "created_at": row[3].isoformat() if row[3] else None,
                "last_used_at": row[4].isoformat() if row[4] else None,
            })
        cur.close()
        return out
    finally:
        try:
            conn.close()
        except Exception:
            pass


def revoke_key(user_id: str, key_id: int) -> bool:
    """Mark a key revoked. Returns True iff a row was updated.

    User scope is enforced — a user can only revoke their own keys.
    """
    if not user_id or not key_id:
        return False
    conn = _connect()
    if conn is None:
        with _mem_lock:
            row = _mem_keys.get(int(key_id))
            if (row is None or row["user_id"] != user_id
                    or row["revoked_at"] is not None):
                return False
            row["revoked_at"] = datetime.utcnow()
            # Drop from the hash index so authenticate() returns None.
            _mem_hash_index.pop(row["key_hash"], None)
        logger.info("api_keys: revoked key id=%s for user=%s (memory)",
                    key_id, user_id)
        return True

    try:
        cur = conn.cursor()
        cur.execute(
            """
            UPDATE api_keys
               SET revoked_at = NOW()
             WHERE id = %s AND user_id = %s AND revoked_at IS NULL
            """,
            (int(key_id), user_id),
        )
        updated = cur.rowcount or 0
        conn.commit()
        cur.close()
        if updated:
            logger.info("api_keys: revoked key id=%s for user=%s",
                        key_id, user_id)
        return updated > 0
    finally:
        try:
            conn.close()
        except Exception:
            pass


def authenticate(raw_key: str) -> Optional[dict]:
    """Look up an API key by raw value. Returns ``{api_key_id, user_id}``
    on hit, ``None`` on miss / revoked / malformed input.

    Side-effect on hit: best-effort UPDATE of ``last_used_at = NOW()``.
    Failure of that update never blocks authentication — observability
    only.
    """
    if not raw_key or not isinstance(raw_key, str):
        return None
    if not raw_key.startswith(RAW_KEY_PREFIX):
        return None
    if len(raw_key) != RAW_KEY_TOTAL_LEN:
        return None

    key_hash = _hash(raw_key)

    conn = _connect()
    if conn is None:
        with _mem_lock:
            kid = _mem_hash_index.get(key_hash)
            if kid is None:
                return None
            row = _mem_keys.get(kid)
            if row is None or row["revoked_at"] is not None:
                return None
            row["last_used_at"] = datetime.utcnow()
            return {"api_key_id": int(kid), "user_id": row["user_id"]}

    try:
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id, user_id
              FROM api_keys
             WHERE key_hash = %s AND revoked_at IS NULL
             LIMIT 1
            """,
            (key_hash,),
        )
        row = cur.fetchone()
        if row is None:
            cur.close()
            return None
        api_key_id = int(row[0])
        user_id = str(row[1])
        # Best-effort last_used_at bump.
        try:
            cur.execute(
                "UPDATE api_keys SET last_used_at = NOW() WHERE id = %s",
                (api_key_id,),
            )
            conn.commit()
        except Exception as exc:
            logger.debug("api_keys: last_used_at bump failed for id=%s: %s",
                         api_key_id, exc)
            try:
                conn.rollback()
            except Exception:
                pass
        cur.close()
        return {"api_key_id": api_key_id, "user_id": user_id}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def check_and_increment_quota(api_key_id: int) -> tuple[bool, int, int]:
    """Atomically check the daily quota and increment if under limit.

    Returns ``(allowed, count_after, daily_cap)``.

    Pattern mirrors ``backend/middleware/rate_limit.py``:
        INSERT … ON CONFLICT DO UPDATE … WHERE count < cap RETURNING count
    Rows produced = 1 → allowed. No row → at cap → denied.

    The Postgres path serialises conflicting upserts so even with N
    concurrent requests landing at count=cap-1, only the remaining
    increments needed to reach the cap succeed.
    """
    cap = DAILY_REQUEST_CAP
    if not api_key_id:
        return False, 0, cap

    conn = _connect()
    if conn is None:
        # In-memory atomic compare-and-swap via the lock.
        today = date.today().isoformat()
        key = (int(api_key_id), today)
        with _mem_lock:
            current = _mem_usage[key]
            if current >= cap:
                return False, current, cap
            _mem_usage[key] = current + 1
            return True, current + 1, cap

    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO api_key_usage (api_key_id, usage_date, request_count)
            VALUES (%s, CURRENT_DATE, 1)
            ON CONFLICT (api_key_id, usage_date) DO UPDATE
            SET request_count = api_key_usage.request_count + 1
            WHERE api_key_usage.request_count < %s
            RETURNING request_count
            """,
            (int(api_key_id), cap),
        )
        row = cur.fetchone()
        conn.commit()

        if row is not None:
            count_after = int(row[0])
            cur.close()
            return True, count_after, cap

        # Upsert blocked — at or over cap. Read current for an accurate
        # error body.
        cur.execute(
            """
            SELECT request_count FROM api_key_usage
             WHERE api_key_id = %s AND usage_date = CURRENT_DATE
            """,
            (int(api_key_id),),
        )
        cur_row = cur.fetchone()
        current = int(cur_row[0]) if cur_row else cap
        cur.close()
        return False, current, cap
    except Exception as exc:
        logger.warning(
            "api_keys: quota DB upsert failed for key_id=%s — denying: %s",
            api_key_id, exc,
        )
        try:
            conn.rollback()
        except Exception:
            pass
        return False, 0, cap
    finally:
        try:
            conn.close()
        except Exception:
            pass


def _reset_memory_for_tests() -> None:
    """Test helper — wipe the in-memory store between tests."""
    global _mem_id_seq
    with _mem_lock:
        _mem_keys.clear()
        _mem_hash_index.clear()
        _mem_usage.clear()
        _mem_id_seq = 0
