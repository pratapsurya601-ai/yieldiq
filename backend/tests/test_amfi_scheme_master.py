"""Unit tests for data_pipeline.sources.amfi_scheme_master.

Two surfaces under test:

    1. parse_plan_option(name) → (plan, option) heuristic — covers the
       common AMFI scheme-name formats and the regulatory defaults
       (Regular when "Direct" is absent; Growth when no payout token).

    2. iter_scheme_master_rows(text) — confirms AMC banner tracking
       works across multiple sections of a NAVAll dump.
"""
from __future__ import annotations

import pytest

from data_pipeline.sources.amfi_scheme_master import (
    iter_scheme_master_rows,
    parse_plan_option,
)


# ── parse_plan_option ────────────────────────────────────────────────


@pytest.mark.parametrize(
    "name,expected",
    [
        # Direct / Growth — the canonical Phase-1-canary shape.
        (
            "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth",
            ("Direct", "Growth"),
        ),
        # Regular / Growth — "Regular" word explicit.
        (
            "Axis Bluechip Fund - Regular Plan - Growth",
            ("Regular", "Growth"),
        ),
        # Implicit Regular (no "Direct" anywhere) — SEBI 2018 default.
        (
            "Nippon India Small Cap Fund - Growth Plan",
            ("Regular", "Growth"),
        ),
        # IDCW payout with Direct plan.
        (
            "ICICI Prudential Bluechip Fund - Direct Plan (IDCW)",
            ("Direct", "IDCW"),
        ),
        # IDCW reinvestment must beat plain IDCW match.
        (
            "SBI Magnum Multicap Fund - Direct - IDCW Reinvestment",
            ("Direct", "IDCW-Reinvest"),
        ),
        # Hyphen-joined IDCW-Reinvest.
        (
            "Kotak Flexicap Fund - Direct Plan - IDCW-Reinvest",
            ("Direct", "IDCW-Reinvest"),
        ),
        # Legacy "Dividend" wording (pre-2021 rename) still routes to IDCW.
        (
            "Franklin India Equity Fund - Regular Plan - Dividend",
            ("Regular", "IDCW"),
        ),
        # No "Plan" word at all — common in newer naming.
        (
            "Mirae Asset Large Cap Fund Direct Growth",
            ("Direct", "Growth"),
        ),
        # Empty / whitespace input — defaults safely.
        ("", ("Regular", "Growth")),
        ("   ", ("Regular", "Growth")),
    ],
)
def test_parse_plan_option(name: str, expected: tuple[str, str]) -> None:
    assert parse_plan_option(name) == expected


def test_parse_plan_option_prefers_reinvest_over_plain_idcw() -> None:
    # Defensive: the literal "IDCW" appears in both target classes; the
    # reinvest regex must run first. Regression guard against a future
    # refactor that flips the order.
    plan, option = parse_plan_option(
        "Sample Fund - Direct - IDCW Reinvestment"
    )
    assert option == "IDCW-Reinvest"
    assert plan == "Direct"


# ── iter_scheme_master_rows ──────────────────────────────────────────


FIXTURE_TWO_AMCS = """
;        Open Ended Schemes ( Equity Scheme - Large Cap Fund )

Aditya Birla Sun Life Mutual Fund

Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
100033;INF209K01157;INF209K01165;Aditya Birla Sun Life Frontline Equity Fund - Direct Plan - Growth;485.7234;27-May-2026

HDFC Mutual Fund

Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date
118989;INF179K01YV8;INF179K01YW6;HDFC Mid-Cap Opportunities Fund - Regular Plan - IDCW;142.5610;27-May-2026
"""


def test_iter_scheme_master_rows_tracks_amc_banner() -> None:
    rows = list(iter_scheme_master_rows(FIXTURE_TWO_AMCS))
    assert len(rows) == 2
    aditya, hdfc = rows
    assert aditya["amc"] == "Aditya Birla Sun Life Mutual Fund"
    assert aditya["plan"] == "Direct"
    assert aditya["option"] == "Growth"
    assert aditya["scheme_code"] == "100033"
    assert hdfc["amc"] == "HDFC Mutual Fund"
    assert hdfc["plan"] == "Regular"
    assert hdfc["option"] == "IDCW"
    assert hdfc["scheme_code"] == "118989"


def test_iter_scheme_master_rows_handles_missing_banner() -> None:
    # If the NAVAll dump opens with a scheme row before any AMC banner
    # (unlikely but possible on a malformed feed), amc falls back to
    # "Unknown" rather than raising.
    rogue = (
        "Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date\n"
        "999999;ISINA;ISINB;Test Scheme - Direct Plan - Growth;100.0000;27-May-2026\n"
    )
    rows = list(iter_scheme_master_rows(rogue))
    assert len(rows) == 1
    assert rows[0]["amc"] == "Unknown"
