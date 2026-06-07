"""Tests for the bank operating-income derivation helper (Issue #204).

Schedule III Division I (RBI banking format) does not carry a single
"operating income" line. The service layer derives it from the four
bank P&L inputs so EBIT margin / interest coverage / valuation gates
stop rendering NULL on the bank cohort.

These tests pin the contract of ``derive_bank_operating_income`` and
the surfacing behaviour of ``_build_year`` (which routes bank rows
through the helper when the GAAP ``ebit`` column is null).
"""
from __future__ import annotations

from datetime import date

import pytest

from backend.services.financials_service import (
    _Row,
    _build_year,
    derive_bank_operating_income,
)


# ─────────────────────────────────────────────────────────────────────
# Helper unit tests
# ─────────────────────────────────────────────────────────────────────

def test_derive_bank_operating_income_path_a():
    """Path A: NII + non-interest income − opex with all four inputs."""
    # HDFCBANK FY24 rough scale (₹Cr).
    out = derive_bank_operating_income(
        interest_earned=258_340.0,
        interest_expended=149_080.0,
        non_interest_income=49_241.0,
        operating_expenses=63_046.0,
        total_income=None,
    )
    # (258_340 − 149_080) + 49_241 − 63_046 = 95_455
    assert out == pytest.approx(95_455.0, rel=1e-4)


def test_derive_bank_operating_income_path_b_fallback():
    """Path B: total_income − interest_expended − opex (when
    non_interest_income is missing but total_income is present)."""
    out = derive_bank_operating_income(
        interest_earned=None,
        interest_expended=149_080.0,
        non_interest_income=None,
        operating_expenses=63_046.0,
        total_income=307_581.0,
    )
    # 307_581 − 149_080 − 63_046 = 95_455
    assert out == pytest.approx(95_455.0, rel=1e-4)


def test_derive_bank_operating_income_returns_none_when_inputs_missing():
    """Both derivation paths should fail closed when their inputs are absent."""
    # No interest_expended, no total_income → cannot derive.
    assert derive_bank_operating_income(
        interest_earned=100.0,
        interest_expended=None,
        non_interest_income=10.0,
        operating_expenses=20.0,
        total_income=None,
    ) is None

    # Empty everything.
    assert derive_bank_operating_income(
        interest_earned=None,
        interest_expended=None,
        non_interest_income=None,
        operating_expenses=None,
        total_income=None,
    ) is None


def test_derive_bank_operating_income_handles_zero_inputs():
    """Zero is a real value (not None) — derivation should land on the
    arithmetic result, not return None."""
    out = derive_bank_operating_income(
        interest_earned=100.0,
        interest_expended=80.0,
        non_interest_income=0.0,
        operating_expenses=10.0,
        total_income=None,
    )
    assert out == pytest.approx(10.0, rel=1e-6)


# ─────────────────────────────────────────────────────────────────────
# _build_year integration — bank vs non-bank routing
# ─────────────────────────────────────────────────────────────────────

def _bank_row_with_null_ebit() -> _Row:
    return _Row(
        period_end=date(2024, 3, 31),
        period_type="annual",
        revenue=258_340.0,
        ebit=None,
        interest_earned=258_340.0,
        interest_expended=149_080.0,
        non_interest_income=49_241.0,
        operating_expenses=63_046.0,
        total_income=307_581.0,
        pat=64_062.0,
        total_equity=350_000.0,
        total_debt=22_000_000.0,
    )


def test_build_year_derives_operating_income_for_bank(monkeypatch):
    """For a pure-bank ticker with NULL ebit and populated bank inputs,
    the year payload surfaces a derived operating_income."""
    # Force is_pure_bank_for_de True regardless of the local taxonomy.
    from backend.services.analysis import sector_overrides
    monkeypatch.setattr(
        sector_overrides, "is_pure_bank_for_de", lambda _t: True,
    )

    row = _bank_row_with_null_ebit()
    out = _build_year(row, prev=None, ticker="HDFCBANK")

    assert out["operating_income"] == pytest.approx(95_455.0, rel=1e-4)
    # Operating margin uses the derived value, not None.
    assert out["operating_margin_pct"] is not None
    assert out["operating_margin_pct"] == pytest.approx(36.9, abs=0.2)


def test_build_year_non_bank_leaves_operating_income_null(monkeypatch):
    """Non-banks must not be routed through the bank derivation even when
    interest_earned/expended happen to be non-null on the row."""
    from backend.services.analysis import sector_overrides
    monkeypatch.setattr(
        sector_overrides, "is_pure_bank_for_de", lambda _t: False,
    )

    row = _bank_row_with_null_ebit()
    out = _build_year(row, prev=None, ticker="TCS")

    # ebit is None and the ticker is not a bank — operating_income stays None.
    assert out["operating_income"] is None
    assert out["operating_margin_pct"] is None
