"""Backfill stocks.industry / stocks.sector — NSE-archive-first.

Cascade priority:
  1. ``nse_sector_constituents`` table (canonical, populated from NSE
     sectoral-index CSVs by ``data_pipeline.sources.nse_sectoral_indices``).
  2. yfinance ``Ticker.info`` — fallback only when NSE has no entry
     (typically micro-caps / SME-board listings not in any sectoral index).

Idempotent UPSERT key: ticker.

Why NSE first: NSE sectoral classification is the authoritative SEBI-
filed view of what a stock _is_ (it gates inclusion in the sectoral
indices that drive ETF flows). yfinance ``.info`` for Indian listings
is wrapped/translated by Yahoo and routinely mis-tags banks, NBFCs and
realty trusts — symptoms we have spent multiple PRs (#187, #188) hot-
fixing in the scoring path.
"""
from __future__ import annotations

from sqlalchemy import text

from . import _common as C


UPDATE_SQL = text("""
    UPDATE stocks
       SET sector             = COALESCE(:sector, sector),
           industry           = COALESCE(:industry, industry),
           nifty_sector_index = COALESCE(:nifty_index, nifty_sector_index),
           updated_at         = now()
     WHERE ticker = :ticker
""")


# Pre-load NSE constituents into a process-local cache the first time
# any worker thread asks for them — avoids 5,500 round-trips for the
# common case where one ticker maps to one row.
_NSE_CACHE: dict[str, dict] | None = None


def _load_nse_cache(session_factory) -> dict[str, dict]:
    """Return ``{ticker: {sector, nifty_index}}`` from nse_sector_constituents.

    A ticker can appear in multiple indices (Nifty Bank + Nifty Private
    Bank for HDFCBANK). We pick the most specific one — Private Bank /
    PSU Bank > Bank, FinService > everything else — but the canonical
    sector label is the same ("Banks" / "Financial Services") so the
    choice only affects ``nifty_sector_index``.
    """
    global _NSE_CACHE
    if _NSE_CACHE is not None:
        return _NSE_CACHE

    priority = {
        # More-specific indices win when a ticker is a member of several.
        "Nifty Private Bank": 3,
        "Nifty PSU Bank":     3,
        "Nifty Bank":         2,
        "Nifty Financial Services": 1,
    }

    sess = session_factory()
    try:
        rows = sess.execute(text("""
            SELECT ticker, nifty_index, canonical_sector
              FROM nse_sector_constituents
        """)).fetchall()
    finally:
        sess.close()

    cache: dict[str, dict] = {}
    for ticker, nifty_index, sector in rows:
        existing = cache.get(ticker)
        my_p = priority.get(nifty_index, 0)
        if existing is None or my_p > priority.get(existing["nifty_index"], 0):
            cache[ticker] = {
                "sector": sector,
                "nifty_index": nifty_index,
            }
    _NSE_CACHE = cache
    return cache


def _yf_info(ticker: str) -> dict:
    """Single yfinance .info call, normalised to (sector, industry)."""
    import yfinance as yf

    info = yf.Ticker(C.yf_symbol(ticker)).info or {}
    return {
        "sector": (info.get("sector") or "").strip() or None,
        "industry": (info.get("industry") or "").strip() or None,
    }


def _fetch_one(session_factory):
    """Closure over session factory + NSE cache."""
    nse = _load_nse_cache(session_factory)

    def inner(ticker: str) -> dict:
        bare = C.bare(ticker)
        sector = industry = nifty_index = None
        source = ""

        # 1. NSE first — zero network cost (cache hit).
        hit = nse.get(bare)
        if hit:
            sector = hit["sector"]
            nifty_index = hit["nifty_index"]
            # Treat the NSE index name as the industry label too — it's
            # more meaningful than yfinance's translated sub-industry
            # (e.g. "Nifty IT" beats "Information Technology Services").
            industry = nifty_index
            source = "nse_sectoral"

        # 2. yfinance fallback when NSE has nothing.
        if sector is None:
            yf_res, err = C.with_retries(
                lambda: _yf_info(ticker), label=f"industry:{ticker}"
            )
            if err and not yf_res:
                return {"status": "error", "source": "yfinance", "error": err}
            if yf_res:
                sector = sector or yf_res.get("sector")
                industry = industry or yf_res.get("industry")
                if sector or industry:
                    source = "yfinance"

        if not (sector or industry):
            return {"status": "skip", "source": source or "all", "error": "no info"}

        sess = session_factory()
        try:
            sess.execute(UPDATE_SQL, {
                "ticker":      bare,
                "sector":      sector,
                "industry":    industry,
                "nifty_index": nifty_index,
            })
            sess.commit()
        except Exception as e:
            sess.rollback()
            return {"status": "error", "source": source, "error": f"db: {e}"[:200]}
        finally:
            sess.close()
        return {"status": "ok", "source": source, "error": ""}
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
