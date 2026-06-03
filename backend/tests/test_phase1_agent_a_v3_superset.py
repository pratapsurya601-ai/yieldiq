# backend/tests/test_phase1_agent_a_v3_superset.py
# =================================================================
# Phase 1 — Agent A v3 superset migration tests.
#
# Validates the SQL contents of
#   data_pipeline/migrations/202606031123_fair_value_history_superset.sql
# and its rollback. Deliberately DB-less — backend/tests has no
# shared Postgres fixture (same pattern as test_data_quality_rank.py
# and test_corporate_actions_precedence.py).
#
# What we prove here:
#
#   1. All 5 new columns are added by the forward migration
#      (provenance, manifest_id, quarantine_reason, quarantined_at,
#      quarantine_source).
#   2. The migration contains NO UPDATE statements against
#      fair_value, mos_pct, wacc, or confidence — i.e. it is
#      schema-only and cannot retroactively recompute engine output.
#   3. The migration contains NO row-marking UPDATE for
#      quarantine_reason — that fill is a SEPARATE later migration.
#   4. The partial served-slice index ix_fv_history_served exists
#      and is filtered WHERE quarantine_reason IS NULL.
#   5. updated_at has SET DEFAULT NOW().
#   6. The provenance and quarantine_reason CHECK constraints exist
#      and use the locked Pydantic-contract vocabulary.
#   7. The duplicate-index DROP IF EXISTS statements are present.
#   8. The rollback drops all 5 columns + the partial index + the
#      updated_at default, and does NOT recreate the dropped
#      duplicate indexes.
# =================================================================
from __future__ import annotations

import re
from pathlib import Path

import pytest

MIGRATIONS_DIR = (
    Path(__file__).resolve().parents[2] / "data_pipeline" / "migrations"
)
FORWARD = MIGRATIONS_DIR / "202606031123_fair_value_history_superset.sql"
ROLLBACK = MIGRATIONS_DIR / "202606031123_fair_value_history_superset_rollback.sql"


@pytest.fixture(scope="module")
def forward_sql() -> str:
    assert FORWARD.exists(), f"missing migration file: {FORWARD}"
    return FORWARD.read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def rollback_sql() -> str:
    assert ROLLBACK.exists(), f"missing rollback file: {ROLLBACK}"
    return ROLLBACK.read_text(encoding="utf-8")


# ---- Column additions -------------------------------------------------

NEW_COLUMNS = (
    "provenance",
    "manifest_id",
    "quarantine_reason",
    "quarantined_at",
    "quarantine_source",
)


def test_all_five_new_columns_added(forward_sql: str) -> None:
    """Each new column appears in an ADD COLUMN IF NOT EXISTS clause."""
    for col in NEW_COLUMNS:
        pattern = rf"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+{col}\b"
        assert re.search(pattern, forward_sql, re.IGNORECASE), (
            f"forward migration missing ADD COLUMN IF NOT EXISTS for {col}"
        )


def test_provenance_has_default_live(forward_sql: str) -> None:
    """provenance must default to 'live' so existing rows backfill cleanly."""
    pattern = (
        r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+provenance\s+TEXT\s+"
        r"NOT\s+NULL\s+DEFAULT\s+'live'"
    )
    assert re.search(pattern, forward_sql, re.IGNORECASE)


def test_manifest_id_is_nullable_text(forward_sql: str) -> None:
    """manifest_id is the string handle to the in-code MANIFEST list; NULLable."""
    pattern = r"ADD\s+COLUMN\s+IF\s+NOT\s+EXISTS\s+manifest_id\s+TEXT\s+NULL"
    assert re.search(pattern, forward_sql, re.IGNORECASE)


# ---- Schema-only invariant -------------------------------------------

def test_no_update_of_engine_output_columns(forward_sql: str) -> None:
    """The migration MUST NOT touch fair_value / mos_pct / wacc /
    confidence values — that would be retroactive recompute and is
    forbidden by CLAUDE.md manifest invariants."""
    for col in ("fair_value", "mos_pct", "wacc", "confidence"):
        pattern = rf"UPDATE\s+fair_value_history\s+SET\s+[^;]*\b{col}\b"
        assert not re.search(pattern, forward_sql, re.IGNORECASE | re.DOTALL), (
            f"forward migration unexpectedly UPDATEs {col}; this is a "
            "no-retroactive-corroboration violation."
        )


def test_no_quarantine_reason_data_fill(forward_sql: str) -> None:
    """The 40,139-row pre-epoch fill is a SEPARATE later migration.
    This one is schema-only."""
    # No UPDATE on fair_value_history that sets quarantine_reason.
    pattern = (
        r"UPDATE\s+fair_value_history\s+SET\s+[^;]*\bquarantine_reason\s*="
    )
    assert not re.search(pattern, forward_sql, re.IGNORECASE | re.DOTALL), (
        "forward migration includes a quarantine_reason data-fill "
        "UPDATE; that belongs in a separate later migration."
    )


def test_no_update_statements_on_fv_history_at_all(forward_sql: str) -> None:
    """Strongest form: no UPDATE fair_value_history at all in this migration."""
    pattern = r"UPDATE\s+fair_value_history"
    assert not re.search(pattern, forward_sql, re.IGNORECASE), (
        "schema-only migration must contain zero UPDATE statements on "
        "fair_value_history."
    )


# ---- Partial index --------------------------------------------------

def test_served_partial_index_present(forward_sql: str) -> None:
    """ix_fv_history_served is the served-slice partial index."""
    # Must reference the columns and the WHERE clause on quarantine_reason.
    assert re.search(
        r"CREATE\s+INDEX\s+IF\s+NOT\s+EXISTS\s+ix_fv_history_served\s+ON\s+"
        r"fair_value_history\s*\(\s*ticker\s*,\s*date\s*\)\s+"
        r"WHERE\s+quarantine_reason\s+IS\s+NULL",
        forward_sql,
        re.IGNORECASE,
    ), "partial served-slice index ix_fv_history_served missing or malformed"


# ---- updated_at default ---------------------------------------------

def test_updated_at_default_now(forward_sql: str) -> None:
    assert re.search(
        r"ALTER\s+COLUMN\s+updated_at\s+SET\s+DEFAULT\s+NOW\s*\(\s*\)",
        forward_sql,
        re.IGNORECASE,
    ), "updated_at SET DEFAULT NOW() missing"


# ---- CHECK constraints ----------------------------------------------

def test_provenance_check_constraint_vocabulary(forward_sql: str) -> None:
    """provenance CHECK must mirror the Pydantic Literal in
    backend/models/fair_value_history.py: snapshot, golden, live."""
    for val in ("snapshot", "golden", "live"):
        assert f"'{val}'" in forward_sql, (
            f"provenance CHECK missing value '{val}'"
        )


def test_quarantine_reason_check_constraint_vocabulary(forward_sql: str) -> None:
    for val in (
        "pre_manifest_epoch",
        "step_unverified",
        "mos_out_of_band",
        "provenance_missing",
    ):
        assert f"'{val}'" in forward_sql, (
            f"quarantine_reason CHECK missing value '{val}'"
        )


# ---- Duplicate-index drops ------------------------------------------

def test_drops_duplicate_indexes(forward_sql: str) -> None:
    """Folded escalation §6.1 — drop the two duplicate single-column
    indexes. IF EXISTS keeps it safe when they were already removed."""
    assert re.search(
        r"DROP\s+INDEX\s+IF\s+EXISTS\s+ix_fair_value_history_date",
        forward_sql,
        re.IGNORECASE,
    )
    assert re.search(
        r"DROP\s+INDEX\s+IF\s+EXISTS\s+ix_fair_value_history_ticker",
        forward_sql,
        re.IGNORECASE,
    )


# ---- Rollback --------------------------------------------------------

def test_rollback_drops_all_five_columns(rollback_sql: str) -> None:
    for col in NEW_COLUMNS:
        assert re.search(
            rf"DROP\s+COLUMN\s+IF\s+EXISTS\s+{col}\b",
            rollback_sql,
            re.IGNORECASE,
        ), f"rollback missing DROP COLUMN IF EXISTS for {col}"


def test_rollback_drops_partial_index(rollback_sql: str) -> None:
    assert re.search(
        r"DROP\s+INDEX\s+IF\s+EXISTS\s+ix_fv_history_served",
        rollback_sql,
        re.IGNORECASE,
    )


def test_rollback_drops_updated_at_default(rollback_sql: str) -> None:
    assert re.search(
        r"ALTER\s+COLUMN\s+updated_at\s+DROP\s+DEFAULT",
        rollback_sql,
        re.IGNORECASE,
    )


def test_rollback_does_not_recreate_duplicate_indexes(rollback_sql: str) -> None:
    """The dropped duplicates were dupes by definition — re-creating
    them in rollback would re-introduce the write amplification."""
    assert not re.search(
        r"CREATE\s+INDEX\s+[^;]*\bix_fair_value_history_date\b",
        rollback_sql,
        re.IGNORECASE | re.DOTALL,
    )
    assert not re.search(
        r"CREATE\s+INDEX\s+[^;]*\bix_fair_value_history_ticker\b",
        rollback_sql,
        re.IGNORECASE | re.DOTALL,
    )


# ---- Transactionality ------------------------------------------------

def test_forward_is_transactional(forward_sql: str) -> None:
    assert re.search(r"^\s*BEGIN\s*;", forward_sql, re.IGNORECASE | re.MULTILINE)
    assert re.search(r"^\s*COMMIT\s*;", forward_sql, re.IGNORECASE | re.MULTILINE)


def test_rollback_is_transactional(rollback_sql: str) -> None:
    assert re.search(r"^\s*BEGIN\s*;", rollback_sql, re.IGNORECASE | re.MULTILINE)
    assert re.search(r"^\s*COMMIT\s*;", rollback_sql, re.IGNORECASE | re.MULTILINE)
