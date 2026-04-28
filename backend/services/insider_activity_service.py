"""
insider_activity_service.py — query helpers for the governance pillar.

Reads from the two scaffolded tables created by
`backend/migrations/016_create_insider_activity.sql`:

  - bulk_block_deals       (NSE + BSE bulk / block trade reports)
  - insider_transactions   (SEBI Reg 7 / PIT insider filings)

The ingest scripts (scripts/ingest_bulk_block_deals.py,
scripts/ingest_insider_txns.py) write to these tables; this service is
the read-side. Nothing in here scrapes the network — it is pure DB
access plus aggregation.

Related existing code (DO NOT confuse):
  - data_pipeline/sources/nse_bulk_deals.py writes to the legacy
    `bulk_deals` ORM table (different schema). Once Task 8 ships the
    full ingest, that path is deprecated. See
    docs/insider_activity_design.md, open question #1.
  - backend/services/sebi_sast_service.py fetches NSE PIT live every
    pulse run and aggregates in-memory. Once `insider_transactions` is
    populated daily, the pulse pipeline should switch to
    `summarize_insider_activity()` here.

Public API (foundation only — no API router wired yet):
  - get_recent_bulk_block(ticker, days=90) -> list[dict]
  - get_recent_insider_txns(ticker, days=180) -> list[dict]
  - summarize_insider_activity(ticker) -> dict
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta
from typing import Any, Dict, Iterable, List, Optional, Sequence

logger = logging.getLogger("yieldiq.insider_activity")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Storage abstraction
# ---------------------------------------------------------------------------
#
# Production reads from Postgres (Neon). Tests inject an in-memory list of
# dicts via the `rows` parameter so we don't need a live DB. This keeps the
# service code pure-Python and the test suite hermetic.


def _filter_recent(
    rows: Iterable[Dict[str, Any]],
    *,
    ticker: str,
    date_field: str,
    days: int,
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    today = today or date.today()
    cutoff = today - timedelta(days=max(1, int(days)))
    t = (ticker or "").upper().strip()
    out: List[Dict[str, Any]] = []
    for r in rows:
        if not isinstance(r, dict):
            continue
        if str(r.get("ticker", "")).upper().strip() != t:
            continue
        d = r.get(date_field)
        if isinstance(d, str):
            try:
                d = datetime.strptime(d, "%Y-%m-%d").date()
            except ValueError:
                continue
        if not isinstance(d, date):
            continue
        if d < cutoff:
            continue
        out.append(r)
    out.sort(key=lambda r: r.get(date_field) or date.min, reverse=True)
    return out


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def get_recent_bulk_block(
    ticker: str,
    days: int = 90,
    *,
    rows: Optional[Sequence[Dict[str, Any]]] = None,
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Return bulk + block deal rows for `ticker` in the last `days`.

    `rows` is an optional in-memory source for tests / fixtures. In
    production this argument is omitted and the function loads from
    Postgres (TODO once a session helper is wired in — see
    docs/insider_activity_design.md, open question #2).
    """
    if rows is None:
        rows = _load_bulk_block_from_db(ticker=ticker, days=days)
    return _filter_recent(
        rows, ticker=ticker, date_field="deal_date", days=days, today=today
    )


def get_recent_insider_txns(
    ticker: str,
    days: int = 180,
    *,
    rows: Optional[Sequence[Dict[str, Any]]] = None,
    today: Optional[date] = None,
) -> List[Dict[str, Any]]:
    """Return SEBI insider filings for `ticker` in the last `days`."""
    if rows is None:
        rows = _load_insider_from_db(ticker=ticker, days=days)
    return _filter_recent(
        rows, ticker=ticker, date_field="filing_date", days=days, today=today
    )


def summarize_insider_activity(
    ticker: str,
    *,
    bulk_block_rows: Optional[Sequence[Dict[str, Any]]] = None,
    insider_rows: Optional[Sequence[Dict[str, Any]]] = None,
    today: Optional[date] = None,
) -> Dict[str, Any]:
    """High-level aggregate over the last 90 days (deals) / 180 days (insider).

    Returns a dict shaped like:

      {
        "ticker": "RELIANCE",
        "bulk_block": {
            "count": 4, "buy_count": 3, "sell_count": 1,
            "net_quantity": 120000, "net_value_inr": 36500000.0,
        },
        "insider": {
            "count": 7, "buy_count": 2, "sell_count": 5,
            "net_value_inr": -12300000.0,
            "promoter_count": 1, "director_count": 4, "kmp_count": 2,
        },
      }

    Net value is signed: buys positive, sells negative. INR (not Cr).
    """
    bb = get_recent_bulk_block(
        ticker, days=90, rows=bulk_block_rows, today=today
    )
    ins = get_recent_insider_txns(
        ticker, days=180, rows=insider_rows, today=today
    )

    bb_summary = {
        "count": len(bb),
        "buy_count": sum(1 for r in bb if r.get("buy_sell") == "B"),
        "sell_count": sum(1 for r in bb if r.get("buy_sell") == "S"),
        "net_quantity": 0,
        "net_value_inr": 0.0,
    }
    for r in bb:
        qty = int(r.get("quantity") or 0)
        price = float(r.get("price") or 0.0)
        sign = 1 if r.get("buy_sell") == "B" else -1 if r.get("buy_sell") == "S" else 0
        bb_summary["net_quantity"] += sign * qty
        bb_summary["net_value_inr"] += sign * qty * price

    ins_summary = {
        "count": len(ins),
        "buy_count": sum(1 for r in ins if r.get("buy_sell") == "B"),
        "sell_count": sum(1 for r in ins if r.get("buy_sell") == "S"),
        "net_value_inr": 0.0,
        "promoter_count": sum(
            1 for r in ins if (r.get("insider_role") or "").lower() == "promoter"
        ),
        "director_count": sum(
            1 for r in ins if (r.get("insider_role") or "").lower() == "director"
        ),
        "kmp_count": sum(
            1 for r in ins if (r.get("insider_role") or "").lower() == "kmp"
        ),
    }
    for r in ins:
        val = float(r.get("value_inr") or 0.0)
        sign = 1 if r.get("buy_sell") == "B" else -1 if r.get("buy_sell") == "S" else 0
        ins_summary["net_value_inr"] += sign * val

    return {
        "ticker": (ticker or "").upper().strip(),
        "bulk_block": bb_summary,
        "insider": ins_summary,
    }


# ---------------------------------------------------------------------------
# DB loaders — stubs. Hooked up once the ingest scripts populate the
# tables on Neon. Currently return [] so the public API degrades to
# "no activity" rather than 500-ing.
# ---------------------------------------------------------------------------


def _load_bulk_block_from_db(*, ticker: str, days: int) -> List[Dict[str, Any]]:
    # TODO: hook into backend.services.local_data_service or a dedicated
    # SQLAlchemy session. Tracked in docs/insider_activity_design.md.
    logger.debug(
        "bulk_block DB load not wired yet (ticker=%s days=%s)", ticker, days
    )
    return []


def _load_insider_from_db(*, ticker: str, days: int) -> List[Dict[str, Any]]:
    # TODO: see _load_bulk_block_from_db.
    logger.debug(
        "insider DB load not wired yet (ticker=%s days=%s)", ticker, days
    )
    return []
