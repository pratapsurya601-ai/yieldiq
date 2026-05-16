# backend/services/quarterly_results_service.py
# ═══════════════════════════════════════════════════════════════
# Quarterly XBRL P&L reader for the 41 NIFTY-50 tickers whose
# Ind-AS quarterly results have been ingested into
# `company_quarterly_results` (see migration 030).
#
# Why this exists: yfinance's TTM cash-flow / revenue series fires
# `ttm_fcf == 0` on ~77% of cache today. NSE XBRL gives us audited
# quarterly P&L straight from the filing, so for the tickers we
# cover we can compute a clean TTM (revenue + net profit + employee
# cost + depreciation) and skip the noisy yfinance path.
#
# Scope (additive, read-only):
#   - get_quarterly_results(ticker, ...) — list of dicts, newest first
#   - compute_ttm_from_xbrl(ticker)      — TTM aggregates or None
#
# Banks / insurers (HDFCBANK, ICICIBANK, SBIN, KOTAKBANK, AXISBANK,
# INDUSINDBK, HDFCLIFE, SBILIFE) are NOT in the 41 yet — separate
# spike is parsing their bank-flavoured Ind-AS schedule.
#
# IMPORTANT — fiscal_quarter label bug: the `fiscal_quarter` string
# in the table is off-by-one-year for Apr-Dec quarters (e.g.
# 2024-09-30 is tagged "Q2 FY24" but should be "Q2 FY25"). Always
# sort by `period_end` here — never trust the label string.
#
# FCF: quarterly XBRL does NOT carry a cash-flow statement, so this
# module deliberately does not produce a TTM FCF. Callers that want
# to swap the XBRL TTM into the DCF path must keep yfinance's FCF
# (or fall back to annual FCF) for the FCF leg. A follow-up PR will
# parse the cash-flow XBRL and add `ttm_fcf` here.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from typing import Optional

from backend.services.analysis.db import _get_pipeline_session


_logger = logging.getLogger("yieldiq.quarterly_results")


# Columns the read path returns. Listed explicitly so a future
# ALTER TABLE adding (say) ESG fields cannot silently widen the
# shape that downstream callers depend on.
_SELECT_COLS = (
    "ticker, fiscal_quarter, period_start, period_end, "
    "is_consolidated, is_audited, is_single_segment, "
    "revenue_cr, other_income_cr, total_expenses_cr, "
    "profit_before_tax_cr, tax_expense_cr, net_profit_cr, "
    "comprehensive_income_cr, employee_benefit_cr, "
    "finance_costs_cr, depreciation_cr, other_expenses_cr, "
    "basic_eps, diluted_eps, face_value, paid_up_capital_cr, "
    "xbrl_url, filed_at, ingested_at"
)


def _strip_suffix(ticker: str) -> str:
    """Tickers in the table are bare symbols (INFY, RELIANCE, etc.)
    while the analysis service passes INFY.NS / RELIANCE.NS."""
    return ticker.replace(".NS", "").replace(".BO", "").upper()


def _as_float(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def get_quarterly_results(
    ticker: str,
    n_quarters: int = 4,
    consolidated: bool = True,
) -> Optional[list[dict]]:
    """
    Fetch the latest `n_quarters` rows for `ticker` from
    `company_quarterly_results`, newest first.

    Prefers consolidated filings. Falls back to standalone if no
    consolidated rows exist for the ticker — many single-entity
    companies file only standalone, and a standalone print is
    strictly better than no data at all.

    Returns None when the DB is unreachable OR the ticker has zero
    rows of any kind. Callers must treat None as "fall back to the
    existing path" — never as an error.

    Ordering is by `period_end DESC`. We never sort by the
    `fiscal_quarter` string because the upstream labels are
    off-by-one-year for Apr-Dec quarters (see module docstring).
    """
    db = _get_pipeline_session()
    if db is None:
        return None
    db_ticker = _strip_suffix(ticker)
    try:
        from sqlalchemy import text

        def _fetch(is_consolidated: bool) -> list[dict]:
            rows = db.execute(
                text(
                    f"SELECT {_SELECT_COLS} "
                    "FROM company_quarterly_results "
                    "WHERE ticker = :t AND is_consolidated = :c "
                    "ORDER BY period_end DESC "
                    "LIMIT :n"
                ),
                {"t": db_ticker, "c": is_consolidated, "n": n_quarters},
            ).mappings().all()
            return [dict(r) for r in rows]

        if consolidated:
            rows = _fetch(True)
            if not rows:
                rows = _fetch(False)
                if rows:
                    _logger.info(
                        "quarterly_results: %s has no consolidated rows, "
                        "falling back to standalone (%d rows)",
                        db_ticker, len(rows),
                    )
        else:
            rows = _fetch(False)

        if not rows:
            return None
        return rows
    except Exception as exc:
        _logger.warning(
            "quarterly_results: query failed for %s (%s)",
            db_ticker, str(exc)[:120],
        )
        return None
    finally:
        try:
            db.close()
        except Exception:
            pass


def compute_ttm_from_xbrl(ticker: str) -> Optional[dict]:
    """
    Aggregate the latest 4 quarters into a TTM dict.

    Output (all values in raw INR, NOT crores — matches the unit
    convention of `enriched["latest_revenue"]` / `_query_ttm_financials`
    so the analysis service can swap this in without touching the
    consumers downstream):

        {
            "revenue_ttm":        float,
            "net_profit_ttm":     float,
            "employee_cost_ttm":  float,
            "depreciation_ttm":   float,
            "quarters_used":      int,        # 1..4
            "partial":            bool,       # True if < 4 quarters
            "period_end":         "YYYY-MM-DD",  # latest row's period_end
            "source":             "nse_xbrl",
        }

    Returns None when there are zero rows for the ticker. A `partial`
    result is returned when 1-3 quarters are available — callers
    should typically reject partial results for TTM use (the spec
    requires we ONLY swap XBRL in when not partial), but the value
    is still returned so observability / debugging is easier.

    Per-field aggregation rule: if ANY of the 4 quarters has NULL
    for that field, that field is None in the output. (A TTM that
    silently treats NULL as 0 would understate the metric — better
    to surface the gap and let the caller decide.)
    """
    rows = get_quarterly_results(ticker, n_quarters=4, consolidated=True)
    if not rows:
        return None

    def _sum(field: str) -> Optional[float]:
        vals = [_as_float(r.get(field)) for r in rows]
        if any(v is None for v in vals):
            return None
        # Convert crore → INR at the boundary so downstream code
        # (which speaks raw INR) doesn't need to know we came from
        # a `*_cr` source.
        return sum(vals) * 1e7

    quarters_used = len(rows)
    partial = quarters_used < 4

    latest_period_end = rows[0].get("period_end")
    period_end_str = (
        latest_period_end.isoformat()
        if hasattr(latest_period_end, "isoformat")
        else str(latest_period_end) if latest_period_end else None
    )

    return {
        "revenue_ttm":       _sum("revenue_cr"),
        "net_profit_ttm":    _sum("net_profit_cr"),
        "employee_cost_ttm": _sum("employee_benefit_cr"),
        "depreciation_ttm":  _sum("depreciation_cr"),
        "quarters_used":     quarters_used,
        "partial":           partial,
        "period_end":        period_end_str,
        "source":            "nse_xbrl",
    }


def resolve_ttm_for_analysis(
    ticker: str,
    *,
    query_ttm_financials,
    query_latest_annual_financials,
    compute_xbrl_ttm=compute_ttm_from_xbrl,
) -> dict:
    """
    Decide which TTM source to use for the analysis service and
    return the result as a plain dict the caller can apply to its
    `enriched` payload.

    Inputs are injected (not imported) so the function is hermetically
    testable without touching Neon or yfinance.

    Return shape:
        {
            "ttm_source":              "nse_xbrl" | "yfinance",
            "quarterly_last_filed_at": str | None,
            "fcf_data_source":         str,        # for ValuationOutput
            "enriched_updates":        dict,       # keys to merge into `enriched`
            "annual_fcf_fallback":     dict | None # latest annual row when
                                                  # XBRL TTM fires (FCF leg)
        }

    Decision rule:
      1. If XBRL TTM exists AND is not partial (4-quarter window) →
         use XBRL revenue + PAT; FCF still resolved from annual /
         yfinance below (XBRL has no cash flow statement).
      2. Else fall back to the existing local-DB TTM row.
      3. Else fall back to the existing annual row's FCF only.

    The function never mutates anything — the caller is responsible
    for applying `enriched_updates` to its local dict so the
    surrounding control flow (cyclical normalization, FCF floor,
    etc.) stays untouched.
    """
    out = {
        "ttm_source": "yfinance",
        "quarterly_last_filed_at": None,
        "fcf_data_source": "yfinance",
        "enriched_updates": {},
        "annual_fcf_fallback": None,
    }
    try:
        xbrl_ttm = compute_xbrl_ttm(ticker)
    except Exception:
        xbrl_ttm = None

    if xbrl_ttm is not None and not xbrl_ttm.get("partial"):
        out["ttm_source"] = "nse_xbrl"
        out["quarterly_last_filed_at"] = xbrl_ttm.get("period_end")
        out["fcf_data_source"] = "ttm+nse_xbrl"
        if xbrl_ttm.get("revenue_ttm") is not None:
            out["enriched_updates"]["latest_revenue"] = xbrl_ttm["revenue_ttm"]
        if xbrl_ttm.get("net_profit_ttm") is not None:
            out["enriched_updates"]["latest_pat"] = xbrl_ttm["net_profit_ttm"]
        # FCF leg: best-effort annual fallback. TODO(follow-up PR):
        # parse cash-flow XBRL so we can produce ttm_fcf here too.
        try:
            out["annual_fcf_fallback"] = query_latest_annual_financials(ticker)
        except Exception:
            out["annual_fcf_fallback"] = None
        return out

    # XBRL absent or partial → existing TTM/annual ladder.
    try:
        ttm_data = query_ttm_financials(ticker)
    except Exception:
        ttm_data = None
    if ttm_data:
        out["fcf_data_source"] = "ttm"
        if ttm_data.get("fcf") is not None:
            out["enriched_updates"]["latest_fcf"] = ttm_data["fcf"]
        if ttm_data.get("revenue") is not None:
            out["enriched_updates"]["latest_revenue"] = ttm_data["revenue"]
        if ttm_data.get("pat") is not None:
            out["enriched_updates"]["latest_pat"] = ttm_data["pat"]
        return out

    try:
        annual_data = query_latest_annual_financials(ticker)
    except Exception:
        annual_data = None
    if annual_data:
        out["fcf_data_source"] = "annual"
        if annual_data.get("fcf") is not None:
            out["enriched_updates"]["latest_fcf"] = annual_data["fcf"]
    return out
