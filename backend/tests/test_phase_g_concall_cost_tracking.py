"""Phase G-cost (2026-05-23) — per-row LLM spend tracking.

Migration 058 adds three additive columns to `concall_transcripts`:
  * ai_input_tokens   INTEGER
  * ai_output_tokens  INTEGER
  * ai_cost_usd       NUMERIC(8,4)

These tests verify:
  A) The SQLAlchemy model exposes the three new columns.
  B) `compute_groq_cost_usd` returns the correct USD amount for the
     Llama 3.3 70B pricing currently in `GROQ_PRICING_USD_PER_MTOKEN`,
     and returns 0.0 for an unknown model.
  C) `summarise_concall_with_usage` captures `prompt_tokens` /
     `completion_tokens` from the Groq response and computes cost.
  D) When the LLM output trips the SEBI sanitizer, the spend is still
     recorded honestly (we paid for the call regardless).
  E) `populate_concall_summary` persists the three new columns when
     Groq returns usage.
  F) `populate_concall_summary` leaves the three columns NULL when
     the call short-circuits (no Groq spend).
  G) The legacy `summarise_concall(...)` string-only contract is
     preserved.

No live Groq — the client is patched in every test.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.models.concalls import ConcallTranscript  # noqa: E402
from backend.services import concall_service  # noqa: E402


# ---------- fixtures --------------------------------------------------------

@pytest.fixture()
def db_factory(monkeypatch: pytest.MonkeyPatch):
    """In-memory SQLite carrying the full ConcallTranscript schema
    including the Phase G-cost columns (model edit accompanying
    migration 058)."""
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


def _seed_one(Session) -> int:
    s = Session()
    try:
        row = ConcallTranscript(
            ticker="HDFCBANK.NS",
            filing_date=date(2026, 4, 19),
            subject="Q4 FY26 earnings call",
            pdf_url="https://example.com/q4.pdf",
            # Pre-populate transcript_text so populate_concall_summary
            # skips the PDF fetch path and goes straight to Groq.
            transcript_text=(
                "Good morning everyone. Revenue was 75,000 Cr, up 14% YoY. "
                "Net profit was up 18% with stable net interest margin. "
                "Retail loans drove growth across multiple segments. We "
                "committed capex for 200 new branches in FY27. Management "
                "guided to mid-teens loan growth for the coming year. "
            ) * 5,
        )
        s.add(row)
        s.commit()
        return row.id
    finally:
        s.close()


def _patch_groq(monkeypatch, *, content: str, prompt_tokens: int,
                completion_tokens: int) -> MagicMock:
    """Patch `_groq_client` to return a stub completion with usage."""
    fake_usage = MagicMock(spec=[])
    fake_usage.prompt_tokens = prompt_tokens
    fake_usage.completion_tokens = completion_tokens

    fake_message = MagicMock()
    fake_message.content = content
    fake_choice = MagicMock()
    fake_choice.message = fake_message

    fake_completion = MagicMock(spec=[])
    fake_completion.choices = [fake_choice]
    fake_completion.usage = fake_usage

    fake_client = MagicMock()
    fake_client.chat.completions.create.return_value = fake_completion
    monkeypatch.setattr(concall_service, "_groq_client", lambda: fake_client)
    return fake_client


# ---------- A) schema -------------------------------------------------------

def test_migration_058_adds_cost_columns():
    cols = {c.name for c in ConcallTranscript.__table__.columns}
    assert {"ai_input_tokens", "ai_output_tokens", "ai_cost_usd"}.issubset(cols)


# ---------- B) pricing math -------------------------------------------------

def test_compute_groq_cost_llama_70b_known_rates():
    # Llama 3.3 70B: $0.59/Mtoken in, $0.79/Mtoken out.
    # 12,000 in × 0.59 / 1M = 0.00708
    # 400  out × 0.79 / 1M = 0.000316
    # total = 0.007396 → rounded to 4dp = 0.0074
    cost = concall_service.compute_groq_cost_usd(
        "llama-3.3-70b-versatile", 12_000, 400
    )
    assert cost == pytest.approx(0.0074, rel=0, abs=1e-6)


def test_compute_groq_cost_unknown_model_returns_zero():
    cost = concall_service.compute_groq_cost_usd("unknown-model-xyz", 10_000, 500)
    assert cost == 0.0


def test_compute_groq_cost_zero_tokens():
    cost = concall_service.compute_groq_cost_usd(
        "llama-3.3-70b-versatile", 0, 0
    )
    assert cost == 0.0


# ---------- C) summarise_concall_with_usage --------------------------------

def test_summarise_with_usage_captures_token_counts(monkeypatch):
    _patch_groq(
        monkeypatch,
        content=(
            "- Revenue grew 14% YoY to Rs 75,000 Cr\n"
            "- Net profit up 18% with stable NIM\n"
            "- Retail loans drove growth across segments\n"
            "- Capex committed to 200 new branches in FY27\n"
            "- Management guided to mid-teens loan growth"
        ),
        prompt_tokens=12_000,
        completion_tokens=400,
    )
    transcript = "x" * 1000  # > 200 chars so we don't short-circuit
    result = concall_service.summarise_concall_with_usage(transcript)
    assert result.summary.startswith("- Revenue grew 14%")
    assert result.input_tokens == 12_000
    assert result.output_tokens == 400
    assert result.cost_usd == pytest.approx(0.0074, abs=1e-6)
    assert result.model == "llama-3.3-70b-versatile"


# ---------- D) SEBI-withheld path still records spend ----------------------

def test_summarise_with_usage_records_spend_when_sebi_withheld(monkeypatch):
    # Output contains a banned word ("buy") — sanitizer should swap
    # for the withheld sentinel, BUT we still paid for the call so
    # cost should be recorded.
    _patch_groq(
        monkeypatch,
        content="- You should buy this stock at current levels",
        prompt_tokens=5_000,
        completion_tokens=20,
    )
    result = concall_service.summarise_concall_with_usage("x" * 1000)
    assert result.summary == concall_service._SEBI_WITHHELD_MESSAGE
    assert result.input_tokens == 5_000
    assert result.output_tokens == 20
    assert result.cost_usd > 0  # 5000 * 0.59/1M + 20 * 0.79/1M ≈ 0.00297


# ---------- E) populate persists cost --------------------------------------

def test_populate_persists_token_and_cost_columns(db_factory, monkeypatch):
    row_id = _seed_one(db_factory)
    _patch_groq(
        monkeypatch,
        content=(
            "- Revenue grew 14% YoY to Rs 75,000 Cr\n"
            "- Net profit up 18% with stable NIM\n"
            "- Retail loans drove growth\n"
            "- Capex committed to new branches\n"
            "- Management guided to mid-teens loan growth"
        ),
        prompt_tokens=10_000,
        completion_tokens=500,
    )
    concall_service.populate_concall_summary(row_id)

    s = db_factory()
    try:
        refreshed = s.get(ConcallTranscript, row_id)
        assert refreshed is not None
        assert refreshed.ai_summary is not None
        assert "Revenue grew 14%" in refreshed.ai_summary
        assert refreshed.ai_input_tokens == 10_000
        assert refreshed.ai_output_tokens == 500
        # 10000 * 0.59/1M + 500 * 0.79/1M = 0.0059 + 0.000395 = 0.006295 → 0.0063
        assert float(refreshed.ai_cost_usd) == pytest.approx(0.0063, abs=1e-4)
    finally:
        s.close()


# ---------- F) NULL cost when no Groq spend incurred -----------------------

def test_populate_leaves_cost_null_when_groq_unavailable(db_factory, monkeypatch):
    row_id = _seed_one(db_factory)
    # Groq client absent → summarise_concall_with_usage returns empty
    # ConcallSummaryResult; populate should write the unavailable
    # sentinel but NOT touch the cost columns.
    monkeypatch.setattr(concall_service, "_groq_client", lambda: None)
    concall_service.populate_concall_summary(row_id)

    s = db_factory()
    try:
        refreshed = s.get(ConcallTranscript, row_id)
        assert refreshed.ai_summary == concall_service._SUMMARY_UNAVAILABLE_MESSAGE
        assert refreshed.ai_input_tokens is None
        assert refreshed.ai_output_tokens is None
        assert refreshed.ai_cost_usd is None
    finally:
        s.close()


# ---------- G) legacy contract --------------------------------------------

def test_legacy_summarise_concall_still_returns_string(monkeypatch):
    _patch_groq(
        monkeypatch,
        content="- one\n- two\n- three\n- four\n- five",
        prompt_tokens=100, completion_tokens=20,
    )
    out = concall_service.summarise_concall("x" * 1000)
    assert isinstance(out, str)
    assert out.startswith("- one")
