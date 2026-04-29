"""Backfill corporate_actions from yfinance dividends / splits feed.

Cascade:
  1. yfinance Ticker.splits + Ticker.dividends

Strategy: clear existing rows for the ticker, then re-insert from yf
(yfinance is authoritative for splits/divs). Cheaper than a true UPSERT
because (ticker, ex_date, action_type) isn't unique-indexed and yf
includes everything historic in one shot.
"""
from __future__ import annotations

from datetime import date

from sqlalchemy import text

from . import _common as C


DELETE_SQL = text("DELETE FROM corporate_actions WHERE ticker = :ticker")
INSERT_SQL = text("""
    INSERT INTO corporate_actions
        (ticker, action_type, ex_date, ratio, remarks, adjustment_factor)
    VALUES
        (:ticker, :action_type, :ex_date, :ratio, :remarks, :adjustment_factor)
""")


def _from_yfinance(ticker_yf: str) -> list[dict]:
    import yfinance as yf
    yt = yf.Ticker(ticker_yf)
    splits = yt.splits
    divs = yt.dividends

    rows: list[dict] = []
    if splits is not None and len(splits) > 0:
        for ex, factor in splits.items():
            try:
                ex_d = ex.date() if hasattr(ex, "date") else date.fromisoformat(str(ex)[:10])
                f = float(factor)
            except Exception:
                continue
            if f <= 0 or f > 100:
                continue
            rows.append({
                "action_type": "SPLIT" if f < 1 else "BONUS_OR_SPLIT",
                "ex_date": ex_d,
                "ratio": f"factor={f:g}",
                "remarks": f"yfinance splits: {f:g}",
                "adjustment_factor": f,
            })
    if divs is not None and len(divs) > 0:
        for ex, amt in divs.items():
            try:
                ex_d = ex.date() if hasattr(ex, "date") else date.fromisoformat(str(ex)[:10])
                a = float(amt)
            except Exception:
                continue
            if a <= 0:
                continue
            rows.append({
                "action_type": "DIVIDEND",
                "ex_date": ex_d,
                "ratio": f"Rs {a:.4f}",
                "remarks": f"yfinance dividend Rs {a:.4f}",
                "adjustment_factor": 1.0,
            })
    return rows


def _fetch_one(session_factory):
    def inner(ticker: str) -> dict:
        sym = C.yf_symbol(ticker)
        rows, err = C.with_retries(lambda: _from_yfinance(sym),
                                   label=f"corp_actions:{ticker}")
        if err and not rows:
            return {"status": "error", "source": "yfinance", "error": err}
        if not rows:
            return {"status": "skip", "source": "yfinance", "error": "no actions"}
        bare = C.bare(ticker)
        sess = session_factory()
        try:
            sess.execute(DELETE_SQL, {"ticker": bare})
            for r in rows:
                sess.execute(INSERT_SQL, {"ticker": bare, **r})
            sess.commit()
        except Exception as e:
            sess.rollback()
            return {"status": "error", "source": "yfinance", "error": f"db: {e}"[:200]}
        finally:
            sess.close()
        return {"status": "ok", "source": "yfinance", "rows": len(rows), "error": ""}
    return inner


def backfill(tickers: list[str], session_factory, *, dry_run: bool = False) -> C.BackfillReport:
    return C.drive_workers(
        "corporate_actions",
        tickers,
        _fetch_one(session_factory),
        workers=5,
        sleep_s=0.5,
        dry_run=dry_run,
    )
