# dashboard/auth.py
# ═══════════════════════════════════════════════════════════════
# YieldIQ — SQLite Auth Module
# Replaces users.json with a proper auth system:
#   - Email + bcrypt-hashed password
#   - Session tokens with 30-day expiry
#   - Tier stored in DB (free / premium / pro)
#   - Works alongside existing tier_gate.py with zero changes to app.py
#
# Public UI entry points (called from app.py):
#   render_login_page()   -> dict | None   (login form)
#   render_signup_page()  -> dict | None   (signup form)
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import os
import secrets
import hashlib
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

import streamlit as st

# ── bcrypt: use if available, fall back to sha256 PBKDF2 ────────
try:
    import bcrypt
    _BCRYPT = True
except ImportError:
    _BCRYPT = False

DB_PATH = Path(__file__).parent / "auth.db"

# ── Session lifetime (tier-based) ────────────────────────────
SESSION_EXPIRY_DAYS_FREE    = 7   # free tier: 7-day sessions
SESSION_EXPIRY_DAYS_PAID    = 30  # premium / pro: 30-day sessions

# ── Session rotation ─────────────────────────────────────────
SESSION_ROTATION_HOURS      = 24  # issue a new token after 24 h of use
SESSION_ROTATION_GRACE_SECS = 300 # old token stays valid for 5 min after rotation

# ── Rate-limiting constants ──────────────────────────────────
RATE_LIMIT_MAX_ATTEMPTS   = 5   # failed attempts before lockout
RATE_LIMIT_WINDOW_MINUTES = 15  # sliding window for counting failures
LOCKOUT_DURATION_MINUTES  = 30  # how long the account stays locked
ATTEMPT_CLEANUP_HOURS     = 24  # delete attempt rows older than this


# ══════════════════════════════════════════════════════════════
# DB INITIALISATION
# ══════════════════════════════════════════════════════════════

def init_auth_db() -> None:
    """Create tables if they don't exist. Safe to call on every startup.

    Also runs additive ALTER TABLE migrations so existing deployments gain
    the new columns without losing data.
    """
    with _conn() as con:
        con.executescript("""
        CREATE TABLE IF NOT EXISTS users (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            email         TEXT    UNIQUE NOT NULL COLLATE NOCASE,
            password_hash TEXT    NOT NULL,
            tier          TEXT    NOT NULL DEFAULT 'free',
            created_at    TEXT    NOT NULL,
            last_login    TEXT,
            is_active     INTEGER NOT NULL DEFAULT 1
        );

        CREATE TABLE IF NOT EXISTS sessions (
            token         TEXT    PRIMARY KEY,
            user_id       INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
            created_at    TEXT    NOT NULL,
            expires_at    TEXT    NOT NULL,
            ip_hint       TEXT,
            fingerprint   TEXT,
            rotated_at    TEXT,
            superseded_by TEXT
        );

        CREATE TABLE IF NOT EXISTS login_attempts (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            email        TEXT    NOT NULL COLLATE NOCASE,
            attempt_time TEXT    NOT NULL
        );

        CREATE INDEX IF NOT EXISTS idx_sessions_user      ON sessions(user_id);
        CREATE INDEX IF NOT EXISTS idx_users_email        ON users(email);
        CREATE INDEX IF NOT EXISTS idx_attempts_email     ON login_attempts(email);
        CREATE INDEX IF NOT EXISTS idx_attempts_time      ON login_attempts(attempt_time);
        """)

        # Additive migration: add new columns to sessions for existing DBs.
        # ALTER TABLE ADD COLUMN is idempotent via the try/except.
        for col_def in (
            "ALTER TABLE sessions ADD COLUMN fingerprint   TEXT",
            "ALTER TABLE sessions ADD COLUMN rotated_at    TEXT",
            "ALTER TABLE sessions ADD COLUMN superseded_by TEXT",
        ):
            try:
                con.execute(col_def)
            except sqlite3.OperationalError:
                pass  # column already exists


# ══════════════════════════════════════════════════════════════
# PASSWORD HELPERS
# ══════════════════════════════════════════════════════════════

def _hash_password(password: str) -> str:
    if _BCRYPT:
        return bcrypt.hashpw(password.encode(), bcrypt.gensalt(rounds=12)).decode()
    # PBKDF2-SHA256 fallback (still strong, not as ideal as bcrypt)
    salt = secrets.token_hex(16)
    dk   = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
    return f"pbkdf2${salt}${dk.hex()}"


def _check_password(password: str, stored_hash: str) -> bool:
    if stored_hash.startswith("pbkdf2$"):
        _, salt, dk_hex = stored_hash.split("$", 2)
        dk = hashlib.pbkdf2_hmac("sha256", password.encode(), salt.encode(), 260_000)
        return secrets.compare_digest(dk.hex(), dk_hex)
    if _BCRYPT:
        try:
            return bcrypt.checkpw(password.encode(), stored_hash.encode())
        except Exception:
            return False
    return False


# ══════════════════════════════════════════════════════════════
# USER MANAGEMENT
# ══════════════════════════════════════════════════════════════

def register_user(email: str, password: str, tier: str = "free") -> dict:
    """
    Register a new user.
    Returns {"ok": True, "user_id": int} or {"ok": False, "error": str}.
    """
    email = email.strip().lower()
    if not email or "@" not in email:
        return {"ok": False, "error": "Invalid email address."}
    if len(password) < 8:
        return {"ok": False, "error": "Password must be at least 8 characters."}
    if tier not in ("free", "starter", "premium", "pro"):
        tier = "free"

    pw_hash = _hash_password(password)
    now     = _utcnow()

    try:
        with _conn() as con:
            cur = con.execute(
                "INSERT INTO users (email, password_hash, tier, created_at) VALUES (?,?,?,?)",
                (email, pw_hash, tier, now),
            )
            return {"ok": True, "user_id": cur.lastrowid}
    except sqlite3.IntegrityError:
        return {"ok": False, "error": "An account with that email already exists."}
    except Exception as exc:
        return {"ok": False, "error": str(exc)}


def login_user(
    email:      str,
    password:   str,
    user_agent: str = "",
    ip:         str = "",
) -> dict:
    """
    Verify credentials and create a session token.

    Session lifetime is tier-based:
      - free:         7 days  (SESSION_EXPIRY_DAYS_FREE)
      - premium / pro: 30 days (SESSION_EXPIRY_DAYS_PAID)

    A fingerprint (SHA-256 of user_agent + ip) is stored with the session
    and checked on every subsequent validate_session() call.  Pass empty
    strings to skip fingerprinting.

    Rate limiting: 5 failed attempts within 15 minutes triggers a 30-minute
    lockout.  Attempt rows older than 24 hours are cleaned up on each call.

    Returns {"ok": True, "token": str, "tier": str, "email": str, "user_id": int}
    or      {"ok": False, "error": str}.
    """
    email = email.strip().lower()

    # 1. Purge stale attempt rows for this email (> 24 hrs old)
    _cleanup_old_attempts(email)

    # 2. Reject immediately if currently locked out
    lock = _check_rate_limit(email)
    if lock:
        return lock

    # 3. Look up account
    with _conn() as con:
        row = con.execute(
            "SELECT id, password_hash, tier, is_active FROM users WHERE email=?",
            (email,),
        ).fetchone()

    if not row:
        return {"ok": False, "error": "No account found for that email."}

    user_id, pw_hash, tier, is_active = row
    if not is_active:
        return {"ok": False, "error": "This account has been disabled."}

    # 4. Check password — record failure and show remaining attempts
    if not _check_password(password, pw_hash):
        _record_failed_attempt(email)
        window_start = _utcnow(seconds=-(RATE_LIMIT_WINDOW_MINUTES * 60))
        with _conn() as con:
            count = con.execute(
                "SELECT COUNT(*) FROM login_attempts WHERE email=? AND attempt_time >= ?",
                (email, window_start),
            ).fetchone()[0]
        remaining = max(0, RATE_LIMIT_MAX_ATTEMPTS - count)
        if remaining > 0:
            return {
                "ok": False,
                "error": (
                    f"Incorrect password. "
                    f"{remaining} attempt(s) remaining before your account is locked."
                ),
            }
        return {
            "ok": False,
            "error": (
                f"Incorrect password. "
                f"Your account is now locked for {LOCKOUT_DURATION_MINUTES} minutes "
                f"due to too many failed attempts."
            ),
        }

    # 5. Successful login — clear failure history and issue token
    _clear_failed_attempts(email)

    fp     = _fingerprint(user_agent, ip) if (user_agent or ip) else None
    token  = secrets.token_urlsafe(32)
    now    = _utcnow()
    expiry = _utcnow(days=_expiry_days(tier))

    with _conn() as con:
        con.execute(
            """INSERT INTO sessions
               (token, user_id, created_at, expires_at, fingerprint, rotated_at)
               VALUES (?,?,?,?,?,?)""",
            (token, user_id, now, expiry, fp, now),
        )
        con.execute(
            "UPDATE users SET last_login=? WHERE id=?",
            (now, user_id),
        )

    return {"ok": True, "token": token, "tier": tier, "email": email, "user_id": user_id}


# ══════════════════════════════════════════════════════════════
# SESSION MANAGEMENT
# ══════════════════════════════════════════════════════════════

def validate_session(
    token:      str,
    user_agent: str = "",
    ip:         str = "",
) -> Optional[dict]:
    """
    Validate a session token.

    Returns on success:
        {"user_id": int, "email": str, "tier": str, "new_token": str | None}

    "new_token" is set when session rotation occurred (caller should persist
    the new token and discard the old one).  It is None when no rotation happened.

    Returns None when:
      - token not found or expired (expired rows are deleted automatically)
      - account is disabled
      - fingerprint mismatch — the session is deleted as a precaution against
        session hijacking (only enforced when both the stored fingerprint and
        the current user_agent/ip are non-empty)

    Grace-window path: if the token was already rotated (superseded_by is set)
    and is still within its 5-minute grace window, the call succeeds and
    new_token points to the replacement so the caller can update its state.
    """
    if not token:
        return None

    now = _utcnow()
    with _conn() as con:
        row = con.execute(
            """SELECT s.user_id, s.expires_at, s.fingerprint,
                      s.rotated_at, s.superseded_by, s.created_at,
                      u.email, u.tier, u.is_active
               FROM sessions s JOIN users u ON s.user_id = u.id
               WHERE s.token = ?""",
            (token,),
        ).fetchone()

    if not row:
        return None

    (user_id, expires_at, stored_fp, rotated_at,
     superseded_by, created_at, email, tier, is_active) = row

    if not is_active:
        _delete_session(token)
        return None

    if now > expires_at:
        _delete_session(token)
        return None

    # Fingerprint check — only enforce when both sides are populated
    if stored_fp and (user_agent or ip):
        current_fp = _fingerprint(user_agent, ip)
        if not secrets.compare_digest(stored_fp, current_fp):
            _delete_session(token)
            return None

    # Grace-window path: this token was already rotated; return its replacement
    if superseded_by:
        return {
            "user_id":   user_id,
            "email":     email,
            "tier":      tier,
            "new_token": superseded_by,
        }

    # Check whether rotation is due (SESSION_ROTATION_HOURS since last rotation)
    reference_ts = rotated_at or created_at
    reference_dt = datetime.strptime(reference_ts, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    age_hours = (datetime.now(timezone.utc) - reference_dt).total_seconds() / 3600

    new_token = None
    if age_hours >= SESSION_ROTATION_HOURS:
        new_token = _rotate_session(token, user_id, tier, stored_fp)

    return {
        "user_id":   user_id,
        "email":     email,
        "tier":      tier,
        "new_token": new_token,
    }


def get_session(
    token:      str,
    user_agent: str = "",
    ip:         str = "",
) -> Optional[dict]:
    """Alias for validate_session — more readable at call sites."""
    return validate_session(token, user_agent=user_agent, ip=ip)


def logout_session(token: str) -> None:
    """Invalidate a single session token."""
    _delete_session(token)


def logout_all_sessions(user_id: int) -> int:
    """
    Invalidate every session for a given user (log out all devices).
    Returns the number of sessions deleted.
    """
    with _conn() as con:
        cur = con.execute("DELETE FROM sessions WHERE user_id=?", (user_id,))
    return cur.rowcount


def refresh_session(
    token:      str,
    user_agent: str = "",
    ip:         str = "",
) -> Optional[str]:
    """
    Extend an existing valid session by its full tier-based lifetime.

    Fingerprint is re-checked via validate_session.  Returns the active token
    (may be a new token if rotation occurred during this call), or None if the
    session is invalid.
    """
    session = validate_session(token, user_agent=user_agent, ip=ip)
    if not session:
        return None
    # Use the rotated token if one was just issued
    active_token = session.get("new_token") or token
    new_expiry   = _utcnow(days=_expiry_days(session["tier"]))
    with _conn() as con:
        con.execute(
            "UPDATE sessions SET expires_at=? WHERE token=?",
            (new_expiry, active_token),
        )
    return active_token


# ══════════════════════════════════════════════════════════════
# ADMIN HELPERS
# ══════════════════════════════════════════════════════════════

def set_tier(email: str, new_tier: str) -> dict:
    """
    Set a user's tier. Called from admin_cli.py.
    Returns {"ok": True} or {"ok": False, "error": str}.
    """
    email = email.strip().lower()
    if new_tier not in ("free", "starter", "premium", "pro"):
        return {"ok": False, "error": f"Invalid tier '{new_tier}'. Choose: free, starter, pro"}

    with _conn() as con:
        cur = con.execute(
            "UPDATE users SET tier=? WHERE email=?",
            (new_tier, email),
        )
        if cur.rowcount == 0:
            return {"ok": False, "error": f"No user found with email '{email}'"}

    return {"ok": True}


def list_users() -> list[dict]:
    """Return all users (for admin inspection)."""
    with _conn() as con:
        rows = con.execute(
            "SELECT email, tier, created_at, last_login, is_active FROM users ORDER BY created_at DESC"
        ).fetchall()
    return [
        {"email": r[0], "tier": r[1], "created_at": r[2],
         "last_login": r[3], "is_active": bool(r[4])}
        for r in rows
    ]


def deactivate_user(email: str) -> dict:
    """Disable a user account without deleting it."""
    email = email.strip().lower()
    with _conn() as con:
        cur = con.execute("UPDATE users SET is_active=0 WHERE email=?", (email,))
        if cur.rowcount == 0:
            return {"ok": False, "error": f"No user found with email '{email}'"}
    return {"ok": True}


def delete_expired_sessions() -> int:
    """Clean up expired sessions. Returns number deleted."""
    now = _utcnow()
    with _conn() as con:
        cur = con.execute("DELETE FROM sessions WHERE expires_at < ?", (now,))
    return cur.rowcount


def unlock_account(email: str) -> dict:
    """
    Admin: clear all login_attempts for an email, immediately removing any lockout.
    Returns {"ok": True, "cleared": int}.
    """
    email = email.strip().lower()
    with _conn() as con:
        cur = con.execute("DELETE FROM login_attempts WHERE email=?", (email,))
    return {"ok": True, "cleared": cur.rowcount}


# ══════════════════════════════════════════════════════════════
# INTERNAL UTILITIES
# ══════════════════════════════════════════════════════════════

def _conn() -> sqlite3.Connection:
    con = sqlite3.connect(str(DB_PATH), timeout=10)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA foreign_keys=ON")
    return con


def _utcnow(days: int = 0, seconds: int = 0) -> str:
    """Return ISO-format UTC timestamp, optionally offset by days and/or seconds."""
    dt = datetime.now(timezone.utc) + timedelta(days=days, seconds=seconds)
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _delete_session(token: str) -> None:
    with _conn() as con:
        con.execute("DELETE FROM sessions WHERE token=?", (token,))


# ── Session helpers ──────────────────────────────────────────

def _fingerprint(user_agent: str, ip: str) -> str:
    """
    SHA-256 of normalised User-Agent + IP.
    Used to detect session token theft across different clients.
    """
    raw = f"{user_agent.strip()}|{ip.strip()}"
    return hashlib.sha256(raw.encode()).hexdigest()


def _expiry_days(tier: str) -> int:
    """Return session lifetime in days for the given tier."""
    return SESSION_EXPIRY_DAYS_PAID if tier in ("starter", "premium", "pro") else SESSION_EXPIRY_DAYS_FREE


def _rotate_session(
    old_token:   str,
    user_id:     int,
    tier:        str,
    fingerprint: Optional[str],
) -> str:
    """
    Issue a replacement token for old_token.

    - A fresh token row is inserted inheriting the original expiry deadline
      (the user keeps the remainder of their session lifetime).
    - The old token is updated with superseded_by = new_token and its
      expires_at is shortened to now + SESSION_ROTATION_GRACE_SECS (5 min),
      giving in-flight requests time to complete.
    """
    new_token = secrets.token_urlsafe(32)
    now       = _utcnow()
    grace_exp = _utcnow(seconds=SESSION_ROTATION_GRACE_SECS)

    with _conn() as con:
        original_expiry = con.execute(
            "SELECT expires_at FROM sessions WHERE token=?", (old_token,)
        ).fetchone()[0]

        con.execute(
            """INSERT INTO sessions
               (token, user_id, created_at, expires_at, fingerprint, rotated_at, superseded_by)
               VALUES (?,?,?,?,?,?,NULL)""",
            (new_token, user_id, now, original_expiry, fingerprint, now),
        )
        con.execute(
            """UPDATE sessions
               SET superseded_by=?, expires_at=?, rotated_at=?
               WHERE token=?""",
            (new_token, grace_exp, now, old_token),
        )

    return new_token


# ── Rate-limiting helpers ────────────────────────────────────

def _cleanup_old_attempts(email: str) -> None:
    """Delete login_attempts older than ATTEMPT_CLEANUP_HOURS for this email."""
    cutoff = _utcnow(seconds=-(ATTEMPT_CLEANUP_HOURS * 3600))
    with _conn() as con:
        con.execute(
            "DELETE FROM login_attempts WHERE email=? AND attempt_time < ?",
            (email, cutoff),
        )


def _check_rate_limit(email: str) -> Optional[dict]:
    """
    Return None if the account is not rate-limited.
    Return {"ok": False, "error": str, "locked_until": str} if locked.

    Lockout logic:
      - Count failed attempts in the last RATE_LIMIT_WINDOW_MINUTES.
      - If >= RATE_LIMIT_MAX_ATTEMPTS, the account is locked for
        LOCKOUT_DURATION_MINUTES from the time of the most recent failure.
    """
    window_start = _utcnow(seconds=-(RATE_LIMIT_WINDOW_MINUTES * 60))
    with _conn() as con:
        rows = con.execute(
            """SELECT attempt_time FROM login_attempts
               WHERE email=? AND attempt_time >= ?
               ORDER BY attempt_time DESC""",
            (email, window_start),
        ).fetchall()

    if len(rows) < RATE_LIMIT_MAX_ATTEMPTS:
        return None

    # Lockout expires LOCKOUT_DURATION_MINUTES after the most recent attempt
    most_recent_str  = rows[0][0]
    most_recent_dt   = datetime.strptime(most_recent_str, "%Y-%m-%dT%H:%M:%SZ").replace(
        tzinfo=timezone.utc
    )
    locked_until_dt  = most_recent_dt + timedelta(minutes=LOCKOUT_DURATION_MINUTES)
    now_dt           = datetime.now(timezone.utc)

    if now_dt >= locked_until_dt:
        return None  # Window passed; lockout expired

    remaining_secs   = int((locked_until_dt - now_dt).total_seconds())
    mins, secs       = divmod(remaining_secs, 60)
    time_str         = f"{mins}m {secs}s" if mins else f"{secs}s"
    locked_until_str = locked_until_dt.strftime("%Y-%m-%dT%H:%M:%SZ")
    until_human      = locked_until_dt.strftime("%H:%M UTC")

    return {
        "ok": False,
        "error": (
            f"Account temporarily locked due to too many failed login attempts. "
            f"Please try again in {time_str} (after {until_human})."
        ),
        "locked_until": locked_until_str,
    }


def _record_failed_attempt(email: str) -> None:
    """Insert a failed-attempt row for this email."""
    with _conn() as con:
        con.execute(
            "INSERT INTO login_attempts (email, attempt_time) VALUES (?,?)",
            (email, _utcnow()),
        )


def _clear_failed_attempts(email: str) -> None:
    """Remove all failed-attempt rows for this email (called on successful login)."""
    with _conn() as con:
        con.execute("DELETE FROM login_attempts WHERE email=?", (email,))


# ── Auto-init on import ──────────────────────────────────────
init_auth_db()


# ══════════════════════════════════════════════════════════════
# UI RENDERING
# ══════════════════════════════════════════════════════════════

def _inject_auth_page_css() -> None:
    """Inject full-page styles: hides Streamlit chrome, sets light background,
    styles the center column as a card, and polishes input + button elements."""
    st.markdown("""
    <style>
    /* ── Hide Streamlit chrome ─────────────────────────────────── */
    [data-testid="stSidebar"]              { display: none !important; }
    [data-testid="stHeader"]               { display: none !important; }
    [data-testid="stToolbar"]              { display: none !important; }
    [data-testid="stDecoration"]           { display: none !important; }
    #MainMenu, footer                       { visibility: hidden !important; }
    .stDeployButton                         { display: none !important; }

    /* ── Page background ───────────────────────────────────────── */
    [data-testid="stAppViewContainer"] {
        background: linear-gradient(160deg, #EFF6FF 0%, #F0F9FF 55%, #F8FAFC 100%) !important;
        min-height: 100vh;
    }
    section.main > div.block-container {
        padding: 0 1rem !important;
        max-width: 100% !important;
    }

    /* ── Card: center column (2nd in 3-col layout) ─────────────── */
    div[data-testid="stHorizontalBlock"]
        > div[data-testid="column"]:nth-child(2)
        > div[data-testid="stVerticalBlock"] {
        background: #FFFFFF;
        border-radius: 20px;
        padding: 44px 40px !important;
        box-shadow: 0 4px 6px -1px rgba(0,0,0,0.04),
                    0 24px 48px -8px rgba(15,23,42,0.10);
        margin-top: 48px;
        margin-bottom: 48px;
    }

    /* ── Label text ────────────────────────────────────────────── */
    div[data-testid="column"]:nth-child(2) .stTextInput > label {
        font-size: 13px !important;
        font-weight: 600 !important;
        color: #374151 !important;
    }

    /* ── Input fields ──────────────────────────────────────────── */
    div[data-testid="column"]:nth-child(2) .stTextInput input {
        border-radius: 10px !important;
        border: 1.5px solid #E2E8F0 !important;
        font-size: 14px !important;
        height: 44px !important;
        color: #111827 !important;
        background: #FAFAFA !important;
        padding: 0 14px !important;
        transition: border-color 0.15s, box-shadow 0.15s !important;
    }
    div[data-testid="column"]:nth-child(2) .stTextInput input:focus {
        border-color: #1D4ED8 !important;
        box-shadow: 0 0 0 3px rgba(29,78,216,0.12) !important;
        background: #FFFFFF !important;
        outline: none !important;
    }

    /* ── Primary button ────────────────────────────────────────── */
    div[data-testid="column"]:nth-child(2) .stButton > button[kind="primary"] {
        background: linear-gradient(135deg, #1D4ED8 0%, #2563EB 100%) !important;
        color: #FFFFFF !important;
        border: none !important;
        border-radius: 10px !important;
        height: 48px !important;
        font-size: 15px !important;
        font-weight: 700 !important;
        letter-spacing: 0.01em !important;
        box-shadow: 0 4px 14px rgba(29,78,216,0.28) !important;
        transition: all 0.2s !important;
        margin-top: 4px !important;
    }
    div[data-testid="column"]:nth-child(2) .stButton > button[kind="primary"]:hover {
        background: linear-gradient(135deg, #1E40AF 0%, #1D4ED8 100%) !important;
        box-shadow: 0 6px 20px rgba(29,78,216,0.38) !important;
        transform: translateY(-1px) !important;
    }

    /* ── Secondary button ──────────────────────────────────────── */
    div[data-testid="column"]:nth-child(2) .stButton > button[kind="secondary"] {
        background: transparent !important;
        color: #1D4ED8 !important;
        border: 1.5px solid #DBEAFE !important;
        border-radius: 10px !important;
        font-size: 14px !important;
        font-weight: 500 !important;
        height: 44px !important;
        transition: all 0.15s !important;
    }
    div[data-testid="column"]:nth-child(2) .stButton > button[kind="secondary"]:hover {
        background: #EFF6FF !important;
        border-color: #93C5FD !important;
    }

    /* ── Checkbox label ────────────────────────────────────────── */
    div[data-testid="column"]:nth-child(2) .stCheckbox label p {
        font-size: 12px !important;
        color: #6B7280 !important;
    }

    /* ── Alert/error box ───────────────────────────────────────── */
    div[data-testid="column"]:nth-child(2) [data-testid="stAlert"] {
        border-radius: 10px !important;
        font-size: 13px !important;
    }
    </style>
    """, unsafe_allow_html=True)


def render_login_page() -> Optional[dict]:
    """
    Render the full-page login form.

    Returns the login_user() result dict ({"ok": True, "token": ..., ...})
    when the form is submitted with valid credentials, or None otherwise.

    Typical usage in app.py:
        result = render_login_page()
        if result and result["ok"]:
            st.session_state["auth_token"] = result["token"]
            st.session_state["auth_email"] = result["email"]
            st.rerun()
    """
    _inject_auth_page_css()

    _, col, _ = st.columns([1, 2, 1])

    with col:
        # ── Logo + tagline ─────────────────────────────────────────
        st.html("""
        <div style="text-align:center;margin-bottom:36px;">
          <div style="display:inline-flex;align-items:center;gap:10px;margin-bottom:14px;">
            <div style="width:44px;height:44px;
                        background:linear-gradient(135deg,#1D4ED8 0%,#06B6D4 100%);
                        border-radius:12px;display:flex;align-items:center;
                        justify-content:center;box-shadow:0 4px 12px rgba(29,78,216,0.30);">
              <span style="font-size:22px;line-height:1;">📈</span>
            </div>
            <span style="font-size:28px;font-weight:800;color:#111827;
                         font-family:Inter,sans-serif;letter-spacing:-0.025em;">YieldIQ</span>
          </div>
          <div style="font-size:13px;color:#6B7280;letter-spacing:0.04em;
                      font-weight:500;text-transform:uppercase;">
            Institutional-grade stock valuation
          </div>
        </div>
        """)

        # ── Heading ────────────────────────────────────────────────
        st.html("""
        <div style="margin-bottom:28px;">
          <div style="font-size:24px;font-weight:800;color:#111827;
                      font-family:Inter,sans-serif;letter-spacing:-0.01em;
                      margin-bottom:6px;">Welcome back</div>
          <div style="font-size:14px;color:#6B7280;">Sign in to your account to continue</div>
        </div>
        """)

        # ── Error placeholder ──────────────────────────────────────
        _err_slot = st.empty()

        # ── Email field ────────────────────────────────────────────
        st.html("""
        <div style="font-size:13px;font-weight:600;color:#374151;
                    margin-bottom:6px;display:flex;align-items:center;gap:6px;">
          <span style="font-size:14px;">✉️</span> Email address
        </div>
        """)
        email = st.text_input(
            "Email address",
            placeholder="you@example.com",
            label_visibility="collapsed",
            key="_login_email",
        )

        # ── Password field ─────────────────────────────────────────
        st.html("""
        <div style="font-size:13px;font-weight:600;color:#374151;
                    margin-top:16px;margin-bottom:6px;
                    display:flex;align-items:center;gap:6px;">
          <span style="font-size:14px;">🔒</span> Password
        </div>
        """)
        show_pw = st.checkbox("Show password", key="_login_show_pw")
        password = st.text_input(
            "Password",
            placeholder="Your password",
            type="default" if show_pw else "password",
            label_visibility="collapsed",
            key="_login_password",
        )

        # ── Forgot password ────────────────────────────────────────
        st.html("""
        <div style="text-align:right;margin-top:6px;margin-bottom:24px;">
          <span style="font-size:12px;color:#1D4ED8;cursor:pointer;font-weight:500;">
            Forgot password?
          </span>
        </div>
        """)

        # ── Sign In button ─────────────────────────────────────────
        submitted = st.button(
            "Sign In",
            type="primary",
            use_container_width=True,
            key="_login_submit",
        )

        result = None
        if submitted:
            if not email.strip():
                _err_slot.error("Please enter your email address.")
            elif not password:
                _err_slot.error("Please enter your password.")
            else:
                with st.spinner("Signing in…"):
                    result = login_user(email, password)
                if not result["ok"]:
                    _err_slot.error(result["error"])
                    result = None

        # ── Divider ────────────────────────────────────────────────
        st.html("""
        <div style="display:flex;align-items:center;gap:14px;margin:24px 0;">
          <div style="flex:1;height:1px;background:#E5E7EB;"></div>
          <div style="font-size:12px;color:#9CA3AF;font-weight:500;">or</div>
          <div style="flex:1;height:1px;background:#E5E7EB;"></div>
        </div>
        """)

        # ── Switch to signup ───────────────────────────────────────
        if st.button(
            "Create free account",
            type="secondary",
            use_container_width=True,
            key="_login_to_signup",
        ):
            st.session_state["_auth_page"] = "signup"
            st.rerun()

        # ── Legal footer ───────────────────────────────────────────
        st.html("""
        <div style="margin-top:32px;padding-top:20px;border-top:1px solid #F3F4F6;
                    text-align:center;font-size:11px;color:#9CA3AF;line-height:1.8;">
          By signing in, you agree to our
          <span style="color:#6B7280;text-decoration:underline;cursor:pointer;">Terms of Service</span>
          and
          <span style="color:#6B7280;text-decoration:underline;cursor:pointer;">Privacy Policy</span>.
          <br>YieldIQ does not provide investment advice.
        </div>
        """)

    return result


def render_signup_page() -> Optional[dict]:
    """
    Render the full-page signup form.

    Returns {"ok": True, "user_id": int} on successful registration, or None otherwise.
    On success, the caller should immediately call login_user() to issue a token,
    then proceed with the normal auth flow.

    Typical usage in app.py:
        result = render_signup_page()
        if result and result["ok"]:
            login_result = login_user(st.session_state["_signup_email_val"], ...)
            st.session_state["auth_token"] = login_result["token"]
            st.rerun()
    """
    _inject_auth_page_css()

    _, col, _ = st.columns([1, 2, 1])

    with col:
        # ── Logo ───────────────────────────────────────────────────
        st.html("""
        <div style="text-align:center;margin-bottom:28px;">
          <div style="display:inline-flex;align-items:center;gap:10px;margin-bottom:14px;">
            <div style="width:44px;height:44px;
                        background:linear-gradient(135deg,#1D4ED8 0%,#06B6D4 100%);
                        border-radius:12px;display:flex;align-items:center;
                        justify-content:center;box-shadow:0 4px 12px rgba(29,78,216,0.30);">
              <span style="font-size:22px;line-height:1;">📈</span>
            </div>
            <span style="font-size:28px;font-weight:800;color:#111827;
                         font-family:Inter,sans-serif;letter-spacing:-0.025em;">YieldIQ</span>
          </div>
        </div>
        """)

        # ── Heading ────────────────────────────────────────────────
        st.html("""
        <div style="margin-bottom:20px;">
          <div style="font-size:24px;font-weight:800;color:#111827;
                      font-family:Inter,sans-serif;letter-spacing:-0.01em;
                      margin-bottom:8px;">Start your free trial</div>
          <div style="font-size:14px;color:#6B7280;">
            5 free analyses per day. No credit card required.
          </div>
        </div>
        """)

        # ── Feature checklist ──────────────────────────────────────
        st.html("""
        <div style="background:linear-gradient(135deg,#EFF6FF,#F0F9FF);
                    border:1px solid #BAE6FD;border-radius:14px;
                    padding:16px 20px;margin-bottom:24px;">
          <div style="font-size:11px;font-weight:700;color:#0369A1;
                      letter-spacing:0.08em;text-transform:uppercase;margin-bottom:12px;">
            What you get for free
          </div>
          <div style="display:grid;grid-template-columns:1fr 1fr;gap:8px;">
            <div style="font-size:12.5px;color:#1E3A8A;display:flex;
                        align-items:flex-start;gap:7px;line-height:1.4;">
              <span style="color:#059669;font-weight:800;font-size:13px;flex-shrink:0;">✓</span>
              DCF valuation for any US stock
            </div>
            <div style="font-size:12.5px;color:#1E3A8A;display:flex;
                        align-items:flex-start;gap:7px;line-height:1.4;">
              <span style="color:#059669;font-weight:800;font-size:13px;flex-shrink:0;">✓</span>
              AI-powered growth forecasting
            </div>
            <div style="font-size:12.5px;color:#1E3A8A;display:flex;
                        align-items:flex-start;gap:7px;line-height:1.4;">
              <span style="color:#059669;font-weight:800;font-size:13px;flex-shrink:0;">✓</span>
              Bear / Base / Bull scenario analysis
            </div>
            <div style="font-size:12.5px;color:#1E3A8A;display:flex;
                        align-items:flex-start;gap:7px;line-height:1.4;">
              <span style="color:#059669;font-weight:800;font-size:13px;flex-shrink:0;">✓</span>
              PDF report download
            </div>
          </div>
        </div>
        """)

        # ── Error placeholder ──────────────────────────────────────
        _err_slot = st.empty()

        # ── Email field ────────────────────────────────────────────
        st.html("""
        <div style="font-size:13px;font-weight:600;color:#374151;
                    margin-bottom:6px;display:flex;align-items:center;gap:6px;">
          <span style="font-size:14px;">✉️</span> Email address
        </div>
        """)
        email = st.text_input(
            "Email",
            placeholder="you@example.com",
            label_visibility="collapsed",
            key="_signup_email",
        )

        # ── Password field ─────────────────────────────────────────
        st.html("""
        <div style="font-size:13px;font-weight:600;color:#374151;
                    margin-top:16px;margin-bottom:6px;
                    display:flex;align-items:center;gap:6px;">
          <span style="font-size:14px;">🔒</span> Password
        </div>
        """)
        show_pw = st.checkbox("Show passwords", key="_signup_show_pw")
        pw_type = "default" if show_pw else "password"
        password = st.text_input(
            "Password",
            placeholder="At least 8 characters",
            type=pw_type,
            label_visibility="collapsed",
            key="_signup_password",
        )

        # ── Confirm password ───────────────────────────────────────
        st.html("""
        <div style="font-size:13px;font-weight:600;color:#374151;
                    margin-top:16px;margin-bottom:6px;
                    display:flex;align-items:center;gap:6px;">
          <span style="font-size:14px;">🔒</span> Confirm password
        </div>
        """)
        confirm = st.text_input(
            "Confirm password",
            placeholder="Repeat your password",
            type=pw_type,
            label_visibility="collapsed",
            key="_signup_confirm",
        )

        st.html('<div style="height:8px;"></div>')

        # ── Create account button ──────────────────────────────────
        submitted = st.button(
            "Create Free Account",
            type="primary",
            use_container_width=True,
            key="_signup_submit",
        )

        result = None
        if submitted:
            if not email.strip() or not password or not confirm:
                _err_slot.error("Please fill in all fields.")
            elif "@" not in email:
                _err_slot.error("Please enter a valid email address.")
            elif password != confirm:
                _err_slot.error("Passwords don't match. Please try again.")
            elif len(password) < 8:
                _err_slot.error("Password must be at least 8 characters.")
            else:
                with st.spinner("Creating your account…"):
                    result = register_user(email, password)
                if not result["ok"]:
                    _err_slot.error(result["error"])
                    result = None
                else:
                    # Stash email so caller can auto-login after signup
                    st.session_state["_signup_email_val"] = email.strip().lower()

        # ── Divider + back to login ────────────────────────────────
        st.html("""
        <div style="display:flex;align-items:center;gap:14px;margin:24px 0;">
          <div style="flex:1;height:1px;background:#E5E7EB;"></div>
          <div style="font-size:12px;color:#9CA3AF;font-weight:500;">or</div>
          <div style="flex:1;height:1px;background:#E5E7EB;"></div>
        </div>
        """)

        if st.button(
            "Already have an account? Sign in",
            type="secondary",
            use_container_width=True,
            key="_signup_to_login",
        ):
            st.session_state["_auth_page"] = "login"
            st.rerun()

        # ── Legal footer ───────────────────────────────────────────
        st.html("""
        <div style="margin-top:28px;padding-top:18px;border-top:1px solid #F3F4F6;
                    text-align:center;font-size:11px;color:#9CA3AF;line-height:1.8;">
          By creating an account, you agree to our
          <span style="color:#6B7280;text-decoration:underline;cursor:pointer;">Terms of Service</span>
          and
          <span style="color:#6B7280;text-decoration:underline;cursor:pointer;">Privacy Policy</span>.
          <br>YieldIQ does not provide investment advice.
        </div>
        """)

    return result
