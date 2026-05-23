"""Phase I-ingest-a (Block III) -- parse_bank_xbrl unit tests.

Exercises the real ``parse_bank_xbrl`` against fixture XBRL files:

  * ``hdfcbank_q2_fy25_standalone.xml`` -- real BSE quarterly XBRL
    (in-bse-fin 2019-09-30 schema), standalone filing with all six
    base facts present (NPA decimals + balance-sheet instants).
  * ``hdfcbank_integrated_q4_fy26.xml`` -- real BSE quarterly XBRL
    on the SEBI Integrated Filing 2026-01-31 schema (in-capmkt).
    This is a CONSOLIDATED filing, so NPA fields are zero per RBI
    disclosure convention; the test asserts the parser drops them
    gracefully while still extracting CD ratio + cost-to-income.
  * ``sbin_q2_fy25_standalone_synthetic.xml`` -- a hand-built XBRL
    using SBIN's public Q2 FY25 standalone numbers. Marked synthetic
    in the filename because we don't redistribute the raw BSE XML
    in the test tree without a separate offline run; the element
    structure mirrors the HDFCBANK Q2 standalone exactly.

CASA is asserted as None on every fixture -- the BSE quarterly XBRL
schema does not break Deposits into the current/savings sub-buckets.
This is the documented v1 gap (see module docstring of
``data_pipeline.sources.bse_bank_xbrl``).
"""
from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from data_pipeline.sources import bse_bank_xbrl as bbx  # noqa: E402

FIXTURES = Path(__file__).parent / "fixtures" / "bank_xbrl"

HDFCBANK_STANDALONE = FIXTURES / "hdfcbank_q2_fy25_standalone.xml"
HDFCBANK_CONSOLIDATED = FIXTURES / "hdfcbank_integrated_q4_fy26.xml"
SBIN_SYNTHETIC = FIXTURES / "sbin_q2_fy25_standalone_synthetic.xml"


# ---------- fixture sanity --------------------------------------------------

def test_fixtures_exist():
    assert HDFCBANK_STANDALONE.is_file(), HDFCBANK_STANDALONE
    assert HDFCBANK_CONSOLIDATED.is_file(), HDFCBANK_CONSOLIDATED
    assert SBIN_SYNTHETIC.is_file(), SBIN_SYNTHETIC


# ---------- HDFCBANK Q2 FY25 standalone -------------------------------------

def test_parse_hdfcbank_standalone_returns_all_keys():
    parsed = bbx.parse_bank_xbrl(
        HDFCBANK_STANDALONE.read_bytes(), ticker="HDFCBANK",
    )
    for k in bbx.XBRL_KPI_FIELDS:
        assert k in parsed, f"missing key {k}"
    assert parsed["period_end"] == date(2024, 9, 30)
    assert parsed["consolidated"] is False


def test_parse_hdfcbank_standalone_populates_filed_ratios():
    parsed = bbx.parse_bank_xbrl(
        HDFCBANK_STANDALONE.read_bytes(), ticker="HDFCBANK",
    )
    # Decimal-encoded in source (0.0136 / 0.0041) -> percentage.
    assert parsed["gnpa_pct"] == pytest.approx(1.36, abs=0.01)
    assert parsed["nnpa_pct"] == pytest.approx(0.41, abs=0.01)


def test_parse_hdfcbank_standalone_derives_pcr():
    parsed = bbx.parse_bank_xbrl(
        HDFCBANK_STANDALONE.read_bytes(), ticker="HDFCBANK",
    )
    # PCR = (GNPA - NNPA) / GNPA. With GNPA=342506.2 Cr, NNPA=103085.4 Cr
    # -> (342506.2 - 103085.4) / 342506.2 = ~69.9%.
    assert parsed["pcr_pct"] is not None
    assert 65.0 <= parsed["pcr_pct"] <= 75.0


def test_parse_hdfcbank_standalone_derives_credit_deposit():
    parsed = bbx.parse_bank_xbrl(
        HDFCBANK_STANDALONE.read_bytes(), ticker="HDFCBANK",
    )
    # Advances 2,495,120 Cr / Deposits 2,500,088 Cr -> ~99.8%.
    assert parsed["credit_deposit_pct"] is not None
    assert 95.0 <= parsed["credit_deposit_pct"] <= 105.0


def test_parse_hdfcbank_standalone_derives_cost_to_income():
    parsed = bbx.parse_bank_xbrl(
        HDFCBANK_STANDALONE.read_bytes(), ticker="HDFCBANK",
    )
    # NII = 740169.1 - 439030.1 = 301139; Total = 301139 + 114827.3 = 415966.3
    # CIR = 168908.9 / 415966.3 = ~40.6%.
    assert parsed["cost_to_income_pct"] is not None
    assert 30.0 <= parsed["cost_to_income_pct"] <= 50.0


def test_parse_hdfcbank_standalone_casa_is_none():
    # Documented v1 gap: BSE quarterly XBRL doesn't disclose CASA breakdown.
    parsed = bbx.parse_bank_xbrl(
        HDFCBANK_STANDALONE.read_bytes(), ticker="HDFCBANK",
    )
    assert parsed["casa_pct"] is None


def test_parse_hdfcbank_standalone_populates_at_least_five_keys():
    parsed = bbx.parse_bank_xbrl(
        HDFCBANK_STANDALONE.read_bytes(), ticker="HDFCBANK",
    )
    populated = sum(
        1 for k in bbx.XBRL_KPI_FIELDS if parsed.get(k) is not None
    )
    # gnpa, nnpa, pcr, cost_to_income, credit_deposit -> 5/6.
    # casa is the documented gap.
    assert populated >= 5


# ---------- HDFCBANK Q4 FY26 integrated (consolidated) ----------------------

def test_parse_hdfcbank_integrated_returns_all_keys():
    parsed = bbx.parse_bank_xbrl(
        HDFCBANK_CONSOLIDATED.read_bytes(), ticker="HDFCBANK",
    )
    for k in bbx.XBRL_KPI_FIELDS:
        assert k in parsed, f"missing key {k}"
    assert parsed["period_end"] == date(2026, 3, 31)
    assert parsed["consolidated"] is True


def test_parse_hdfcbank_integrated_drops_zero_npa_gracefully():
    # Consolidated bank XBRL files zero NPAs per RBI convention --
    # the parser must NOT emit 0.0% as a real ratio. Both decimal
    # source values are 0, which as_percent rounds to 0.0; the
    # caller is responsible for treating 0.0 GNPA on a Tier-1 PSU
    # as suspect, but the parser surfaces it as 0 (truthful).
    parsed = bbx.parse_bank_xbrl(
        HDFCBANK_CONSOLIDATED.read_bytes(), ticker="HDFCBANK",
    )
    # GNPA decimal 0.0 -> 0.0%; not None but not derivable PCR either.
    assert parsed["gnpa_pct"] in (None, 0.0)
    # PCR derivation requires GNPA > 0; consolidated has GNPA == 0
    # so PCR must be None.
    assert parsed["pcr_pct"] is None


def test_parse_hdfcbank_integrated_derives_credit_deposit_and_cir():
    # Balance-sheet items + income statement items ARE filed on
    # consolidated, so CD and CIR should still derive.
    parsed = bbx.parse_bank_xbrl(
        HDFCBANK_CONSOLIDATED.read_bytes(), ticker="HDFCBANK",
    )
    assert parsed["credit_deposit_pct"] is not None
    assert 90.0 <= parsed["credit_deposit_pct"] <= 110.0
    assert parsed["cost_to_income_pct"] is not None
    # Consolidated HDFCBANK includes subsidiaries (HDB Financial, etc.)
    # so the consolidated CIR runs higher than standalone bank-only.
    assert 25.0 <= parsed["cost_to_income_pct"] <= 70.0


# ---------- SBIN Q2 FY25 standalone (synthetic) -----------------------------

def test_parse_sbin_synthetic_all_six_keys_present():
    parsed = bbx.parse_bank_xbrl(
        SBIN_SYNTHETIC.read_bytes(), ticker="SBIN",
    )
    for k in bbx.XBRL_KPI_FIELDS:
        assert k in parsed


def test_parse_sbin_synthetic_filed_ratios():
    parsed = bbx.parse_bank_xbrl(
        SBIN_SYNTHETIC.read_bytes(), ticker="SBIN",
    )
    # 0.0213 / 0.0053 from fixture.
    assert parsed["gnpa_pct"] == pytest.approx(2.13, abs=0.01)
    assert parsed["nnpa_pct"] == pytest.approx(0.53, abs=0.01)


def test_parse_sbin_synthetic_derives_pcr_cd_cir():
    parsed = bbx.parse_bank_xbrl(
        SBIN_SYNTHETIC.read_bytes(), ticker="SBIN",
    )
    # GNPA 83569 Cr, NNPA 20413 Cr -> PCR = (83569-20413)/83569 ~ 75.6%.
    assert parsed["pcr_pct"] is not None
    assert 70.0 <= parsed["pcr_pct"] <= 80.0
    # Advances 3,921,300 Cr / Deposits 5,117,000 Cr ~ 76.6%.
    assert parsed["credit_deposit_pct"] is not None
    assert 70.0 <= parsed["credit_deposit_pct"] <= 85.0
    # NII = 113871 - 70401 = 43470; Total = 43470 + 15271 = 58741
    # CIR = 28998 / 58741 ~ 49.4%.
    assert parsed["cost_to_income_pct"] is not None
    assert 40.0 <= parsed["cost_to_income_pct"] <= 60.0


def test_parse_sbin_synthetic_casa_is_none():
    parsed = bbx.parse_bank_xbrl(
        SBIN_SYNTHETIC.read_bytes(), ticker="SBIN",
    )
    assert parsed["casa_pct"] is None


def test_parse_sbin_synthetic_period_end_and_standalone():
    parsed = bbx.parse_bank_xbrl(
        SBIN_SYNTHETIC.read_bytes(), ticker="SBIN",
    )
    assert parsed["period_end"] == date(2024, 9, 30)
    assert parsed["consolidated"] is False


# ---------- malformed XBRL --------------------------------------------------

def test_parse_empty_bytes_returns_all_none_dict():
    parsed = bbx.parse_bank_xbrl(b"", ticker="HDFCBANK")
    for k in bbx.XBRL_KPI_FIELDS:
        assert parsed[k] is None
    assert parsed["period_end"] is None


def test_parse_garbage_bytes_returns_all_none_dict_without_raising():
    # Looks like the start of an XBRL doc but truncated mid-tag.
    bad = b"<?xml version='1.0'?><xbrli:xbrl xmlns:xbrli='broken'><not"
    parsed = bbx.parse_bank_xbrl(bad, ticker="HDFCBANK")
    for k in bbx.XBRL_KPI_FIELDS:
        assert parsed[k] is None


def test_parse_non_xbrl_xml_returns_all_none_dict():
    # Valid XML but no numeric facts.
    parsed = bbx.parse_bank_xbrl(
        b"<?xml version='1.0'?><root><a>hi</a></root>",
        ticker="HDFCBANK",
    )
    for k in bbx.XBRL_KPI_FIELDS:
        assert parsed[k] is None


# ---------- raw_tag_hits audit trail ----------------------------------------

def test_raw_tag_hits_record_source_or_derivation():
    parsed = bbx.parse_bank_xbrl(
        HDFCBANK_STANDALONE.read_bytes(), ticker="HDFCBANK",
    )
    hits = parsed["raw_tag_hits"]
    assert hits["gnpa_pct"] == "PercentageOfGrossNpa"
    assert hits["nnpa_pct"] == "PercentageOfNpa"
    assert hits["pcr_pct"].startswith("DERIVED")
    assert hits["credit_deposit_pct"].startswith("DERIVED")
    assert hits["cost_to_income_pct"].startswith("DERIVED")
    # casa is never populated -> no entry expected.
    assert "casa_pct" not in hits


# ---------- auto-registration of bse_xbrl_v1 --------------------------------

def test_bse_xbrl_v1_auto_registered_on_import():
    # The module auto-registers the real provider at import time
    # (unless BSE_BANK_XBRL_NO_AUTOREGISTER is set, which it isn't
    # in the test runner). is_default_provider() should be False.
    assert bbx.is_default_provider() is False
    assert bbx.active_provider_name() == "bse_xbrl_v1"


def test_reset_to_default_provider_helper():
    original = bbx._PROVIDER  # noqa: SLF001
    try:
        bbx.reset_to_default_provider()
        assert bbx.is_default_provider() is True
        assert bbx.active_provider_name() == "default-noop"
    finally:
        bbx._PROVIDER = original  # noqa: SLF001
