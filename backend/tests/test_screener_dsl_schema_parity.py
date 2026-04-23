# backend/tests/test_screener_dsl_schema_parity.py
# Parity test: every DSL key published by /api/v1/public/screener/fields
# must map to a real column that parses and executes against the live DB.
#
# Why this exists
# ---------------
# Between v32 and v35 the screener DSL drifted from the PG schema three
# separate times (fv.mos → fv.mos_pct, fv.score → fv.confidence,
# rh.pe_ratio when the CTE only projected roe/roce/de_ratio). Every drift
# surfaced to users as HTTP 400 "screener query rejected by DB: 42703"
# and, before the frontend error path was fixed, as a silent "No stocks
# match" empty state. This test makes such a drift impossible to merge:
# it iterates the published /screener/fields contract and executes one
# benign predicate per field. If ANY field's column doesn't exist or is
# not exposed by the SELECT scope, the endpoint returns 400/500 and the
# test fails loudly in CI.
#
# Modes
# -----
# * DATABASE_URL set  → hits the real DB via the app; a full schema-parity
#                       check. This is what CI runs.
# * DATABASE_URL unset → the test is skipped. The static mapper-vs-fields
#                       subset check below still runs and is enough to
#                       catch "field published but not mapped" drift.
#
# Run:
#   pytest backend/tests/test_screener_dsl_schema_parity.py -v
from __future__ import annotations

import os
import sys
from pathlib import Path

# Ensure project root is importable when invoked directly.
_ROOT = str(Path(__file__).resolve().parent.parent.parent)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

import pytest


def _client():
    """Lazy TestClient — lets the static mapper-vs-fields test run in
    lightweight environments that don't have the full app's deps
    (sqlalchemy, psycopg2, etc). CI gets the full dep set installed."""
    from fastapi.testclient import TestClient
    from backend.main import app
    return TestClient(app)

# Benign predicates per field type. Each predicate is chosen so that:
#   * it is syntactically valid regardless of the column's actual value
#     distribution (no casts that could blow up on NULLs)
#   * it binds a parseable value for the mapper's float() / string branch
#   * the runtime overhead is dominated by the LIMIT 1 on the outer query
_NUMERIC_PROBE = ("<", "1e18")  # always true for any finite column
_STRING_PROBE = ("!=", "__yieldiq_sentinel__")  # always true


def _probe_for(field_type: str) -> tuple[str, str]:
    if field_type == "string":
        return _STRING_PROBE
    return _NUMERIC_PROBE


def _fetch_fields() -> list[dict]:
    r = _client().get("/api/v1/public/screener/fields")
    assert r.status_code == 200, f"/screener/fields failed: {r.status_code} {r.text}"
    body = r.json()
    assert isinstance(body, dict) and "fields" in body, body
    fields = body["fields"]
    assert isinstance(fields, list) and fields, "fields list is empty"
    return fields


def _parse_mapped_keys_from_source() -> set[str]:
    import re

    src = Path(_ROOT, "backend", "routers", "public.py").read_text(encoding="utf-8")
    m = re.search(
        r"_ALLOWED_FIELDS:\s*dict\[str,\s*str\]\s*=\s*\{([^}]+)\}",
        src,
        re.DOTALL,
    )
    assert m, "could not locate _ALLOWED_FIELDS literal in public.py"
    keys = set(re.findall(r'"([a-z_]+)"\s*:', m.group(1)))
    assert keys, "parsed mapper dict is empty"
    return keys


def _parse_published_keys_from_source() -> set[str]:
    """Extract the field keys from the /screener/fields handler source.

    The handler returns a static dict literal; parsing the source lets
    this static test run without importing the FastAPI app (which
    pulls in sqlalchemy / psycopg2).
    """
    import re

    src = Path(_ROOT, "backend", "routers", "public.py").read_text(encoding="utf-8")
    # Locate the async def screener_fields() block and grab the
    # `"key": "..."` entries inside its return dict.
    m = re.search(
        r"async def screener_fields\(\).*?return \{(.*?)^\}",
        src,
        re.DOTALL | re.MULTILINE,
    )
    if not m:
        # Fallback: match to next top-level decorator if the final `}`
        # isn't at column 0 (it's inside a function).
        m = re.search(
            r"async def screener_fields\(\).*?(?=^@router|\Z)",
            src,
            re.DOTALL | re.MULTILINE,
        )
    assert m, "could not locate screener_fields handler in public.py"
    body = m.group(0)
    keys = set(re.findall(r'"key"\s*:\s*"([a-z_]+)"', body))
    assert keys, "parsed /screener/fields handler has no keys"
    return keys


def test_every_published_field_has_a_column_mapping():
    """Static guard: every /screener/fields key must appear in
    _ALLOWED_FIELDS inside backend/routers/public.py.

    This runs without a DB or the FastAPI app — catches the most
    common drift (someone adds a field to /screener/fields but
    forgets the mapper).
    """
    mapped = _parse_mapped_keys_from_source()
    published = _parse_published_keys_from_source()
    missing = published - mapped
    assert not missing, (
        f"/screener/fields publishes keys with no SQL column mapping: {sorted(missing)}. "
        f"Add them to _ALLOWED_FIELDS in backend/routers/public.py."
    )


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping live-DB parity execution",
)
def test_every_published_field_executes_against_live_db():
    """Live-DB guard: iterate every field from /screener/fields and
    execute a benign predicate through the real query endpoint. Any
    HTTP 400/500 here means the DSL→SQL column mapping is out of sync
    with the PG schema.
    """
    c = _client()
    r0 = c.get("/api/v1/public/screener/fields")
    assert r0.status_code == 200, r0.text
    fields = r0.json()["fields"]
    failures: list[str] = []

    for f in fields:
        key = f["key"]
        ftype = f.get("type", "number")
        op, val = _probe_for(ftype)
        filters = f"{key}{op}{val}"
        r = c.get(
            "/api/v1/public/screener/query",
            params={"filters": filters, "limit": 1},
        )
        if r.status_code != 200:
            failures.append(
                f"  - {key} ({ftype}) → HTTP {r.status_code}: "
                f"{r.text[:200]}"
            )
            continue
        body = r.json()
        # Schema: {total, limit, offset, sort, filters_applied, results}
        for required in ("total", "results", "filters_applied"):
            if required not in body:
                failures.append(
                    f"  - {key}: response missing `{required}` — body={body!r}"
                )

    assert not failures, (
        "Screener DSL fields failed live-DB parity:\n"
        + "\n".join(failures)
        + "\n\nFix _ALLOWED_FIELDS in backend/routers/public.py and/or "
          "the CTE projections so every published field maps to a real "
          "column in the JOIN scope."
    )


@pytest.mark.skipif(
    not os.environ.get("DATABASE_URL"),
    reason="DATABASE_URL not set — skipping live-DB parity execution",
)
def test_sort_keys_execute_against_live_db():
    """Every sort key advertised by /screener/fields (under
    `sort_keys`) must also produce a 200. A typo in _SORT_MAP would
    fall back to mos_pct silently, but an unknown SQL column in
    _SORT_MAP would 400."""
    c = _client()
    r = c.get("/api/v1/public/screener/fields")
    assert r.status_code == 200
    sort_keys = r.json().get("sort_keys", [])
    assert sort_keys, "no sort_keys advertised"

    failures: list[str] = []
    for key in sort_keys:
        resp = c.get(
            "/api/v1/public/screener/query",
            params={"sort": key, "limit": 1},
        )
        if resp.status_code != 200:
            failures.append(
                f"  - sort={key!r} → HTTP {resp.status_code}: {resp.text[:200]}"
            )

    assert not failures, (
        "Screener sort keys failed live-DB parity:\n" + "\n".join(failures)
    )
