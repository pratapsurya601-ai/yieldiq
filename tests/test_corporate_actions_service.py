# tests/test_corporate_actions_service.py
# ═══════════════════════════════════════════════════════════════
# Unit tests for backend.services.corporate_actions_service (Phase A).
#
# Scope: skeleton + fallback behaviour. No seed data exists yet, so
# the tests assert the safe no-op contract:
#   * STRUCTURAL_ACTION_TYPES contains the documented set.
#   * has_structural_break() returns False when the DB query returns
#     no structural rows (including when the DB is unreachable).
#   * compute_cagr_structural_aware() falls back to compute_revenue_cagr
#     when there is no break.
#   * get_actions() returns [] cleanly when DB is unreachable.
#   * Schema migration file ships with the expected DDL bits.
#
# Hermetic: monkeypatches _get_cursor / get_actions so no live Postgres
# is needed.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import os
import sys
from datetime import date
from pathlib import Path

import pytest

_HERE = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.dirname(_HERE)
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from backend.services import corporate_actions_service as cas


# ── 1. Constant surface ─────────────────────────────────────────
def test_structural_action_types_documented_set():
    expected = {
        "MERGER",
        "REVERSE_MERGER",
        "DEMERGER",
        "SCHEME_OF_ARRANGEMENT",
        "MATERIAL_ACQUISITION",
    }
    assert cas.STRUCTURAL_ACTION_TYPES == frozenset(expected)


# ── 2. Method signatures exist ──────────────────────────────────
def test_public_api_signatures_present():
    assert callable(cas.get_actions)
    assert callable(cas.has_structural_break)
    assert callable(cas.compute_cagr_structural_aware)


# ── 3. get_actions returns [] on missing DB ─────────────────────
def test_get_actions_returns_empty_when_db_unreachable(monkeypatch):
    monkeypatch.setattr(cas, "_get_cursor", lambda: (None, None))
    assert cas.get_actions("HDFCBANK") == []
    assert cas.get_actions("HDFCBANK", action_type="REVERSE_MERGER") == []
    assert cas.get_actions("HDFCBANK", since=date(2020, 1, 1)) == []


def test_get_actions_rejects_empty_ticker(monkeypatch):
    # Should never even open a cursor for an empty ticker.
    def _boom():
        raise AssertionError("_get_cursor must not be called for empty ticker")
    monkeypatch.setattr(cas, "_get_cursor", _boom)
    assert cas.get_actions("") == []
    assert cas.get_actions("   ") == []


# ── 4. has_structural_break: False with no rows ─────────────────
def test_has_structural_break_false_when_no_rows(monkeypatch):
    monkeypatch.setattr(cas, "get_actions", lambda *a, **kw: [])
    assert cas.has_structural_break("HDFCBANK") is False
    assert cas.has_structural_break("HDFCBANK", window_years=5) is False


def test_has_structural_break_ignores_non_structural_rows(monkeypatch):
    # Dividend / split rows must NOT trigger a structural break.
    rows = [
        {"ticker": "HDFCBANK", "ex_date": date(2024, 5, 1),
         "action_type": "DIVIDEND"},
        {"ticker": "HDFCBANK", "ex_date": date(2024, 8, 1),
         "action_type": "SPLIT"},
    ]
    monkeypatch.setattr(cas, "get_actions", lambda *a, **kw: rows)
    assert cas.has_structural_break("HDFCBANK") is False


def test_has_structural_break_true_when_structural_row_present(monkeypatch):
    rows = [
        {"ticker": "HDFCBANK", "ex_date": date(2023, 7, 1),
         "action_type": "REVERSE_MERGER"},
    ]
    monkeypatch.setattr(cas, "get_actions", lambda *a, **kw: rows)
    # Phase-A behavioural contract: detection wiring works even though
    # no seed rows exist in prod yet. This test proves Phase B will
    # activate without code changes.
    assert cas.has_structural_break("HDFCBANK", window_years=5) is True


def test_has_structural_break_zero_window_returns_false(monkeypatch):
    monkeypatch.setattr(cas, "get_actions",
                        lambda *a, **kw: pytest.fail("should not query"))
    assert cas.has_structural_break("HDFCBANK", window_years=0) is False


# ── 5. compute_cagr_structural_aware fallback ───────────────────
def test_compute_cagr_falls_back_to_plain_when_no_break(monkeypatch):
    monkeypatch.setattr(cas, "has_structural_break", lambda *a, **kw: False)
    # Series: 100 → 121 over 2 steps (3 points = 2 years) → ~10% CAGR.
    series = [100.0, 110.0, 121.0]
    out = cas.compute_cagr_structural_aware("FOO", "revenue", years=2,
                                            series=series)
    assert out is not None
    assert abs(out - 0.10) < 0.005


def test_compute_cagr_returns_none_when_series_missing():
    # Phase A: no cache fallback yet — None in, None out.
    out = cas.compute_cagr_structural_aware("FOO", "revenue", years=3,
                                            series=None)
    assert out is None


# ── 6. Migration file present with key DDL ──────────────────────
def test_migration_files_exist_and_contain_columns():
    repo_root = Path(_ROOT)
    paths = [
        repo_root / "data_pipeline" / "migrations" /
        "041_corporate_actions_structural.sql",
        repo_root / "db" / "migrations" /
        "012_corporate_actions_structural.sql",
    ]
    for p in paths:
        assert p.exists(), f"missing migration: {p}"
        text = p.read_text(encoding="utf-8")
        for needle in (
            "ADD COLUMN IF NOT EXISTS multiplier",
            "ADD COLUMN IF NOT EXISTS source_url",
            "ADD COLUMN IF NOT EXISTS source_doc",
            "ADD COLUMN IF NOT EXISTS notes",
            "ck_structural_sourced",
            "REVERSE_MERGER",
            "DEMERGER",
        ):
            assert needle in text, f"{p.name} missing: {needle}"
