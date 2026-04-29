"""Backfill annual rows of `financials` — NSE-XBRL-first.

Cascade priority:
  1. ``data_pipeline.sources.nse_xbrl_fundamentals.fetch_ticker_financials``
     — direct NSE XBRL filings, 15+ years of history, consolidated-
     preferred. This is the same path the v48 fundamentals backfill
     used to populate ~3,000 tickers.
  2. yfinance ``Ticker.financials`` — fallback only when NSE returns
     nothing (newly-listed tickers without filings yet, SME-board
     symbols).
  3. Finnhub — kept as final long-tail fallback (only if FINNHUB_API_KEY
     set).

Idempotent UPSERT key: (ticker, period_end, period_type='annual').

Note on units: NSE XBRL parser produces values in CRORES (per-filing
scale-anchored normalisation in ``parse_nse_xbrl``). yfinance returns
raw INR. The DB convention used by ``store_financials`` is CRORES, so
the NSE rows go through the canonical helper while the yfinance fallback
divides by 1e7 before writing.
"""
from __future__ import annotations

import logging
import os
from datetime import date

from sqlalchemy import text

from . import _common as C

logger = logging.getLogger(__name__)


# ── per-row source precedence ────────────────────────────────────────
# Lower rank = higher quality. Used by the UPSERT precedence guard
# below so a later yfinance backfill can NEVER overwrite an existing
# NSE_XBRL row for the same (ticker, period_end, period_type).
# Mirrors db/migrations/006_data_quality_rank.sql.
_RANK_BY_SOURCE = {
    "NSE_XBRL":            10,
    "NSE_XBRL_STANDALONE": 15,
    "NSE_XBRL_SYNTH":      20,
    "BSE_PEERCOMP":        30,
    "BSE_API":             40,
    "finnhub":             50,
    "yfinance":            60,
}


def _rank_for(source: str | None) -> int:
    """Return the precedence rank for a data_source label (default 70)."""
    return _RANK_BY_SOURCE.get(source or "", 70)


# Each updatable column uses the pattern:
#   col = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
#               THEN COALESCE(EXCLUDED.col, financials.col)
#               ELSE financials.col END
# meaning a lower-or-equal rank can write (with COALESCE preserving
# non-null), but a strictly higher (worse) rank can never displace
# the existing value. data_quality_rank itself uses LEAST() so a row's
# rank can only ever improve (decrease).
UPSERT_SQL = text("""
    INSERT INTO financials (
        ticker, period_end, period_type,
        revenue, pat, ebit, cfo, capex, free_cash_flow,
        eps_diluted, total_debt, cash_and_equivalents,
        total_equity, total_assets, roe,
        data_source, data_quality_rank, currency
    ) VALUES (
        :ticker, :period_end, :period_type,
        :revenue, :pat, :ebit, :cfo, :capex, :fcf,
        :eps, :debt, :cash,
        :equity, :total_assets, :roe,
        :data_source, :data_quality_rank, 'INR'
    )
    ON CONFLICT (ticker, period_end, period_type) DO UPDATE SET
        revenue = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
                       THEN COALESCE(EXCLUDED.revenue, financials.revenue)
                       ELSE financials.revenue END,
        pat = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
                   THEN COALESCE(EXCLUDED.pat, financials.pat)
                   ELSE financials.pat END,
        ebit = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
                    THEN COALESCE(EXCLUDED.ebit, financials.ebit)
                    ELSE financials.ebit END,
        cfo = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
                   THEN COALESCE(EXCLUDED.cfo, financials.cfo)
                   ELSE financials.cfo END,
        capex = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
                     THEN COALESCE(EXCLUDED.capex, financials.capex)
                     ELSE financials.capex END,
        free_cash_flow = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
                              THEN COALESCE(EXCLUDED.free_cash_flow, financials.free_cash_flow)
                              ELSE financials.free_cash_flow END,
        eps_diluted = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
                           THEN COALESCE(EXCLUDED.eps_diluted, financials.eps_diluted)
                           ELSE financials.eps_diluted END,
        total_debt = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
                          THEN COALESCE(EXCLUDED.total_debt, financials.total_debt)
                          ELSE financials.total_debt END,
        cash_and_equivalents = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
                                    THEN COALESCE(EXCLUDED.cash_and_equivalents, financials.cash_and_equivalents)
                                    ELSE financials.cash_and_equivalents END,
        total_equity = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
                            THEN COALESCE(EXCLUDED.total_equity, financials.total_equity)
                            ELSE financials.total_equity END,
        total_assets = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
                            THEN COALESCE(EXCLUDED.total_assets, financials.total_assets)
                            ELSE financials.total_assets END,
        roe = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
                   THEN COALESCE(EXCLUDED.roe, financials.roe)
                   ELSE financials.roe END,
        data_source = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
                           THEN COALESCE(EXCLUDED.data_source, financials.data_source)
                           ELSE financials.data_source END,
        data_quality_rank = LEAST(EXCLUDED.data_quality_rank, financials.data_quality_rank)
""")


def _coerce(x) -> float | None:
    try:
        if x is None:
            return None
        f = float(x)
        if f != f:
            return None
        return f
    except (TypeError, ValueError):
        return None


# ── NSE XBRL primary ─────────────────────────────────────────────────

def _from_nse_xbrl(ticker_bare: str) -> list[dict]:
    """Pull annual rows via NSE XBRL filings. Returns canonical (Cr) rows."""
    from data_pipeline.sources.nse_xbrl_fundamentals import fetch_ticker_financials

    rows = fetch_ticker_financials(ticker_bare, max_annual=15, max_quarterly=0)
    out: list[dict] = []
    for r in rows:
        if r.get("period_type") != "annual":
            continue
        pat = _coerce(r.get("pat"))
        equity = _coerce(r.get("total_equity"))
        roe = None
        if pat is not None and equity not in (None, 0):
            raw_roe = (pat / equity) * 100.0
            if -200 <= raw_roe <= 200:
                roe = raw_roe
        cfo = _coerce(r.get("cfo"))
        capex = _coerce(r.get("capex"))
        fcf = (cfo - abs(capex)) if (cfo is not None and capex is not None) else None
        out.append({
            "period_end":  r.get("period_end"),
            "revenue":     _coerce(r.get("revenue")),
            "pat":         pat,
            "ebit":        _coerce(r.get("ebit")),
            "cfo":         cfo,
            "capex":       capex,
            "fcf":         fcf,
            "eps":         _coerce(r.get("eps_diluted")),
            "debt":        _coerce(r.get("total_debt")),
            "cash":        _coerce(r.get("cash")),
            "equity":      equity,
            "total_assets": _coerce(r.get("total_assets")),
            "roe":         roe,
        })
    return out


# ── yfinance fallback ────────────────────────────────────────────────

def _from_yfinance(ticker_yf: str) -> list[dict]:
    """Last-resort yfinance fallback. Converts raw INR -> Cr (/1e7)."""
    import yfinance as yf

    yt = yf.Ticker(ticker_yf)
    income = yt.financials
    balance = yt.balance_sheet
    cashflow = yt.cashflow

    if income is None or income.empty:
        return []

    def _cr(x):
        v = _coerce(x)
        return None if v is None else v / 1e7

    rows: list[dict] = []
    for col in income.columns:
        try:
            pe = col.date() if hasattr(col, "date") else date.fromisoformat(str(col)[:10])
        except Exception:
            continue
        ic = income[col]
        bs = balance[col] if balance is not None and col in balance.columns else None
        cf = cashflow[col] if cashflow is not None and col in cashflow.columns else None

        revenue = _cr(ic.get("Total Revenue"))
        pat = _cr(ic.get("Net Income"))
        ebit = _cr(ic.get("EBIT") or ic.get("Operating Income"))
        eps = _coerce(ic.get("Diluted EPS") or ic.get("Basic EPS"))  # per-share, not scaled
        debt_lt = _cr(bs.get("Long Term Debt") if bs is not None else None) or 0.0
        debt_st = _cr(bs.get("Short Long Term Debt") if bs is not None else None) or 0.0
        debt = (debt_lt + debt_st) or None
        cash = _cr(bs.get("Cash") if bs is not None else None)
        equity = _cr(bs.get("Total Stockholder Equity") if bs is not None else None)
        total_assets = _cr(bs.get("Total Assets") if bs is not None else None)
        cfo = _cr(cf.get("Total Cash From Operating Activities") if cf is not None else None)
        capex = _cr(cf.get("Capital Expenditures") if cf is not None else None)
        fcf = (cfo - abs(capex)) if (cfo is not None and capex is not None) else None
        roe = None
        if pat is not None and equity not in (None, 0):
            raw_roe = (pat / equity) * 100.0
            if -200 <= raw_roe <= 200:
                roe = raw_roe

        rows.append({
            "period_end": pe,
            "revenue": revenue, "pat": pat, "ebit": ebit,
            "cfo": cfo, "capex": capex, "fcf": fcf,
            "eps": eps, "debt": debt, "cash": cash,
            "equity": equity, "total_assets": total_assets, "roe": roe,
        })
    return rows


# ── driver ───────────────────────────────────────────────────────────

def _fetch_one(session_factory):
    def inner(ticker: str) -> dict:
        bare = C.bare(ticker)

        # 1. NSE XBRL first.
        rows, err = C.with_retries(
            lambda: _from_nse_xbrl(bare),
            label=f"nse_xbrl:{bare}",
        )
        source = "nse_xbrl"

        # 2. yfinance fallback only if NSE returned nothing.
        if not rows:
            sym = C.yf_symbol(ticker)
            yf_rows, yf_err = C.with_retries(
                lambda: _from_yfinance(sym),
                label=f"yfinance:{ticker}",
            )
            if yf_rows:
                rows = yf_rows
                source = "yfinance"
                err = None
            elif yf_err and not err:
                err = yf_err

        if not rows and err:
            return {"status": "error", "source": source, "error": err}
        if not rows:
            return {"status": "skip", "source": source, "error": "no annual data"}

        sess = session_factory()
        try:
            for r in rows:
                ds = "NSE_XBRL" if source == "nse_xbrl" else "yfinance"
                sess.execute(UPSERT_SQL, {
                    "ticker": bare,
                    "period_end": r["period_end"],
                    "period_type": "annual",
                    "revenue": r["revenue"], "pat": r["pat"], "ebit": r["ebit"],
                    "cfo": r["cfo"], "capex": r["capex"], "fcf": r["fcf"],
                    "eps": r["eps"], "debt": r["debt"], "cash": r["cash"],
                    "equity": r["equity"], "total_assets": r["total_assets"],
                    "roe": r["roe"],
                    "data_source": ds,
                    "data_quality_rank": _rank_for(ds),
                })
            sess.commit()
        except Exception as e:
            sess.rollback()
            return {"status": "error", "source": source, "error": f"db: {e}"[:200]}
        finally:
            sess.close()
        return {"status": "ok", "source": source, "error": "", "rows": len(rows)}
    return inner


def backfill(tickers: list[str], session_factory, *, dry_run: bool = False) -> C.BackfillReport:
    return C.drive_workers(
        "annual_financials",
        tickers,
        _fetch_one(session_factory),
        workers=3,           # NSE XBRL is heavier per ticker — fewer workers
        sleep_s=0.6,
        dry_run=dry_run,
    )
