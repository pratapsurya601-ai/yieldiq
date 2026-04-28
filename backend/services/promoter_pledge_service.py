"""promoter_pledge_service.py — promoter share-pledge tracking.

Indian governance signal: when a promoter group pledges shares as
collateral for personal/group loans, it's a leading indicator of
distress. Sharp jumps in pledged_pct historically precede price
collapses (RCOM, Zee, Future Retail, Anil Ambani group, etc.).

Data sources
------------
BSE — https://www.bseindia.com/corporates/sastpledge.aspx
    HTML page; can be filtered by scrip code. The "Disclosure under
    Reg. 31(1) and 31(2) of SEBI (SAST) Regulations, 2011" filings
    each publish a row with promoter, encumbered_shares, % of total
    paid-up capital, % of promoter holding, and date.

NSE — https://www.nseindia.com/companies-listing/corporate-filings-pledge
    JSON API behind a cookie-gated front page. Use a session with the
    main NSE landing page primed, then GET
    https://www.nseindia.com/api/corporate-pledgedata?index=equities

Both are public, no API key required. Scraping is in scope for a
follow-up session — this module only provides the read path and
the stub fetchers.

Schema lives in `data_pipeline/migrations/016_promoter_pledges.sql`.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

logger = logging.getLogger("yieldiq.governance.pledge")


# ── Data class ────────────────────────────────────────────────


@dataclass(frozen=True)
class PledgeRow:
    """One snapshot of promoter pledge state for a single ticker."""

    ticker: str
    as_of_date: date
    promoter_group_pct: Optional[float]
    pledged_pct: Optional[float]
    pledged_shares: Optional[int]
    source_url: Optional[str]


# ── DB helpers ────────────────────────────────────────────────


def _get_raw_cursor():
    """Return (conn, cursor) from the shared pipeline engine, or (None, None).

    Mirrors the pattern used in `notifications_service`. Caller MUST
    close both. Returns (None, None) when DATABASE_URL is unset, so
    unit tests can patch this out cleanly.
    """
    try:
        from data_pipeline.db import engine
    except Exception as exc:  # pragma: no cover — only hit in broken envs
        logger.warning("promoter_pledge_service: pipeline engine import failed: %s", exc)
        return None, None
    if engine is None:
        return None, None
    conn = engine.raw_connection()
    cur = conn.cursor()
    return conn, cur


def _row_to_pledge(row: tuple) -> PledgeRow:
    ticker, as_of, prom_pct, pl_pct, pl_shares, source_url = row
    return PledgeRow(
        ticker=ticker,
        as_of_date=as_of,
        promoter_group_pct=float(prom_pct) if prom_pct is not None else None,
        pledged_pct=float(pl_pct) if pl_pct is not None else None,
        pledged_shares=int(pl_shares) if pl_shares is not None else None,
        source_url=source_url,
    )


# ── Public read API ───────────────────────────────────────────


def get_latest_pledge(ticker: str) -> Optional[PledgeRow]:
    """Return the most recent pledge snapshot for `ticker`, or None."""
    conn, cur = _get_raw_cursor()
    if cur is None:
        return None
    try:
        cur.execute(
            """
            SELECT ticker, as_of_date, promoter_group_pct,
                   pledged_pct, pledged_shares, source_url
              FROM promoter_pledges
             WHERE ticker = %s
             ORDER BY as_of_date DESC
             LIMIT 1
            """,
            (ticker,),
        )
        row = cur.fetchone()
        return _row_to_pledge(row) if row else None
    finally:
        cur.close()
        conn.close()


def compute_pledge_change_pp(
    ticker: str, lookback_days: int = 90
) -> Optional[float]:
    """Return percentage-point change in pledged_pct vs `lookback_days` ago.

    Picks the most recent row, then the most recent row whose as_of_date
    is <= (latest - lookback_days). Returns None if either side is
    missing or has a NULL pledged_pct.

    A positive value means the promoter group has *increased* pledging
    over the window — that's the bad direction.
    """
    conn, cur = _get_raw_cursor()
    if cur is None:
        return None
    try:
        cur.execute(
            """
            SELECT as_of_date, pledged_pct
              FROM promoter_pledges
             WHERE ticker = %s
             ORDER BY as_of_date DESC
             LIMIT 1
            """,
            (ticker,),
        )
        latest = cur.fetchone()
        if not latest or latest[1] is None:
            return None
        latest_date, latest_pct = latest

        cutoff = latest_date - timedelta(days=lookback_days)
        cur.execute(
            """
            SELECT as_of_date, pledged_pct
              FROM promoter_pledges
             WHERE ticker = %s
               AND as_of_date <= %s
             ORDER BY as_of_date DESC
             LIMIT 1
            """,
            (ticker, cutoff),
        )
        prior = cur.fetchone()
        if not prior or prior[1] is None:
            return None
        return float(latest_pct) - float(prior[1])
    finally:
        cur.close()
        conn.close()


# ── Stub fetchers (implementation TBD) ───────────────────────


def fetch_from_bse(ticker: str) -> list[PledgeRow]:
    """Fetch pledge disclosures from BSE for a single ticker.

    Source: https://www.bseindia.com/corporates/sastpledge.aspx
    The page is HTML; we'll need to map `ticker` → BSE scrip code
    (already stored in `stocks.bse_code`) and POST the form. The
    response is a tabular HTML; parse with BeautifulSoup.

    Be polite: BSE rate-limits aggressively. Use the same headers
    pattern from `bse_shareholding_service.py` (Mozilla UA, BSE
    Referer/Origin) and 1–2s sleep between calls.

    # TODO: implement scraper — see docs/promoter_pledge_tracking_design.md
    """
    raise NotImplementedError(
        "BSE pledge scraper not yet implemented — see "
        "docs/promoter_pledge_tracking_design.md, follow-up task #1."
    )


def fetch_from_nse(ticker: str) -> list[PledgeRow]:
    """Fetch pledge disclosures from NSE for a single ticker.

    Source: https://www.nseindia.com/companies-listing/corporate-filings-pledge
    Underlying JSON: https://www.nseindia.com/api/corporate-pledgedata?index=equities
    Cookie-gated — must prime a `requests.Session` with a GET to the
    NSE landing page first, then re-use the cookie jar for the API call.

    NSE returns ALL recent pledge disclosures across all tickers in one
    payload, so a smart impl batches: fetch once, group by symbol, write
    in bulk. Don't loop per-ticker.

    # TODO: implement scraper — see docs/promoter_pledge_tracking_design.md
    """
    raise NotImplementedError(
        "NSE pledge scraper not yet implemented — see "
        "docs/promoter_pledge_tracking_design.md, follow-up task #2."
    )
