"""Backfill stocks.industry / stocks.sector from yfinance .info.

Cascade:
  1. yfinance Ticker(.NS).info -> "industry" / "sector"
  2. Fallback NSE indices map (TODO: requires nifty_sector_index loader,
     not blocking — the audit currently only flags missing yfinance data).

Idempotent UPSERT key: ticker.
"""
from __future__ import annotations

from sqlalchemy import text

from . import _common as C


UPDATE_SQL = text("""
    UPDATE stocks
       SET sector     = COALESCE(:sector, sector),
           industry   = COALESCE(:industry, industry),
           updated_at = now()
     WHERE ticker = :ticker
""")


def _yf_info(ticker: str) -> dict:
    """Single yfinance .info call, normalised to (sector, industry)."""
    import yfinance as yf  # local import — keeps non-yf workers light

    info = yf.Ticker(C.yf_symbol(ticker)).info or {}
    return {
        "sector": (info.get("sector") or "").strip() or None,
        "industry": (info.get("industry") or "").strip() or None,
    }


def _fetch_one(session_factory):
    """Return a closure over the SQLAlchemy session factory.

    We open a fresh short-lived session per ticker — keeps the connection
    pool small and avoids long-running transactions while we wait on yf.
    """
    def inner(ticker: str) -> dict:
        result, err = C.with_retries(lambda: _yf_info(ticker), label=f"industry:{ticker}")
        if err:
            return {"status": "error", "source": "yfinance", "error": err}
        if not result or (not result.get("sector") and not result.get("industry")):
            return {"status": "skip", "source": "yfinance", "error": "no info"}
        sess = session_factory()
        try:
            sess.execute(
                UPDATE_SQL,
                {"ticker": C.bare(ticker),
                 "sector": result.get("sector"),
                 "industry": result.get("industry")},
            )
            sess.commit()
        except Exception as e:
            sess.rollback()
            return {"status": "error", "source": "yfinance", "error": f"db: {e}"[:200]}
        finally:
            sess.close()
        return {"status": "ok", "source": "yfinance", "error": ""}
    return inner


def backfill(tickers: list[str], session_factory, *, dry_run: bool = False) -> C.BackfillReport:
    return C.drive_workers(
        "industry",
        tickers,
        _fetch_one(session_factory),
        workers=5,
        sleep_s=0.4,
        dry_run=dry_run,
    )
