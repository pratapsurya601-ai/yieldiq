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
# FCF (since PR #XXX / migration 034): SEBI LODR Reg 33 lets listed
# entities publish cash flow only HALF-YEARLY (Sep + Mar). The
# parser at data_pipeline/sources/nse_quarterly_xbrl.py extracts
# CFO / CapEx / FCF from those H1 + Q4 filings (Q1 / Q3 still carry
# no cash flow). `compute_ttm_from_xbrl` stitches the latest two
# half-year prints into a 12-month FCF:
#
#   * Latest = Q4 (Mar)            → fcf_ttm := Q4.fcf_cr  (full FY)
#   * Latest = Q2 (Sep)            → fcf_ttm := Q2.fcf_cr + (PrevQ4.fcf_cr - PrevQ2.fcf_cr)
#   * Latest = Q1/Q3 (no CF)       → fcf_ttm := latest Q4 row (full FY, possibly stale)
#
# `fcf_ttm` is None when the two half-year rows needed for the
# stitched window are missing — callers should fall back to the
# existing annual / yfinance path.
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
    "cfo_cr, cfi_cr, cff_cr, capex_cr, fcf_cr, "
    "cashflow_period_months, has_cashflow_statement, "
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


def _get_latest_cashflow_rows(
    ticker: str, n: int = 4, consolidated: bool = True,
) -> Optional[list[dict]]:
    """Fetch latest `n` rows that carry cash-flow data (cfo_cr IS NOT NULL).

    Used by the FCF TTM aggregator. Mirrors `get_quarterly_results`'s
    consolidated-preferred-with-standalone-fallback strategy so the
    FCF leg comes from the same filing series as the P&L leg.
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
                    "SELECT period_end, cfo_cr, capex_cr, fcf_cr, "
                    "cashflow_period_months "
                    "FROM company_quarterly_results "
                    "WHERE ticker = :t AND is_consolidated = :c "
                    "  AND cfo_cr IS NOT NULL "
                    "ORDER BY period_end DESC "
                    "LIMIT :n"
                ),
                {"t": db_ticker, "c": is_consolidated, "n": n},
            ).mappings().all()
            return [dict(r) for r in rows]

        if consolidated:
            rows = _fetch(True) or _fetch(False)
        else:
            rows = _fetch(False)
        return rows or None
    except Exception as exc:
        _logger.warning(
            "cashflow rows query failed for %s (%s)",
            db_ticker, str(exc)[:120],
        )
        return None
    finally:
        try:
            db.close()
        except Exception:
            pass


def _compute_fcf_ttm_from_halfyear(
    cf_rows: list[dict],
) -> tuple[Optional[float], Optional[str], int]:
    """Stitch the latest half-year prints into a 12-month FCF.

    Inputs: rows ordered period_end DESC, each carrying
        period_end, cfo_cr, capex_cr, fcf_cr, cashflow_period_months
    where cashflow_period_months ∈ {6, 12}:
       * 6  → H1 print (Apr-Sep YTD)
       * 12 → Q4/FY print (Apr-Mar YTD = full FY)

    Returns (fcf_ttm_in_inr, basis_label, rows_used).

    Stitching rules (period_end month):
      - Latest = Q4 (Mar):
            fcf_ttm = latest.fcf_cr               (full FY, 12 months)
            basis   = 'fy_q4'
      - Latest = Q2 (Sep):
            fcf_ttm = latest.fcf_cr
                      + (prev_Q4.fcf_cr - prev_Q2.fcf_cr)
            basis   = 'h1_plus_prev_h2'
            (Requires the previous-FY Q4 and Q2 prints; if either
            absent, falls back to most recent Q4 row → 'fy_q4_stale')
      - Else (no Q2/Q4 row in window): None.

    fcf_cr is in Cr; output is INR (× 1e7) to match the convention
    `enriched["latest_fcf"]` / `_query_ttm_financials`.
    """
    if not cf_rows:
        return None, None, 0

    def _is_q2(r: dict) -> bool:
        pe = r.get("period_end")
        return pe is not None and getattr(pe, "month", None) == 9
    def _is_q4(r: dict) -> bool:
        pe = r.get("period_end")
        return pe is not None and getattr(pe, "month", None) == 3
    def _f(r: dict, key: str) -> Optional[float]:
        v = r.get(key)
        try:
            return float(v) if v is not None else None
        except (TypeError, ValueError):
            return None

    latest = cf_rows[0]
    # Case A: latest is FY-Q4 print — fcf is already 12-month YTD.
    if _is_q4(latest):
        fcf = _f(latest, "fcf_cr")
        if fcf is None:
            return None, None, 0
        return fcf * 1e7, "fy_q4", 1

    # Case B: latest is H1 (Sep). Need previous-FY Q4 + previous-FY Q2.
    if _is_q2(latest):
        h1_fcf = _f(latest, "fcf_cr")
        prev_q4 = next((r for r in cf_rows[1:] if _is_q4(r)), None)
        prev_q2 = next((r for r in cf_rows[1:] if _is_q2(r)), None)
        if h1_fcf is not None and prev_q4 is not None and prev_q2 is not None:
            pq4 = _f(prev_q4, "fcf_cr")
            pq2 = _f(prev_q2, "fcf_cr")
            if pq4 is not None and pq2 is not None:
                h2_prev_fcf = pq4 - pq2   # H2 of previous FY
                return (h1_fcf + h2_prev_fcf) * 1e7, "h1_plus_prev_h2", 3
        # Fall back to the latest Q4 we have (stale by up to 6 months).
        if prev_q4 is not None:
            pq4_fcf = _f(prev_q4, "fcf_cr")
            if pq4_fcf is not None:
                return pq4_fcf * 1e7, "fy_q4_stale", 1
        return None, None, 0

    # Case C: latest is a Q1/Q3 row that carried cash flow (rare —
    # voluntary disclosure). Fall back to latest Q4.
    q4 = next((r for r in cf_rows if _is_q4(r)), None)
    if q4 is not None:
        v = _f(q4, "fcf_cr")
        if v is not None:
            return v * 1e7, "fy_q4_stale", 1
    return None, None, 0


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

    # FCF TTM (since migration 034): stitch latest two H1/Q4 prints.
    # Decoupled from the 4-quarter P&L window since cash flow lives
    # only on H1 (Sep) and Q4 (Mar) filings. We query up to 4 cash-
    # flow rows so we always cover (latest, prev_Q4, prev_Q2).
    fcf_ttm: Optional[float] = None
    fcf_basis: Optional[str] = None
    fcf_rows_used: int = 0
    try:
        cf_rows = _get_latest_cashflow_rows(ticker, n=4, consolidated=True)
        if cf_rows:
            fcf_ttm, fcf_basis, fcf_rows_used = _compute_fcf_ttm_from_halfyear(cf_rows)
    except Exception as exc:
        _logger.info("fcf ttm compute skipped for %s: %s", ticker, str(exc)[:120])

    return {
        "revenue_ttm":       _sum("revenue_cr"),
        "net_profit_ttm":    _sum("net_profit_cr"),
        "employee_cost_ttm": _sum("employee_benefit_cr"),
        "depreciation_ttm":  _sum("depreciation_cr"),
        # FCF TTM in raw INR; basis records which stitching path was
        # taken so the surface layer can label the source precisely.
        "fcf_ttm":           fcf_ttm,
        "fcf_ttm_basis":     fcf_basis,
        "fcf_ttm_rows_used": fcf_rows_used,
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
        # FCF leg: prefer XBRL TTM (migration 034 — stitched H1+H2
        # half-year prints). Fall back to the latest annual row when
        # the half-year window is incomplete (e.g. company that has
        # only one half-year filing in our table so far).
        fcf_from_xbrl = xbrl_ttm.get("fcf_ttm")
        if fcf_from_xbrl is not None:
            out["enriched_updates"]["latest_fcf"] = fcf_from_xbrl
            basis = xbrl_ttm.get("fcf_ttm_basis") or "xbrl"
            out["fcf_data_source"] = f"ttm+nse_xbrl_cf_{basis}"
            out["annual_fcf_fallback"] = None
        else:
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
