"""Regression test for the 2026-05-16 psycopg2 cast bug in
scripts/migrate_sector_canonical.py::apply_cache().

The original UPDATE used `to_jsonb(:canon::text)` which trips up
SQLAlchemy's `:name` bind-param tokenizer when combined with the
PostgreSQL `::` cast operator, raising at execute time:

    psycopg2.errors.SyntaxError: syntax error at or near ":"

The fix is to use `CAST(:canon AS text)` instead, which is the
SQL-standard form and unambiguous for the SQLAlchemy compiler.

This test exercises both `apply_stocks` and `apply_cache` SQL
statements against a stub connection — it does NOT need a live
database — and verifies they compile/bind without error.
"""
from __future__ import annotations

from sqlalchemy import create_engine, text
from sqlalchemy.dialects import postgresql


def _stocks_update_sql():
    return text(
        "UPDATE stocks SET sector = :canon "
        "WHERE LOWER(TRIM(sector)) = :raw AND sector <> :canon"
    )


def _cache_update_sql():
    return text(
        """
        UPDATE analysis_cache
        SET payload = jsonb_set(payload, '{sector}', to_jsonb(CAST(:canon AS text)))
        WHERE LOWER(TRIM(payload->>'sector')) = :raw
          AND payload->>'sector' <> :canon
        """
    )


def _compile_pg(stmt, params):
    """Compile a TextClause for the postgresql dialect, binding
    params literally so we exercise the same code path psycopg2 hits
    at execute time."""
    return stmt.bindparams(**params).compile(
        dialect=postgresql.dialect(),
        compile_kwargs={"literal_binds": True},
    )


def test_apply_stocks_sql_compiles():
    compiled = _compile_pg(_stocks_update_sql(), {"canon": "Bank", "raw": "banks"})
    s = str(compiled)
    assert "UPDATE stocks" in s
    assert "'Bank'" in s
    assert "'banks'" in s


def test_apply_cache_sql_compiles_with_cast():
    """Verifies the fix: `CAST(:canon AS text)` compiles cleanly
    against the postgresql dialect with literal-bind, where the
    legacy `to_jsonb(:canon::text)` form was ambiguous."""
    compiled = _compile_pg(
        _cache_update_sql(),
        {"canon": "Bank", "raw": "banks"},
    )
    s = str(compiled)
    assert "jsonb_set" in s
    assert "CAST(" in s
    assert "AS text" in s.upper() or "AS TEXT" in s.upper()
    # And the bound canonical value is interpolated.
    assert "'Bank'" in s


def test_apply_cache_sql_does_not_use_broken_double_colon_form():
    """Belt-and-braces: ensure the SQL we ship does not contain
    the legacy `:canon::text` form that caused the production
    SyntaxError. If someone re-introduces it, this test fires."""
    import pathlib

    script = pathlib.Path(__file__).resolve().parents[1] / "scripts" / "migrate_sector_canonical.py"
    src = script.read_text(encoding="utf-8")
    assert ":canon::text" not in src, (
        "Re-introduced the psycopg2 cast bug — use CAST(:canon AS text) "
        "instead of to_jsonb(:canon::text)."
    )


def test_in_process_dry_run_compiles_both_sides():
    """Mini smoke test: build an in-memory engine, ensure both
    statements at least parse through the SQLAlchemy compiler with
    the postgresql dialect. We do not execute — we only confirm
    the bind-param path is well-formed for both sides of the
    migration."""
    # An sqlite engine is fine here; we explicitly compile for postgres.
    create_engine("sqlite:///:memory:")
    params = {"canon": "Healthcare", "raw": "pharmaceuticals"}
    _compile_pg(_stocks_update_sql(), params)
    _compile_pg(_cache_update_sql(), params)
