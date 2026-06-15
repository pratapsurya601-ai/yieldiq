# data_pipeline/tests/test_nse_xbrl_interim_period_type.py
"""
Tests for the NSE-XBRL interim period-type fix.

Bug: NSE's "Annual" endpoint also serves H1 (Sep-30, ~182d) and 9-month
(Dec-31, ~275d) CUMULATIVE filings, not just the March full-year. The
ingester defaulted every Annual-endpoint filing to period_type='annual',
and `_detect_period_type_from_contexts` only resolved 300+ day (annual)
and 60-120 day (quarterly) spans — H1/9M fell in an unhandled
121-299-day dead zone and returned None, so the wrong 'annual' default
stuck. Interim cumulative rows then entered the DCF's
WHERE period_type='annual' query as if they were full fiscal years,
cratering fair value (RELIANCE FV ₹471 vs ~₹1,535).

Fix invariant under test: a row whose reporting period is < ~300 days
must NEVER be classified or persisted as period_type='annual'.

No network — XBRL bytes and context dicts are inlined.
"""
from __future__ import annotations

from datetime import date, timedelta

import pytest

from data_pipeline.sources.nse_xbrl_fundamentals import (
    _ANNUAL_MIN_DAYS,
    _INTERIM_MIN_DAYS,
    _best_duration_for_period_end,
    _detect_period_type_from_contexts,
    _extract_contexts,
    parse_nse_xbrl,
)


_PERIOD_END = date(2024, 3, 31)


def _contexts_with_span(days: int, period_end: date = _PERIOD_END,
                        cid: str = "D_PERIOD") -> dict[str, dict[str, str]]:
    """Build a single-duration-context map ending on period_end with an
    exact span of `days`."""
    start = period_end - timedelta(days=days)
    return {
        cid: {"start": start.isoformat(), "end": period_end.isoformat()},
    }


# ── _detect_period_type_from_contexts band coverage ─────────────────


@pytest.mark.parametrize(
    "days,expected",
    [
        (365, "annual"),      # full fiscal year
        (366, "annual"),      # leap-ish full year
        (300, "annual"),      # exact annual lower bound
        (299, "interim"),     # was dead-zone -> None, now interim
        (275, "interim"),     # 9-month cumulative (Dec-31 filing)
        (182, "interim"),     # H1 cumulative (Sep-30 filing)
        (150, "interim"),     # exact interim lower bound
        (149, None),          # below interim band, above quarterly -> None
        (121, None),          # old dead-zone boundary, between bands -> None
        (120, "quarterly"),   # quarterly upper bound
        (91, "quarterly"),    # standard quarter
        (60, "quarterly"),    # quarterly lower bound
        (59, None),           # below quarterly band
        (30, None),           # too short to classify
    ],
)
def test_detect_period_type_bands(days, expected):
    contexts = _contexts_with_span(days)
    assert _detect_period_type_from_contexts(contexts, _PERIOD_END) == expected


def test_dead_zone_boundaries_no_longer_return_none_when_interim():
    """The 121-299 day dead zone that used to return None now resolves
    to 'interim' for the H1/9M sub-band [150, 300)."""
    for days in (150, 182, 200, 275, 299):
        contexts = _contexts_with_span(days)
        result = _detect_period_type_from_contexts(contexts, _PERIOD_END)
        assert result == "interim", (
            f"{days}d should be 'interim', got {result!r}"
        )
        assert result != "annual", f"{days}d must NEVER be 'annual'"


def test_no_matching_end_date_returns_none():
    contexts = _contexts_with_span(365, period_end=_PERIOD_END)
    # Ask about a period_end that no context ends on.
    assert _detect_period_type_from_contexts(contexts, date(2020, 3, 31)) is None


def test_best_duration_picks_longest_span():
    """When OneD (quarter) and FourD (full-year) contexts coexist, the
    longest span wins — that is the reporting period the row represents."""
    pe = _PERIOD_END
    contexts = {
        "OneD": {"start": (pe - timedelta(days=90)).isoformat(),
                 "end": pe.isoformat()},
        "FourD": {"start": (pe - timedelta(days=365)).isoformat(),
                  "end": pe.isoformat()},
    }
    best_days, best_start = _best_duration_for_period_end(contexts, pe)
    assert best_days == 365
    assert best_start == pe - timedelta(days=365)


# ── "Four"-prefix shortcut must not over-promote interim filings ─────


def test_four_prefix_full_year_promotes_to_annual():
    """A Four-prefixed context spanning a full FY legitimately -> annual
    (the OneD/FourD Q4 rescue)."""
    pe = _PERIOD_END
    contexts = {
        # OneD covers only Q4; FourD covers the full FY ending on pe.
        "OneD": {"start": (pe - timedelta(days=90)).isoformat(),
                 "end": pe.isoformat()},
        "FourD": {"start": (pe - timedelta(days=365)).isoformat(),
                  "end": pe.isoformat()},
    }
    assert _detect_period_type_from_contexts(contexts, pe) == "annual"


def test_four_prefix_nine_month_does_not_promote_to_annual():
    """A Four-prefixed (cumulative) context that only spans 9 months on a
    Dec-31 filing must NOT be promoted to 'annual'."""
    dec_end = date(2023, 12, 31)
    contexts = {
        # FourD here is a 9-month YTD cumulative, NOT a full year.
        "FourD": {"start": date(2023, 4, 1).isoformat(),
                  "end": dec_end.isoformat()},
        # OneD is the Oct-Dec quarter.
        "OneD": {"start": date(2023, 10, 1).isoformat(),
                 "end": dec_end.isoformat()},
    }
    result = _detect_period_type_from_contexts(contexts, dec_end)
    assert result != "annual", "9-month FourD must not force 'annual'"
    assert result == "interim"


def test_four_prefix_half_year_does_not_promote_to_annual():
    sep_end = date(2023, 9, 30)
    contexts = {
        "FourD": {"start": date(2023, 4, 1).isoformat(),
                  "end": sep_end.isoformat()},
    }
    result = _detect_period_type_from_contexts(contexts, sep_end)
    assert result != "annual"
    assert result == "interim"


# ── Parse-level: H1 / 9M filing from the Annual endpoint ────────────
#
# Models an interim cumulative filing (Dec-31, 9-month span) that NSE
# served under the "Annual" endpoint, so parse_nse_xbrl is called with
# the endpoint hint period_type="annual". The context duration (275d)
# must override that to a non-annual type.
_NINE_MONTH_FROM_ANNUAL_ENDPOINT = (
    b"""<?xml version="1.0" encoding="UTF-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:in-bse-fin="https://www.bseindia.com/xbrl/fin">
  <context id="FourD_9M">
    <period>
      <startDate>2023-04-01</startDate>
      <endDate>2023-12-31</endDate>
    </period>
  </context>
  <context id="I_9M">
    <period>
      <instant>2023-12-31</instant>
    </period>
  </context>
  <in-bse-fin:RevenueFromOperations contextRef="FourD_9M" unitRef="INR" decimals="0">5400000000000</in-bse-fin:RevenueFromOperations>
  <in-bse-fin:ProfitBeforeTax contextRef="FourD_9M" unitRef="INR" decimals="0">600000000000</in-bse-fin:ProfitBeforeTax>
  <in-bse-fin:ProfitLossForPeriod contextRef="FourD_9M" unitRef="INR" decimals="0">450000000000</in-bse-fin:ProfitLossForPeriod>
  <in-bse-fin:Assets contextRef="I_9M" unitRef="INR" decimals="0">9000000000000</in-bse-fin:Assets>
  <in-bse-fin:Equity contextRef="I_9M" unitRef="INR" decimals="0">4000000000000</in-bse-fin:Equity>
</xbrl>
"""
)


def test_nine_month_filing_from_annual_endpoint_not_marked_annual():
    dec_end = date(2023, 12, 31)
    # Sanity: the duration context resolves to interim.
    contexts = _extract_contexts(_NINE_MONTH_FROM_ANNUAL_ENDPOINT)
    assert _detect_period_type_from_contexts(contexts, dec_end) == "interim"

    # Endpoint hint says "annual" (it came off the Annual endpoint), but
    # the parsed row must NOT carry period_type='annual'.
    row = parse_nse_xbrl(
        _NINE_MONTH_FROM_ANNUAL_ENDPOINT, ticker="RELIANCE",
        period_end=dec_end, period_type="annual",
    )
    assert row is not None
    assert row["period_type"] != "annual", (
        "9-month interim filing pulled from the Annual endpoint must "
        "never be persisted as period_type='annual'"
    )
    assert row["period_type"] == "interim"


def test_interim_row_carries_period_days_and_start_in_raw_payload():
    dec_end = date(2023, 12, 31)
    row = parse_nse_xbrl(
        _NINE_MONTH_FROM_ANNUAL_ENDPOINT, ticker="RELIANCE",
        period_end=dec_end, period_type="annual",
    )
    assert row is not None
    raw = row.get("raw")
    assert isinstance(raw, dict), "expected an audit payload under 'raw'"
    # Apr-01 .. Dec-31 = 274 days.
    assert raw["period_days"] == 274
    assert raw["period_start"] == "2023-04-01"
    assert raw["period_end"] == "2023-12-31"
    assert raw["period_type"] == "interim"
    # And the span sits inside the interim band, below annual.
    assert _INTERIM_MIN_DAYS <= raw["period_days"] < _ANNUAL_MIN_DAYS


# ── Parse-level: a true full-year filing still resolves to annual ───
_FULL_YEAR_XBRL = (
    b"""<?xml version="1.0" encoding="UTF-8"?>
<xbrl xmlns="http://www.xbrl.org/2003/instance"
      xmlns:in-bse-fin="https://www.bseindia.com/xbrl/fin">
  <context id="FourD_FY">
    <period>
      <startDate>2023-04-01</startDate>
      <endDate>2024-03-31</endDate>
    </period>
  </context>
  <in-bse-fin:RevenueFromOperations contextRef="FourD_FY" unitRef="INR" decimals="0">7000000000000</in-bse-fin:RevenueFromOperations>
  <in-bse-fin:ProfitLossForPeriod contextRef="FourD_FY" unitRef="INR" decimals="0">650000000000</in-bse-fin:ProfitLossForPeriod>
</xbrl>
"""
)


def test_full_year_filing_still_marked_annual_with_period_days():
    row = parse_nse_xbrl(
        _FULL_YEAR_XBRL, ticker="RELIANCE", period_end=_PERIOD_END,
        period_type="annual",
    )
    assert row is not None
    assert row["period_type"] == "annual"
    raw = row.get("raw")
    assert isinstance(raw, dict)
    assert raw["period_days"] >= _ANNUAL_MIN_DAYS
    assert raw["period_type"] == "annual"
