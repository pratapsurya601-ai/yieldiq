"""Unit tests for backend/services/related_party_service.py.

Drives the service from a JSON fixture (tests/fixtures/sample_rpts.json)
so we don't need a Postgres instance. The service exposes a ``fetcher``
injection point exactly for this purpose.

Coverage:
  * get_rpts_for_year — basic query + ordering invariance.
  * summarize_rpts    — totals_by_txn_type, intra-promoter, large-txn.
  * detect_red_flags  — each rule fires on the intended exemplar (ADANIENT,
                        RELIANCE-royalty) and stays silent on TCS / INFY.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from backend.services.related_party_service import (  # noqa: E402
    RedFlagContext,
    detect_red_flags,
    get_rpts_for_year,
    summarize_rpts,
    extract_rpts_from_pdf_with_llm,
)


# ---------------------------------------------------------------------------
# Fixture loader — single source of truth for both fetcher + context.
# ---------------------------------------------------------------------------

FIXTURE_PATH = ROOT / "tests" / "fixtures" / "sample_rpts.json"


@pytest.fixture(scope="module")
def fixture_blob():
    with open(FIXTURE_PATH, encoding="utf-8") as fh:
        return json.load(fh)


@pytest.fixture
def fetcher(fixture_blob):
    rows = fixture_blob["rows"]

    def _fetch(ticker: str, fiscal_year: int):
        return [
            r for r in rows
            if r["ticker"] == ticker and r["fiscal_year"] == fiscal_year
        ]

    return _fetch


def _ctx_for(fixture_blob, ticker: str, **overrides) -> RedFlagContext:
    raw = fixture_blob["_context"].get(ticker, {})
    return RedFlagContext(
        net_worth_inr=raw.get("net_worth_inr"),
        revenue_inr=raw.get("revenue_inr"),
        book_value_lookup=raw.get("book_value_lookup", {}),
        prior_year_total_inr=overrides.get("prior_year_total_inr"),
    )


# ---------------------------------------------------------------------------
# get_rpts_for_year
# ---------------------------------------------------------------------------

def test_get_rpts_returns_only_requested_year(fetcher):
    rows = get_rpts_for_year("RELIANCE", 2025, fetcher=fetcher)
    assert len(rows) == 3
    assert all(r.fiscal_year == 2025 for r in rows)
    assert all(r.ticker == "RELIANCE" for r in rows)


def test_get_rpts_empty_when_unknown(fetcher):
    assert get_rpts_for_year("UNKNOWN", 2025, fetcher=fetcher) == []


# ---------------------------------------------------------------------------
# summarize_rpts
# ---------------------------------------------------------------------------

def test_summarize_totals_by_txn_type(fixture_blob, fetcher):
    rev = fixture_blob["_context"]["RELIANCE"]["revenue_inr"]
    s = summarize_rpts("RELIANCE", 2025, fetcher=fetcher, revenue_inr=rev)
    assert s["total_count"] == 3
    assert s["totals_by_txn_type"]["royalty"] == 220_000_000_000
    assert s["totals_by_txn_type"]["loan_given"] == 25_000_000_000
    # Royalty (220B) is > 1% of 9000B revenue (= 90B) so it surfaces as large.
    large_txn_types = {r["txn_type"] for r in s["large_transactions"]}
    assert "royalty" in large_txn_types


def test_summarize_intra_promoter_rows_for_adani(fixture_blob, fetcher):
    s = summarize_rpts("ADANIENT", 2025, fetcher=fetcher)
    promoter_names = {r["related_party_name"] for r in s["intra_promoter_rows"]}
    assert "Adani Infra LLP" in promoter_names
    assert s["non_arms_length_count"] >= 2  # two rows have is_arms_length=false


def test_summarize_clean_for_tcs(fetcher):
    s = summarize_rpts("TCS", 2025, fetcher=fetcher)
    assert s["non_arms_length_count"] == 0
    assert s["intra_promoter_rows"] == []


# ---------------------------------------------------------------------------
# detect_red_flags — positive cases.
# ---------------------------------------------------------------------------

def test_adani_fires_loan_to_promoter_flag(fixture_blob, fetcher):
    ctx = _ctx_for(fixture_blob, "ADANIENT")
    flags = detect_red_flags("ADANIENT", 2025, fetcher=fetcher, context=ctx)
    codes = {f.code for f in flags}
    assert "RPT_LOAN_TO_PROMOTER" in codes


def test_adani_fires_asset_sale_below_book_flag(fixture_blob, fetcher):
    ctx = _ctx_for(fixture_blob, "ADANIENT")
    flags = detect_red_flags("ADANIENT", 2025, fetcher=fetcher, context=ctx)
    codes = {f.code for f in flags}
    assert "RPT_ASSET_SALE_BELOW_BOOK" in codes


def test_adani_fires_vague_consultancy_flag(fixture_blob, fetcher):
    ctx = _ctx_for(fixture_blob, "ADANIENT")
    flags = detect_red_flags("ADANIENT", 2025, fetcher=fetcher, context=ctx)
    codes = {f.code for f in flags}
    assert "RPT_VAGUE_CONSULTANCY" in codes


def test_adani_fires_balance_spike_yoy(fixture_blob, fetcher):
    # Compute prior-year (FY2024) total from the fixture and pass as context.
    py_rows = fetcher("ADANIENT", 2024)
    py_total = sum((r.get("amount_inr") or 0) for r in py_rows)
    ctx = _ctx_for(fixture_blob, "ADANIENT", prior_year_total_inr=py_total)
    flags = detect_red_flags("ADANIENT", 2025, fetcher=fetcher, context=ctx)
    codes = {f.code for f in flags}
    assert "RPT_BALANCE_SPIKE" in codes


def test_reliance_fires_royalty_flag(fixture_blob, fetcher):
    ctx = _ctx_for(fixture_blob, "RELIANCE")
    flags = detect_red_flags("RELIANCE", 2025, fetcher=fetcher, context=ctx)
    codes = {f.code for f in flags}
    assert "RPT_ROYALTY_HEAVY" in codes


# ---------------------------------------------------------------------------
# detect_red_flags — negative-control cases.
# ---------------------------------------------------------------------------

def test_tcs_fires_no_flags(fixture_blob, fetcher):
    ctx = _ctx_for(fixture_blob, "TCS")
    flags = detect_red_flags("TCS", 2025, fetcher=fetcher, context=ctx)
    assert flags == []


def test_infy_fires_no_flags(fixture_blob, fetcher):
    ctx = _ctx_for(fixture_blob, "INFY")
    flags = detect_red_flags("INFY", 2025, fetcher=fetcher, context=ctx)
    assert flags == []


def test_red_flags_silent_when_context_missing(fetcher):
    # Without a denominator (net worth / revenue / book value / prior year)
    # the rules that need it must NOT fire false positives.
    flags = detect_red_flags("ADANIENT", 2025, fetcher=fetcher, context=None)
    codes = {f.code for f in flags}
    assert "RPT_LOAN_TO_PROMOTER" not in codes
    assert "RPT_ROYALTY_HEAVY" not in codes
    assert "RPT_ASSET_SALE_BELOW_BOOK" not in codes
    assert "RPT_BALANCE_SPIKE" not in codes
    # The vague-consultancy rule does not need context, so it can still fire.


# ---------------------------------------------------------------------------
# LLM extraction stub
# ---------------------------------------------------------------------------

def test_llm_extraction_is_not_implemented():
    with pytest.raises(NotImplementedError):
        extract_rpts_from_pdf_with_llm("https://example.com/ar.pdf", "RELIANCE")
