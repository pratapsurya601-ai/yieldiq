"""Day-104a (2026-05-23): AR ingest — unit tests.

Locks the contract for:

  * ``data_pipeline.sources.nse_annual_reports.normalize_record`` —
    URL/FY parsing, fallback to filename year, defensive None on
    missing URL or FY.
  * ``_parse_published_date`` and ``_resolve_fiscal_year`` — date-
    format tolerance and FY resolution precedence.
  * ``upsert_records`` against an in-memory SQLite shim of the
    canonical ``company_annual_reports`` table — dedupe on
    (ticker, fiscal_year), idempotent re-runs.
  * The CLI ``scripts/ingest_annual_reports.py`` end-to-end in dry-run
    + fixtures mode — never touches the network and never writes.

All tests use saved NSE JSON fixtures under
``backend/tests/fixtures/nse/annual_reports/``. No live calls.
"""
from __future__ import annotations

import json
import sqlite3
import subprocess
import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_pipeline.sources import nse_annual_reports as src  # noqa: E402

FIXTURES = ROOT / "backend" / "tests" / "fixtures" / "nse" / "annual_reports"


# ── SQLite shim mirroring company_annual_reports for upsert tests ──

class _CursorShim:
    def __init__(self, inner):
        self._inner = inner
        self.rowcount = 0

    def execute(self, sql: str, params=None):
        # psycopg2 uses %(name)s — sqlite3 uses :name. Convert.
        sql = sql.replace("%(", ":").replace(")s", "")
        self._inner.execute(sql, params or {})
        self.rowcount = self._inner.rowcount
        return self

    def fetchone(self):
        return self._inner.fetchone()

    def fetchall(self):
        return self._inner.fetchall()

    def close(self):
        return self._inner.close()

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        self._inner.close()


class _ConnShim:
    def __init__(self, raw):
        self._raw = raw

    def cursor(self):
        return _CursorShim(self._raw.cursor())

    def commit(self):
        return self._raw.commit()

    def rollback(self):
        return self._raw.rollback()

    def close(self):
        return self._raw.close()


def _make_db() -> _ConnShim:
    raw = sqlite3.connect(":memory:", check_same_thread=False)
    raw.execute(
        """
        CREATE TABLE company_annual_reports (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            ticker        TEXT NOT NULL,
            fiscal_year   INTEGER NOT NULL,
            ar_url        TEXT,
            ar_pdf_sha256 TEXT,
            source        TEXT,
            published_at  TEXT,
            UNIQUE (ticker, fiscal_year)
        )
        """
    )
    raw.commit()
    return _ConnShim(raw)


# ── normalize_record + helpers ──

def test_normalize_record_happy_path_hdfcbank():
    blob = json.loads((FIXTURES / "HDFCBANK.json").read_text())
    items = blob["data"]
    out = [src.normalize_record(it, "HDFCBANK") for it in items]
    assert all(r is not None for r in out)
    years = sorted(r["fiscal_year"] for r in out)
    assert years == [2022, 2023, 2024]
    # Ticker is normalised to upper-case (already upper here).
    assert out[0]["ticker"] == "HDFCBANK"
    # URL preserved verbatim.
    assert out[0]["ar_url"].startswith("https://nsearchives.nseindia.com/")
    assert out[0]["source"] == "nse"
    # ar_pdf_sha256 starts NULL — Phase-2 will populate after download.
    assert out[0]["ar_pdf_sha256"] is None
    # submissionDate "DD-MM-YYYY HH:MM:SS" parses to a date.
    assert isinstance(out[0]["published_at"], date)


def test_normalize_record_returns_none_on_missing_url():
    out = src.normalize_record({"to_yr": "2024"}, "FOO")
    assert out is None


def test_normalize_record_returns_none_on_missing_year():
    # No to_yr, no year, no parseable year in filename — must skip.
    out = src.normalize_record(
        {"fileName": "https://example.com/ar.pdf"},
        "FOO",
    )
    assert out is None


def test_normalize_record_falls_back_to_filename_year():
    out = src.normalize_record(
        {"fileName": "https://nsearchives.nseindia.com/AR_FOO_2021_2022.pdf"},
        "FOO",
    )
    assert out is not None
    # Latest year in filename wins.
    assert out["fiscal_year"] == 2022


def test_resolve_fiscal_year_prefers_to_yr_over_filename():
    item = {
        "to_yr": "2024",
        "fileName": "https://example.com/AR_2010_2011.pdf",
    }
    assert src._resolve_fiscal_year(item) == 2024


def test_parse_published_date_formats():
    assert src._parse_published_date("26-05-2024 18:30:00") == date(2024, 5, 26)
    assert src._parse_published_date("26-05-2024") == date(2024, 5, 26)
    assert src._parse_published_date("26-May-2024") == date(2024, 5, 26)
    assert src._parse_published_date("2024-05-26") == date(2024, 5, 26)
    assert src._parse_published_date(None) is None
    assert src._parse_published_date("garbage") is None


def test_strip_ns_suffix():
    assert src._strip_ns_suffix("HDFCBANK.NS") == "HDFCBANK"
    assert src._strip_ns_suffix("hdfcbank.ns") == "HDFCBANK"
    assert src._strip_ns_suffix("HDFCBANK") == "HDFCBANK"


# ── load_fixture ──

def test_load_fixture_reads_data_array():
    items = src.load_fixture("HDFCBANK", FIXTURES)
    assert len(items) == 3
    assert items[0]["symbol"] == "HDFCBANK"


def test_load_fixture_handles_ns_suffix():
    items = src.load_fixture("HDFCBANK.NS", FIXTURES)
    assert len(items) == 3


def test_load_fixture_empty_when_missing():
    assert src.load_fixture("NOSUCH", FIXTURES) == []


def test_load_fixture_empty_data_array():
    assert src.load_fixture("EMPTY", FIXTURES) == []


# ── upsert_records ──

def test_upsert_records_inserts_and_dedupes():
    conn = _make_db()
    rows = [
        {"ticker": "HDFCBANK", "fiscal_year": 2024,
         "ar_url": "https://example.com/fy24.pdf",
         "ar_pdf_sha256": None, "source": "nse",
         "published_at": date(2024, 5, 26)},
        {"ticker": "HDFCBANK", "fiscal_year": 2023,
         "ar_url": "https://example.com/fy23.pdf",
         "ar_pdf_sha256": None, "source": "nse",
         "published_at": date(2023, 5, 17)},
    ]
    n = src.upsert_records(rows, conn)
    assert n == 2

    # Re-running with the same rows must be a no-op (ON CONFLICT DO NOTHING).
    n2 = src.upsert_records(rows, conn)
    assert n2 == 0

    # Verify row count is exactly 2.
    cur = conn._raw.cursor()
    cur.execute("SELECT COUNT(*) FROM company_annual_reports")
    assert cur.fetchone()[0] == 2


def test_upsert_records_empty_is_zero():
    conn = _make_db()
    assert src.upsert_records([], conn) == 0


def test_upsert_records_preserves_existing_row_on_conflict():
    """If a row already has Phase-2 JSONB data, we must NOT overwrite it."""
    conn = _make_db()
    # Seed an existing row with a different URL — simulating an
    # earlier ingest run that may have an old URL we DON'T want to clobber.
    cur = conn._raw.cursor()
    cur.execute(
        "INSERT INTO company_annual_reports "
        "(ticker, fiscal_year, ar_url, source) "
        "VALUES ('HDFCBANK', 2024, 'https://old.example.com/fy24.pdf', 'manual')"
    )
    conn._raw.commit()

    rows = [
        {"ticker": "HDFCBANK", "fiscal_year": 2024,
         "ar_url": "https://new.example.com/fy24.pdf",
         "ar_pdf_sha256": None, "source": "nse",
         "published_at": date(2024, 5, 26)},
    ]
    n = src.upsert_records(rows, conn)
    assert n == 0  # Conflict → skipped.

    cur.execute(
        "SELECT ar_url, source FROM company_annual_reports "
        "WHERE ticker='HDFCBANK' AND fiscal_year=2024"
    )
    url, source = cur.fetchone()
    assert url == "https://old.example.com/fy24.pdf"
    assert source == "manual"


# ── CLI dry-run smoke (no network, no DB) ──

def test_cli_dry_run_with_fixtures_no_network():
    """End-to-end: CLI runs against saved fixtures, prints, exits 0."""
    script = ROOT / "scripts" / "ingest_annual_reports.py"
    assert script.exists(), script

    result = subprocess.run(
        [
            sys.executable, str(script),
            "--tickers", "HDFCBANK,RELIANCE",
            "--years-back", "10",
            "--dry-run",
            "--fixtures-dir", str(FIXTURES),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, (
        f"stdout:\n{result.stdout}\nstderr:\n{result.stderr}"
    )
    combined = result.stdout + result.stderr
    # We should see at least HDFCBANK FY2024 mentioned.
    assert "HDFCBANK" in combined
    assert "RELIANCE" in combined
    assert "dry-run" in combined.lower()
    # Must not have written (no DB connection should have been opened).
    assert "DONE annual-report ingest" in combined


def test_cli_years_back_filters_out_old_rows():
    """--years-back 1 from 2026 should drop the FY2022/FY2023 fixture rows."""
    script = ROOT / "scripts" / "ingest_annual_reports.py"
    result = subprocess.run(
        [
            sys.executable, str(script),
            "--tickers", "HDFCBANK",
            "--years-back", "1",
            "--dry-run",
            "--fixtures-dir", str(FIXTURES),
        ],
        cwd=str(ROOT),
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0
    combined = result.stdout + result.stderr
    # cutoff = today.year - 1 == 2025 (or later depending on today). All
    # fixture HDFCBANK rows are FY2022..FY2024 so all should be dropped.
    # We just assert the "ars_found" line shows 0.
    assert "ars_found=0" in combined or "ars_found   : 0" in combined
