"""
Tests for backend/services/quarterly_results_service.py — the NSE
XBRL quarterly P&L reader that feeds TTM revenue + net profit into
the analysis service for the 41 NIFTY-50 tickers in
`company_quarterly_results`.

Hermetic: the DB session is mocked, nothing touches Neon.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch


def _row(period_end: date, revenue_cr: float, net_profit_cr: float,
         employee_cr: float = 100.0, depreciation_cr: float = 50.0,
         is_consolidated: bool = True) -> dict:
    return {
        "ticker": "INFY",
        "fiscal_quarter": "Q? FY??",  # deliberately bogus — service must not read it
        "period_start": period_end.replace(day=1),
        "period_end": period_end,
        "is_consolidated": is_consolidated,
        "is_audited": True,
        "is_single_segment": False,
        "revenue_cr": revenue_cr,
        "other_income_cr": 0.0,
        "total_expenses_cr": 0.0,
        "profit_before_tax_cr": 0.0,
        "tax_expense_cr": 0.0,
        "net_profit_cr": net_profit_cr,
        "comprehensive_income_cr": 0.0,
        "employee_benefit_cr": employee_cr,
        "finance_costs_cr": 0.0,
        "depreciation_cr": depreciation_cr,
        "other_expenses_cr": 0.0,
        "basic_eps": 0.0, "diluted_eps": 0.0, "face_value": 5.0,
        "paid_up_capital_cr": 0.0,
        "xbrl_url": "https://example/x.xml",
        "filed_at": None,
        "ingested_at": None,
    }


def _mock_session(rows_by_consolidated: dict[bool, list[dict]]):
    """Build a MagicMock session whose execute().mappings().all()
    returns the rows we stage, keyed by the `c` (is_consolidated)
    parameter the service binds in its query."""
    session = MagicMock()

    def _execute(stmt, params):
        c = params.get("c", True)
        n = params.get("n", 4)
        rows = rows_by_consolidated.get(c, [])[:n]
        result = MagicMock()
        result.mappings.return_value.all.return_value = rows
        return result

    session.execute.side_effect = _execute
    return session


def test_compute_ttm_sums_four_quarters():
    """Happy path: 4 consolidated quarters → TTM = sum, partial=False."""
    from backend.services import quarterly_results_service as qrs

    rows = [
        _row(date(2024, 12, 31), 41764.0, 6822.0),
        _row(date(2024, 9, 30),  40986.0, 6516.0),
        _row(date(2024, 6, 30),  39315.0, 6374.0),
        _row(date(2024, 3, 31),  37923.0, 7969.0),
    ]
    session = _mock_session({True: rows})

    with patch.object(qrs, "_get_pipeline_session", return_value=session):
        ttm = qrs.compute_ttm_from_xbrl("INFY.NS")

    assert ttm is not None
    assert ttm["partial"] is False
    assert ttm["quarters_used"] == 4
    assert ttm["source"] == "nse_xbrl"
    assert ttm["period_end"] == "2024-12-31"
    # 41764 + 40986 + 39315 + 37923 = 159988 Cr → 1.59988e12 INR
    assert ttm["revenue_ttm"] == (41764.0 + 40986.0 + 39315.0 + 37923.0) * 1e7
    assert ttm["net_profit_ttm"] == (6822.0 + 6516.0 + 6374.0 + 7969.0) * 1e7


def test_compute_ttm_partial_when_fewer_than_four_quarters():
    """2 quarters available → partial=True, sum of what we have."""
    from backend.services import quarterly_results_service as qrs

    rows = [
        _row(date(2024, 12, 31), 41764.0, 6822.0),
        _row(date(2024, 9, 30),  40986.0, 6516.0),
    ]
    session = _mock_session({True: rows})

    with patch.object(qrs, "_get_pipeline_session", return_value=session):
        ttm = qrs.compute_ttm_from_xbrl("INFY.NS")

    assert ttm is not None
    assert ttm["partial"] is True
    assert ttm["quarters_used"] == 2
    assert ttm["revenue_ttm"] == (41764.0 + 40986.0) * 1e7


def test_compute_ttm_returns_none_when_no_rows():
    """Ticker not in the 41 → None (caller falls back to yfinance)."""
    from backend.services import quarterly_results_service as qrs

    session = _mock_session({True: [], False: []})

    with patch.object(qrs, "_get_pipeline_session", return_value=session):
        ttm = qrs.compute_ttm_from_xbrl("ADANIPOWER.NS")

    assert ttm is None


def test_get_quarterly_results_falls_back_to_standalone():
    """Single-entity company with only standalone filings → returns those."""
    from backend.services import quarterly_results_service as qrs

    standalone_rows = [
        _row(date(2024, 12, 31), 100.0, 10.0, is_consolidated=False),
    ]
    session = _mock_session({True: [], False: standalone_rows})

    with patch.object(qrs, "_get_pipeline_session", return_value=session):
        out = qrs.get_quarterly_results("FOO.NS", n_quarters=4, consolidated=True)

    assert out is not None
    assert len(out) == 1
    assert out[0]["is_consolidated"] is False


def test_compute_ttm_returns_none_when_db_unavailable():
    """DB session is None (cooldown) → service returns None gracefully."""
    from backend.services import quarterly_results_service as qrs

    with patch.object(qrs, "_get_pipeline_session", return_value=None):
        assert qrs.compute_ttm_from_xbrl("INFY.NS") is None


def test_scale_guard_skips_nestleind_style_poisoned_rows():
    """NESTLEIND fixture: 4 clean rows (~6,747 Cr) + 2 corrupt rows
    (revenue_cr = 4.78e9). Guard must skip the corrupt rows; TTM
    sums only the clean ones.
    """
    from backend.services import quarterly_results_service as qrs

    # 8-row window (compute_ttm now fetches 8 for the median context):
    #   - 6 clean rows at ~6,747 Cr
    #   - 2 poisoned rows at 4.78e9 Cr (NESTLEIND audit case)
    rows = [
        _row(date(2025, 12, 31), 6747.0, 850.0),  # clean (latest)
        _row(date(2025, 9, 30),  6800.0, 870.0),  # clean
        _row(date(2025, 6, 30),  4.78e9, 880.0),  # POISONED
        _row(date(2025, 3, 31),  6650.0, 800.0),  # clean
        _row(date(2024, 12, 31), 4.78e9, 820.0),  # POISONED
        _row(date(2024, 9, 30),  6500.0, 810.0),  # clean
        _row(date(2024, 6, 30),  6400.0, 790.0),  # clean
        _row(date(2024, 3, 31),  6300.0, 780.0),  # clean
    ]
    session = _mock_session({True: rows})
    with patch.object(qrs, "_get_pipeline_session", return_value=session):
        ttm = qrs.compute_ttm_from_xbrl("NESTLEIND.NS")

    assert ttm is not None
    assert "scale_outlier_skipped" in ttm["data_issues"]
    # 2 rows skipped (the 4.78e9 ones) -- check they are logged.
    assert len(ttm["scale_skipped"]) == 2
    for skip in ttm["scale_skipped"]:
        assert skip["field"] == "revenue_cr"
        assert skip["reason"] == "scale_outlier_skipped"
    # Latest 4 clean rows are: Dec'25, Sep'25, Mar'25, Sep'24
    # (Jun'25 and Dec'24 skipped).
    expected = (6747.0 + 6800.0 + 6650.0 + 6500.0) * 1e7
    assert ttm["revenue_ttm"] == expected
    assert ttm["quarters_used"] == 4
    assert ttm["partial"] is False


def test_scale_guard_huhtamaki_pattern():
    """HUHTAMAKI fixture: same 4.78e9 vs ~600 Cr pattern at a
    smaller scale. Guard must still fire on the 10x rule.
    """
    from backend.services import quarterly_results_service as qrs

    rows = [
        _row(date(2025, 12, 31), 600.0, 50.0),
        _row(date(2025, 9, 30),  610.0, 55.0),
        _row(date(2025, 6, 30),  4.78e9, 60.0),  # POISONED
        _row(date(2025, 3, 31),  605.0, 52.0),
        _row(date(2024, 12, 31), 590.0, 48.0),
        _row(date(2024, 9, 30),  580.0, 47.0),
        _row(date(2024, 6, 30),  570.0, 46.0),
        _row(date(2024, 3, 31),  560.0, 45.0),
    ]
    session = _mock_session({True: rows})
    with patch.object(qrs, "_get_pipeline_session", return_value=session):
        ttm = qrs.compute_ttm_from_xbrl("HUHTAMAKI.NS")

    assert "scale_outlier_skipped" in ttm["data_issues"]
    assert len(ttm["scale_skipped"]) == 1
    # Aggregate is over the 4 latest clean rows.
    expected = (600.0 + 610.0 + 605.0 + 590.0) * 1e7
    assert ttm["revenue_ttm"] == expected


def test_scale_guard_does_not_fire_on_normal_ticker():
    """Negative case: TCS-style consistent ~63k Cr quarters. Guard
    must NOT fire; all rows included.
    """
    from backend.services import quarterly_results_service as qrs

    rows = [
        _row(date(2025, 12, 31), 64259.0, 12380.0),
        _row(date(2025, 9, 30),  64988.0, 11909.0),
        _row(date(2025, 6, 30),  62613.0, 12040.0),
        _row(date(2025, 3, 31),  64479.0, 12434.0),
        _row(date(2024, 12, 31), 62885.0, 12380.0),
        _row(date(2024, 9, 30),  62613.0, 11909.0),
        _row(date(2024, 6, 30),  62613.0, 11762.0),
        _row(date(2024, 3, 31),  61237.0, 12502.0),
    ]
    session = _mock_session({True: rows})
    with patch.object(qrs, "_get_pipeline_session", return_value=session):
        ttm = qrs.compute_ttm_from_xbrl("TCS.NS")

    assert ttm["data_issues"] == []
    assert ttm["scale_skipped"] == []
    assert ttm["quarters_used"] == 4
    assert ttm["partial"] is False
    expected = (64259.0 + 64988.0 + 62613.0 + 64479.0) * 1e7
    assert ttm["revenue_ttm"] == expected


def test_scale_guard_does_not_false_positive_legitimate_growth():
    """A ticker that genuinely scaled (e.g. WAAREEENERGIES post-IPO
    ramp -- ~2x q-o-q growth): guard must NOT fire. 10x threshold is
    generous enough to tolerate doubling.
    """
    from backend.services import quarterly_results_service as qrs

    # Steady ramp from ~500 Cr to ~3000 Cr (6x over 8 quarters).
    rows = [
        _row(date(2025, 12, 31), 3000.0, 300.0),
        _row(date(2025, 9, 30),  2500.0, 250.0),
        _row(date(2025, 6, 30),  2000.0, 200.0),
        _row(date(2025, 3, 31),  1600.0, 160.0),
        _row(date(2024, 12, 31), 1200.0, 120.0),
        _row(date(2024, 9, 30),  900.0,  90.0),
        _row(date(2024, 6, 30),  700.0,  70.0),
        _row(date(2024, 3, 31),  500.0,  50.0),
    ]
    session = _mock_session({True: rows})
    with patch.object(qrs, "_get_pipeline_session", return_value=session):
        ttm = qrs.compute_ttm_from_xbrl("WAAREEENERGIES.NS")

    assert ttm["data_issues"] == []
    assert ttm["scale_skipped"] == []
    assert ttm["quarters_used"] == 4


def test_scale_guard_skips_negative_revenue():
    """Negative revenue is impossible; guard must flag it as corrupt."""
    from backend.services import quarterly_results_service as qrs

    rows = [
        _row(date(2025, 12, 31), 6747.0, 850.0),
        _row(date(2025, 9, 30),  6800.0, 870.0),
        _row(date(2025, 6, 30),  -500.0, 880.0),  # NEGATIVE revenue -> corrupt
        _row(date(2025, 3, 31),  6650.0, 800.0),
        _row(date(2024, 12, 31), 6600.0, 820.0),
        _row(date(2024, 9, 30),  6500.0, 810.0),
    ]
    session = _mock_session({True: rows})
    with patch.object(qrs, "_get_pipeline_session", return_value=session):
        ttm = qrs.compute_ttm_from_xbrl("FOO.NS")

    assert "scale_outlier_skipped" in ttm["data_issues"]
    assert len(ttm["scale_skipped"]) == 1
    assert ttm["scale_skipped"][0]["field"] == "revenue_cr"


def test_scale_guard_absolute_cap_fires_when_median_unavailable():
    """Single-row ticker (no median context): only the absolute Rs.10T
    cap can catch corruption. Verify it does.
    """
    from backend.services import quarterly_results_service as qrs

    rows = [_row(date(2025, 12, 31), 4.78e9, 850.0)]  # POISONED, no peers
    session = _mock_session({True: rows})
    with patch.object(qrs, "_get_pipeline_session", return_value=session):
        ttm = qrs.compute_ttm_from_xbrl("FOO.NS")

    assert ttm is not None
    assert "scale_outlier_skipped" in ttm["data_issues"]
    assert "incomplete_due_to_scale_anomalies" in ttm["data_issues"]
    assert ttm["revenue_ttm"] is None
    assert ttm["quarters_used"] == 0


def test_compute_ttm_handles_null_field_as_none():
    """If any quarter has NULL revenue_cr, revenue_ttm must be None
    (we'd rather surface the gap than silently treat NULL as 0)."""
    from backend.services import quarterly_results_service as qrs

    rows = [
        _row(date(2024, 12, 31), 41764.0, 6822.0),
        _row(date(2024, 9, 30),  40986.0, 6516.0),
        _row(date(2024, 6, 30),  39315.0, 6374.0),
        _row(date(2024, 3, 31),  37923.0, 7969.0),
    ]
    rows[1]["revenue_cr"] = None
    session = _mock_session({True: rows})

    with patch.object(qrs, "_get_pipeline_session", return_value=session):
        ttm = qrs.compute_ttm_from_xbrl("INFY.NS")

    assert ttm is not None
    assert ttm["revenue_ttm"] is None
    # net_profit_ttm still summed cleanly.
    assert ttm["net_profit_ttm"] == (6822.0 + 6516.0 + 6374.0 + 7969.0) * 1e7
