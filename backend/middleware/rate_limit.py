# backend/middleware/rate_limit.py
# Daily rate limiter per user. Resets at midnight UTC.
#
# Durability rewrite (2026-04-22):
#   Previously a pure in-memory `defaultdict(int)` keyed by user_id:date.
#   That meant every Railway deploy reset every user's counter to zero,
#   and multi-worker setups had independent counters (free users could
#   effectively do N × 5 analyses where N = worker count). Founder
#   observed "unlimited analyses from a non-superuser account" on
#   2026-04-22 after ~15 deploys in a single day.
#
#   Now: counter is persisted in Neon Postgres (`daily_usage` table)
#   using an atomic UPSERT-with-guard that only increments the count
#   when it's strictly below the tier limit. That makes the cap real:
#   no cross-worker double-counting, no reset on redeploy, no race on
#   the 5th-to-6th-call boundary.
#
#   Local dev without DATABASE_URL falls back to the in-memory dict
#   (same class, same API), so dev experience is unchanged.
#
# Table schema (created lazily on first use):
#
#   CREATE TABLE daily_usage (
#       user_id TEXT NOT NULL,
#       usage_date DATE NOT NULL,
#       count INTEGER NOT NULL DEFAULT 0,
#       updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
#       PRIMARY KEY (user_id, usage_date)
#   );
#
# We use `usage_date` not `date` because `date` is a reserved word in
# many SQL dialects and some ORMs trip over it.
from __future__ import annotations

import logging
import threading
from collections import defaultdict
from datetime import date

logger = logging.getLogger("yieldiq.rate_limit")


class RateLimiter:
    """Daily rate limiter per user. Postgres-backed with in-memory fallback."""

    TIER_LIMITS = {
        "free": 5,
        "starter": 999999,   # legacy alias
        "pro": 999999,
        "analyst": 999999,
    }

    def __init__(self):
        # In-memory fallback for local dev (no DATABASE_URL) and for DB
        # failures. NOT the source of truth when Postgres is reachable.
        self._counts: dict[str, int] = defaultdict(int)
        self._lock = threading.Lock()
        self._schema_initialized = False
        self._schema_lock = threading.Lock()

    # ── DB plumbing ───────────────────────────────────────────

    def _get_session(self):
        """Lazy import + session acquire. Returns None if DB unavailable."""
        try:
            from data_pipeline.db import Session  # type: ignore
        except Exception:
            return None
        if Session is None:
            return None
        try:
            return Session()
        except Exception as exc:
            logger.debug("rate_limit: Session() failed: %s", exc)
            return None

    def _ensure_schema(self, sess) -> bool:
        """Idempotent CREATE TABLE IF NOT EXISTS on first use per process.
        Returns False if creation failed (caller falls back to memory)."""
        if self._schema_initialized:
            return True
        with self._schema_lock:
            if self._schema_initialized:
                return True
            try:
                from sqlalchemy import text
                sess.execute(text("""
                    CREATE TABLE IF NOT EXISTS daily_usage (
                        user_id TEXT NOT NULL,
                        usage_date DATE NOT NULL,
                        count INTEGER NOT NULL DEFAULT 0,
                        updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
                        PRIMARY KEY (user_id, usage_date)
                    )
                """))
                sess.commit()
                self._schema_initialized = True
                return True
            except Exception as exc:
                logger.warning("rate_limit: schema init failed: %s", exc)
                try: sess.rollback()
                except Exception: pass
                return False

    # ── Public API ────────────────────────────────────────────

    def check_and_increment(self, user_id: str, tier: str) -> tuple[bool, int, int]:
        """Atomically increment the daily counter IF under the tier limit.

        Returns: (allowed, count_after_this_call, limit)

        When the user is at or over limit, returns (False, current_count,
        limit) and does NOT increment. When allowed, returns (True,
        new_count, limit) with the counter already bumped.
        """
        limit = self.TIER_LIMITS.get(tier, 5)
        sess = self._get_session()
        if sess is None:
            return self._mem_check_and_increment(user_id, limit)

        try:
            if not self._ensure_schema(sess):
                return self._mem_check_and_increment(user_id, limit)

            from sqlalchemy import text
            # Atomic UPSERT-with-guard:
            #   - If no row exists: insert count=1, return 1.
            #   - If row exists and count < limit: increment, return new count.
            #   - If row exists and count >= limit: ON CONFLICT WHERE clause
            #     fails, nothing returned — we then read current and block.
            # The WHERE on the ON CONFLICT DO UPDATE is what makes this
            # race-safe: Postgres serializes conflicting upserts, so even
            # under heavy concurrency only `limit` increments ever succeed.
            row = sess.execute(
                text("""
                    INSERT INTO daily_usage (user_id, usage_date, count, updated_at)
                    VALUES (:u, CURRENT_DATE, 1, now())
                    ON CONFLICT (user_id, usage_date) DO UPDATE
                    SET count = daily_usage.count + 1,
                        updated_at = now()
                    WHERE daily_usage.count < :lim
                    RETURNING count
                """),
                {"u": user_id, "lim": limit}
            ).fetchone()
            sess.commit()

            if row is not None:
                return True, int(row[0]), limit

            # Upsert blocked — user is at or over limit. Read current for
            # accurate error body.
            current_row = sess.execute(
                text("""
                    SELECT count FROM daily_usage
                    WHERE user_id = :u AND usage_date = CURRENT_DATE
                """),
                {"u": user_id}
            ).fetchone()
            current = int(current_row[0]) if current_row else limit
            return False, current, limit

        except Exception as exc:
            logger.warning(
                "rate_limit: DB increment failed for %s — falling back to memory: %s",
                user_id, exc,
            )
            try: sess.rollback()
            except Exception: pass
            return self._mem_check_and_increment(user_id, limit)
        finally:
            try: sess.close()
            except Exception: pass

    def get_usage(self, user_id: str, tier: str) -> tuple[int, int]:
        """Return (used_today, limit) without incrementing."""
        limit = self.TIER_LIMITS.get(tier, 5)
        sess = self._get_session()
        if sess is None:
            return self._mem_get_usage(user_id), limit

        try:
            if not self._ensure_schema(sess):
                return self._mem_get_usage(user_id), limit

            from sqlalchemy import text
            row = sess.execute(
                text("""
                    SELECT count FROM daily_usage
                    WHERE user_id = :u AND usage_date = CURRENT_DATE
                """),
                {"u": user_id}
            ).fetchone()
            return int(row[0]) if row else 0, limit
        except Exception as exc:
            logger.debug("rate_limit: DB read failed — memory fallback: %s", exc)
            return self._mem_get_usage(user_id), limit
        finally:
            try: sess.close()
            except Exception: pass

    def cleanup_old(self) -> int:
        """Delete rows from days before today. Safe to call from a daily
        cron; the atomic UPSERT doesn't need this for correctness, it's
        just bookkeeping. Returns number of rows removed."""
        sess = self._get_session()
        if sess is None:
            today = date.today().isoformat()
            removed = 0
            with self._lock:
                old = [k for k in self._counts if not k.endswith(today)]
                for k in old:
                    del self._counts[k]
                    removed += 1
            return removed
        try:
            from sqlalchemy import text
            result = sess.execute(
                text("DELETE FROM daily_usage WHERE usage_date < CURRENT_DATE")
            )
            sess.commit()
            return int(result.rowcount or 0)
        except Exception as exc:
            logger.warning("rate_limit: cleanup_old failed: %s", exc)
            try: sess.rollback()
            except Exception: pass
            return 0
        finally:
            try: sess.close()
            except Exception: pass

    # ── In-memory fallback (local dev, DB failures) ───────────

    def _mem_check_and_increment(self, user_id: str, limit: int) -> tuple[bool, int, int]:
        key = f"{user_id}:{date.today().isoformat()}"
        with self._lock:
            current = self._counts[key]
            if current >= limit:
                return False, current, limit
            self._counts[key] += 1
            return True, current + 1, limit

    def _mem_get_usage(self, user_id: str) -> int:
        key = f"{user_id}:{date.today().isoformat()}"
        with self._lock:
            return self._counts.get(key, 0)


rate_limiter = RateLimiter()
