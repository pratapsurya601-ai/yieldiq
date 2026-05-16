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
