"""Tests for the bank-format extraction in yf_fetcher.extract_income_records
(Issue #206 — Schedule III Division I bank XBRL fields).

The annual ingest pipeline (data_pipeline.xbrl.yf_fetcher) ingests
income / balance / cashflow rows for every covered ticker. For commercial
banks (HDFCBANK, ICICIBANK, SBIN, AXISBANK, …) yfinance surfaces extra
rows that map to the RBI Schedule III Div I lines:

  ``Interest Income``           → interest_earned
  ``Interest Expense``          → interest_expended
  ``Net Non Interest Income``   → other_income (non-interest income)
  ``Total Operating Expenses``  → operating_expense

These tests pin that contract using an in-memory pandas DataFrame so the
parser is exercised in isolation (no network / yfinance call).
"""
from __future__ import annotations

import math
import sys
import types
from datetime import datetime

import pandas as pd

# yf_fetcher.py uses flat ``from config import RUPEES_TO_CRORES`` and
# ``from tickers import get_yf_symbol`` — both rely on a sys.path hack
# that the production ingest scripts apply at startup. The backend test
# environment doesn't path-hack, so we register synthetic shims for the
# two flat modules, import yf_fetcher (which only USES these constants
# at import time / inside helpers we don't exercise), then restore the
# real ``config`` PACKAGE for subsequent tests in the same session.
_PRE_EXISTING_CONFIG = sys.modules.get("config")
_PRE_EXISTING_TICKERS = sys.modules.get("tickers")

if (
    _PRE_EXISTING_CONFIG is None
    or not hasattr(_PRE_EXISTING_CONFIG, "RUPEES_TO_CRORES")
):
    _shim_config = types.ModuleType("config")
    _shim_config.RUPEES_TO_CRORES = 1e7
    _shim_config.NSE_DELAY = 0.0
    sys.modules["config"] = _shim_config

if _PRE_EXISTING_TICKERS is None:
    _shim_tickers = types.ModuleType("tickers")
    _shim_tickers.get_yf_symbol = lambda t: t
    sys.modules["tickers"] = _shim_tickers

from data_pipeline.xbrl.yf_fetcher import extract_income_records  # noqa: E402

# Restore so tests later in the session (which import backend.main and
# expect ``config`` to be a real PACKAGE) are unaffected.
if _PRE_EXISTING_CONFIG is not None:
    sys.modules["config"] = _PRE_EXISTING_CONFIG
else:
    sys.modules.pop("config", None)
if _PRE_EXISTING_TICKERS is not None:
    sys.modules["tickers"] = _PRE_EXISTING_TICKERS
else:
    sys.modules.pop("tickers", None)

# 1 Cr = 1e7 raw rupees; yfinance reports raw rupees, the extractor
# divides by RUPEES_TO_CRORES = 1e7 (see safe_val).
CR = 1e7


def _bank_income_df():
    """Construct a synthetic bank P&L frame in the shape yfinance returns
    for a commercial bank (rows are line-items, columns are period-ends).
    """
    col = pd.Timestamp("2024-03-31")
    data = {
        # Headline lines (industrial schema — banks fill the same slots).
        "Total Revenue":               258_340.0 * CR,
        "Net Income":                   64_062.0 * CR,
        "Pretax Income":                85_000.0 * CR,
        "Tax Provision":                21_000.0 * CR,
        "Basic EPS":                       89.7,
        "Diluted EPS":                     89.5,
        # Bank-specific rows (Schedule III Div I).
        "Interest Income":             258_340.0 * CR,
        "Interest Expense":            149_080.0 * CR,
        "Net Non Interest Income":      49_241.0 * CR,
        "Total Operating Expenses":     63_046.0 * CR,
    }
    df = pd.DataFrame({col: list(data.values())}, index=list(data.keys()))
    return {
        "ticker": "HDFCBANK",
        "annual_income": df,
    }


def _industrial_income_df():
    """Synthetic non-bank P&L (no bank rows) so the bank aliases must
    stay NULL — the fetcher must not invent values for non-banks."""
    col = pd.Timestamp("2024-03-31")
    data = {
        "Total Revenue":               240_000.0 * CR,
        "Gross Profit":                100_000.0 * CR,
        "EBITDA":                       80_000.0 * CR,
        "EBIT":                         60_000.0 * CR,
        "Operating Expense":           180_000.0 * CR,
        "Interest Expense":              5_000.0 * CR,
        "Other Income Expense":          3_000.0 * CR,
        "Net Income":                   50_000.0 * CR,
        "Pretax Income":                65_000.0 * CR,
        "Tax Provision":                15_000.0 * CR,
        "Basic EPS":                      150.0,
        "Diluted EPS":                    149.0,
    }
    df = pd.DataFrame({col: list(data.values())}, index=list(data.keys()))
    return {
        "ticker": "TCS",
        "annual_income": df,
    }


def test_bank_income_record_populates_schedule_iii_div_i_fields():
    """Every Schedule III Div I bank line we ingest must land on the
    canonical column. None of them may be NaN."""
    data = _bank_income_df()
    records = extract_income_records(data, period_type="annual")
    assert len(records) == 1, "expected exactly one income row"
    rec = records[0]

    # The eight required fields per the Issue #206 brief.
    assert rec["revenue"] == 258_340.0
    assert rec["interest_earned"] == 258_340.0
    assert rec["interest_expended"] == 149_080.0
    # ``other_income`` is the non-interest income slot for banks
    # (Schedule III Div I "Other Income" = fee + commission + treasury).
    assert rec["other_income"] == 49_241.0
    assert rec["operating_expense"] == 63_046.0
    assert rec["total_income"] == 258_340.0
    assert rec["net_income"] == 64_062.0
    # eps_diluted comes through as a per-share rupee value (not scaled).
    assert rec["eps_diluted"] == 89.5

    # No NaN slips through.
    for k, v in rec.items():
        if isinstance(v, float):
            assert not math.isnan(v), f"field {k} is NaN"


def test_bank_format_fields_null_for_non_banks():
    """When a row's income frame contains no bank-specific rows the
    Schedule III Div I aliases must stay None — we never want to invent
    bank fields for industrials (would muddy the bank cohort detection
    and the operating_income derivation)."""
    data = _industrial_income_df()
    records = extract_income_records(data, period_type="annual")
    assert len(records) == 1
    rec = records[0]

    # Industrial fields populate as before — regression guard for the
    # backwards-compatible path.
    assert rec["revenue"] == 240_000.0
    assert rec["gross_profit"] == 100_000.0
    assert rec["ebit"] == 60_000.0
    assert rec["operating_expense"] == 180_000.0

    # Bank aliases stay None (no Interest Income / Net NII row in the frame).
    assert rec["interest_earned"] is None
    assert rec["interest_expended"] is None
    assert rec["total_income"] is None


def test_bank_quarterly_records_also_populate_bank_fields():
    """Quarterly ingest path uses the same extractor with
    period_type='quarterly' — bank-format aliases must populate there
    too so the quarterly bank surface (margin chart, NII trend) lights
    up after this change."""
    data = _bank_income_df()
    # Rename frame key to quarterly_income to take the q-path.
    data["quarterly_income"] = data.pop("annual_income")
    records = extract_income_records(data, period_type="quarterly")
    assert len(records) == 1
    rec = records[0]
    assert rec["period_type"] == "quarterly"
    assert rec["interest_earned"] == 258_340.0
    assert rec["interest_expended"] == 149_080.0
    assert rec["operating_expense"] == 63_046.0
