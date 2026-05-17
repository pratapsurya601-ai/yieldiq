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


# ── TTM scale-sanity guard (2026-05-17) ────────────────────────────
# Background: the legacy XBRL parser misses some old templates and
# writes scale-corrupt values (e.g. NESTLEIND revenue_cr = 4.78e9
# crores = 47 quadrillion INR) into company_quarterly_results. A
# 2026-05-17 audit of `company_quarterly_results` found 6,996
# corrupt rows across 840 tickers. Even after re-ingest the parser
# misses some templates, so the bug recurs.
#
# This guard runs at the TTM aggregator boundary -- it cannot fix
# the underlying parser, but it stops poisoned rows from leaking
# into TTM sums (which then drive absurd FVs, e.g. NESTLEIND MoS
# +285%). The guard is intentionally generous (10x median); we'd
# rather miss a true 11x outlier than false-positive a real growth
# event. Tighten later if the audit data justifies it.
#
# Fields guarded independently (a row may have correct revenue but
# corrupt cashflow): revenue_cr, net_profit_cr, cfo_cr, fcf_cr.

# Absolute cap (Cr) used when median is unavailable (<2 rows).
# Rs.1e6 Cr = Rs.10 trillion -- larger than any Indian listed company's
# annual revenue, so anything above this is provably corrupt.
_ABS_SCALE_CAP_CR = 1e6
_MEDIAN_MULTIPLE = 10.0
_SCALE_GUARD_FIELDS = ("revenue_cr", "net_profit_cr", "cfo_cr", "fcf_cr")


def _ticker_field_median(rows: list[dict], field: str) -> Optional[float]:
    """Median absolute value of `field` across `rows`; None if <2 non-null."""
    vals = [
        abs(float(r[field]))
        for r in rows
        if r.get(field) is not None
        and isinstance(r.get(field), (int, float))
    ]
    if len(vals) < 2:
        return None
    vals_sorted = sorted(vals)
    mid = len(vals_sorted) // 2
    if len(vals_sorted) % 2 == 1:
        return vals_sorted[mid]
    return 0.5 * (vals_sorted[mid - 1] + vals_sorted[mid])


def _row_is_scale_corrupt(
    row: dict, field: str, median: Optional[float],
) -> bool:
    """True iff `row[field]` is a scale outlier and should be skipped.

    Rules (in order):
      * value is None / non-numeric -> not corrupt (aggregator handles
        NULL separately).
      * value < 0 for revenue_cr -> corrupt (revenue can't be negative;
        net profit / cashflow may legitimately be negative).
      * |value| > 10 x ticker_median (when median known) -> corrupt.
      * |value| > 1e6 Cr absolute fallback (always applied) -> corrupt.
    """
    v = row.get(field)
    if v is None or not isinstance(v, (int, float)):
        return False
    try:
        fv = float(v)
    except (TypeError, ValueError):
        return False
    av = abs(fv)
    # Revenue cannot be negative.
    if field == "revenue_cr" and fv < 0:
        return True
    # Absolute cap (always applied; catches the new-ticker <2-quarter case).
    if av > _ABS_SCALE_CAP_CR:
        return True
    # Median-relative cap (generous 10x).
    if median is not None and av > _MEDIAN_MULTIPLE * median:
        return True
    return False


def _apply_scale_guard(
    rows: list[dict], ticker: str,
) -> tuple[list[dict], list[dict]]:
    """Return (clean_rows, skipped_log).

    Per-row, per-field check: if ANY guarded field on a row is
    corrupt, the whole row is skipped (a row with a corrupt cashflow
    can't be trusted for revenue either -- it came from the same
    broken filing parse). `skipped_log` is a list of dicts with
    {period_end, field, value, median, reason} for observability.

    Median is computed once per field over the input rows so the
    guard fires symmetrically (skipping a row doesn't shift the
    median for the next row's check).
    """
    if not rows:
        return rows, []
    medians = {f: _ticker_field_median(rows, f) for f in _SCALE_GUARD_FIELDS}
    clean: list[dict] = []
    skipped: list[dict] = []
    for r in rows:
        bad_field = None
        for f in _SCALE_GUARD_FIELDS:
            if _row_is_scale_corrupt(r, f, medians[f]):
                bad_field = f
                break
        if bad_field is None:
            clean.append(r)
            continue
        pe = r.get("period_end")
        skipped.append({
            "period_end": pe.isoformat() if hasattr(pe, "isoformat") else str(pe),
            "field": bad_field,
            "value": r.get(bad_field),
            "median": medians[bad_field],
            "reason": "scale_outlier_skipped",
        })
        _logger.warning(
            "ttm_scale_guard: skipped %s row period_end=%s field=%s "
            "value=%s median=%s (scale_outlier_skipped)",
            ticker, skipped[-1]["period_end"], bad_field,
            r.get(bad_field), medians[bad_field],
        )
    return clean, skipped


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
    # Fetch up to 8 quarters so the scale-sanity guard has a wider
    # median window. We still aggregate over only the latest 4 clean
    # rows (TTM = trailing twelve months), but a wider median makes
    # the 10x cap less likely to false-positive a 2-quarter spike.
    rows_window = get_quarterly_results(ticker, n_quarters=8, consolidated=True)
    if not rows_window:
        return None

    # ── Scale-sanity guard (2026-05-17, defends against parser bugs).
    clean_window, scale_skipped = _apply_scale_guard(rows_window, ticker)
    rows = clean_window[:4]
    data_issues: list[str] = []
    if scale_skipped:
        data_issues.append("scale_outlier_skipped")

    if not rows:
        # All rows were corrupt -- caller should fall back to annual.
        return {
            "revenue_ttm":       None,
            "net_profit_ttm":    None,
            "employee_cost_ttm": None,
            "depreciation_ttm":  None,
            "fcf_ttm":           None,
            "fcf_ttm_basis":     None,
            "fcf_ttm_rows_used": 0,
            "quarters_used":     0,
            "partial":           True,
            "period_end":        None,
            "source":            "nse_xbrl",
            "data_issues":       data_issues + ["incomplete_due_to_scale_anomalies"],
            "scale_skipped":     scale_skipped,
        }

    def _sum(field: str) -> Optional[float]:
        vals = [_as_float(r.get(field)) for r in rows]
        if any(v is None for v in vals):
            return None
        # Convert crore -> INR at the boundary so downstream code
        # (which speaks raw INR) doesn't need to know we came from
        # a `*_cr` source.
        return sum(vals) * 1e7

    quarters_used = len(rows)
    # If guard left fewer than 4 quarters, mark TTM as incomplete so
    # the caller falls back to annual data (matches existing
    # `partial=True` semantics in resolve_ttm_for_analysis).
    partial = quarters_used < 4
    if partial and scale_skipped:
        data_issues.append("incomplete_due_to_scale_anomalies")

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
            # Apply scale guard on cashflow window too -- a poisoned
            # cfo_cr / fcf_cr value would otherwise flow straight into
            # the H1+H2 stitched FCF and produce an absurd terminal.
            cf_rows, cf_skipped = _apply_scale_guard(cf_rows, ticker)
            if cf_skipped and "scale_outlier_skipped" not in data_issues:
                data_issues.append("scale_outlier_skipped")
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
        "data_issues":       data_issues,
        "scale_skipped":     scale_skipped,
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
