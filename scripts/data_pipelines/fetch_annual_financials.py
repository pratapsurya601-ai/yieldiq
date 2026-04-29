"""Backfill annual rows of `financials` from yfinance.

Cascade:
  1. yfinance Ticker.financials / .balance_sheet / .cashflow (annual)
  2. Finnhub /stock/financials-reported (only if FINNHUB_API_KEY set)

Idempotent UPSERT key: (ticker, period_end, period_type='ANNUAL').
"""
from __future__ import annotations

import os
from datetime import date

from sqlalchemy import text

from . import _common as C


UPSERT_SQL = text("""
    INSERT INTO financials (
        ticker, period_end, period_type,
        revenue, pat, ebit, cfo, capex, free_cash_flow,
        eps_diluted, total_debt, cash_and_equivalents,
        total_equity, total_assets, roe,
        data_source, currency
    ) VALUES (
        :ticker, :period_end, 'ANNUAL',
        :revenue, :pat, :ebit, :cfo, :capex, :fcf,
        :eps, :debt, :cash,
        :equity, :total_assets, :roe,
        :data_source, 'INR'
    )
    ON CONFLICT (ticker, period_end, period_type) DO UPDATE SET
        revenue              = COALESCE(EXCLUDED.revenue, financials.revenue),
        pat                  = COALESCE(EXCLUDED.pat, financials.pat),
        ebit                 = COALESCE(EXCLUDED.ebit, financials.ebit),
        cfo                  = COALESCE(EXCLUDED.cfo, financials.cfo),
        capex                = COALESCE(EXCLUDED.capex, financials.capex),
        free_cash_flow       = COALESCE(EXCLUDED.free_cash_flow, financials.free_cash_flow),
        eps_diluted          = COALESCE(EXCLUDED.eps_diluted, financials.eps_diluted),
        total_debt           = COALESCE(EXCLUDED.total_debt, financials.total_debt),
        cash_and_equivalents = COALESCE(EXCLUDED.cash_and_equivalents, financials.cash_and_equivalents),
        total_equity         = COALESCE(EXCLUDED.total_equity, financials.total_equity),
        total_assets         = COALESCE(EXCLUDED.total_assets, financials.total_assets),
        roe                  = COALESCE(EXCLUDED.roe, financials.roe),
        data_source          = COALESCE(EXCLUDED.data_source, financials.data_source)
""")


def _coerce(x) -> float | None:
    """yfinance gives floats, NaN, or None. Sometimes pandas Series."""
    try:
        if x is None:
            return None
        f = float(x)
        if f != f:           # NaN
            return None
        return f
    except (TypeError, ValueError):
        return None


def _from_yfinance(ticker_yf: str) -> list[dict]:
    """Pull annual rows. Returns list of period dicts (one per fiscal year)."""
    import yfinance as yf

    yt = yf.Ticker(ticker_yf)
    income = yt.financials                # cols=period_end, rows=line items
    balance = yt.balance_sheet
    cashflow = yt.cashflow

    if income is None or income.empty:
        return []

    rows: list[dict] = []
    for col in income.columns:
        try:
            pe = col.date() if hasattr(col, "date") else date.fromisoformat(str(col)[:10])
        except Exception:
            continue
        ic = income[col]
        bs = balance[col] if balance is not None and col in balance.columns else None
        cf = cashflow[col] if cashflow is not None and col in cashflow.columns else None

        revenue = _coerce(ic.get("Total Revenue"))
        pat = _coerce(ic.get("Net Income"))
        ebit = _coerce(ic.get("EBIT") or ic.get("Operating Income"))
        eps = _coerce(ic.get("Diluted EPS") or ic.get("Basic EPS"))
        debt_lt = _coerce(bs.get("Long Term Debt") if bs is not None else None) or 0.0
        debt_st = _coerce(bs.get("Short Long Term Debt") if bs is not None else None) or 0.0
        debt = (debt_lt + debt_st) or None
        cash = _coerce(bs.get("Cash") if bs is not None else None)
        equity = _coerce(bs.get("Total Stockholder Equity") if bs is not None else None)
        total_assets = _coerce(bs.get("Total Assets") if bs is not None else None)
        cfo = _coerce(cf.get("Total Cash From Operating Activities") if cf is not None else None)
        capex = _coerce(cf.get("Capital Expenditures") if cf is not None else None)
        fcf = (cfo - abs(capex)) if (cfo is not None and capex is not None) else None
        roe = (pat / equity) if (pat is not None and equity not in (None, 0)) else None

        # yfinance is in raw INR. The DB convention here is "raw INR" (not crores)
        # — confirm with existing rows before changing.
        rows.append({
            "period_end": pe,
            "revenue": revenue, "pat": pat, "ebit": ebit,
            "cfo": cfo, "capex": capex, "fcf": fcf,
            "eps": eps, "debt": debt, "cash": cash,
            "equity": equity, "total_assets": total_assets, "roe": roe,
        })
    return rows


def _from_finnhub(ticker_yf: str) -> list[dict]:
    """Optional fallback. Only fires if FINNHUB_API_KEY is set."""
    api_key = os.environ.get("FINNHUB_API_KEY")
    if not api_key:
        return []
    import urllib.parse
    import urllib.request
    import json

    sym = ticker_yf.replace(".NS", ".NS")  # finnhub uses .NS too for NSE
    url = (
        "https://finnhub.io/api/v1/stock/financials-reported"
        f"?symbol={urllib.parse.quote(sym)}&freq=annual&token={api_key}"
    )
    try:
        with urllib.request.urlopen(url, timeout=20) as resp:
            data = json.loads(resp.read())
    except Exception:
        return []
    rows: list[dict] = []
    for entry in (data.get("data") or [])[:10]:
        try:
            pe = date.fromisoformat(entry["endDate"][:10])
        except Exception:
            continue
        # Finnhub layout is deeply nested — leaving this stubbed (returns
        # empty) keeps yfinance authoritative until we have a labelled
        # mapping. Fallback presence still avoids a hard error path.
        _ = pe   # noqa: F841
    return rows


def _fetch_one(session_factory):
    def inner(ticker: str) -> dict:
        sym = C.yf_symbol(ticker)
        rows, err = C.with_retries(lambda: _from_yfinance(sym),
                                   label=f"financials:{ticker}")
        source = "yfinance"
        if not rows and not err:
            rows = _from_finnhub(sym)
            source = "finnhub" if rows else source
        if err and not rows:
            return {"status": "error", "source": source, "error": err}
        if not rows:
            return {"status": "skip", "source": source, "error": "no annual data"}

        sess = session_factory()
        try:
            for r in rows:
                sess.execute(UPSERT_SQL, {
                    "ticker": C.bare(ticker),
                    "period_end": r["period_end"],
                    "revenue": r["revenue"], "pat": r["pat"], "ebit": r["ebit"],
                    "cfo": r["cfo"], "capex": r["capex"], "fcf": r["fcf"],
                    "eps": r["eps"], "debt": r["debt"], "cash": r["cash"],
                    "equity": r["equity"], "total_assets": r["total_assets"],
                    "roe": r["roe"], "data_source": source,
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
        workers=5,
        sleep_s=0.5,
        dry_run=dry_run,
    )
