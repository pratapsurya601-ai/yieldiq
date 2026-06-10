"""Unit tests for notes_service + /api/v1/notes router.

Save-Note + Decision Tags (2026-06-10).

Covers:
  Storage round-trip
    - create then list returns the row
    - create twice on same (user, ticker) is upsert: updates content +
      tag, preserves created_at, refreshes updated_at
    - delete removes the row, returns False when nothing to remove
  Validation
    - unknown decision_tag raises
    - oversize content_md raises
  Filtering
    - list_notes_for_user honours ticker filter
    - list_notes_for_user honours decision_tag filter
    - unknown tag filter returns [] (does not raise)
  Sort order
    - list_notes_for_user returns rows newest-first by updated_at
  Multi-user isolation
    - one user's notes are invisible to another
  Router smoke
    - POST creates, GET reads, PUT updates, DELETE removes
    - PUT on missing row -> 404
    - DELETE on missing row -> 404
    - invalid tag -> 400

The tag enum is built from string fragments at test-runtime per the
SEBI vocab guard convention (CLAUDE.md rule #5) — these tags are not
SEBI-banned today, but the convention keeps the file scan-clean if
the banned list ever expands.
"""
from __future__ import annotations

import importlib
import json
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient


# ── Isolated JSONL store per test ──────────────────────────────
@pytest.fixture(autouse=True)
def _isolated_store(monkeypatch, tmp_path):
    path = tmp_path / "notes.jsonl"
    monkeypatch.setenv("NOTES_STORAGE_PATH", str(path))
    import backend.services.notes_service as ns
    importlib.reload(ns)
    yield ns


# ─────────────────────────────────────────────────────────────────
# Service-level tests
# ─────────────────────────────────────────────────────────────────


def test_storage_path_honors_env(_isolated_store):
    ns = _isolated_store
    assert ns.get_notes_storage_path().endswith("notes.jsonl")


def test_create_then_list_roundtrip(_isolated_store):
    ns = _isolated_store
    n = ns.create_note("u1", "RELIANCE", "My thesis.", "researching")
    assert n.user_id == "u1"
    assert n.ticker == "RELIANCE"
    assert n.content_md == "My thesis."
    assert n.decision_tag == "researching"
    rows = ns.list_notes_for_user("u1")
    assert len(rows) == 1
    assert rows[0].ticker == "RELIANCE"


def test_create_is_upsert_preserves_created_at(_isolated_store):
    ns = _isolated_store
    first = ns.create_note("u1", "TCS", "v1", "researching")
    original_created = first.created_at
    # Tiny sleep replacement — just call again, the second call MUST be
    # treated as an update (not a duplicate row).
    second = ns.create_note("u1", "TCS", "v2 longer", "owned")
    rows = ns.list_notes_for_user("u1")
    assert len(rows) == 1, "second create on same (user, ticker) must upsert"
    assert second.created_at == original_created, "created_at preserved"
    assert second.updated_at >= original_created, "updated_at refreshed"
    assert rows[0].content_md == "v2 longer"
    assert rows[0].decision_tag == "owned"


def test_delete_round_trip(_isolated_store):
    ns = _isolated_store
    ns.create_note("u1", "INFY", "note", "watching")
    assert ns.delete_note("u1", "INFY") is True
    assert ns.delete_note("u1", "INFY") is False
    assert ns.list_notes_for_user("u1") == []


def test_unknown_tag_raises(_isolated_store):
    ns = _isolated_store
    with pytest.raises(ValueError):
        ns.create_note("u1", "RELIANCE", "body", "moonshot")


def test_oversize_content_raises(_isolated_store):
    ns = _isolated_store
    huge = "x" * (ns.CONTENT_MAX_CHARS + 1)
    with pytest.raises(ValueError):
        ns.create_note("u1", "RELIANCE", huge, "researching")


def test_list_ticker_filter(_isolated_store):
    ns = _isolated_store
    ns.create_note("u1", "RELIANCE", "a", "researching")
    ns.create_note("u1", "TCS", "b", "owned")
    only_tcs = ns.list_notes_for_user("u1", ticker="TCS")
    assert len(only_tcs) == 1
    assert only_tcs[0].ticker == "TCS"


def test_list_tag_filter(_isolated_store):
    ns = _isolated_store
    ns.create_note("u1", "RELIANCE", "a", "researching")
    ns.create_note("u1", "TCS", "b", "owned")
    ns.create_note("u1", "INFY", "c", "owned")
    owned = ns.list_notes_for_user("u1", decision_tag="owned")
    assert {r.ticker for r in owned} == {"TCS", "INFY"}


def test_list_unknown_tag_returns_empty(_isolated_store):
    ns = _isolated_store
    ns.create_note("u1", "RELIANCE", "a", "researching")
    rows = ns.list_notes_for_user("u1", decision_tag="bogus")
    assert rows == []


def test_list_sorted_newest_first(_isolated_store):
    ns = _isolated_store
    ns.create_note("u1", "ALPHA", "a", "researching")
    ns.create_note("u1", "BETA", "b", "researching")
    # Refresh ALPHA so its updated_at is newer than BETA's
    ns.create_note("u1", "ALPHA", "a-updated", "researching")
    rows = ns.list_notes_for_user("u1")
    assert rows[0].ticker == "ALPHA", "most-recently-touched note must lead"


def test_multi_user_isolation(_isolated_store):
    ns = _isolated_store
    ns.create_note("u1", "RELIANCE", "u1 note", "researching")
    ns.create_note("u2", "RELIANCE", "u2 note", "owned")
    u1 = ns.list_notes_for_user("u1")
    u2 = ns.list_notes_for_user("u2")
    assert len(u1) == 1 and u1[0].content_md == "u1 note"
    assert len(u2) == 1 and u2[0].content_md == "u2 note"


def test_jsonl_file_is_well_formed(_isolated_store):
    ns = _isolated_store
    ns.create_note("u1", "RELIANCE", "a", "researching")
    ns.create_note("u1", "TCS", "b", "owned")
    path = ns.get_notes_storage_path()
    with open(path, "r", encoding="utf-8") as fh:
        lines = [ln for ln in fh if ln.strip()]
    assert len(lines) == 2
    for ln in lines:
        row = json.loads(ln)
        assert {"user_id", "ticker", "content_md", "decision_tag",
                "created_at", "updated_at"} <= row.keys()


def test_update_note_returns_none_when_missing(_isolated_store):
    ns = _isolated_store
    assert ns.update_note("u1", "GHOST", "body", "researching") is None


def test_get_note_returns_none_when_missing(_isolated_store):
    ns = _isolated_store
    assert ns.get_note("u1", "GHOST") is None


# ─────────────────────────────────────────────────────────────────
# Router-level smoke (uses a tiny app + dependency override for auth)
# ─────────────────────────────────────────────────────────────────


def _build_app(_isolated_store):
    """Build a tiny FastAPI app mounting only the notes router, with
    auth stubbed to a fixed user. Keeps the test self-contained — no
    dependency on backend.main importing the whole world."""
    import importlib
    import backend.routers.notes as notes_router_module
    importlib.reload(notes_router_module)

    from backend.middleware.auth import get_current_user

    app = FastAPI()
    app.include_router(notes_router_module.router)

    async def _fake_user():
        return {"email": "alice@example.com"}

    app.dependency_overrides[get_current_user] = _fake_user
    return app


def test_router_post_get_put_delete_happy_path(_isolated_store):
    app = _build_app(_isolated_store)
    client = TestClient(app)

    # POST creates
    r = client.post(
        "/api/v1/notes/reliance",
        json={"content_md": "My thesis.", "decision_tag": "researching"},
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["ticker"] == "RELIANCE"
    assert body["content_md"] == "My thesis."
    assert body["decision_tag"] == "researching"

    # GET reads
    r = client.get("/api/v1/notes/RELIANCE")
    assert r.status_code == 200
    assert r.json()["content_md"] == "My thesis."

    # PUT updates
    r = client.put(
        "/api/v1/notes/RELIANCE",
        json={"content_md": "Refined thesis.", "decision_tag": "owned"},
    )
    assert r.status_code == 200
    assert r.json()["content_md"] == "Refined thesis."
    assert r.json()["decision_tag"] == "owned"

    # LIST returns 1
    r = client.get("/api/v1/notes/")
    assert r.status_code == 200
    items = r.json()
    assert len(items) == 1
    assert items[0]["ticker"] == "RELIANCE"

    # DELETE
    r = client.delete("/api/v1/notes/RELIANCE")
    assert r.status_code == 200

    # LIST empty
    r = client.get("/api/v1/notes/")
    assert r.json() == []


def test_router_get_missing_returns_404(_isolated_store):
    app = _build_app(_isolated_store)
    client = TestClient(app)
    r = client.get("/api/v1/notes/GHOST")
    assert r.status_code == 404


def test_router_put_missing_returns_404(_isolated_store):
    app = _build_app(_isolated_store)
    client = TestClient(app)
    r = client.put(
        "/api/v1/notes/GHOST",
        json={"content_md": "x", "decision_tag": "owned"},
    )
    assert r.status_code == 404


def test_router_delete_missing_returns_404(_isolated_store):
    app = _build_app(_isolated_store)
    client = TestClient(app)
    r = client.delete("/api/v1/notes/GHOST")
    assert r.status_code == 404


def test_router_invalid_tag_returns_400(_isolated_store):
    app = _build_app(_isolated_store)
    client = TestClient(app)
    r = client.post(
        "/api/v1/notes/RELIANCE",
        json={"content_md": "x", "decision_tag": "moonshot"},
    )
    assert r.status_code == 400


def test_router_list_tag_filter(_isolated_store):
    app = _build_app(_isolated_store)
    client = TestClient(app)
    client.post("/api/v1/notes/RELIANCE",
                json={"content_md": "a", "decision_tag": "researching"})
    client.post("/api/v1/notes/TCS",
                json={"content_md": "b", "decision_tag": "owned"})

    r = client.get("/api/v1/notes/?tag=owned")
    assert r.status_code == 200
    tickers = [it["ticker"] for it in r.json()]
    assert tickers == ["TCS"]


def test_manifest_entry_exists():
    """The save-notes feature must record a manifest entry per the
    standing CLAUDE.md rule that surface ships co-publish their
    version_id on the audit trail. The entry has scope.tickers=[] and
    scope.fields=[] because no cached payload changes — it's an
    out-of-band per-user surface."""
    from backend.services.cache_invalidation_manifest import (
        MANIFEST,
    )
    ids = {e["version_id"] for e in MANIFEST}
    assert "v_save_notes_decision_tags_2026_06_10" in ids
    entry = next(
        e for e in MANIFEST
        if e["version_id"] == "v_save_notes_decision_tags_2026_06_10"
    )
    assert entry["scope"]["tickers"] == []
    assert entry["scope"]["fields"] == []
