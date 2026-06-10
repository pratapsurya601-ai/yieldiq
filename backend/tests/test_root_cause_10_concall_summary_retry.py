"""ROOT CAUSE #10 — Concall AI summary cache missing for HDFCBANK Q1-FY26.

Today populate_concall_summary persists the bare '(summary unavailable)'
placeholder on first failure, and subsequent list_concalls calls
short-circuit on the non-null ai_summary. There is no operator
visibility into which tickers got dropped on the Phase G backfill,
and no surgical retry path.

Fix:
  1. Migration 202606101846_concall_summary_retry_tracking.sql adds
     ai_summary_attempts + ai_summary_last_attempt_at on
     concall_transcripts, and a concall_ai_summaries_failed dead-letter
     table.
  2. concall_service tracks attempts on every populate run and
     escalates to the dead-letter after _SUMMARY_DEAD_LETTER_THRESHOLD
     (3) attempts. The user-facing copy switches from
     "(summary unavailable)" to "(summary generation failed — see
     transcript)".
  3. concall_service.flush_failed_summaries_for_tickers NULL-s the
     placeholder so the next list_concalls re-enqueues populate.
  4. .github/workflows/concall_summary_retry.yml runs the flush + a
     small backfill for an operator-supplied ticker list.
  5. scripts/audit_concall_summary_coverage.py walks the canary
     universe + writes a CSV of missing summaries grouped by ticker
     so the operator knows exactly what to paste into the retry input.

Source-text only — no DB, no Groq, no FastAPI bootstrap. Locks in
the wiring so a future cleanup can't quietly undo it.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_CONCALL_SVC = _ROOT / "backend" / "services" / "concall_service.py"
_CONCALL_MODEL = _ROOT / "backend" / "models" / "concalls.py"
_MIGRATION = (
    _ROOT / "data_pipeline" / "migrations"
    / "202606101846_concall_summary_retry_tracking.sql"
)
_WORKFLOW = (
    _ROOT / ".github" / "workflows" / "concall_summary_retry.yml"
)
_AUDIT_SCRIPT = _ROOT / "scripts" / "audit_concall_summary_coverage.py"
_MANIFEST = (
    _ROOT / "backend" / "services" / "cache_invalidation_manifest.py"
)


def _read(p: Path) -> str:
    assert p.exists(), f"required source file missing: {p}"
    return p.read_text(encoding="utf-8")


# -- migration -----------------------------------------------------


def test_migration_adds_attempt_tracking_columns() -> None:
    src = _read(_MIGRATION)
    assert (
        "ADD COLUMN IF NOT EXISTS ai_summary_attempts INTEGER NOT NULL DEFAULT 0"
        in src
    )
    assert "ai_summary_last_attempt_at TIMESTAMPTZ NULL" in src


def test_migration_creates_dead_letter_table_with_constrained_reasons() -> None:
    src = _read(_MIGRATION)
    assert "CREATE TABLE IF NOT EXISTS concall_ai_summaries_failed" in src
    # The CHECK constraint locks the reason vocabulary so a typo can't
    # silently create a "new" category that the UI doesn't know about.
    assert "chk_concall_failure_reason" in src
    for reason in (
        "pdf_fetch_failed", "pdf_oversize", "pdf_extract_empty",
        "transcript_too_short", "groq_unavailable", "groq_empty_output",
        "sebi_withheld", "unknown",
    ):
        assert reason in src, f"missing reason in CHECK vocab: {reason}"


def test_migration_adds_unique_concall_id_reason_index() -> None:
    """Upserts in _record_summary_failure rely on this unique index."""
    src = _read(_MIGRATION)
    assert "ux_concall_failed_id_reason" in src


# -- model ---------------------------------------------------------


def test_concall_transcript_model_declares_retry_columns() -> None:
    src = _read(_CONCALL_MODEL)
    assert (
        "ai_summary_attempts = Column(Integer, nullable=False, default=0)"
        in src
    )
    assert "ai_summary_last_attempt_at" in src


def test_concall_dead_letter_model_declared() -> None:
    src = _read(_CONCALL_MODEL)
    assert "class ConcallAiSummaryFailed(Base):" in src
    assert '"concall_ai_summaries_failed"' in src
    assert "ux_concall_failed_id_reason" in src


# -- service: thresholds + dead-letter --------------------------


def test_service_defines_dead_letter_threshold_and_failed_message() -> None:
    src = _read(_CONCALL_SVC)
    assert "_SUMMARY_DEAD_LETTER_THRESHOLD = 3" in src
    assert (
        '_SUMMARY_FAILED_MESSAGE = "(summary generation failed — see transcript)"'
        in src
    )


def test_service_increments_attempts_and_records_failure_reason() -> None:
    src = _read(_CONCALL_SVC)
    assert "def _record_summary_failure(" in src
    # Failure reasons used in populate_concall_summary must each
    # appear so the retry workflow can correlate.
    for reason in (
        "pdf_fetch_failed", "pdf_extract_empty",
        "transcript_too_short", "groq_unavailable", "sebi_withheld",
    ):
        assert f'"{reason}"' in src, f"missing failure tag: {reason}"


def test_service_escalates_to_failed_copy_after_threshold() -> None:
    src = _read(_CONCALL_SVC)
    assert "if attempts >= _SUMMARY_DEAD_LETTER_THRESHOLD:" in src
    assert "row.ai_summary = _SUMMARY_FAILED_MESSAGE" in src


# -- service: flush helper ----------------------------------------


def test_flush_failed_summaries_helper_exists_and_respects_threshold() -> None:
    src = _read(_CONCALL_SVC)
    assert "def flush_failed_summaries_for_tickers(" in src
    # The flush MUST NOT touch rows that already crossed the threshold —
    # the operator should investigate root cause before re-attempting.
    assert "(r.ai_summary_attempts or 0) >= max_attempts" in src


# -- service: list_concalls re-enqueue guard ----------------------


def test_list_concalls_does_not_reenqueue_failed_rows() -> None:
    """A row carrying _SUMMARY_FAILED_MESSAGE is in the dead-letter —
    re-enqueueing populate on every page view would waste Groq budget."""
    src = _read(_CONCALL_SVC)
    assert "attempts < _SUMMARY_DEAD_LETTER_THRESHOLD" in src


# -- audit script -------------------------------------------------


def test_audit_script_emits_csv_grouped_by_ticker() -> None:
    src = _read(_AUDIT_SCRIPT)
    assert "def audit_coverage(" in src
    assert "csv.DictWriter" in src
    # The "RETRY_TICKERS" line is the convenience surface for the
    # operator — its presence is part of the contract.
    assert "RETRY_TICKERS (csv input):" in src


# -- workflow -----------------------------------------------------


def test_retry_workflow_exists_with_required_inputs() -> None:
    src = _read(_WORKFLOW)
    assert "name: Concall Summary Retry (operator)" in src
    assert "workflow_dispatch:" in src
    assert "tickers:" in src
    assert "max_attempts_threshold:" in src
    assert "dry_run:" in src


def test_retry_workflow_invokes_flush_and_then_backfill() -> None:
    src = _read(_WORKFLOW)
    assert "flush_failed_summaries_for_tickers" in src
    assert "backfill_concall_summaries.py" in src


# -- manifest entry -----------------------------------------------


def test_manifest_records_peer_score_concall_backfill_entry() -> None:
    src = _read(_MANIFEST)
    assert (
        '"version_id": "v_peer_score_concall_backfill_2026_06_11"' in src
    )
    unwrapped = src.replace('"\n            "', "").replace('"\n        "', "")
    assert (
        "missing concall summaries can be backfilled via retry workflow"
        in unwrapped
    )
