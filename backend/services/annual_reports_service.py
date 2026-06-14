# backend/services/annual_reports_service.py
# ===============================================================
# Annual-reports INDEX service.
#
# This service returns the per-ticker list of annual report PDF
# links (one row per fiscal year) used by AnnualReportsPanel on
# the analysis page.
#
# Day-103d refactor (2026-05-22):
#   The Day-103b agent shipped a brand-new `annual_reports` table
#   without realising `company_annual_reports` (migration 027)
#   already covered this need (plus a Claude-extracted structured
#   layer on top). We now read from the canonical table and the
#   duplicate is dropped in migration 053. Column mapping:
#       fiscal_year ← fiscal_year
#       filed_date  ← published_at  (renamed; same meaning)
#       source_url  ← ar_url
# ===============================================================
from __future__ import annotations

import logging
import os
from typing import Any, Optional

logger = logging.getLogger("yieldiq.annual_reports")


def _connect():
    """Open a psycopg2 connection. Returns None if DATABASE_URL is
    unset or the connect fails -- callers must handle the None.
    Same pattern as backend/services/concall_intel_service.py."""
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg2  # type: ignore
        return psycopg2.connect(url)
    except Exception as exc:
        logger.debug("annual_reports: psycopg2.connect failed (%s)", exc)
        return None


def list_annual_reports(
    ticker: str,
    limit: int = 15,
    conn: Optional[Any] = None,
) -> list[dict]:
    """Return annual report links for `ticker`, newest fiscal year first.

    Args:
        ticker: NSE/BSE ticker symbol (case-insensitive; we upper-case).
        limit: Maximum rows to return. Caller can request more for an
            "all years" view; default 15 covers FY12..FY26.
        conn: Optional pre-opened psycopg2 connection (used by tests
            so we don't rely on DATABASE_URL).

    Returns:
        A list of dicts of shape::

            {"fiscal_year": int,
             "filed_date":  "YYYY-MM-DD" | None,
             "source_url":  str}

        Empty list for unknown tickers — does NOT raise.
    """
    if not ticker or not isinstance(ticker, str):
        return []
    if not isinstance(limit, int) or limit <= 0:
        limit = 15
    # Cap the limit so a misconfigured caller can't sweep the table.
    limit = min(limit, 100)

    t = ticker.strip().upper()
    if not t:
        return []
    # Suffix-tolerant matching: company_annual_reports stores the BARE
    # ticker ("RELIANCE") while callers pass the .NS-suffixed form
    # ("RELIANCE.NS"), so an exact `ticker = %s` match returned [] for
    # every NSE name. Strip .NS/.BO and match the bare + both suffixed
    # forms — identical to get_latest_signals_for_ticker in
    # backend/routers/annual_reports.py (the AR-signals endpoint).
    bare = t
    for suffix in (".NS", ".BO"):
        if bare.endswith(suffix):
            bare = bare[: -len(suffix)]
            break

    owns_conn = False
    if conn is None:
        conn = _connect()
        owns_conn = True
    if conn is None:
        # No DATABASE_URL / connect failed — surface an empty list so
        # the UI degrades gracefully (Day-102 audit explicitly calls
        # for SEBI-safe empty states, not 500s).
        return []

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT fiscal_year, published_at, ar_url
                  FROM company_annual_reports
                 WHERE ticker IN (%s, %s, %s)
                 ORDER BY fiscal_year DESC
                 LIMIT %s
                """,
                (bare, f"{bare}.NS", f"{bare}.BO", limit),
            )
            rows = cur.fetchall() or []
    except Exception as exc:
        logger.warning("list_annual_reports query failed for %s: %s", t, exc)
        return []
    finally:
        if owns_conn:
            try:
                conn.close()
            except Exception:
                pass

    out: list[dict] = []
    for fy, filed_date, source_url in rows:
        # psycopg2 hands us datetime.date; the SQLite test shim hands us
        # an ISO string already. Normalise to "YYYY-MM-DD" | None.
        if filed_date is None:
            iso = None
        elif hasattr(filed_date, "isoformat"):
            iso = filed_date.isoformat()
        else:
            iso = str(filed_date)
        out.append({
            "fiscal_year": int(fy),
            "filed_date": iso,
            "source_url": source_url,
        })
    return out
