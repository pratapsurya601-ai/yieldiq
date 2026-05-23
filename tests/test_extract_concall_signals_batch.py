"""Unit tests for scripts/extract_concall_signals_batch.py.

Pure helpers only — the batch loop itself talks to the DB and Anthropic
which are integration concerns covered by smoke testing.
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from types import SimpleNamespace

import pytest

_ROOT = Path(__file__).resolve().parent.parent
_SCRIPTS = _ROOT / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))

import extract_concall_signals_batch as batch  # type: ignore[import-not-found]


def _row(subject: str, filing_year: int = 2026):
    return SimpleNamespace(
        subject=subject,
        filing_date=date(filing_year, 3, 15),
    )


def test_fiscal_period_prefers_parsed_subject():
    # Parser returns "Q3-FY25" -> normalised to "Q3FY25".
    out = batch._resolve_fiscal_period(
        _row("Q3 FY25 earnings call"),
        signals={"fiscal_period": "Q1FY26"},  # should be ignored
    )
    assert out == "Q3FY25"


def test_fiscal_period_falls_back_to_llm_when_subject_unparseable():
    # _parse_period_from_subject returns truncated subject for these.
    out = batch._resolve_fiscal_period(
        _row("Investor meet recording link"),
        signals={"fiscal_period": "Q4FY26"},
    )
    assert out == "Q4FY26"


def test_fiscal_period_final_fallback_to_filing_year():
    out = batch._resolve_fiscal_period(
        _row("Investor meet recording link", filing_year=2025),
        signals={},
    )
    assert out == "FY25"


def test_fiscal_period_unknown_when_no_signals_no_date():
    row = SimpleNamespace(subject="", filing_date=None)
    out = batch._resolve_fiscal_period(row, signals={})
    assert out == "UNKNOWN"
