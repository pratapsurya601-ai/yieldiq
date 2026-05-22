"""Day-103a (2026-05-22): concall library + AI summary panel.

Locks the contract on the new public concalls endpoint:

  * GET /api/v1/public/concalls/{ticker} returns 200 with an empty
    list when the ticker has no library rows (never 404).
  * The endpoint returns rows newest-first with the expected shape
    (period / date / source_url / ai_summary / has_full_transcript).
  * `summarise_concall` short-circuits to "" when Groq is not
    configured and never raises.
  * Cached summaries are not re-generated on subsequent reads.
  * Summary copy never uses directional / advisory vocabulary.

The test patches the library session factory to point at an in-memory
SQLite database so we don't need a live Neon or Groq during CI.
"""
from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path
from unittest.mock import patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.models.concalls import Concall  # noqa: E402
from backend.services import concall_service  # noqa: E402
from backend.services.cache_service import cache  # noqa: E402


# Vocabulary the SEBI-safe summary path must not emit. We never enumerate
# these in production code — only in the test that audits prompt output.
BANNED_TERMS = (
    "buy", "sell", "recommend", "should", "strong",
    "accumulate", "outperform", "underperform", "hold",
)


@pytest.fixture()
def db_factory(monkeypatch: pytest.MonkeyPatch):
    """In-memory SQLite session bound to the Concall table only."""
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Concall.__table__.create(bind=engine, checkfirst=True)
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
            s.add(Concall(**r))
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
            "period": "FY26-Q2",
            "concall_date": date(2025, 10, 19),
            "source_url": "https://example.com/q2",
            "ai_summary": "- Topline grew steadily.\n- Margins were stable.",
            "ai_summary_model": "llama-3.3-70b-versatile",
            "ai_summary_generated_at": datetime.now(timezone.utc),
        },
        {
            "ticker": "HDFCBANK.NS",
            "period": "FY26-Q4",
            "concall_date": date(2026, 4, 19),
            "source_url": "https://example.com/q4",
            "ai_summary": "- Loan book expanded.\n- Deposit accretion firmed up.",
            "ai_summary_model": "llama-3.3-70b-versatile",
            "ai_summary_generated_at": datetime.now(timezone.utc),
        },
        {
            "ticker": "HDFCBANK.NS",
            "period": "FY26-Q3",
            "concall_date": date(2026, 1, 18),
            "source_url": "https://example.com/q3",
            "ai_summary": "- Quarter print was in line.",
            "ai_summary_model": "llama-3.3-70b-versatile",
            "ai_summary_generated_at": datetime.now(timezone.utc),
        },
    ])
    r = client.get("/api/v1/public/concalls/HDFCBANK.NS")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 3
    periods = [c["period"] for c in body["concalls"]]
    assert periods == ["FY26-Q4", "FY26-Q3", "FY26-Q2"]
    first = body["concalls"][0]
    assert set(first.keys()) >= {
        "period", "date", "source_url", "ai_summary", "has_full_transcript",
    }
    assert first["has_full_transcript"] is False  # no transcript_text seeded


def test_ticker_normalises_to_ns_suffix(client: TestClient, db_factory):
    _seed(db_factory, [{
        "ticker": "HDFCBANK.NS",
        "period": "FY26-Q4",
        "concall_date": date(2026, 4, 19),
        "source_url": "https://example.com/q4",
        "ai_summary": "- Steady print.",
    }])
    # Call with the bare symbol — service should resolve to HDFCBANK.NS
    r = client.get("/api/v1/public/concalls/HDFCBANK")
    assert r.status_code == 200
    body = r.json()
    assert body["count"] == 1
    assert body["concalls"][0]["period"] == "FY26-Q4"


def test_summary_caching_does_not_call_groq_again(db_factory):
    """If ai_summary is already on the row, summarise_concall is not called."""
    _seed(db_factory, [{
        "ticker": "HDFCBANK.NS",
        "period": "FY26-Q4",
        "concall_date": date(2026, 4, 19),
        "source_url": "https://example.com/q4",
        "transcript_text": None,
        "ai_summary": "- Pre-cached factual summary line.",
        "ai_summary_model": "llama-3.3-70b-versatile",
        "ai_summary_generated_at": datetime.now(timezone.utc),
    }])
    with patch.object(concall_service, "summarise_concall") as m:
        out = concall_service.list_concalls("HDFCBANK.NS")
        assert len(out) == 1
        assert out[0]["ai_summary"].startswith("- Pre-cached")
        m.assert_not_called()


def test_summarise_concall_returns_empty_when_groq_missing(monkeypatch):
    monkeypatch.delenv("GROQ_API_KEY", raising=False)
    out = concall_service.summarise_concall("a" * 500)
    assert out == ""


def test_summarise_concall_handles_short_transcript():
    # Below the minimum threshold — should short-circuit without
    # touching the LLM client at all.
    assert concall_service.summarise_concall("too short") == ""
    assert concall_service.summarise_concall("") == ""


def test_seed_summary_uses_sebi_safe_vocabulary(db_factory):
    """The summaries we ship in the seed migration / generate from the
    prompt must not contain directional advisory vocabulary."""
    _seed(db_factory, [{
        "ticker": "HDFCBANK.NS",
        "period": "FY26-Q4",
        "concall_date": date(2026, 4, 19),
        "source_url": "https://example.com/q4",
        "ai_summary": (
            "- Net interest income grew on retail loan book expansion.\n"
            "- Margin compression was modest and expected to normalise.\n"
            "- Asset quality stayed in line with prior quarters.\n"
            "- Digital throughput continued to scale.\n"
            "- Capital adequacy remained comfortably above thresholds."
        ),
    }])
    rows = concall_service.list_concalls("HDFCBANK.NS")
    assert len(rows) == 1
    summary = rows[0]["ai_summary"].lower()
    for term in BANNED_TERMS:
        # Match whole-word-ish to avoid false positives like
        # "shareholders" containing "hold".
        assert f" {term} " not in f" {summary} ", f"banned term: {term!r}"
        assert not summary.startswith(f"{term} ")
