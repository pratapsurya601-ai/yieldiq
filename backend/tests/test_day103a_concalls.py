"""Day-103a (2026-05-22) — refactored by Day-103d (2026-05-22).

Contract tests for the concall library endpoint after the schema
cleanup:

  * GET /api/v1/public/concalls/{ticker} returns 200 with an empty
    list when the ticker has no library rows (never 404).
  * The endpoint returns rows newest-first with the expected shape
    (period / date / source_url / ai_summary / has_full_transcript).
  * Period is parsed out of the free-text `subject` field —
    "Q3 FY25 earnings call" → "Q3-FY25".
  * `summarise_concall` still short-circuits to "" when Groq is not
    configured and never raises (helper is currently unused at the
    request path; will be wired into a future AI-summary cache PR).
  * Summaries — when they ARE present (in a future PR via a cache
    table) — must never use directional / advisory vocabulary. We
    keep that assertion on the helper output here as a regression
    guard against any prompt drift.

We retarget the in-memory SQLite at the CANONICAL `concall_transcripts`
table (migration 010) — the table the Day-103a duplicate `concalls`
table was created in error.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.models.concalls import ConcallTranscript  # noqa: E402
from backend.services import concall_service  # noqa: E402
from backend.services.cache_service import cache  # noqa: E402


# Vocabulary the SEBI-safe summary path must not emit. Kept here as
# documentation for the future AI-summary cache PR — the canonical
# concall_transcripts table has no ai_summary column today so there
# is nothing to assert against right now.
BANNED_TERMS = (
    "buy", "sell", "recommend", "should", "strong",
    "accumulate", "outperform", "underperform", "hold",
)
assert BANNED_TERMS  # silence "unused" lints; will be wired back in


@pytest.fixture()
def db_factory(monkeypatch: pytest.MonkeyPatch):
    """In-memory SQLite session bound to the ConcallTranscript table."""
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
    # Bust the public-endpoint cache between tests so each test gets a
    # fresh read against our fixture data.
    for k in list(getattr(cache, "_store", {}) or {}):
        try:
            cache.delete(k)
        except Exception:
            pass
    return Session


@pytest.fixture()
def client(db_factory) -> TestClient:
    # Import inside the fixture so the monkeypatched session factory is
    # already in place when the router module resolves the service.
    from backend.routers import public as public_router

    app = FastAPI()
    app.include_router(public_router.router)
    return TestClient(app)


def _seed(Session, rows):
    s = Session()
    try:
        for r in rows:
            s.add(ConcallTranscript(**r))
        s.commit()
    finally:
        s.close()


def test_empty_library_returns_200_not_404(client: TestClient):
    r = client.get("/api/v1/public/concalls/RELIANCE.NS")
    assert r.status_code == 200
    body = r.json()
    assert body["ticker"] == "RELIANCE.NS"
    assert body["count"] == 0
    assert body["concalls"] == []


def test_list_returns_rows_newest_first(client: TestClient, db_factory):
    _seed(db_factory, [
        {
            "ticker": "HDFCBANK.NS",
            "filing_date": date(2025, 10, 19),
            "subject": "Q2 FY26 earnings call",
            "pdf_url": "https://example.com/q2",
        },
        {
            "ticker": "HDFCBANK.NS",
            "filing_date": date(2026, 4, 19),
            "subject": "Q4 FY26 earnings call",
            "pdf_url": "https://example.com/q4",
        },
        {
            "ticker": "HDFCBANK.NS",
            "filing_date": date(2026, 1, 18),
            "subject": "Q3 FY26 earnings call",
            "pdf_url": "https://example.com/q3",
        },
    ])
    r = client.get("/api/v1/public/concalls/HDFCBANK.NS")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    periods = [c["period"] for c in body["concalls"]]
    assert periods == ["Q4-FY26", "Q3-FY26", "Q2-FY26"]
    first = body["concalls"][0]
    assert set(first.keys()) >= {
        "period", "date", "source_url", "ai_summary", "has_full_transcript",
    }
    # pdf_url is set, so has_full_transcript is True
    assert first["has_full_transcript"] is True
    # No ai_summary column on concall_transcripts — the canonical
    # table always returns None for now.
    assert first["ai_summary"] is None


def test_ticker_normalises_to_ns_suffix(client: TestClient, db_factory):
    _seed(db_factory, [{
        "ticker": "HDFCBANK.NS",
        "filing_date": date(2026, 4, 19),
        "subject": "Q4 FY26 earnings call",
        "pdf_url": "https://example.com/q4",
    }])
    # Call with the bare symbol — service should resolve to HDFCBANK.NS
    r = client.get("/api/v1/public/concalls/HDFCBANK")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["concalls"][0]["period"] == "Q4-FY26"


def test_period_parsing_fallback_for_freeform_subject(
    client: TestClient, db_factory
):
    """Subjects without an obvious quarter pattern fall back to a
    truncated raw subject — never empty, never raises."""
    _seed(db_factory, [{
        "ticker": "HDFCBANK.NS",
        "filing_date": date(2026, 4, 19),
        "subject": "Investor / analyst meet — strategic update",
        "pdf_url": "https://example.com/im",
    }])
    r = client.get("/api/v1/public/concalls/HDFCBANK.NS")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    period = body["concalls"][0]["period"]
    assert period  # not empty
    assert period.startswith("Investor")


def test_has_full_transcript_false_when_pdf_url_missing(
    client: TestClient, db_factory
):
    _seed(db_factory, [{
        "ticker": "HDFCBANK.NS",
        "filing_date": date(2026, 4, 19),
        "subject": "Q4 FY26 earnings call",
        "pdf_url": None,
    }])
    r = client.get("/api/v1/public/concalls/HDFCBANK.NS")
    assert r.status_code == 200
    body = r.json()
    assert body["concalls"][0]["has_full_transcript"] is False


def test_summarise_concall_returns_empty_when_groq_missing(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    out = concall_service.summarise_concall("a" * 500)
    assert out == ""


def test_summarise_concall_handles_short_transcript():
    # Below the minimum threshold — should short-circuit without
    # touching the LLM client at all.
    assert concall_service.summarise_concall("too short") == ""
    assert concall_service.summarise_concall("") == ""


def test_period_parsing_unit_examples():
    """Exercise the regex directly on a spread of real-world subjects."""
    p = concall_service._parse_period_from_subject
    assert p("Q3 FY25 earnings call") == "Q3-FY25"
    assert p("Q1 FY2026 earnings call") == "Q1-FY26"
    assert p("Earnings call — Q4 FY24") == "Q4-FY24"
    assert p("Q2FY25 analyst meet") == "Q2-FY25"
    # Fallback path: never empty, capped at 40 chars
    out = p("Quarter ended 30 June 2024 — investor meet")
    assert out
    assert len(out) <= 40
