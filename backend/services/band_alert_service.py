# backend/services/band_alert_service.py
# ═══════════════════════════════════════════════════════════════
# Sector-percentile band-shift alert engine.
#
# When hex_service computes a Value-axis percentile band for a ticker,
# we record it in `valuation_band_history`. If the new band differs
# from the previous record for that ticker, we fan an alert out to
# every user watchlisting the ticker (`band_alerts` table) AND drop
# an in-app notification via the existing notifications_service so
# the bell-drawer surfaces it within 60s.
#
# Side-channel only — every public function in this module is
# wrapped in try/except by callers (hex_service) so a DB hiccup
# in the alert pipeline can NEVER fail the analysis response.
#
# Schema lives in `db/migrations/007_band_alerts.sql` (mirror in
# `data_pipeline/migrations/021_band_alerts.sql`).
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("yieldiq.band_alerts")

# Bands we treat as "real" valuation states. data_limited / unknown
# transitions are noise and never fire an alert.
_REAL_BANDS: frozenset[str] = frozenset({
    "strong_discount",
    "below_peers",
    "in_range",
    "above_peers",
    "notably_overvalued",
})


def _human_band(band: str) -> str:
    """Map internal band key to user-facing label (matches sector_percentile)."""
    return {
        "strong_discount":     "Notable discount to peers",
        "below_peers":         "Below peer range",
        "in_range":            "In peer range",
        "above_peers":         "Above peer range",
        "notably_overvalued":  "Notable premium to peers",
    }.get(band, band.replace("_", " ").title())


# ── DB cursor helper ─────────────────────────────────────────────
def _get_cursor():
    """Return (conn, cursor) from the pipeline engine, or (None, None).

    Mirrors notifications_service._get_raw_cursor — kept private here so
    the alert path has no cross-module dependency that could fail closed.
    """
    try:
        from data_pipeline.db import engine
    except Exception as exc:
        logger.warning("band_alerts: pipeline engine import failed: %s", exc)
        return None, None
    if engine is None:
        return None, None
    try:
        conn = engine.raw_connection()
        cur = conn.cursor()
        return conn, cur
    except Exception as exc:
        logger.warning("band_alerts: engine.raw_connection() failed: %s", exc)
        return None, None


def _close(conn, cur) -> None:
    try:
        if cur is not None:
            cur.close()
    except Exception:
        pass
    try:
        if conn is not None:
            conn.close()
    except Exception:
        pass


# ── 1. record_band_for_ticker ───────────────────────────────────
def record_band_for_ticker(
    ticker: str,
    band: str,
    percentile: Optional[int],
    cohort_size: Optional[int],
    sector: Optional[str],
) -> bool:
    """Insert a row into valuation_band_history.

    Idempotent on (ticker, computed_at). Returns True on insert, False
    on no-op / DB unavailable. Never raises.
    """
    if not ticker or not band:
        return False
    conn, cur = _get_cursor()
    if conn is None or cur is None:
        return False
    try:
        cur.execute(
            """
            INSERT INTO valuation_band_history
                (ticker, band, percentile, cohort_size, sector_label)
            VALUES (%s, %s, %s, %s, %s)
            ON CONFLICT (ticker, computed_at) DO NOTHING
            """,
            (
                ticker.upper(),
                band,
                int(percentile) if percentile is not None else None,
                int(cohort_size) if cohort_size is not None else None,
                (sector or "")[:64] or None,
            ),
        )
        conn.commit()
        return True
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("band_alerts.record_band_for_ticker failed ticker=%s", ticker)
        return False
    finally:
        _close(conn, cur)


# ── 2. detect_band_shift ────────────────────────────────────────
def detect_band_shift(ticker: str) -> Optional[dict]:
    """Compare the latest two band entries for `ticker`.

    Returns {from_band, to_band} if they differ AND both are 'real'
    bands (i.e. not data_limited). Returns None otherwise.
    """
    if not ticker:
        return None
    conn, cur = _get_cursor()
    if conn is None or cur is None:
        return None
    try:
        cur.execute(
            """
            SELECT band
              FROM valuation_band_history
             WHERE ticker = %s
             ORDER BY computed_at DESC
             LIMIT 2
            """,
            (ticker.upper(),),
        )
        rows = cur.fetchall()
    except Exception:
        logger.exception("band_alerts.detect_band_shift query failed ticker=%s", ticker)
        return None
    finally:
        _close(conn, cur)

    if len(rows) < 2:
        return None
    new_band = rows[0][0]
    old_band = rows[1][0]
    if new_band == old_band:
        return None
    # Skip transitions involving data_limited / unknown bands — they're
    # cohort-availability noise, not valuation signal.
    if new_band not in _REAL_BANDS or old_band not in _REAL_BANDS:
        return None
    return {"from_band": old_band, "to_band": new_band}


# ── 3. fire_alerts_for_shift ────────────────────────────────────
def _watchlisters(ticker: str) -> list[str]:
    """Return list of user_email values watching `ticker`.

    Reads the Postgres `watchlist` table (db/schema.sql §4). The
    Supabase-mirrored watchlist is read separately by the frontend; on
    the backend we treat email as the canonical user_id, which matches
    backend.routers.alerts._user_id() fallback ordering.
    """
    if not ticker:
        return []
    conn, cur = _get_cursor()
    if conn is None or cur is None:
        return []
    try:
        cur.execute(
            "SELECT DISTINCT user_email FROM watchlist WHERE ticker = %s",
            (ticker.upper(),),
        )
        return [r[0] for r in cur.fetchall() if r and r[0]]
    except Exception:
        # `watchlist` table may not exist on early-stage envs; logging
        # at info keeps the production logs quiet for that case.
        logger.info("band_alerts.watchlisters query failed (table missing?) ticker=%s",
                    ticker)
        return []
    finally:
        _close(conn, cur)


def fire_alerts_for_shift(ticker: str, from_band: str, to_band: str) -> int:
    """Fan out a band-shift alert.

    For each user watchlisting `ticker`:
      * INSERT a band_alerts row (audit / digest source).
      * Best-effort create an in-app notification via notifications_service.

    Returns the count of users notified. Never raises.
    """
    users = _watchlisters(ticker)
    if not users:
        return 0

    ticker_u = ticker.upper()
    title = f"{ticker_u}: {_human_band(from_band)} → {_human_band(to_band)}"
    body = (
        f"Sector-percentile band shifted for {ticker_u}. "
        "Tap to open the analysis."
    )
    link = f"/analyze/{ticker_u}"

    inserted = 0
    conn, cur = _get_cursor()
    if conn is None or cur is None:
        return 0
    try:
        for uid in users:
            try:
                cur.execute(
                    """
                    INSERT INTO band_alerts (user_id, ticker, from_band, to_band)
                    VALUES (%s, %s, %s, %s)
                    """,
                    (uid, ticker_u, from_band, to_band),
                )
                inserted += 1
            except Exception:
                logger.exception(
                    "band_alerts: insert failed user=%s ticker=%s", uid, ticker_u,
                )
        conn.commit()
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
    finally:
        _close(conn, cur)

    # Surface via notifications drawer (best-effort, decoupled from the
    # band_alerts insert path so a notifications_service blip can't roll
    # back the audit row).
    try:
        from backend.services import notifications_service as ns
        for uid in users:
            try:
                ns.create_notification(
                    user_id=uid,
                    type="alert_fired",
                    title=title,
                    body=body,
                    link=link,
                    metadata={
                        "ticker": ticker_u,
                        "from_band": from_band,
                        "to_band": to_band,
                        "kind": "band_shift",
                    },
                )
            except Exception:
                logger.exception(
                    "band_alerts: notifications_service.create_notification failed "
                    "user=%s ticker=%s", uid, ticker_u,
                )
    except Exception as exc:
        logger.info("band_alerts: notifications_service unavailable: %s", exc)

    logger.info(
        "band_alerts: fired ticker=%s shift=%s->%s users=%d",
        ticker_u, from_band, to_band, inserted,
    )
    return inserted


# ── 4. Public read helpers (used by the API router) ─────────────
def list_recent_for_user(user_id: str, *, limit: int = 50) -> list[dict]:
    """Return the user's recent band-shift alerts (read + unread)."""
    if not user_id:
        return []
    limit = max(1, min(int(limit or 50), 200))
    conn, cur = _get_cursor()
    if conn is None or cur is None:
        return []
    try:
        cur.execute(
            """
            SELECT id, ticker, from_band, to_band, fired_at,
                   delivered_email, delivered_push, user_dismissed
              FROM band_alerts
             WHERE user_id = %s
             ORDER BY fired_at DESC
             LIMIT %s
            """,
            (user_id, limit),
        )
        rows = cur.fetchall()
    except Exception:
        logger.exception("band_alerts.list_recent_for_user failed user=%s", user_id)
        return []
    finally:
        _close(conn, cur)

    out = []
    for r in rows:
        (id_, ticker, from_b, to_b, fired_at, demail, dpush, dismissed) = r
        out.append({
            "id": int(id_),
            "ticker": ticker,
            "from_band": from_b,
            "to_band": to_b,
            "from_label": _human_band(from_b) if from_b else None,
            "to_label": _human_band(to_b) if to_b else None,
            "fired_at": fired_at.isoformat() if fired_at else None,
            "delivered_email": bool(demail),
            "delivered_push": bool(dpush),
            "user_dismissed": bool(dismissed),
        })
    return out


def dismiss_alert(user_id: str, alert_id: int) -> bool:
    """Mark a single band_alerts row as user-dismissed."""
    if not user_id or not alert_id:
        return False
    conn, cur = _get_cursor()
    if conn is None or cur is None:
        return False
    try:
        cur.execute(
            """
            UPDATE band_alerts
               SET user_dismissed = TRUE
             WHERE id = %s AND user_id = %s
            """,
            (int(alert_id), user_id),
        )
        updated = cur.rowcount or 0
        conn.commit()
        return updated > 0
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("band_alerts.dismiss_alert failed")
        return False
    finally:
        _close(conn, cur)


def list_pending_email_digest(*, hours: int = 24) -> dict[str, list[dict]]:
    """Group undelivered band alerts by user_id for the daily digest worker.

    Returns {user_id: [{ticker, from_band, to_band, fired_at}, ...]}.
    """
    conn, cur = _get_cursor()
    if conn is None or cur is None:
        return {}
    try:
        cur.execute(
            """
            SELECT id, user_id, ticker, from_band, to_band, fired_at
              FROM band_alerts
             WHERE delivered_email = FALSE
               AND user_dismissed = FALSE
               AND fired_at > NOW() - (%s || ' hours')::interval
             ORDER BY user_id, fired_at DESC
            """,
            (str(int(hours)),),
        )
        rows = cur.fetchall()
    except Exception:
        logger.exception("band_alerts.list_pending_email_digest failed")
        return {}
    finally:
        _close(conn, cur)

    grouped: dict[str, list[dict]] = {}
    for r in rows:
        (id_, uid, ticker, from_b, to_b, fired_at) = r
        grouped.setdefault(uid, []).append({
            "id": int(id_),
            "ticker": ticker,
            "from_band": from_b,
            "to_band": to_b,
            "from_label": _human_band(from_b) if from_b else None,
            "to_label": _human_band(to_b) if to_b else None,
            "fired_at": fired_at.isoformat() if fired_at else None,
        })
    return grouped


def mark_emails_delivered(alert_ids: list[int]) -> int:
    """Stamp delivered_email=TRUE on the supplied IDs. Used by the digest worker."""
    if not alert_ids:
        return 0
    conn, cur = _get_cursor()
    if conn is None or cur is None:
        return 0
    try:
        cur.execute(
            """
            UPDATE band_alerts
               SET delivered_email = TRUE
             WHERE id = ANY(%s)
            """,
            ([int(i) for i in alert_ids],),
        )
        updated = cur.rowcount or 0
        conn.commit()
        return int(updated)
    except Exception:
        try:
            conn.rollback()
        except Exception:
            pass
        logger.exception("band_alerts.mark_emails_delivered failed")
        return 0
    finally:
        _close(conn, cur)


# ── 5. Combined entry point used by hex_service ─────────────────
def record_and_maybe_fire(
    ticker: str,
    band: str,
    percentile: Optional[int],
    cohort_size: Optional[int],
    sector: Optional[str],
) -> Optional[dict]:
    """One-shot helper: record + detect + fire.

    Returns the shift dict {from_band, to_band, notified_users} on a real
    shift, None otherwise. Wrapped exceptions only — never raises.
    """
    try:
        if not record_band_for_ticker(ticker, band, percentile, cohort_size, sector):
            return None
        # Skip shift detection for data_limited / non-real bands.
        if band not in _REAL_BANDS:
            return None
        shift = detect_band_shift(ticker)
        if not shift:
            return None
        notified = fire_alerts_for_shift(
            ticker, shift["from_band"], shift["to_band"],
        )
        return {**shift, "notified_users": notified}
    except Exception:
        logger.exception("band_alerts.record_and_maybe_fire failed ticker=%s", ticker)
        return None
