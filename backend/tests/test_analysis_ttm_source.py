"""
Tests for the TTM source resolver wired into the analysis service
in feat/wire-quarterly-xbrl-to-analysis.

These tests hit `resolve_ttm_for_analysis` — the pure helper that
sits between the analysis service and the data layer. Mocking
that one seam exercises the exact decision the wired snippet
makes without spinning up the rest of the analysis pipeline
(yfinance + Neon + DuckDB).

The two cases that matter for production:
  - Ticker IS in the 41 NIFTY-50 set with 4 fresh quarters →
    ttm_source = "nse_xbrl", revenue + PAT swapped in.
  - Ticker is NOT in the 41 (e.g. ADANIPOWER, INDUSINDBK) →
    ttm_source = "yfinance" via the legacy TTM/annual ladder.
"""
from __future__ import annotations


def _xbrl_full(period_end="2024-12-31"):
    return {
        "revenue_ttm":       1.59988e12,   # 159988 Cr → INR
        "net_profit_ttm":    2.7681e11,
        "employee_cost_ttm": 8.5783e11,
        "depreciation_ttm":  4.6e10,
        "quarters_used":     4,
        "partial":           False,
        "period_end":        period_end,
        "source":            "nse_xbrl",
    }


def _xbrl_partial():
    out = _xbrl_full()
    out["partial"] = True
    out["quarters_used"] = 2
    return out


def _legacy_ttm():
    return {"fcf": 50_000_000_000.0, "revenue": 1.2e12, "pat": 2.0e11,
            "period_end": "2024-09-30", "currency": "INR", "source": "ttm"}


def _annual():
    return {"fcf": 60_000_000_000.0, "revenue": 1.1e12, "pat": 1.9e11,
            "period_end": "2024-03-31", "currency": "INR", "source": "annual"}


# ── Path 1: ticker in the 41, full XBRL TTM available ─────────────

def test_xbrl_full_window_overrides_yfinance():
    from backend.services.quarterly_results_service import (
        resolve_ttm_for_analysis,
    )

    res = resolve_ttm_for_analysis(
        "INFY.NS",
        query_ttm_financials=lambda t: _legacy_ttm(),
        query_latest_annual_financials=lambda t: _annual(),
        compute_xbrl_ttm=lambda t: _xbrl_full(),
    )

    assert res["ttm_source"] == "nse_xbrl"
    assert res["quarterly_last_filed_at"] == "2024-12-31"
    assert res["fcf_data_source"] == "ttm+nse_xbrl"
    # Revenue + PAT came from XBRL (not the 1.2e12 legacy_ttm value).
    assert res["enriched_updates"]["latest_revenue"] == 1.59988e12
    assert res["enriched_updates"]["latest_pat"] == 2.7681e11
    # XBRL has no FCF — caller fills FCF from the annual fallback.
    assert "latest_fcf" not in res["enriched_updates"]
    assert res["annual_fcf_fallback"]["fcf"] == 60_000_000_000.0


# ── Path 2: ticker NOT in the 41 → legacy yfinance ladder ─────────

def test_no_xbrl_falls_back_to_yfinance_ttm():
    from backend.services.quarterly_results_service import (
        resolve_ttm_for_analysis,
    )

    res = resolve_ttm_for_analysis(
        "ADANIPOWER.NS",
        query_ttm_financials=lambda t: _legacy_ttm(),
        query_latest_annual_financials=lambda t: _annual(),
        compute_xbrl_ttm=lambda t: None,
    )

    assert res["ttm_source"] == "yfinance"
    assert res["quarterly_last_filed_at"] is None
    assert res["fcf_data_source"] == "ttm"
    assert res["enriched_updates"]["latest_revenue"] == 1.2e12
    assert res["enriched_updates"]["latest_pat"] == 2.0e11
    assert res["enriched_updates"]["latest_fcf"] == 50_000_000_000.0


# ── Path 3: partial XBRL (only 1-3 quarters) — must NOT swap in ──

def test_partial_xbrl_window_does_not_override_yfinance():
    """A 2-quarter partial TTM would understate the metric. The
    resolver must reject it and use the legacy ladder."""
    from backend.services.quarterly_results_service import (
        resolve_ttm_for_analysis,
    )

    res = resolve_ttm_for_analysis(
        "TCS.NS",
        query_ttm_financials=lambda t: _legacy_ttm(),
        query_latest_annual_financials=lambda t: _annual(),
        compute_xbrl_ttm=lambda t: _xbrl_partial(),
    )

    assert res["ttm_source"] == "yfinance"
    assert res["fcf_data_source"] == "ttm"
    assert res["enriched_updates"]["latest_revenue"] == 1.2e12


# ── Path 4: nothing at all → annual FCF only, no TTM swap ─────────

def test_no_data_anywhere_returns_yfinance_with_no_updates():
    from backend.services.quarterly_results_service import (
        resolve_ttm_for_analysis,
    )

    res = resolve_ttm_for_analysis(
        "OBSCURE.NS",
        query_ttm_financials=lambda t: None,
        query_latest_annual_financials=lambda t: None,
        compute_xbrl_ttm=lambda t: None,
    )

    assert res["ttm_source"] == "yfinance"
    assert res["fcf_data_source"] == "yfinance"
    assert res["enriched_updates"] == {}
    assert res["annual_fcf_fallback"] is None


def test_xbrl_exception_falls_back_to_yfinance():
    """If compute_ttm_from_xbrl raises (e.g. Neon hiccup mid-query),
    the resolver must not crash the analysis pipeline."""
    from backend.services.quarterly_results_service import (
        resolve_ttm_for_analysis,
    )

    def _boom(_):
        raise RuntimeError("neon timeout")

    res = resolve_ttm_for_analysis(
        "INFY.NS",
        query_ttm_financials=lambda t: _legacy_ttm(),
        query_latest_annual_financials=lambda t: _annual(),
        compute_xbrl_ttm=_boom,
    )

    assert res["ttm_source"] == "yfinance"
    assert res["enriched_updates"]["latest_revenue"] == 1.2e12


# ── ValuationOutput carries the new provenance fields ─────────────

def test_valuation_output_carries_ttm_source_field():
    """Pre-PR clients ignore unknown fields, but the model itself
    must accept the new keys so the analysis service can pass them."""
    from backend.models.responses import ValuationOutput

    required = dict(fair_value=100.0, current_price=100.0,
                    margin_of_safety=0.0, verdict="fairly_valued")
    v = ValuationOutput(ttm_source="nse_xbrl",
                        quarterly_last_filed_at="2024-12-31",
                        **required)
    assert v.ttm_source == "nse_xbrl"
    assert v.quarterly_last_filed_at == "2024-12-31"

    # Default keeps prior wire shape (yfinance / None).
    v2 = ValuationOutput(**required)
    assert v2.ttm_source == "yfinance"
    assert v2.quarterly_last_filed_at is None
