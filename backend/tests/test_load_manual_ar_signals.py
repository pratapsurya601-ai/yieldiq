"""Tests for scripts/load_manual_ar_signals.py.

Fixture-based: writes two sample JSON files into a tmp folder, mocks
the DB write path, and exercises the loader via its main() function.
Asserts:

* Clean fixture loads with quality_flag='ok'.
* "strong buy" fixture trips the sanitizer (multiple banned-vocab
  hits) and either swaps in place (<= threshold) or marks the row
  'sebi_withheld' (> threshold).
* Filename / JSON cross-check is enforced.
* --dry-run does not touch the DB.
* Re-run via ON CONFLICT path is exercised (mock cursor sees a
  second execute with the same key).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Make scripts/ importable.
SCRIPTS = ROOT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import load_manual_ar_signals as loader  # noqa: E402


_CLEAN = {
    "ticker": "HDFCBANK",
    "fiscal_year": 2025,
    "segment_data": [
        {"segment": "Retail", "revenue_cr": 12000, "ebit_cr": 2400,
         "fy": "FY25", "quote": "Retail segment grew steadily."},
    ],
    "capex_commitments": [
        {"amount_cr": 800, "fy": "FY26", "project": "Branch expansion",
         "quote": "Branch network expansion budgeted at Rs 800 Cr."},
    ],
    "related_party_transactions": [
        {"counterparty": "HDB Financial", "relationship": "subsidiary",
         "nature": "loans", "amount_cr": 50.0, "fy": "FY25",
         "quote": "Loans to HDB Financial of Rs 50 Cr."},
    ],
    "auditor_flags": [
        {"type": "emphasis_of_matter",
         "description": "Standard emphasis of matter on legacy item.",
         "as_of": "2025-03-31"},
    ],
    "contingent_liabilities": [
        {"description": "Pending tax assessments.",
         "amount_cr": 234, "as_of": "2025-03-31"},
    ],
    "management_outlook": "Management commentary is constructive on FY26.",
}


def _write(folder: Path, name: str, payload: dict) -> Path:
    p = folder / name
    p.write_text(json.dumps(payload), encoding="utf-8")
    return p


@pytest.fixture
def folder_with_two(tmp_path: Path) -> Path:
    """Two valid JSON files: one clean, one with multiple banned words."""
    _write(tmp_path, "HDFCBANK_2025.json", _CLEAN)

    dirty = json.loads(json.dumps(_CLEAN))
    dirty["ticker"] = "RELIANCE"
    dirty["fiscal_year"] = 2024
    # Pack in lots of banned words to definitely cross the > 5 threshold:
    # "buy", "strong", "recommend", "target", "should", "accumulate" = 6
    dirty["management_outlook"] = (
        "We strongly recommend investors buy this name; "
        "the target price is well above CMP, and you should accumulate "
        "aggressively. Rating: outperform."
    )
    dirty["segment_data"][0]["quote"] = "Strong buy signal across all segments."
    _write(tmp_path, "RELIANCE_2024.json", dirty)
    return tmp_path


# ---------------------------------------------------------------------------
# Filename + validation
# ---------------------------------------------------------------------------

def test_parse_filename_valid():
    assert loader.parse_filename("HDFCBANK_2025.json") == ("HDFCBANK", 2025)


def test_parse_filename_rejects_bad_pattern():
    assert loader.parse_filename("hdfcbank_2025.json") is None
    assert loader.parse_filename("HDFCBANK.json") is None
    assert loader.parse_filename("HDFCBANK_25.json") is None


def test_load_and_validate_clean(tmp_path: Path):
    p = _write(tmp_path, "HDFCBANK_2025.json", _CLEAN)
    payload = loader.load_and_validate(p)
    assert payload["ticker"] == "HDFCBANK"
    assert payload["fiscal_year"] == 2025


def test_load_and_validate_filename_ticker_mismatch(tmp_path: Path):
    payload = dict(_CLEAN, ticker="TCS")
    p = _write(tmp_path, "HDFCBANK_2025.json", payload)
    with pytest.raises(ValueError, match="filename ticker"):
        loader.load_and_validate(p)


def test_load_and_validate_filename_fy_mismatch(tmp_path: Path):
    payload = dict(_CLEAN, fiscal_year=2023)
    p = _write(tmp_path, "HDFCBANK_2025.json", payload)
    with pytest.raises(ValueError, match="filename FY"):
        loader.load_and_validate(p)


def test_load_and_validate_missing_top_key(tmp_path: Path):
    bad = {k: v for k, v in _CLEAN.items() if k != "auditor_flags"}
    p = _write(tmp_path, "HDFCBANK_2025.json", bad)
    with pytest.raises(ValueError, match="missing top-level keys"):
        loader.load_and_validate(p)


# ---------------------------------------------------------------------------
# Sanitizer behaviour
# ---------------------------------------------------------------------------

def test_sanitize_clean_payload_ok_no_hits():
    payload = json.loads(json.dumps(_CLEAN))
    _, flag, n = loader.sanitize(payload)
    assert flag == "ok"
    assert n == 0


def test_sanitize_strong_buy_triggers_withheld():
    """The spec requirement: fixture containing 'strong buy' (plus
    additional banned vocab) must trip the sanitizer over threshold
    and produce 'sebi_withheld'.
    """
    payload = json.loads(json.dumps(_CLEAN))
    payload["management_outlook"] = (
        "We strongly recommend investors buy this name; the target "
        "price is well above CMP, and you should accumulate aggressively. "
        "Outperform rating."
    )
    payload["segment_data"][0]["quote"] = "Strong buy signal across all segments."
    out, flag, n = loader.sanitize(payload)
    assert n > 5, f"expected > 5 hits to exceed threshold, got {n}"
    assert flag == "sebi_withheld"
    # Withheld rows have free-text fields blanked.
    assert out["management_outlook"] == ""
    assert out["segment_data"][0]["quote"] == ""


def test_sanitize_few_hits_swaps_in_place_keeps_ok():
    payload = json.loads(json.dumps(_CLEAN))
    payload["segment_data"][0]["quote"] = "Retail performance was strong."
    out, flag, n = loader.sanitize(payload)
    assert 0 < n <= loader.SANITIZER_SWAP_THRESHOLD
    assert flag == "ok"
    assert "[redacted]" in out["segment_data"][0]["quote"]
    assert "strong" not in out["segment_data"][0]["quote"].lower()


# ---------------------------------------------------------------------------
# End-to-end via main() with mocked DB
# ---------------------------------------------------------------------------

def test_dry_run_does_not_touch_db(folder_with_two: Path, capsys):
    """--dry-run must never call _connect_required."""
    with patch.object(loader, "_connect_required") as mock_conn:
        rc = loader.main(["--folder", str(folder_with_two), "--dry-run"])
    assert rc == 0
    mock_conn.assert_not_called()
    out = capsys.readouterr().out.strip()
    # 1 clean + 1 over-threshold withheld; nothing should fail.
    assert "loaded=1" in out
    assert "withheld=1" in out
    assert "failed=0" in out


def _mock_conn_with_ar_lookup(ar_id: int = 99):
    """Build a fake psycopg2-like connection where any
    company_annual_reports lookup returns (ar_id,) and other
    statements no-op.
    """
    cur = MagicMock()

    def _execute(sql, params=None):
        cur.last_sql = sql
        cur.last_params = params
        if "company_annual_reports" in sql:
            cur.fetchone.return_value = (ar_id,)
        else:
            cur.fetchone.return_value = None

    cur.execute.side_effect = _execute
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)
    return conn, cur


def test_full_run_writes_both_files(folder_with_two: Path, capsys):
    conn, cur = _mock_conn_with_ar_lookup(ar_id=42)
    with patch.object(loader, "_connect_required", return_value=conn):
        rc = loader.main(["--folder", str(folder_with_two)])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert "loaded=1" in out
    assert "withheld=1" in out
    assert "failed=0" in out

    # At least one INSERT INTO ar_signals call happened.
    insert_calls = [
        c for c in cur.execute.call_args_list
        if "INSERT INTO ar_signals" in c.args[0]
    ]
    assert len(insert_calls) == 2  # one per file

    # The withheld row must use the 'sebi_withheld' flag in its params.
    flags_used = {c.args[1][7] for c in insert_calls}  # quality_flag is 8th
    assert "sebi_withheld" in flags_used
    assert "ok" in flags_used

    # Manual model_version / prompt_version / cost are stamped.
    for c in insert_calls:
        params = c.args[1]
        assert params[8] == loader.MODEL_VERSION  # model_version
        assert params[9] == loader.PROMPT_VERSION  # prompt_version
        assert params[12] == 0                     # cost_usd


def test_subset_filter_only_loads_matching_ticker(
    folder_with_two: Path, capsys,
):
    conn, cur = _mock_conn_with_ar_lookup(ar_id=7)
    with patch.object(loader, "_connect_required", return_value=conn):
        rc = loader.main([
            "--folder", str(folder_with_two), "--tickers", "HDFCBANK",
        ])
    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert "loaded=1" in out and "withheld=0" in out and "failed=0" in out
    insert_calls = [
        c for c in cur.execute.call_args_list
        if "INSERT INTO ar_signals" in c.args[0]
    ]
    assert len(insert_calls) == 1


def test_missing_ar_row_marks_file_failed(
    folder_with_two: Path, capsys,
):
    """When company_annual_reports has no matching row, the file is
    reported as failed but the loader continues with the rest.
    """
    cur = MagicMock()

    def _execute(sql, params=None):
        if "company_annual_reports" in sql:
            cur.fetchone.return_value = None  # no AR row
        else:
            cur.fetchone.return_value = None

    cur.execute.side_effect = _execute
    cur.__enter__ = MagicMock(return_value=cur)
    cur.__exit__ = MagicMock(return_value=False)

    conn = MagicMock()
    conn.cursor.return_value = cur
    conn.__enter__ = MagicMock(return_value=conn)
    conn.__exit__ = MagicMock(return_value=False)

    with patch.object(loader, "_connect_required", return_value=conn):
        rc = loader.main(["--folder", str(folder_with_two)])

    assert rc == 0
    out = capsys.readouterr().out.strip()
    assert "failed=2" in out
    assert "loaded=0" in out


def test_upsert_uses_on_conflict_do_update(folder_with_two: Path):
    """Re-running on the same file must hit the ON CONFLICT path —
    inspect the SQL passed to the cursor.
    """
    conn, cur = _mock_conn_with_ar_lookup(ar_id=11)
    with patch.object(loader, "_connect_required", return_value=conn):
        loader.main(["--folder", str(folder_with_two), "--tickers", "HDFCBANK"])
        loader.main(["--folder", str(folder_with_two), "--tickers", "HDFCBANK"])

    insert_sqls = [
        c.args[0] for c in cur.execute.call_args_list
        if "INSERT INTO ar_signals" in c.args[0]
    ]
    assert len(insert_sqls) == 2
    for sql in insert_sqls:
        assert "ON CONFLICT (annual_report_id, model_version, prompt_version)" in sql
        assert "DO UPDATE" in sql
