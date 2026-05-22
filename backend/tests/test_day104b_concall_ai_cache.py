"""Day-104b (2026-05-23) — concall AI-summary cache.

Tests the lazy populate path wired into `list_concalls`:

  * Migration 055 adds the four AI-summary cache columns to
    `concall_transcripts` (ai_summary, ai_summary_model,
    ai_summary_generated_at, transcript_text).
  * `list_concalls` returns a cached `ai_summary` value when present.
  * `list_concalls` returns `ai_summary: None` for rows whose summary
    has not yet been generated (and enqueues a BackgroundTask).
  * `populate_concall_summary` writes the Groq output to the DB when
    given a row with cached `transcript_text`.
  * `populate_concall_summary` writes the `(summary unavailable)`
    sentinel when Groq fails — so we never re-enter the code path
    for a permanently broken row.
  * The SEBI banned-word lint catches a directional summary and
    rewrites it to the withheld-pending-review sentinel.

The Groq client is patched out — no network in these tests.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.models.concalls import ConcallTranscript  # noqa: E402
from backend.services import concall_service  # noqa: E402


# ─────────────────────────────────────────────────────────────────
# Fixtures
# ─────────────────────────────────────────────────────────────────
@pytest.fixture()
def db_factory(monkeypatch: pytest.MonkeyPatch):
    """In-memory SQLite with the full ConcallTranscript schema (incl
    Day-104b columns)."""
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    ConcallTranscript.__table__.create(bind=engine, checkfirst=True)
    Session = sessionmaker(bind=engine, future=True)

    def fake_session():
        return Session()

    monkeypatch.setattr(concall_service, "_get_library_session", fake_session)
    return Session


def _seed(Session, rows: list[dict]) -> list[int]:
    """Insert rows; return their assigned IDs in insertion order."""
    s = Session()
    ids: list[int] = []
    try:
        objs = [ConcallTranscript(**r) for r in rows]
        for o in objs:
            s.add(o)
        s.commit()
        for o in objs:
            ids.append(o.id)
    finally:
        s.close()
    return ids


class _FakeBackgroundTasks:
    """Stand-in for FastAPI's BackgroundTasks that just records calls."""

    def __init__(self) -> None:
        self.tasks: list[tuple] = []

    def add_task(self, fn, *args, **kwargs):
        self.tasks.append((fn, args, kwargs))


# ─────────────────────────────────────────────────────────────────
# A) Migration adds the columns
# ─────────────────────────────────────────────────────────────────
def test_migration_055_adds_ai_summary_columns():
    """Schema-level: the SQLAlchemy model exposes all four new columns
    (the SQL migration is idempotent ADD COLUMN IF NOT EXISTS so we
    assert the model surface instead of running the migration)."""
    cols = {c.name for c in ConcallTranscript.__table__.columns}
    assert {
        "ai_summary",
        "ai_summary_model",
        "ai_summary_generated_at",
        "transcript_text",
    }.issubset(cols)


# ─────────────────────────────────────────────────────────────────
# B) list_concalls reflects the cache state
# ─────────────────────────────────────────────────────────────────
def test_list_concalls_returns_cached_ai_summary(db_factory):
    _seed(db_factory, [{
        "ticker": "HDFCBANK.NS",
        "filing_date": date(2026, 4, 19),
        "subject": "Q4 FY26 earnings call",
        "pdf_url": "https://example.com/q4.pdf",
        "ai_summary": (
            "- Revenue grew 14% YoY to Rs 75,000 Cr\n"
            "- Net profit up 18% with stable NIM\n"
            "- Retail loans drove growth across segments\n"
            "- Capex committed to 200 new branches in FY27\n"
            "- Management guided to mid-teens loan growth"
        ),
    }])
    out = concall_service.list_concalls("HDFCBANK.NS")
    assert len(out) == 1
    assert out[0]["ai_summary"] is not None
    assert "Revenue grew 14%" in out[0]["ai_summary"]


def test_list_concalls_returns_none_when_not_yet_summarised(db_factory):
    _seed(db_factory, [{
        "ticker": "HDFCBANK.NS",
        "filing_date": date(2026, 4, 19),
        "subject": "Q4 FY26 earnings call",
        "pdf_url": "https://example.com/q4.pdf",
        # ai_summary deliberately unset
    }])
    bg = _FakeBackgroundTasks()
    out = concall_service.list_concalls("HDFCBANK.NS", background_tasks=bg)
    assert len(out) == 1
    assert out[0]["ai_summary"] is None
    # And a populate task was enqueued for it.
    assert len(bg.tasks) == 1
    fn, args, _ = bg.tasks[0]
    assert fn is concall_service.populate_concall_summary
    assert isinstance(args[0], int)


def test_list_concalls_skips_enqueue_when_no_pdf(db_factory):
    """Rows without a pdf_url cannot be summarised — no task enqueued."""
    _seed(db_factory, [{
        "ticker": "HDFCBANK.NS",
        "filing_date": date(2026, 4, 19),
        "subject": "Q4 FY26 earnings call",
        "pdf_url": None,
    }])
    bg = _FakeBackgroundTasks()
    out = concall_service.list_concalls("HDFCBANK.NS", background_tasks=bg)
    assert len(out) == 1
    assert out[0]["ai_summary"] is None
    assert bg.tasks == []


# ─────────────────────────────────────────────────────────────────
# C) populate_concall_summary writes to DB
# ─────────────────────────────────────────────────────────────────
def test_populate_writes_summary_when_groq_succeeds(db_factory, monkeypatch):
    ids = _seed(db_factory, [{
        "ticker": "HDFCBANK.NS",
        "filing_date": date(2026, 4, 19),
        "subject": "Q4 FY26 earnings call",
        "pdf_url": "https://example.com/q4.pdf",
        "transcript_text": (
            "Good morning everyone. Revenue for the quarter was 75,000 Cr, "
            "growing 14% year on year. Net profit was up 18% with stable "
            "net interest margin. Our retail loan book continues to drive "
            "growth across multiple segments. Management has committed "
            "capex for 200 new branches in FY27. We guide to mid-teens "
            "loan growth for the coming year."
        ) * 5,
    }])
    cid = ids[0]

    # Mock the Groq client used by summarise_concall.
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=(
            "- Revenue grew 14% YoY to Rs 75,000 Cr\n"
            "- Net profit up 18% with stable NIM\n"
            "- Retail loans drove growth across segments\n"
            "- Capex committed to 200 new branches in FY27\n"
            "- Management guided to mid-teens loan growth"
        )))]
    )
    monkeypatch.setattr(concall_service, "_groq_client", lambda: fake_client)

    concall_service.populate_concall_summary(cid)

    s = db_factory()
    try:
        row = s.get(ConcallTranscript, cid)
        assert row is not None
        assert row.ai_summary is not None
        assert "Revenue grew 14%" in row.ai_summary
        assert row.ai_summary_model == concall_service._LIBRARY_SUMMARY_MODEL
        assert row.ai_summary_generated_at is not None
    finally:
        s.close()


def test_populate_writes_unavailable_sentinel_on_groq_failure(
    db_factory, monkeypatch
):
    ids = _seed(db_factory, [{
        "ticker": "HDFCBANK.NS",
        "filing_date": date(2026, 4, 19),
        "subject": "Q4 FY26 earnings call",
        "pdf_url": "https://example.com/q4.pdf",
        "transcript_text": "Real transcript text " * 100,
    }])
    cid = ids[0]

    # Groq client raises mid-call.
    fake_client = MagicMock()
    fake_client.chat.completions.create.side_effect = RuntimeError("Groq down")
    monkeypatch.setattr(concall_service, "_groq_client", lambda: fake_client)

    concall_service.populate_concall_summary(cid)

    s = db_factory()
    try:
        row = s.get(ConcallTranscript, cid)
        assert row is not None
        assert row.ai_summary == concall_service._SUMMARY_UNAVAILABLE_MESSAGE
        assert row.ai_summary_generated_at is not None
    finally:
        s.close()


def test_populate_writes_unavailable_when_pdf_fetch_fails(
    db_factory, monkeypatch
):
    """No cached transcript_text + PDF fetch fails → sentinel."""
    ids = _seed(db_factory, [{
        "ticker": "HDFCBANK.NS",
        "filing_date": date(2026, 4, 19),
        "subject": "Q4 FY26 earnings call",
        "pdf_url": "https://example.com/missing.pdf",
    }])
    cid = ids[0]
    monkeypatch.setattr(concall_service, "_fetch_pdf_bytes", lambda url: None)

    concall_service.populate_concall_summary(cid)

    s = db_factory()
    try:
        row = s.get(ConcallTranscript, cid)
        assert row.ai_summary == concall_service._SUMMARY_UNAVAILABLE_MESSAGE
    finally:
        s.close()


# ─────────────────────────────────────────────────────────────────
# D) SEBI banned-word lint
# ─────────────────────────────────────────────────────────────────
def test_sebi_banned_words_detected():
    # Word-boundary, case-insensitive
    assert concall_service._contains_banned_vocab(
        "We recommend a buy rating"
    ) in {"recommend", "buy"}
    assert concall_service._contains_banned_vocab(
        "STRONG growth ahead"
    ) == "strong"
    # Innocent uses are not flagged
    assert concall_service._contains_banned_vocab("Household income rose") is None
    assert concall_service._contains_banned_vocab("Five-segment business") is None
    assert concall_service._contains_banned_vocab("") is None


def test_summarise_concall_withholds_when_banned_vocab_slips_through(monkeypatch):
    """If the LLM ignores the prompt and emits a directional word,
    summarise_concall returns the withheld-pending-review sentinel."""
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=(
            "- Revenue grew 14% YoY\n"
            "- Stock is a strong buy at current levels\n"
            "- Margins stable\n"
            "- Capex on track\n"
            "- Management guided to mid-teens growth"
        )))]
    )
    monkeypatch.setattr(concall_service, "_groq_client", lambda: fake_client)

    out = concall_service.summarise_concall("transcript " * 100)
    assert out == concall_service._SEBI_WITHHELD_MESSAGE


def test_summarise_concall_passes_clean_output_through(monkeypatch):
    clean = (
        "- Revenue grew 14% YoY to Rs 75,000 Cr\n"
        "- Net profit up 18% with stable NIM\n"
        "- Retail loans drove growth across segments\n"
        "- Capex committed to 200 new branches in FY27\n"
        "- Management guided to mid-teens loan growth"
    )
    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = MagicMock(
        choices=[MagicMock(message=MagicMock(content=clean))]
    )
    monkeypatch.setattr(concall_service, "_groq_client", lambda: fake_client)

    out = concall_service.summarise_concall("transcript " * 100)
    assert out == clean
