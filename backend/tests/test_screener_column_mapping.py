# backend/tests/test_screener_column_mapping.py
# CI guard: every alias in SCREENER_FIELD_MAP must point at a column
# that actually exists in the live PG schema (inside the JOIN scope of
# the screener_query handler — i.e. projected by one of the CTEs).
#
# This complements test_screener_dsl_schema_parity.py which hits the
# full /screener/query HTTP endpoint. That file exercises the query
# pipeline end-to-end; this one runs one lightweight SELECT per alias
# and fails fast with per-alias diagnostics. Both exist because the
# 2026-04-25 bug (mapper pointed pe_ratio at rh.pe_ratio when the
# latest_ratio CTE didn't project that column) slipped past every
# review. The screener_query test only catches the bug if the specific
# failing filter combo is exercised; this test catches every column
# drift deterministically.
#
# Skip policy: if neither DATABASE_URL nor NEON_DATABASE_URL is set,
# skip the live probe — the static mapper-vs-fields check in
# test_screener_dsl_schema_parity.py still runs in that environment.
from __future__ import annotations

import os
import sys
from pathlib import Path

_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest


def _resolve_dsn() -> str | None:
    # Match the precedence used by backend.routers.public at runtime.
    return os.environ.get("DATABASE_URL") or os.environ.get("NEON_DATABASE_URL")


@pytest.mark.skipif(
    not _resolve_dsn(),
    reason="no DATABASE_URL / NEON_DATABASE_URL; skipping live column probe",
)
def test_every_screener_alias_maps_to_live_column():
    """Every entry in SCREENER_FIELD_MAP must resolve to a real column.

    We call validate_screener_column_mapping() directly — it issues one
    ``SELECT <col> FROM <table> LIMIT 1`` per mapped expression and
    returns a list of human-readable failures. Empty list = pass.
    """
    from backend.routers.public import (
        SCREENER_FIELD_MAP,
        validate_screener_column_mapping,
    )

    assert SCREENER_FIELD_MAP, "SCREENER_FIELD_MAP is empty"
    failures = validate_screener_column_mapping(_resolve_dsn())
    assert not failures, (
        "Screener alias → column mapping has drifted from live schema:\n"
        + "\n".join(f"  - {f}" for f in failures)
        + "\n\nEither fix SCREENER_FIELD_MAP in backend/routers/public.py "
          "or re-project the column in the correct CTE inside screener_query."
    )
