# backend/services/notes_service.py
# ═══════════════════════════════════════════════════════════════
# Save-Note + Decision Tags service — power-user retention surface.
#
# What this is
# ------------
# Per-(user, ticker) rich-text note + decision tag. Users jot down
# their research as they walk an analysis page; the tag captures the
# current state of their thinking ("researching", "watching", "owned",
# etc.) so they can later filter the cross-ticker notes index by where
# a position stands rather than by ticker alone.
#
# Why JSONL (not Neon)
# --------------------
# Same rationale as mos_band_alerts_service.py (task #131):
#   * No migration handshake required for ship.
#   * Cron-friendly backup — one tar over the data/ dir.
#   * Reads bypass the Neon connection pool entirely. The notes index
#     fans out across every note row for the signed-in user, so we
#     don't want a per-read JOIN against analysis_cache contending
#     with the analyze hot path on Aiven.
#   * Migration sketch when we move: INSERT…SELECT FROM
#     jsonb_populate_recordset(:payload) — see comment on
#     get_notes_storage_path() below.
#
# Storage shape
# -------------
# One JSONL file. Each row is one note keyed by (user_id, ticker).
# A second create on the same key returns the existing row updated
# in place (idempotent upsert) — this is what powers auto-save on
# blur: the frontend doesn't track create-vs-update, it just POSTs
# the latest content and lets the service decide.
#
# Tags
# ----
# Frozen enum — five values today. Kept here (not in models/) so
# the router and the frontend SaveNotePanel can share the canonical
# set via a single import path. Add new tags here ONLY; never widen
# the set in the router/frontend independently or the validator
# falls behind.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal, Optional

logger = logging.getLogger(__name__)

# ── Tag enum ───────────────────────────────────────────────────
# Five values. Source-of-truth for both the router validator and
# the frontend chip selector — exported via the public surface as
# VALID_DECISION_TAGS so SaveNotePanel.tsx can mirror it.
DecisionTag = Literal[
    "researching",
    "watching",
    "skipping",
    "owned",
    "sold",
]
VALID_DECISION_TAGS: frozenset[str] = frozenset({
    "researching",
    "watching",
    "skipping",
    "owned",
    "sold",
})

# Content-length cap. Notes are research-journal scratch, not essays
# — a 50KB cap keeps the JSONL row size predictable and prevents a
# pathological client from blowing up the file.
CONTENT_MAX_CHARS = 50_000

# Single global write-lock — JSONL append/rewrite is not atomic on
# Windows and multiple browser tabs can race the auto-save endpoint.
# A process-local lock is enough for single-replica Railway; multi-
# replica must move to Neon (see migration sketch on the storage-
# path helper).
_LOCK = threading.Lock()


# ── Data ───────────────────────────────────────────────────────
@dataclass
class Note:
    user_id: str
    ticker: str
    content_md: str
    decision_tag: str
    created_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    updated_at: datetime = field(
        default_factory=lambda: datetime.now(timezone.utc)
    )

    # ── JSON round-trip helpers ────────────────────────────────
    def to_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "ticker": self.ticker,
            "content_md": self.content_md,
            "decision_tag": self.decision_tag,
            "created_at": (
                self.created_at.isoformat()
                if isinstance(self.created_at, datetime)
                else self.created_at
            ),
            "updated_at": (
                self.updated_at.isoformat()
                if isinstance(self.updated_at, datetime)
                else self.updated_at
            ),
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Note":
        def _parse_dt(v):
            if not v:
                return datetime.now(timezone.utc)
            if isinstance(v, datetime):
                return v
            try:
                return datetime.fromisoformat(str(v).replace("Z", "+00:00"))
            except Exception:
                return datetime.now(timezone.utc)

        return cls(
            user_id=str(d["user_id"]),
            ticker=str(d["ticker"]).strip().upper(),
            content_md=str(d.get("content_md") or ""),
            decision_tag=str(d.get("decision_tag") or "researching"),
            created_at=_parse_dt(d.get("created_at")),
            updated_at=_parse_dt(d.get("updated_at")),
        )

    def key(self) -> tuple[str, str]:
        return (self.user_id, self.ticker)


# ── Storage path / IO ──────────────────────────────────────────
def get_notes_storage_path() -> str:
    """Path to the JSONL store.

    Env override: ``NOTES_STORAGE_PATH`` — used by tests + the
    operator runbook so prod and CI never share state. Defaults to
    a path under ``data/`` so it survives Railway container restarts
    on the mounted volume.

    Migration sketch (when we move to Neon):
        INSERT INTO user_ticker_notes (user_id, ticker, content_md,
            decision_tag, created_at, updated_at)
        SELECT * FROM jsonb_populate_recordset(NULL::user_ticker_notes,
            :payload::jsonb);
    """
    env = os.environ.get("NOTES_STORAGE_PATH")
    if env:
        return env
    root = Path(__file__).resolve().parents[2]  # repo root
    return str(root / "data" / "user_ticker_notes.jsonl")


def _ensure_dir(path: str) -> None:
    d = os.path.dirname(path)
    if d:
        os.makedirs(d, exist_ok=True)


def _read_all() -> list[Note]:
    """Read every note. Returns [] if the file does not exist."""
    path = get_notes_storage_path()
    if not os.path.exists(path):
        return []
    out: list[Note] = []
    try:
        with open(path, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    out.append(Note.from_dict(json.loads(line)))
                except Exception as e:
                    logger.warning("notes_service: skip malformed row: %s", e)
    except OSError as e:
        logger.warning("notes_service: read failed at %s: %s", path, e)
    return out


def _write_all(notes: Iterable[Note]) -> None:
    path = get_notes_storage_path()
    _ensure_dir(path)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        for n in notes:
            fh.write(json.dumps(n.to_dict(), separators=(",", ":")) + "\n")
    # Best-effort atomic rename. os.replace is atomic on Windows for
    # same-volume files since Python 3.3 — good enough for single-
    # replica deployment.
    os.replace(tmp, path)


# ── Validation ─────────────────────────────────────────────────
def _validate(content_md: str, decision_tag: str) -> None:
    """Raise ValueError on bad input. Shared by all write paths so
    the same rules apply whether the caller is the router, a test,
    or a future cron importer."""
    if not isinstance(content_md, str):
        raise ValueError("content_md must be a string")
    if len(content_md) > CONTENT_MAX_CHARS:
        raise ValueError(
            f"content_md exceeds {CONTENT_MAX_CHARS} character limit"
        )
    if decision_tag not in VALID_DECISION_TAGS:
        raise ValueError(
            f"decision_tag must be one of {sorted(VALID_DECISION_TAGS)}"
        )


# ── Public API ─────────────────────────────────────────────────
def create_note(
    user_id: str,
    ticker: str,
    content_md: str,
    decision_tag: str,
) -> Note:
    """Create OR update a note for (user_id, ticker). Idempotent —
    a second call on the same key updates content + tag and refreshes
    updated_at; created_at is preserved from the original row.

    This is intentionally upsert-semantics so the frontend auto-save
    path doesn't have to choose between POST and PUT. The PUT route
    is kept for API hygiene and explicit-edit flows.
    """
    if not user_id:
        raise ValueError("user_id is required")
    if not ticker:
        raise ValueError("ticker is required")
    _validate(content_md, decision_tag)

    now = datetime.now(timezone.utc)
    note = Note(
        user_id=str(user_id),
        ticker=str(ticker).strip().upper(),
        content_md=content_md,
        decision_tag=decision_tag,
        created_at=now,
        updated_at=now,
    )
    with _LOCK:
        rows = _read_all()
        existing_idx = next(
            (i for i, r in enumerate(rows) if r.key() == note.key()),
            None,
        )
        if existing_idx is not None:
            # Preserve created_at from the original row; refresh body + tag.
            preserved_created = rows[existing_idx].created_at
            note.created_at = preserved_created
            rows[existing_idx] = note
        else:
            rows.append(note)
        _write_all(rows)
    return note


def list_notes_for_user(
    user_id: str,
    ticker: Optional[str] = None,
    decision_tag: Optional[str] = None,
) -> list[Note]:
    """Return all notes for the given user. Optional ticker filter
    narrows to a single ticker (used by the analysis-page side panel
    to fetch its own note via the same list endpoint). Optional
    decision_tag filter powers the notes-index page chip filter.
    """
    if not user_id:
        return []
    rows = [r for r in _read_all() if r.user_id == str(user_id)]
    if ticker:
        t = str(ticker).strip().upper()
        rows = [r for r in rows if r.ticker == t]
    if decision_tag:
        if decision_tag not in VALID_DECISION_TAGS:
            # Filter by an unknown tag returns empty rather than raising
            # — the index page passes raw query strings and a typo
            # should yield "no notes" rather than 400.
            return []
        rows = [r for r in rows if r.decision_tag == decision_tag]
    # Sort newest-first by updated_at so the index page top row is the
    # most recently touched note. created_at as secondary key is a
    # stable tiebreaker for rows touched in the same wall-clock second.
    rows.sort(key=lambda r: (r.updated_at, r.created_at), reverse=True)
    return rows


def get_note(user_id: str, ticker: str) -> Optional[Note]:
    """Read a single note by primary key. Returns None when missing."""
    if not user_id or not ticker:
        return None
    t = str(ticker).strip().upper()
    for r in _read_all():
        if r.user_id == str(user_id) and r.ticker == t:
            return r
    return None


def update_note(
    user_id: str,
    ticker: str,
    content_md: str,
    decision_tag: str,
) -> Optional[Note]:
    """Update an existing note. Returns None when the row does not
    exist (router maps to 404). Use create_note when you want
    upsert semantics — this path is strict-update for the explicit
    edit flow.
    """
    if not user_id or not ticker:
        return None
    _validate(content_md, decision_tag)
    t = str(ticker).strip().upper()
    with _LOCK:
        rows = _read_all()
        idx = next(
            (i for i, r in enumerate(rows)
             if r.user_id == str(user_id) and r.ticker == t),
            None,
        )
        if idx is None:
            return None
        rows[idx].content_md = content_md
        rows[idx].decision_tag = decision_tag
        rows[idx].updated_at = datetime.now(timezone.utc)
        updated = rows[idx]
        _write_all(rows)
    return updated


def delete_note(user_id: str, ticker: str) -> bool:
    """Delete a note. Returns True if a row was removed, False when
    nothing matched (router maps False -> 404)."""
    if not user_id or not ticker:
        return False
    t = str(ticker).strip().upper()
    with _LOCK:
        rows = _read_all()
        before = len(rows)
        rows = [
            r for r in rows
            if not (r.user_id == str(user_id) and r.ticker == t)
        ]
        if len(rows) == before:
            return False
        _write_all(rows)
    return True


__all__ = [
    "Note",
    "DecisionTag",
    "VALID_DECISION_TAGS",
    "CONTENT_MAX_CHARS",
    "get_notes_storage_path",
    "create_note",
    "list_notes_for_user",
    "get_note",
    "update_note",
    "delete_note",
]
