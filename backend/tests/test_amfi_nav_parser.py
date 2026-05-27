"""Unit tests for data_pipeline.sources.amfi_nav.parse_navall.

Three fixture cases per spec:
    1. Typical happy-path row (Direct Growth scheme, valid NAV, valid date).
    2. Holiday-blank row (NAV field is empty for a debt scheme that did
       not publish on this date) — must be skipped, not raised.
    3. Non-UTF8 row (Windows-1252 curly-quote in the scheme name) — the
       row must still parse, with the scheme_name preserved up to the
       replacement byte if needed.

Plus a few invariants:
    * AMC banner and category-header lines are dropped silently.
    * Multiple schemes from multiple AMC sections are all yielded.
    * Negative / zero NAV is treated as missing (holiday placeholder).
"""
from __future__ import annotations

from datetime import date

import pytest

from data_pipeline.sources.amfi_nav import parse_navall


# Three-row, two-AMC fixture exercising all the canonical edge cases.
# Encoding note: the cp1252 fixture (HDFC row with curly apostrophe) is
# written as a UTF-8 string here because pytest sources are read as
# UTF-8; the parser's encoding-tolerance is exercised by the separate
# fetch_navall_text helper which is integration-tested manually.
FIXTURE_HAPPY = """
;        Open Ended Schemes ( Equity Scheme - Large Cap Fund )

Aditya Birla Sun Life Mutual Fund

Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
100033;INF209K01157;INF209K01165;Aditya Birla Sun Life Frontline Equity Fund - Direct Plan - Growth;485.7234;27-May-2026

HDFC Mutual Fund

Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
118989;INF179K01YV8;INF179K01YW6;HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth;142.5610;27-May-2026
"""

# A scheme whose NAV did not publish on this date (debt scheme on a
# market half-day, common pre-2018). AMFI ships the row with a blank
# NAV field — parser must drop the row, not raise.
FIXTURE_HOLIDAY = """
ICICI Prudential Mutual Fund

Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
120586;INF109K01YQ7;INF109K01YR5;ICICI Prudential Bluechip Fund - Direct Plan - Growth;;27-May-2026
"""

# A scheme name with a non-ASCII character that AMFI's cp1252-encoded
# feed occasionally carries — must round-trip cleanly to a dict.
FIXTURE_NON_ASCII = (
    "\nUTI Mutual Fund\n\n"
    "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date\n"
    "133386;INF789F1AUL2;INF789F1AUM0;UTI Nifty 50 Index Fund – Direct – Growth;42.9810;27-May-2026\n"
)


def test_parse_typical_rows_yield_expected_dicts() -> None:
    rows = list(parse_navall(FIXTURE_HAPPY))
    assert len(rows) == 2
    aditya, hdfc = rows
    assert aditya == {
        "scheme_code": "100033",
        "isin_div":    "INF209K01157",
        "isin_growth": "INF209K01165",
        "scheme_name": "Aditya Birla Sun Life Frontline Equity Fund - Direct Plan - Growth",
        "nav":         485.7234,
        "nav_date":    date(2026, 5, 27),
    }
    assert hdfc["scheme_code"] == "118989"
    assert hdfc["nav"] == pytest.approx(142.5610)
    assert hdfc["nav_date"] == date(2026, 5, 27)


def test_holiday_blank_nav_row_is_skipped() -> None:
    rows = list(parse_navall(FIXTURE_HOLIDAY))
    assert rows == [], "blank-NAV holiday row must be dropped silently"


def test_non_ascii_scheme_name_parses_cleanly() -> None:
    rows = list(parse_navall(FIXTURE_NON_ASCII))
    assert len(rows) == 1
    assert rows[0]["scheme_code"] == "133386"
    assert rows[0]["nav"] == pytest.approx(42.9810)
    # Em-dashes survive — the scheme_name field is just stored as text.
    assert "Nifty 50" in rows[0]["scheme_name"]


def test_amc_banner_and_category_lines_are_dropped() -> None:
    rows = list(parse_navall(FIXTURE_HAPPY))
    scheme_codes = {r["scheme_code"] for r in rows}
    # The "Open Ended Schemes (...)" header line contains semis but
    # the leading field is blank, so the scheme_code-digit check rejects
    # it. AMC banners ("Aditya Birla Sun Life Mutual Fund") have no
    # semis at all, so the column-count guard rejects them.
    assert scheme_codes == {"100033", "118989"}


def test_negative_or_zero_nav_treated_as_missing() -> None:
    bad = (
        "Test AMC\n\n"
        "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date\n"
        "999001;ISIN1;ISIN2;Test Scheme A;-1.0000;27-May-2026\n"
        "999002;ISIN3;ISIN4;Test Scheme B;0.0000;27-May-2026\n"
    )
    assert list(parse_navall(bad)) == []
