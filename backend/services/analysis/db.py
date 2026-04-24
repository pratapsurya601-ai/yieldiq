# backend/services/analysis/db.py
# ═══════════════════════════════════════════════════════════════
# DB session management + Aiven Postgres fetchers (ROCE inputs,
# bank metrics, financials, shareholding, bulk deals, earnings).
# Extracted verbatim from the historical analysis_service.py
# monolith.
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

from datetime import datetime

from backend.services.analysis.utils import _fx_multiplier


# Track consecutive DB failures. After 3 failures, enter a 60-second
# cooldown (not 5 minutes — that was too aggressive). This allows
# Aiven to wake up from cold start (takes ~10-30s) without blocking
# the entire analysis pipeline for 5 minutes.
import time as _time
_db_fail_count: int = 0
_db_dead_until: float = 0


def _get_pipeline_session():
    """Get a DB session from the data pipeline, or None if unavailable."""
    global _db_fail_count, _db_dead_until
    import logging as _log
    _logger = _log.getLogger("yieldiq.db")

    now = _time.time()
    if now < _db_dead_until:
        return None  # In cooldown — skip instantly
    try:
        from data_pipeline.db import Session as PipelineSession, DATABASE_URL as _db_url
        if PipelineSession is None:
            if _db_url:
                _logger.warning("DB_SESSION: Session is None despite DATABASE_URL being set")
            _db_dead_until = now + 60
            return None
        session = PipelineSession()
        # Success — reset failure counter
        if _db_fail_count > 0:
            _logger.info("DB_SESSION: reconnected after %d failures", _db_fail_count)
        _db_fail_count = 0
        return session
    except Exception as exc:
        _db_fail_count += 1
        # Escalating cooldown: 10s → 30s → 60s
        cooldown = min(60, 10 * _db_fail_count)
        _db_dead_until = now + cooldown
        _logger.warning("DB_SESSION: fail #%d (%s), cooldown %ds",
                        _db_fail_count, str(exc)[:60], cooldown)
        return None


def _fetch_current_assets(ticker: str) -> float | None:
    """Latest current_assets (Crores) from company_financials. None on
    miss — callers should fall back to enriched if needed, though note
    unit mismatch: DB is Crores, enriched is raw INR.

    Paired with _fetch_roce_inputs's current_liabilities: use both from
    DB so the current_ratio numerator and denominator share units."""
    db = _get_pipeline_session()
    if db is None:
        return None
    try:
        from sqlalchemy import text
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")
        row = db.execute(text("""
            SELECT current_assets
            FROM company_financials
            WHERE ticker_nse = :t
              AND statement_type = 'balance_sheet'
              AND period_type = 'annual'
              AND period_end_date IS NOT NULL
            ORDER BY period_end_date DESC
            LIMIT 1
        """), {"t": db_ticker}).mappings().first()
        if row is None:
            return None
        val = row.get("current_assets")
        try:
            return float(val) if val is not None else None
        except (TypeError, ValueError):
            return None
    except Exception:
        return None
    finally:
        try:
            db.close()
        except Exception:
            pass


def _convert_row_to_inr(ticker: str, row) -> tuple[float | None, float | None, float | None]:
    """
    Read fcf / revenue / pat off a Financials row and convert to INR
    based on the row's `currency` column.

    IDEMPOTENCY GUARD: our ingestion layers have historically converted
    USD → INR *before* writing to the Financials table (data/collector.py
    ::_detect_financial_currency multiplies by APPROX_USD_TO_INR for
    HCLTECH, INFY etc). If the migration backfill then tagged the same
    rows as currency='USD', a read-side _fx_multiplier would double-
    convert, producing fcf_base ≈ 83× real (HCLTECH bug, commit b31a7e9
    canary showed FV ₹6,073 vs real ~₹1,500).

    Heuristic: for any large-cap Indian stock, TTM revenue should be
    at least ₹100 crore (₹1 billion = 1e9). If the raw row value already
    exceeds that threshold, treat it as already-INR regardless of the
    currency tag. A genuine USD row would have revenue in the $100M-$10B
    range (1e8–1e10), whereas an INR-already row for the same company
    is 83× larger (1e10–1e12). The boundary is clean.
    """
    ccy = getattr(row, "currency", None) or "INR"
    mult = _fx_multiplier(ccy)

    raw_fcf = row.free_cash_flow
    raw_rev = row.revenue
    raw_pat = row.pat

    if mult != 1.0:
        # Idempotency: if revenue is already in ₹-crore magnitude
        # (> ₹100 crore = 1e9), the ingestion layer already converted.
        # Do NOT multiply again.
        _rev_magnitude = float(raw_rev or 0)
        if _rev_magnitude > 1e10:  # ₹1,000 crore — unmistakably INR-already
            _logger.info(
                "FX_SKIP: %s tagged %s but revenue=%.2e suggests INR-"
                "already (double-convert guard)", ticker, ccy, _rev_magnitude,
            )
            mult = 1.0

    fcf = raw_fcf * mult if raw_fcf is not None else None
    rev = raw_rev * mult if raw_rev is not None else None
    pat = raw_pat * mult if raw_pat is not None else None
    if mult != 1.0:
        _logger.info(
            "FX_CONVERT: %s %s → INR at %.2f (fcf %.2f → %.2f)",
            ticker, ccy, mult, raw_fcf or 0.0, fcf or 0.0,
        )
    return fcf, rev, pat


def _query_ttm_financials(ticker: str):
    """
    Query TTM financials from local DB.
    Returns dict with fcf, revenue, pat (INR-normalised) or None if unavailable.

    3-path FCF resolution (added 2026-04-25 — see test_fcf_fallback_and_fv_clamp):
      Path 1: TTM row has nonzero FCF → use it (source='ttm').
      Path 2: TTM FCF is 0/None BUT at least one of the 4 underlying
              quarterly rows carries non-NULL cfo/capex/fcf → return
              TTM as-is; this is a partial / propagation issue, not a
              missing-data issue (source='ttm').
      Path 3: TTM FCF is 0/None AND all 4 quarterly rows have NULL
              cfo+capex+fcf → the quarterly cash-flow columns are
              unpopulated upstream. Fall back to most recent annual
              FCF (source='ttm+annual_fcf_fallback') so DCF doesn't
              collapse to 0.
    """
    import logging as _log
    _logger = _log.getLogger("yieldiq.db")

    db = _get_pipeline_session()
    if db is None:
        return None
    try:
        from data_pipeline.models import Financials
        from sqlalchemy import desc
        # Strip .NS/.BO suffix for DB lookup
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")
        row = (
            db.query(Financials)
            .filter(Financials.ticker == db_ticker, Financials.period_type == "ttm")
            .order_by(desc(Financials.period_end))
            .first()
        )
        if row is None:
            return None

        # Path 1: healthy TTM FCF → primary path.
        if row.free_cash_flow is not None and float(row.free_cash_flow or 0) != 0.0:
            fcf, rev, pat = _convert_row_to_inr(ticker, row)
            return {
                "fcf": fcf,
                "revenue": rev,
                "pat": pat,
                "period_end": str(row.period_end) if row.period_end else None,
                "currency": getattr(row, "currency", None) or "INR",
                "source": "ttm",
            }

        # Paths 2/3: TTM FCF is missing or zero. Inspect the 4 most
        # recent quarterly rows to decide between "partial / data
        # propagation issue" and "quarterly CF columns unpopulated".
        quarters = (
            db.query(Financials)
            .filter(
                Financials.ticker == db_ticker,
                Financials.period_type == "quarterly",
            )
            .order_by(desc(Financials.period_end))
            .limit(4)
            .all()
        )

        any_quarter_has_cf = False
        for q in quarters or []:
            q_cfo = getattr(q, "cfo", None)
            q_capex = getattr(q, "capex", None)
            q_fcf = getattr(q, "free_cash_flow", None)
            if q_cfo is not None or q_capex is not None or q_fcf is not None:
                any_quarter_has_cf = True
                break

        if any_quarter_has_cf:
            # Path 2: at least one quarterly has cash-flow data — TTM
            # zero/null is a propagation gap, not missing source data.
            # Return the TTM row as-is so callers can decide.
            fcf, rev, pat = _convert_row_to_inr(ticker, row)
            return {
                "fcf": fcf,
                "revenue": rev,
                "pat": pat,
                "period_end": str(row.period_end) if row.period_end else None,
                "currency": getattr(row, "currency", None) or "INR",
                "source": "ttm",
            }

        # Path 3: ALL 4 quarterlies have NULL cfo+capex+fcf — the
        # underlying source rows are unpopulated. Fall back to the
        # most recent annual FCF so DCF doesn't collapse to 0.
        annual = _query_latest_annual_financials(ticker)
        if annual is None:
            return None

        _logger.info(
            "ticker=%s using annual FCF fallback (quarterly FCF columns "
            "unpopulated; ttm_fcf=%s, %d quarterly rows inspected, all "
            "cfo/capex/fcf NULL)",
            ticker, row.free_cash_flow, len(quarters or []),
        )
        annual = dict(annual)
        annual["source"] = "ttm+annual_fcf_fallback"
        return annual
    except Exception:
        return None
    finally:
        try:
            db.close()
        except Exception:
            pass


def _query_latest_annual_financials(ticker: str):
    """
    Query latest annual financials from local DB.
    Returns dict with fcf, revenue, pat (INR-normalised) or None if unavailable.
    """
    db = _get_pipeline_session()
    if db is None:
        return None
    try:
        from data_pipeline.models import Financials
        from sqlalchemy import desc
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")
        row = (
            db.query(Financials)
            .filter(Financials.ticker == db_ticker, Financials.period_type == "annual")
            .order_by(desc(Financials.period_end))
            .first()
        )
        if row and row.free_cash_flow is not None:
            fcf, rev, pat = _convert_row_to_inr(ticker, row)
            return {
                "fcf": fcf,
                "revenue": rev,
                "pat": pat,
                "period_end": str(row.period_end) if row.period_end else None,
                "currency": getattr(row, "currency", None) or "INR",
                "source": "annual",
            }
        return None
    except Exception:
        return None
    finally:
        db.close()


def _query_shareholding(ticker: str) -> dict | None:
    """
    Fetch the latest shareholding pattern (promoter / FII / DII /
    public + pledge) from the ShareholdingPattern table. Returns
    ``None`` if the table/row is missing.
    """
    db = _get_pipeline_session()
    if db is None:
        return None
    try:
        from data_pipeline.models import ShareholdingPattern
        from sqlalchemy import desc
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")
        row = (
            db.query(ShareholdingPattern)
            .filter(ShareholdingPattern.ticker == db_ticker)
            .order_by(desc(ShareholdingPattern.quarter_end))
            .first()
        )
        if row is None:
            return None
        return {
            "promoter_pct":        float(row.promoter_pct) if row.promoter_pct is not None else None,
            "promoter_pledge_pct": float(row.promoter_pledge_pct) if row.promoter_pledge_pct is not None else None,
            "fii_pct":             float(row.fii_pct) if row.fii_pct is not None else None,
            "dii_pct":             float(row.dii_pct) if row.dii_pct is not None else None,
            "public_pct":          float(row.public_pct) if row.public_pct is not None else None,
        }
    except Exception:
        return None
    finally:
        db.close()


def _query_promoter_pledge(ticker: str):
    """Legacy shim — red-flag generator calls this by name. Kept so
    we don't break callers that only need the pledge number."""
    data = _query_shareholding(ticker)
    return data.get("promoter_pledge_pct") if data else None


def _fetch_ebit_and_interest(ticker: str) -> tuple[float | None, float | None]:
    """
    Pull the most recent annual EBIT and interest_expense.

    Priority:
      1. ``company_financials`` table (new XBRL pipeline — has explicit EBIT)
      2. ``financials`` table (now populated by NSE XBRL parser too —
         FIX-XBRL-ROCE added ebit, total_assets, current_liabilities
         extraction upstream so we prefer the explicit ebit column and
         fall back to ebitda only when ebit is absent).

    Returns (None, None) if neither table has data for this ticker.
    """
    db = _get_pipeline_session()
    if db is None:
        return None, None
    try:
        from sqlalchemy import text
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")

        # Try company_financials first (has real EBIT)
        row = db.execute(text("""
            SELECT ebit, interest_expense
            FROM company_financials
            WHERE ticker_nse = :t
              AND statement_type = 'income'
              AND period_type = 'annual'
              AND period_end_date IS NOT NULL
            ORDER BY period_end_date DESC
            LIMIT 1
        """), {"t": db_ticker}).mappings().first()
        def _f(v):
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        if row:
            ebit = _f(row.get("ebit"))
            interest = _f(row.get("interest_expense"))
            if ebit is not None:
                return ebit, interest

        # Fallback: `financials` table. Prefer explicit `ebit` (now
        # populated by the NSE XBRL parser); if NULL, fall back to
        # EBITDA (EBIT + depreciation — a reasonable upper-bound
        # proxy when depreciation is unavailable).
        old_row = db.execute(text("""
            SELECT ebitda, ebit
            FROM financials
            WHERE ticker = :t
              AND period_type = 'annual'
              AND period_end IS NOT NULL
            ORDER BY period_end DESC
            LIMIT 1
        """), {"t": db_ticker}).mappings().first()

        if old_row:
            ebit_val = _f(old_row.get("ebit")) or _f(old_row.get("ebitda"))
            if ebit_val is not None:
                return ebit_val, None  # No interest_expense in old table

        return None, None
    except Exception as exc:
        import logging
        logging.getLogger("yieldiq.analysis").debug(
            "ebit/interest fetch failed for %s: %s", ticker, exc
        )
        return None, None
    finally:
        try:
            db.close()
        except Exception:
            pass


def _fetch_roce_inputs(
    ticker: str,
) -> tuple[float | None, float | None, float | None, float | None]:
    """
    Fetch all ROCE inputs in one round-trip: (ebit, total_assets,
    current_liabilities, interest_expense).

    Priority:
      1. ``company_financials`` (new XBRL pipeline with explicit fields)
      2. ``financials`` (now carries total_assets + current_liabilities
         thanks to FIX-XBRL-ROCE)

    Returns all-Nones if no annual data is available. Any individual
    field may still be None — callers decide how to degrade.
    """
    import logging as _l_top
    _roce_log = _l_top.getLogger("yieldiq.analysis")
    _roce_log.info("roce inputs: called for %s", ticker)
    db = _get_pipeline_session()
    if db is None:
        _roce_log.warning(
            "roce inputs: BAILING for %s — _get_pipeline_session returned None "
            "(DB in cooldown, URL unset, or engine init failed)",
            ticker,
        )
        return None, None, None, None
    try:
        from sqlalchemy import text
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")

        def _f(v):
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        # Prefer company_financials but company_financials is statement-
        # sharded. Pull income + balance rows independently and merge.
        inc_row = db.execute(text("""
            SELECT ebit, interest_expense, period_end_date
            FROM company_financials
            WHERE ticker_nse = :t
              AND statement_type = 'income'
              AND period_type = 'annual'
              AND period_end_date IS NOT NULL
            ORDER BY period_end_date DESC
            LIMIT 1
        """), {"t": db_ticker}).mappings().first()

        bal_row = db.execute(text("""
            SELECT total_assets, current_liabilities
            FROM company_financials
            WHERE ticker_nse = :t
              AND statement_type = 'balance_sheet'
              AND period_type = 'annual'
              AND period_end_date IS NOT NULL
            ORDER BY period_end_date DESC
            LIMIT 1
        """), {"t": db_ticker}).mappings().first()

        ebit = _f(inc_row.get("ebit")) if inc_row else None
        interest = _f(inc_row.get("interest_expense")) if inc_row else None
        ta = _f(bal_row.get("total_assets")) if bal_row else None
        cl = _f(bal_row.get("current_liabilities")) if bal_row else None

        # If company_financials is missing pieces, backfill from
        # `financials` (the NSE XBRL-populated table).
        #
        # ORDER BY quirk: a ticker can have BOTH yfinance rows and
        # NSE_XBRL rows. yfinance periods are often a year NEWER
        # (e.g. 2026-03-31 projected) but missing ebit + current_
        # liabilities. NSE_XBRL rows (e.g. 2024-03-31 actual) have
        # them. A naive `ORDER BY period_end DESC LIMIT 1` picks the
        # yfinance row and comes back all-NULL, failing ROCE.
        #
        # Fix: prefer rows that ACTUALLY CARRY the ROCE denominator
        # (current_liabilities IS NOT NULL), then the freshest within
        # that subset. Falls back to any row if none qualifies.
        if ebit is None or ta is None or cl is None:
            old_row = db.execute(text("""
                SELECT ebit, ebitda, total_assets, current_liabilities
                FROM financials
                WHERE ticker = :t
                  AND period_type = 'annual'
                  AND period_end IS NOT NULL
                ORDER BY
                  (current_liabilities IS NOT NULL) DESC,
                  (total_assets IS NOT NULL) DESC,
                  (ebit IS NOT NULL OR ebitda IS NOT NULL) DESC,
                  period_end DESC
                LIMIT 1
            """), {"t": db_ticker}).mappings().first()
            if old_row:
                if ebit is None:
                    ebit = _f(old_row.get("ebit")) or _f(old_row.get("ebitda"))
                if ta is None:
                    ta = _f(old_row.get("total_assets"))
                if cl is None:
                    cl = _f(old_row.get("current_liabilities"))

        # Diagnostic log — elevated to INFO so we can trace why ROCE
        # ends up None on flagships (DB has the data per manual SQL
        # probe but prod was silently returning None). Drop back to
        # DEBUG once the 50 flagships all compute green.
        import logging as _l
        _l.getLogger("yieldiq.analysis").info(
            "roce inputs for %s (db_ticker=%s): ebit=%s ta=%s cl=%s int=%s "
            "(inc_row=%s bal_row=%s)",
            ticker, db_ticker, ebit, ta, cl, interest,
            "hit" if inc_row else "MISS",
            "hit" if bal_row else "MISS",
        )
        return ebit, ta, cl, interest
    except Exception as exc:
        # Was .debug() — silently swallowed every failure. Elevated so
        # we actually see exceptions. Full traceback too, since the
        # shape of the exception matters for diagnosis.
        import logging as _l
        _l.getLogger("yieldiq.analysis").exception(
            "roce inputs fetch failed for %s: %s: %s",
            ticker, type(exc).__name__, exc,
        )
        return None, None, None, None
    finally:
        try:
            db.close()
        except Exception:
            pass


def _fetch_bank_metrics_inputs(ticker: str) -> dict | None:
    """Fetch the inputs needed for bank-native Prism metrics.

    Returns a dict with up to 4 years of annual income + balance sheet
    data from ``company_financials`` plus the latest ROA/ROE from the
    ``financials`` rollup. All values are Optional — callers decide how
    to degrade.

    Returned shape::

        {
            # Latest period
            "period_end":           "2025-03-31" | None,
            "net_income":           float | None,
            "revenue":              float | None,
            "operating_expense":    float | None,
            "interest_earned":      float | None,  # TODO: XBRL Sch A
            "interest_expended":    float | None,  # TODO: XBRL Sch B
            "total_assets":         float | None,
            "total_liabilities":    float | None,
            "total_equity":         float | None,
            # From `financials` rollup (pre-computed)
            "roa":                  float | None,  # percent
            "roe":                  float | None,  # percent
            # Multi-period series (newest → oldest), for YoY + CAGR
            "revenue_series":       [float, ...],  # up to 4 annual points
            "net_income_series":    [float, ...],
            "total_assets_series":  [float, ...],
            "total_liab_series":    [float, ...],
        }

    Returns ``None`` if the DB is unreachable. Safe to call for any
    ticker — non-banks simply get data back that the caller will not
    use (the caller only reads it when ``_is_bank_like`` is True).
    """
    import logging as _l_top
    _bm_log = _l_top.getLogger("yieldiq.analysis")

    db = _get_pipeline_session()
    if db is None:
        return None
    try:
        from sqlalchemy import text
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")

        def _f(v):
            try:
                return float(v) if v is not None else None
            except (TypeError, ValueError):
                return None

        # Annual income series (up to 4 years, newest first)
        inc_rows = db.execute(text("""
            SELECT period_end_date, revenue, net_income, operating_expense,
                   interest_earned, interest_expended
            FROM company_financials
            WHERE ticker_nse = :t
              AND statement_type = 'income'
              AND period_type = 'annual'
              AND period_end_date IS NOT NULL
            ORDER BY period_end_date DESC
            LIMIT 4
        """), {"t": db_ticker}).mappings().all()

        # Annual balance sheet series
        bal_rows = db.execute(text("""
            SELECT period_end_date, total_assets, total_liabilities,
                   total_equity
            FROM company_financials
            WHERE ticker_nse = :t
              AND statement_type = 'balance_sheet'
              AND period_type = 'annual'
              AND period_end_date IS NOT NULL
            ORDER BY period_end_date DESC
            LIMIT 4
        """), {"t": db_ticker}).mappings().all()

        # Pre-computed ROA/ROE from the `financials` rollup (already
        # normalised to percent upstream).
        fin_row = db.execute(text("""
            SELECT roa, roe, total_assets, total_equity, revenue, pat
            FROM financials
            WHERE ticker = :t
              AND period_type = 'annual'
              AND period_end IS NOT NULL
            ORDER BY period_end DESC
            LIMIT 1
        """), {"t": db_ticker}).mappings().first()

        latest_inc = inc_rows[0] if inc_rows else {}
        latest_bal = bal_rows[0] if bal_rows else {}

        # Revenue from company_financials if present; fall back to
        # `financials.revenue` so HDFCBANK / ICICIBANK (missing opex
        # but present revenue in both tables) still light up.
        rev_latest = _f(latest_inc.get("revenue")) if latest_inc else None
        if rev_latest is None and fin_row:
            rev_latest = _f(fin_row.get("revenue"))

        ni_latest = _f(latest_inc.get("net_income")) if latest_inc else None
        if ni_latest is None and fin_row:
            ni_latest = _f(fin_row.get("pat"))

        ta_latest = _f(latest_bal.get("total_assets")) if latest_bal else None
        if ta_latest is None and fin_row:
            ta_latest = _f(fin_row.get("total_assets"))

        te_latest = _f(latest_bal.get("total_equity")) if latest_bal else None
        if te_latest is None and fin_row:
            te_latest = _f(fin_row.get("total_equity"))

        out = {
            "period_end": (
                str(latest_inc.get("period_end_date"))
                if latest_inc and latest_inc.get("period_end_date")
                else None
            ),
            "net_income": ni_latest,
            "revenue": rev_latest,
            "operating_expense": _f(latest_inc.get("operating_expense")) if latest_inc else None,
            # TODO(NSE-XBRL-Sch-A-B): `interest_earned` / `interest_expended`
            # are not populated by the current ingest — every bank row
            # in company_financials has these as NULL. Wire them here
            # once the Schedule A/B extractor lands in data_pipeline.
            "interest_earned": _f(latest_inc.get("interest_earned")) if latest_inc else None,
            "interest_expended": _f(latest_inc.get("interest_expended")) if latest_inc else None,
            "total_assets": ta_latest,
            "total_liabilities": _f(latest_bal.get("total_liabilities")) if latest_bal else None,
            "total_equity": te_latest,
            "roa": _f(fin_row.get("roa")) if fin_row else None,
            "roe": _f(fin_row.get("roe")) if fin_row else None,
            # Series — newest first
            "revenue_series": [
                _f(r.get("revenue")) for r in inc_rows
                if _f(r.get("revenue")) is not None
            ],
            "net_income_series": [
                _f(r.get("net_income")) for r in inc_rows
                if _f(r.get("net_income")) is not None
            ],
            "total_assets_series": [
                _f(r.get("total_assets")) for r in bal_rows
                if _f(r.get("total_assets")) is not None
            ],
            "total_liab_series": [
                _f(r.get("total_liabilities")) for r in bal_rows
                if _f(r.get("total_liabilities")) is not None
            ],
        }

        _bm_log.info(
            "bank metrics inputs for %s: period=%s rev=%s pat=%s opex=%s "
            "ta=%s tl=%s roa=%s roe=%s inc_rows=%d bal_rows=%d",
            ticker, out["period_end"], out["revenue"], out["net_income"],
            out["operating_expense"], out["total_assets"], out["total_liabilities"],
            out["roa"], out["roe"], len(inc_rows), len(bal_rows),
        )
        return out
    except Exception as exc:
        import logging as _l
        _l.getLogger("yieldiq.analysis").exception(
            "bank metrics fetch failed for %s: %s: %s",
            ticker, type(exc).__name__, exc,
        )
        return None
    finally:
        try:
            db.close()
        except Exception:
            pass


def _query_earnings_date(ticker: str) -> dict | None:
    """Query next earnings date from UpcomingEarnings table."""
    db = _get_pipeline_session()
    if db is None:
        return None
    try:
        from data_pipeline.sources.nse_earnings import get_next_earnings
        return get_next_earnings(ticker, db)
    except Exception:
        return None
    finally:
        db.close()


def _query_bulk_deals(ticker: str, days: int = 90) -> list[dict]:
    """Query recent bulk/block deals from BulkDeal table."""
    db = _get_pipeline_session()
    if db is None:
        return []
    try:
        from data_pipeline.models import BulkDeal
        from sqlalchemy import desc
        from datetime import timedelta
        db_ticker = ticker.replace(".NS", "").replace(".BO", "")
        cutoff = datetime.now().date() - timedelta(days=days)
        rows = (
            db.query(BulkDeal)
            .filter(BulkDeal.ticker == db_ticker, BulkDeal.trade_date >= cutoff)
            .order_by(desc(BulkDeal.trade_date))
            .limit(10)
            .all()
        )
        deals = []
        for r in rows:
            deals.append({
                "date": str(r.trade_date) if r.trade_date else "",
                "client": r.client_name or "",
                "deal_type": r.deal_type or "",
                "qty_lakh": round(float(r.quantity or 0) / 1e5, 2),
                "price": float(r.price or 0),
                "category": r.deal_category or "",
            })
        return deals
    except Exception:
        return []
    finally:
        db.close()
