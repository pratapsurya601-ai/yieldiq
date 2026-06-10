"""ROOT CAUSE #13 — Peer table SCORE column empty.

The peer SCORE column was rendering '—' on every row of the
"Compare with Peers" table even when the subject ticker's side-rail
showed a populated YieldIQ Score. Root cause: peers_service
._cached_score had a DB fallback for fair_value / mos_pct / verdict
but yieldiq_score was explicitly "not persisted; cache-only for now"
(see the legacy comment removed by this PR).

Fix:
  1. Migration 202606101845_fair_value_history_yieldiq_score.sql
     adds yieldiq_score + grade columns to fair_value_history.
  2. data_pipeline.sources.fv_history.store_today_fair_value accepts
     yieldiq_score + grade kwargs (None defaults preserve back-compat).
  3. backend.services.analysis.service.py threads the score + grade
     into the FV write-hook.
  4. backend.services.peers_service._cached_score reads the new columns
     in its DB fallback so peers without a hot cache entry now have a
     score to render.
  5. A pre-migration safety net: if the SELECT fails (e.g. the column
     doesn't exist yet in this environment), fall back to the original
     3-column query so FV/MoS/verdict still surface.

This file is source-text only — no DB, no analysis pipeline bootstrap.
Locks in the wiring so a future cleanup can't quietly undo the persist.
"""
from __future__ import annotations

from pathlib import Path

_ROOT = Path(__file__).resolve().parents[2]
_FV_SOURCE = _ROOT / "data_pipeline" / "sources" / "fv_history.py"
_FV_MODEL = _ROOT / "data_pipeline" / "models.py"
_PEERS_SVC = _ROOT / "backend" / "services" / "peers_service.py"
_ANALYSIS_SVC = _ROOT / "backend" / "services" / "analysis" / "service.py"
_MIGRATION = (
    _ROOT / "data_pipeline" / "migrations"
    / "202606101845_fair_value_history_yieldiq_score.sql"
)
_MANIFEST = (
    _ROOT / "backend" / "services" / "cache_invalidation_manifest.py"
)


def _read(p: Path) -> str:
    assert p.exists(), f"required source file missing: {p}"
    return p.read_text(encoding="utf-8")


# -- migration -----------------------------------------------------


def test_migration_adds_yieldiq_score_and_grade_columns() -> None:
    src = _read(_MIGRATION)
    assert "ADD COLUMN IF NOT EXISTS yieldiq_score INTEGER" in src
    assert "ADD COLUMN IF NOT EXISTS grade" in src


def test_migration_constraints_score_to_0_to_100_range() -> None:
    src = _read(_MIGRATION)
    assert "chk_fv_history_yieldiq_score_range" in src
    assert "yieldiq_score >= 0 AND yieldiq_score <= 100" in src


# -- model ---------------------------------------------------------


def test_fair_value_history_model_declares_score_and_grade() -> None:
    src = _read(_FV_MODEL)
    assert "yieldiq_score = Column(Integer, nullable=True)" in src
    assert "grade = Column(String(4), nullable=True)" in src


# -- write hook ----------------------------------------------------


def test_store_today_fair_value_accepts_score_and_grade_kwargs() -> None:
    src = _read(_FV_SOURCE)
    assert "yieldiq_score: int | None = None" in src
    assert "grade: str | None = None" in src


def test_store_today_fair_value_clamps_score_to_engine_range() -> None:
    """Score is clamped 0..100 so a stray engine value can't trip the
    CHECK constraint and roll back the FV history write."""
    src = _read(_FV_SOURCE)
    assert "max(0, min(100, int(yieldiq_score)))" in src


def test_store_today_fair_value_persists_score_on_insert_and_update() -> None:
    src = _read(_FV_SOURCE)
    # UPDATE branch — only overwrite when the caller provided a value
    # so an unscored backfill doesn't blank a previously populated row.
    assert "if score_clamped is not None:" in src
    assert "existing.yieldiq_score = score_clamped" in src
    # INSERT branch — always pass both fields through.
    assert "yieldiq_score=score_clamped" in src
    assert "grade=grade_clean" in src


# -- analysis service threading -----------------------------------


def test_analysis_service_threads_score_and_grade_into_fv_args() -> None:
    src = _read(_ANALYSIS_SVC)
    # The kwargs reach the FV write hook through the _fv_args dict.
    assert "yieldiq_score=_yiq_score_val" in src
    assert "grade=_yiq_grade_val" in src


def test_analysis_service_guards_score_extraction_from_yiq_score_dict() -> None:
    """yiq_score may be missing keys (TypeError fallback path); the
    extraction must be defensive enough to land None rather than
    crashing the daemon thread."""
    src = _read(_ANALYSIS_SVC)
    assert "_yiq_score_val: int | None = None" in src
    assert "yiq_score.get(\"score\", None)" in src


# -- peers service DB fallback ------------------------------------


def test_peers_service_select_includes_score_and_grade_columns() -> None:
    src = _read(_PEERS_SVC)
    # Lock the SELECT list shape so a column reorder can't silently
    # break the fallback's score mapping.
    assert "SELECT fair_value, mos_pct, verdict, yieldiq_score, grade" in src


def test_peers_service_falls_back_to_legacy_query_on_missing_column() -> None:
    """Pre-migration safety net: if the yieldiq_score column doesn't
    exist yet (a Railway deploy may roll out the code before the
    migration applies), the FV/MoS/verdict surface still works."""
    src = _read(_PEERS_SVC)
    assert "SELECT fair_value, mos_pct, verdict\n" in src or (
        "SELECT fair_value, mos_pct, verdict\r\n" in src
    )


def test_peers_service_no_longer_returns_hard_coded_none_for_score() -> None:
    """The legacy '# not persisted; cache-only for now' comment marked
    the line that made every uncached peer show '—' for the SCORE
    column. Verify it's gone in the DB-hit path."""
    src = _read(_PEERS_SVC)
    assert "not persisted; cache-only for now" not in src


# -- manifest entry -----------------------------------------------


def test_manifest_records_peer_score_concall_backfill_entry() -> None:
    src = _read(_MANIFEST)
    assert (
        '"version_id": "v_peer_score_concall_backfill_2026_06_11"' in src
    )
    # The title is wrapped over multiple string-literal lines in source;
    # search the unwrapped form by stripping the Python " " + newline
    # continuation pattern.
    unwrapped = src.replace('"\n            "', "").replace('"\n        "', "")
    assert (
        "Peer comparison table now shows YieldIQ Score for each peer"
        in unwrapped
    )
