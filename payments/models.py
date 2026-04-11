# payments/models.py
# Subscription DB helpers — CRUD for subscriptions table in auth.db.
from __future__ import annotations
import os
import sqlite3
import threading
from pathlib import Path
from datetime import datetime

_DB_PATH = Path(os.environ.get("YIELDIQ_DATA_DIR", str(Path(__file__).resolve().parent.parent / "dashboard"))) / "auth.db"
_lock = threading.Lock()


def _conn() -> sqlite3.Connection:
    c = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
    c.execute("PRAGMA journal_mode=WAL")  # safe for concurrent reads/writes
    c.row_factory = sqlite3.Row
    return c


def init_subscriptions_table() -> None:
    """Create subscriptions table if it doesn't exist."""
    with _lock:
        c = _conn()
        c.execute("""
            CREATE TABLE IF NOT EXISTS subscriptions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                user_email          TEXT    NOT NULL,
                razorpay_sub_id     TEXT    UNIQUE,
                razorpay_payment_id TEXT,
                razorpay_plan_id    TEXT    NOT NULL,
                tier                TEXT    NOT NULL,
                status              TEXT    NOT NULL DEFAULT 'created',
                amount_paise        INTEGER,
                currency            TEXT    DEFAULT 'INR',
                current_end         TEXT,
                created_at          TEXT    DEFAULT (datetime('now')),
                updated_at          TEXT    DEFAULT (datetime('now'))
            )
        """)
        c.execute("CREATE INDEX IF NOT EXISTS idx_sub_email ON subscriptions(user_email)")
        c.execute("CREATE INDEX IF NOT EXISTS idx_sub_rzp ON subscriptions(razorpay_sub_id)")
        c.commit()
        c.close()


def insert_subscription(
    email: str,
    razorpay_sub_id: str,
    razorpay_plan_id: str,
    tier: str,
    amount_paise: int | None = None,
    currency: str = "INR",
) -> None:
    """Insert a new subscription row."""
    with _lock:
        c = _conn()
        c.execute(
            """INSERT OR REPLACE INTO subscriptions
               (user_email, razorpay_sub_id, razorpay_plan_id, tier,
                amount_paise, currency, status, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 'created', datetime('now'))""",
            (email, razorpay_sub_id, razorpay_plan_id, tier,
             amount_paise, currency),
        )
        c.commit()
        c.close()


def update_subscription_status(
    razorpay_sub_id: str,
    status: str,
    payment_id: str | None = None,
    current_end: str | None = None,
) -> str | None:
    """Update subscription status. Returns the user email if found."""
    with _lock:
        c = _conn()
        row = c.execute(
            "SELECT user_email, tier FROM subscriptions WHERE razorpay_sub_id = ?",
            (razorpay_sub_id,),
        ).fetchone()
        if not row:
            c.close()
            return None

        updates = ["status = ?", "updated_at = datetime('now')"]
        params = [status]
        if payment_id:
            updates.append("razorpay_payment_id = ?")
            params.append(payment_id)
        if current_end:
            updates.append("current_end = ?")
            params.append(current_end)

        params.append(razorpay_sub_id)
        c.execute(
            f"UPDATE subscriptions SET {', '.join(updates)} WHERE razorpay_sub_id = ?",
            params,
        )
        c.commit()
        c.close()
        return row["user_email"]


def get_active_subscription(email: str) -> dict | None:
    """Get the active subscription for a user, if any."""
    with _lock:
        c = _conn()
        row = c.execute(
            """SELECT * FROM subscriptions
               WHERE user_email = ? AND status IN ('active', 'authenticated')
               ORDER BY created_at DESC LIMIT 1""",
            (email,),
        ).fetchone()
        c.close()
        return dict(row) if row else None
