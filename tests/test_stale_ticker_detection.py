"""Tests for scripts/sync_nse_active_universe.py.

We mock the NSE EQUITY_L.csv fetch with a tiny CSV fixture and verify the
delta computation correctly identifies tickers that are active in our DB but
no longer listed on NSE.
"""

from __future__ import annotations

import io
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = REPO_ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import sync_nse_active_universe as sync  # noqa: E402


NSE_CSV_FIXTURE = (
    "SYMBOL,NAME OF COMPANY,SERIES,DATE OF LISTING,PAID UP VALUE,"
    "MARKET LOT,ISIN NUMBER,FACE VALUE\n"
    "RELIANCE,Reliance Industries Limited,EQ,01-JAN-1995,10,1,INE002A01018,10\n"
    "TCS,Tata Consultancy Services Limited,EQ,25-AUG-2004,1,1,INE467B01029,1\n"
    "INFY,Infosys Limited,EQ,08-FEB-1995,5,1,INE009A01021,5\n"
    "  HDFCBANK ,HDFC Bank Limited,EQ,08-NOV-1995,1,1,INE040A01034,1\n"
)


def test_parse_symbols_extracts_symbol_column_and_strips_whitespace():
    symbols = sync._parse_symbols(NSE_CSV_FIXTURE)
    assert symbols == {"RELIANCE", "TCS", "INFY", "HDFCBANK"}


def test_parse_symbols_rejects_csv_without_symbol_column():
    bad_csv = "TICKER,NAME\nRELIANCE,Reliance\n"
    with pytest.raises(ValueError, match="SYMBOL"):
        sync._parse_symbols(bad_csv)


def test_compute_stale_identifies_db_only_tickers():
    db_active = {"RELIANCE", "TCS", "INFY", "CLCIND", "ABAN", "BRFL"}
    nse_active = {"RELIANCE", "TCS", "INFY", "HDFCBANK"}

    stale = sync.compute_stale(db_active, nse_active)

    assert stale == {"CLCIND", "ABAN", "BRFL"}


def test_compute_stale_empty_when_db_subset_of_nse():
    db_active = {"RELIANCE", "TCS"}
    nse_active = {"RELIANCE", "TCS", "INFY"}

    assert sync.compute_stale(db_active, nse_active) == set()


def test_compute_stale_ignores_nse_only_symbols():
    # Symbols listed on NSE but not in our DB should not be reported as stale.
    db_active = {"RELIANCE"}
    nse_active = {"RELIANCE", "NEWLISTING1", "NEWLISTING2"}

    assert sync.compute_stale(db_active, nse_active) == set()


def test_fetch_nse_active_symbols_uses_parser(monkeypatch):
    """End-to-end: fetch path returns symbols parsed from a stubbed response."""

    class _Resp:
        status_code = 200
        text = NSE_CSV_FIXTURE

        def raise_for_status(self):
            pass

    class _FakeCurlCffi:
        @staticmethod
        def get(url, impersonate=None, timeout=None):
            assert "EQUITY_L.csv" in url
            return _Resp()

    monkeypatch.setitem(
        sys.modules, "curl_cffi", type("M", (), {"requests": _FakeCurlCffi})()
    )

    symbols = sync.fetch_nse_active_symbols()
    assert "RELIANCE" in symbols
    assert "HDFCBANK" in symbols
    assert len(symbols) == 4


def test_write_report_emits_two_column_csv(tmp_path):
    out = tmp_path / "stale.csv"
    sync.write_report(str(out), ["CLCIND", "ABAN"])

    rows = list(io.StringIO(out.read_text(encoding="utf-8")))
    assert rows[0].strip() == "ticker,status"
    body = [r.strip() for r in rows[1:]]
    assert "ABAN,stale_not_on_nse_master" in body
    assert "CLCIND,stale_not_on_nse_master" in body
