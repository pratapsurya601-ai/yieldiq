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
    # No category header seen → category falls back to None, not raised.
    assert rows[0]["category"] is None


# Real-feed shape: the category section header is a no-';' line carrying
# the SEBI category in parentheses (e.g. "Open Ended Schemes(Equity
# Scheme - Large Cap Fund)"), with NO leading ';' or inner spaces — this
# matches the live portal.amfiindia.com/spages/NAVAll.txt format.
FIXTURE_WITH_CATEGORY = """\
Scheme Code;ISIN Div Payout/ ISIN Growth;ISIN Div Reinvestment;Scheme Name;Net Asset Value;Date

Open Ended Schemes(Equity Scheme - Large Cap Fund)

Aditya Birla Sun Life Mutual Fund

100033;INF209K01157;INF209K01165;Aditya Birla Sun Life Frontline Equity Fund - Direct Plan - Growth;485.7234;27-May-2026

Open Ended Schemes(Debt Scheme - Liquid Fund)

HDFC Mutual Fund

118989;INF179K01YV8;INF179K01YW6;HDFC Liquid Fund - Regular Plan - Growth;4800.1234;27-May-2026
"""


def test_iter_scheme_master_rows_captures_category() -> None:
    # The category header precedes the AMC banner(s) it applies to and
    # must be carried forward onto each scheme row, and re-set when a new
    # category header appears.
    rows = list(iter_scheme_master_rows(FIXTURE_WITH_CATEGORY))
    assert len(rows) == 2
    equity, debt = rows
    assert equity["category"] == "Equity Scheme - Large Cap Fund"
    assert equity["amc"] == "Aditya Birla Sun Life Mutual Fund"
    assert debt["category"] == "Debt Scheme - Liquid Fund"
    assert debt["amc"] == "HDFC Mutual Fund"


# ── upsert_funds — batched via execute_values ────────────────────────


def test_dedupe_last_by_scheme_code_keeps_last() -> None:
    from data_pipeline.sources.amfi_scheme_master import (
        _dedupe_last_by_scheme_code,
    )

    rows = [
        {"scheme_code": "100", "amc": "A"},
        {"scheme_code": "200", "amc": "B"},
        {"scheme_code": "100", "amc": "A2"},  # dup of 100 — last wins
    ]
    out = _dedupe_last_by_scheme_code(rows)
    assert len(out) == 2
    by_code = {r["scheme_code"]: r for r in out}
    assert by_code["100"]["amc"] == "A2"
    assert by_code["200"]["amc"] == "B"


def test_upsert_funds_batches_and_dedupes(monkeypatch) -> None:
    # upsert_funds must (a) dedupe by scheme_code and (b) hand the rows to
    # psycopg2.extras.execute_values in a single batched call — NOT the
    # per-row executemany that blew the workflow timeout.
    extras = pytest.importorskip("psycopg2.extras")

    captured: dict = {}

    def fake_execute_values(cur, sql, argslist, template=None, page_size=100):
        captured["sql"] = sql
        captured["rows"] = list(argslist)
        captured["template"] = template

    monkeypatch.setattr(extras, "execute_values", fake_execute_values)

    class FakeCursor:
        def __init__(self) -> None:
            self.rowcount = 0
            self.executed: list = []

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def execute(self, sql, params=None):
            self.executed.append((sql, params))

        def executemany(self, sql, seq):  # pragma: no cover - must not run
            raise AssertionError("executemany must not be used (un-batched)")

    class FakeConn:
        def __init__(self) -> None:
            self.cur = FakeCursor()
            self.committed = False

        def cursor(self):
            return self.cur

        def commit(self):
            self.committed = True

    from data_pipeline.sources.amfi_scheme_master import upsert_funds

    base = {
        "isin_growth": "X", "isin_div": "Y", "amc": "A",
        "category": "Equity", "plan": "Direct", "option": "Growth",
    }
    rows = [
        {**base, "scheme_code": "100", "scheme_name": "A - Direct - Growth"},
        {**base, "scheme_code": "100", "scheme_name": "A duplicate"},  # dup
        {**base, "scheme_code": "200", "scheme_name": "B - Direct - Growth"},
    ]
    conn = FakeConn()
    n_up, n_off = upsert_funds(rows, conn)

    assert n_up == 2  # 3 rows deduped to 2
    assert len(captured["rows"]) == 2
    assert "VALUES %s" in captured["sql"]
    assert captured["template"] is not None
    # The soft-deactivate UPDATE still runs after the batched insert.
    assert len(conn.cur.executed) == 1
    assert conn.committed is True
