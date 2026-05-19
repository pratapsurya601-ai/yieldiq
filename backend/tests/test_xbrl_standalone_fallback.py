"""
Tests for the DRREDDY XBRL standalone-fallback root-cause fix
(docs/design/drreddy-revenue-unit-root-cause.md).

Background: get_quarterly_results() falls back to standalone rows
when no consolidated rows exist for a ticker. For group companies
(DRREDDY-class), standalone revenue is ~7% of consolidated, so
summing 4 standalone quarters into a "TTM" produces a value that
is ~14x too small. That poisons every revenue-scaled FCF candidate
in the downstream DCF.

Fix: tag fallback rows with `_standalone_fallback=True`, and when
compute_ttm_from_xbrl detects any tagged row in the TTM window,
return `partial=True` (so resolve_ttm_for_analysis defers to the
yfinance ladder). A structured warning is logged when the path
fires.

Hermetic: DB session is mocked; nothing touches Neon or yfinance.
"""
from __future__ import annotations

from datetime import date
from unittest.mock import MagicMock, patch


def _row(
    period_end: date,
    revenue_cr: float,
    net_profit_cr: float,
    employee_cr: float = 100.0,
    depreciation_cr: float = 50.0,
    is_consolidated: bool = True,
    ticker: str = "DRREDDY",
) -> dict:
    return {
        "ticker": ticker,
        "fiscal_quarter": "Q? FY??",
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
    """Mock session: returns staged rows keyed by `c` (is_consolidated)."""
    session = MagicMock()

    def _execute(stmt, params):
        c = params.get("c", True)
        n = params.get("n", 4)
        rows = rows_by_consolidated.get(c, [])[:n]
        # Return fresh dict copies so the service can mutate (tag) them
        # without bleeding state across test calls.
        rows = [dict(r) for r in rows]
        result = MagicMock()
        result.mappings.return_value.all.return_value = rows
        return result

    session.execute.side_effect = _execute
    return session


# ── 1. consolidated missing, standalone exists → partial=True ──────────
def test_standalone_only_window_returns_partial_true():
    """DRREDDY shape: zero consolidated rows, 4 standalone rows.
    compute_ttm_from_xbrl must mark the result partial=True with
    `standalone_only` in data_issues so the resolver defers."""
    from backend.services import quarterly_results_service as qrs

    standalone = [
        _row(date(2025, 12, 31), 580.0, 80.0, is_consolidated=False),
        _row(date(2025, 9, 30),  585.0, 85.0, is_consolidated=False),
        _row(date(2025, 6, 30),  590.0, 82.0, is_consolidated=False),
        _row(date(2025, 3, 31),  576.0, 78.0, is_consolidated=False),
    ]
    session = _mock_session({True: [], False: standalone})

    with patch.object(qrs, "_get_pipeline_session", return_value=session):
        ttm = qrs.compute_ttm_from_xbrl("DRREDDY.NS")

    assert ttm is not None
    assert ttm["partial"] is True, (
        "standalone-only window must flip partial=True so resolver "
        "defers to yfinance ladder"
    )
    assert "standalone_only" in ttm["data_issues"]
    # The sum of standalone quarters is still computed (for observability),
    # but partial=True prevents resolve_ttm_for_analysis from using it.
    assert ttm["quarters_used"] == 4


# ── 2. consolidated present → partial=False, standalone NOT used ──────
def test_consolidated_present_uses_consolidated_and_not_partial():
    """Happy path: 4 consolidated rows exist. Standalone must not be
    consulted, partial=False, no standalone_only tag."""
    from backend.services import quarterly_results_service as qrs

    consolidated = [
        _row(date(2025, 12, 31), 8000.0, 1200.0, is_consolidated=True),
        _row(date(2025, 9, 30),  8100.0, 1250.0, is_consolidated=True),
        _row(date(2025, 6, 30),  8150.0, 1280.0, is_consolidated=True),
        _row(date(2025, 3, 31),  8200.0, 1300.0, is_consolidated=True),
    ]
    # Standalone rows exist too, but the service must prefer consolidated.
    standalone = [
        _row(date(2025, 12, 31), 580.0, 80.0, is_consolidated=False),
    ]
    session = _mock_session({True: consolidated, False: standalone})

    with patch.object(qrs, "_get_pipeline_session", return_value=session):
        ttm = qrs.compute_ttm_from_xbrl("DRREDDY.NS")

    assert ttm is not None
    assert ttm["partial"] is False
    assert "standalone_only" not in ttm["data_issues"]
    expected = (8000.0 + 8100.0 + 8150.0 + 8200.0) * 1e7
    assert ttm["revenue_ttm"] == expected


# ── 3. mixed window (some tagged, some not) → conservative partial=True
def test_mixed_window_is_conservatively_partial():
    """If ANY row in the TTM window is standalone-fallback tagged,
    the window is treated as partial=True. In practice the fallback
    only fires when the consolidated leg is fully empty, so mixed
    shapes are unlikely — but we want the conservative behaviour for
    defense in depth.

    We construct the mixed window by directly invoking
    compute_ttm_from_xbrl with a mocked get_quarterly_results that
    yields a hand-crafted window."""
    from backend.services import quarterly_results_service as qrs

    mixed_window = [
        _row(date(2025, 12, 31), 8000.0, 1200.0, is_consolidated=True),
        # The standalone-tagged row is what should trip the partial flag.
        {**_row(date(2025, 9, 30), 585.0, 85.0, is_consolidated=False),
         "_standalone_fallback": True},
        _row(date(2025, 6, 30),  8150.0, 1280.0, is_consolidated=True),
        _row(date(2025, 3, 31),  8200.0, 1300.0, is_consolidated=True),
    ]

    with patch.object(qrs, "get_quarterly_results", return_value=mixed_window), \
         patch.object(qrs, "_get_latest_cashflow_rows", return_value=None):
        ttm = qrs.compute_ttm_from_xbrl("DRREDDY.NS")

    assert ttm is not None
    assert ttm["partial"] is True
    assert "standalone_only" in ttm["data_issues"]


# ── 4. DRREDDY-shape: resolver falls through to yfinance ladder ────────
def test_drreddy_shape_resolver_defers_to_yfinance_ladder():
    """End-to-end shape match: standalone-only XBRL window, resolver
    must NOT overwrite enriched.latest_revenue with the bogus
    standalone TTM. It must fall through to query_ttm_financials
    (the yfinance/income_df leg) which has the correct ~₹32,554 Cr
    consolidated revenue.
    """
    from backend.services import quarterly_results_service as qrs

    standalone = [
        _row(date(2025, 12, 31), 580.0, 80.0, is_consolidated=False),
        _row(date(2025, 9, 30),  585.0, 85.0, is_consolidated=False),
        _row(date(2025, 6, 30),  590.0, 82.0, is_consolidated=False),
        _row(date(2025, 3, 31),  576.0, 78.0, is_consolidated=False),
    ]
    session = _mock_session({True: [], False: standalone})

    # Yfinance leg returns the correct consolidated TTM (~₹32,554 Cr
    # = 3.2554e11 raw INR, ~14x larger than the standalone sum).
    yfinance_ttm = {
        "revenue": 3.2554e11,
        "pat": 5.6e10,
        "fcf": 3.343e10,
    }

    def fake_query_ttm(ticker):
        return yfinance_ttm

    def fake_query_annual(ticker):
        return None

    with patch.object(qrs, "_get_pipeline_session", return_value=session):
        out = qrs.resolve_ttm_for_analysis(
            "DRREDDY.NS",
            query_ttm_financials=fake_query_ttm,
            query_latest_annual_financials=fake_query_annual,
        )

    # Resolver must report yfinance source, not nse_xbrl, because the
    # XBRL TTM was partial (standalone_only).
    assert out["ttm_source"] == "yfinance"
    assert out["fcf_data_source"] == "ttm"
    # The bogus standalone sum (~₹2,331 Cr = 2.33e10 INR) must NOT
    # appear; the correct yfinance value must.
    assert out["enriched_updates"]["latest_revenue"] == 3.2554e11
    assert out["enriched_updates"]["latest_pat"] == 5.6e10
    assert out["enriched_updates"]["latest_fcf"] == 3.343e10


# ── Bonus: standalone fallback emits the structured warning log ───────
def test_standalone_fallback_emits_warning_log(caplog):
    """Observability check: the warning log must fire so ops can
    grep for `TTM standalone-only fallback` across tickers."""
    import logging
    from backend.services import quarterly_results_service as qrs

    standalone = [
        _row(date(2025, 12, 31), 580.0, 80.0, is_consolidated=False),
        _row(date(2025, 9, 30),  585.0, 85.0, is_consolidated=False),
        _row(date(2025, 6, 30),  590.0, 82.0, is_consolidated=False),
        _row(date(2025, 3, 31),  576.0, 78.0, is_consolidated=False),
    ]
    session = _mock_session({True: [], False: standalone})

    with caplog.at_level(logging.WARNING, logger="yieldiq.quarterly_results"):
        with patch.object(qrs, "_get_pipeline_session", return_value=session):
            qrs.compute_ttm_from_xbrl("DRREDDY.NS")

    matches = [
        rec for rec in caplog.records
        if "TTM standalone-only fallback" in rec.getMessage()
    ]
    assert matches, "expected structured warning for standalone-only fallback"
    assert "DRREDDY.NS" in matches[0].getMessage()
