# dashboard/alerts.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ — Price Alert Engine  (data layer, no Streamlit)
# ─────────────────────────────────────────────────────────────
# Table: price_alerts lives in the same auth.db as sessions/users.
# UI lives in app.py (tab_alerts block).
#
# Alert types
#   'above'      — fires when current_price >= target_price
#   'below'      — fires when current_price <= target_price
#   'iv_reached' — fires when current_price <= target_price
#                  (semantically "stock has fallen to intrinsic value")
#
# Tier limits
#   free    →  3 active alerts
#   premium → 20 active alerts
#   pro     →  unlimited
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

# Shares auth.db so we can JOIN against users if needed
DB_PATH = Path(__file__).parent / "auth.db"

ALERT_LIMITS: dict[str, int] = {
    "free":    3,
    "starter": 50,
    "premium": 50,      # backwards-compat alias
    "pro":     9_999,   # treated as unlimited throughout the UI
}

ALERT_TYPE_LABELS: dict[str, str] = {
    "above":      "Price rises above",
    "below":      "Price falls below",
    "iv_reached": "Price reaches intrinsic value (≤)",
}

_VALID_TYPES = set(ALERT_TYPE_LABELS)


# ══════════════════════════════════════════════════════════════
# DB INITIALISATION
# ══════════════════════════════════════════════════════════════

def init_alerts_db() -> None:
    """Create the price_alerts table if it doesn't exist. Safe to call at startup."""
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS price_alerts (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id       INTEGER NOT NULL,
            ticker        TEXT    NOT NULL COLLATE NOCASE,
            alert_type    TEXT    NOT NULL
                              CHECK(alert_type IN ('above','below','iv_reached')),
            target_price  REAL    NOT NULL,
            is_active     INTEGER NOT NULL DEFAULT 1,
            created_at    TEXT    NOT NULL,
            triggered_at  TEXT
        );

        CREATE INDEX IF NOT EXISTS idx_alerts_user_active
            ON price_alerts(user_id, is_active);
        CREATE INDEX IF NOT EXISTS idx_alerts_triggered
            ON price_alerts(user_id, triggered_at);
        """)


# ══════════════════════════════════════════════════════════════
# TIER LIMIT HELPERS
# ══════════════════════════════════════════════════════════════

def get_alert_limit(tier: str) -> int:
    """Return the maximum number of active alerts for a tier."""
    return ALERT_LIMITS.get(tier, ALERT_LIMITS["free"])


def count_active_alerts(user_id: int) -> int:
    """Return the number of currently active alerts for a user."""
    with _conn() as con:
        return con.execute(
            "SELECT COUNT(*) FROM price_alerts WHERE user_id=? AND is_active=1",
            (user_id,),
        ).fetchone()[0]


# ══════════════════════════════════════════════════════════════
# CRUD
# ══════════════════════════════════════════════════════════════

def get_active_alerts(user_id: int) -> list[dict]:
    """Return all active alerts for a user, newest first."""
    with _conn() as con:
        rows = con.execute(
            """SELECT id, ticker, alert_type, target_price, created_at
               FROM price_alerts
               WHERE user_id=? AND is_active=1
               ORDER BY created_at DESC""",
            (user_id,),
        ).fetchall()
    return [
        {
            "id":           r[0],
            "ticker":       r[1],
            "alert_type":   r[2],
            "target_price": r[3],
            "created_at":   r[4],
        }
        for r in rows
    ]


def get_triggered_alerts(user_id: int, hours: int = 24) -> list[dict]:
    """Return alerts triggered within the last `hours` hours."""
    cutoff = _utcnow(seconds=-(hours * 3600))
    with _conn() as con:
        rows = con.execute(
            """SELECT id, ticker, alert_type, target_price, triggered_at
               FROM price_alerts
               WHERE user_id=? AND is_active=0
                 AND triggered_at IS NOT NULL AND triggered_at >= ?
               ORDER BY triggered_at DESC""",
            (user_id, cutoff),
        ).fetchall()
    return [
        {
            "id":           r[0],
            "ticker":       r[1],
            "alert_type":   r[2],
            "target_price": r[3],
            "triggered_at": r[4],
        }
        for r in rows
    ]


def create_alert(
    user_id:      int,
    ticker:       str,
    alert_type:   str,
    target_price: float,
    tier:         str,
) -> dict:
    """
    Create a new price alert.

    Returns {"ok": True, "alert_id": int}
    or      {"ok": False, "error": str}.

    Enforces tier-based limits before inserting.
    """
    ticker = ticker.strip().upper()
    if not ticker:
        return {"ok": False, "error": "Ticker cannot be empty."}
    if alert_type not in _VALID_TYPES:
        return {"ok": False, "error": f"Invalid alert type '{alert_type}'."}
    if target_price <= 0:
        return {"ok": False, "error": "Target price must be greater than zero."}

    cap     = get_alert_limit(tier)
    current = count_active_alerts(user_id)
    if current >= cap:
        if tier == "free":
            return {
                "ok": False,
                "error": f"Free tier allows {cap} active alert(s). Upgrade to Starter for 50.",
            }
        if tier in ("starter", "premium"):
            return {
                "ok": False,
                "error": f"Starter tier allows {cap} active alerts. Upgrade to Pro for unlimited.",
            }
        return {"ok": False, "error": f"Alert limit ({cap}) reached."}

    with _conn() as con:
        cur = con.execute(
            """INSERT INTO price_alerts
               (user_id, ticker, alert_type, target_price, created_at)
               VALUES (?,?,?,?,?)""",
            (user_id, ticker, alert_type, target_price, _utcnow()),
        )
    return {"ok": True, "alert_id": cur.lastrowid}


def delete_alert(alert_id: int, user_id: int) -> dict:
    """
    Delete an alert by ID.  user_id is checked to prevent cross-user deletion.
    Returns {"ok": True} or {"ok": False, "error": str}.
    """
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM price_alerts WHERE id=? AND user_id=?",
            (alert_id, user_id),
        )
    if cur.rowcount == 0:
        return {"ok": False, "error": "Alert not found."}
    return {"ok": True}


def delete_all_triggered(user_id: int) -> int:
    """Remove all triggered (inactive) alerts for a user. Returns count deleted."""
    with _conn() as con:
        cur = con.execute(
            "DELETE FROM price_alerts WHERE user_id=? AND is_active=0",
            (user_id,),
        )
    return cur.rowcount


# ══════════════════════════════════════════════════════════════
# ALERT CHECKING
# ══════════════════════════════════════════════════════════════

def check_alerts(user_id: int) -> list[dict]:
    """
    Fetch live prices and compare against all active alerts for a user.

    Alerts that fire are immediately marked inactive (is_active=0) with
    triggered_at = now so they won't fire twice.

    Returns a list of newly-triggered alert dicts:
        [{"ticker", "alert_type", "target_price", "current_price",
          "label", "triggered_at"}, ...]
    """
    active = get_active_alerts(user_id)
    if not active:
        return []

    # Batch-fetch prices to minimise API calls
    tickers = list({a["ticker"] for a in active})
    prices  = _fetch_prices(tickers)
    now     = _utcnow()
    fired   = []

    with _conn() as con:
        for alert in active:
            current = prices.get(alert["ticker"], 0.0)
            if current <= 0:
                continue
            if _should_fire(alert["alert_type"], current, alert["target_price"]):
                con.execute(
                    "UPDATE price_alerts SET is_active=0, triggered_at=? WHERE id=?",
                    (now, alert["id"]),
                )
                fired.append({
                    "id":            alert["id"],
                    "ticker":        alert["ticker"],
                    "alert_type":    alert["alert_type"],
                    "target_price":  alert["target_price"],
                    "current_price": current,
                    "label":         ALERT_TYPE_LABELS[alert["alert_type"]],
                    "triggered_at":  now,
                })

    return fired


def check_alerts_for_all_users() -> dict:
    """
    Run check_alerts for every user that has at least one active alert.

    Intended for a background scheduler (APScheduler, cron job, etc.).
    Each user's check is independent — exceptions are swallowed so one
    bad ticker doesn't abort the entire run.

    Returns {"users_checked": int, "total_triggered": int}.
    """
    with _conn() as con:
        rows = con.execute(
            "SELECT DISTINCT user_id FROM price_alerts WHERE is_active=1"
        ).fetchall()

    users_checked   = 0
    total_triggered = 0

    for (uid,) in rows:
        try:
            fired            = check_alerts(uid)
            total_triggered += len(fired)
            users_checked   += 1
        except Exception:
            pass   # log externally if needed

    return {"users_checked": users_checked, "total_triggered": total_triggered}


# ══════════════════════════════════════════════════════════════
# INTERNAL HELPERS
# ══════════════════════════════════════════════════════════════

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH), timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _utcnow(seconds: int = 0) -> str:
    """Return an ISO-8601 UTC timestamp, optionally offset by `seconds`."""
    dt = datetime.now(timezone.utc) + timedelta(seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _should_fire(alert_type: str, current: float, target: float) -> bool:
    """Return True if the alert condition is met."""
    if alert_type == "above":
        return current >= target
    if alert_type in ("below", "iv_reached"):
        return current <= target
    return False


def _fetch_prices(tickers: list[str]) -> dict[str, float]:
    """
    Return {ticker: last_price} for each ticker.
    Uses yfinance fast_info — a lightweight single HTTP request per ticker.
    Missing or errored tickers are silently omitted.
    """
    prices: dict[str, float] = {}
    try:
        import yfinance as yf
        for ticker in tickers:
            try:
                info  = yf.Ticker(ticker).fast_info
                price = float(getattr(info, "last_price", 0) or 0)
                if price > 0:
                    prices[ticker] = price
            except Exception:
                pass
    except ImportError:
        pass
    return prices


def _get_user_id(email: str) -> Optional[int]:
    """
    Look up user_id from auth.db by email.
    Returns None for guests, unknown addresses, or DB errors.
    """
    if not email or email in ("guest", "admin"):
        return None
    email = email.strip().lower()
    try:
        with _conn() as con:
            row = con.execute(
                "SELECT id FROM users WHERE email=? COLLATE NOCASE", (email,)
            ).fetchone()
        return row[0] if row else None
    except Exception:
        return None


# ── Auto-init on import ──────────────────────────────────────
init_alerts_db()
