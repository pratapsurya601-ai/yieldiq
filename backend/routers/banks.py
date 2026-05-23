"""banks.py -- bank-specific KPI endpoint.

Phase I-frontend (Block II). Public-read endpoint backing the
BankKpiPanel component on /analysis/[ticker] for tickers in the
PURE_BANK_TICKERS_FOR_DE cohort.

One endpoint:

    GET /api/v1/banks/{ticker}/kpis

Returns the latest-annual snapshot (one row) plus the last-4
quarterly rows per metric, plus the ticker's bank-membership
flag so the frontend can hide the panel safely for non-banks.

Shape::

    {
      "ticker": "HDFCBANK",
      "is_bank": true,
      "latest_annual": {
        "period_end": "2024-03-31",
        "branches_total": 7821,
        "branches_tier1": 3100,
        "branches_tier2": 2700,
        "branches_tier3": 2021,
        "atms_total": 19500,
        "customers_millions": 92.0,
        "gnpa_pct": 1.20,
        "nnpa_pct": 0.30,
        "pcr_pct": 72.5,
        "casa_pct": 38.0,
        "cost_to_income_pct": 40.1,
        "credit_deposit_pct": 87.0,
        "sources": ["bse_xbrl", "ar_anthropic"]
      },
      "quarterly_trend": {
        "gnpa_pct": [
          {"period_end": "2024-12-31", "value": 1.10},
          ...
        ],
        ...
      }
    }

Discipline::

    * Never 5xx -- DB failures collapse to is_bank=true (computed
      from sector_overrides) + null fields.
    * Non-bank tickers return is_bank=false + null fields; the
      frontend renders nothing in that case.
    * No CACHE_VERSION bump (additive surface; manifest entry is
      scoped to ['bank_operational_kpis', 'bank_kpis']).
"""
from __future__ import annotations

import logging
import os
from typing import Any, Optional

from fastapi import APIRouter, HTTPException

logger = logging.getLogger("yieldiq.banks")

router = APIRouter(prefix="/api/v1/banks", tags=["banks"])


_LATEST_ANNUAL_FIELDS: tuple[str, ...] = (
    "branches_total", "branches_tier1", "branches_tier2", "branches_tier3",
    "atms_total", "customers_millions",
    "gnpa_pct", "nnpa_pct", "pcr_pct",
    "casa_pct", "cost_to_income_pct", "credit_deposit_pct",
)

_QUARTERLY_METRICS: tuple[str, ...] = (
    "gnpa_pct", "nnpa_pct", "pcr_pct",
    "casa_pct", "cost_to_income_pct", "credit_deposit_pct",
)


def _bare_ticker(ticker: str) -> str:
    bare = (ticker or "").strip().upper()
    for suffix in (".NS", ".BO", ".BSE", ".NSE"):
        if bare.endswith(suffix):
            bare = bare[: -len(suffix)]
            break
    return bare


def _is_pure_bank(ticker: str) -> bool:
    try:
        from backend.services.analysis.sector_overrides import (
            is_pure_bank_for_de,
        )
        return bool(is_pure_bank_for_de(ticker))
    except Exception:
        return False


def _connect():
    url = os.environ.get("DATABASE_URL")
    if not url:
        return None
    try:
        import psycopg2  # type: ignore
        return psycopg2.connect(url)
    except Exception as exc:
        logger.debug("banks: psycopg2.connect failed (%s)", exc)
        return None


def _empty_payload(ticker: str, is_bank: bool) -> dict:
    return {
        "ticker": ticker,
        "is_bank": is_bank,
        "latest_annual": None,
        "quarterly_trend": {m: [] for m in _QUARTERLY_METRICS},
    }


def _row_to_field_map(row: tuple, columns: tuple[str, ...]) -> dict[str, Any]:
    return dict(zip(columns, row))


def _coerce_number(v) -> Optional[float]:
    if v is None:
        return None
    try:
        return float(v)
    except (TypeError, ValueError):
        return None


def _query_latest_annual(conn, ticker: str) -> Optional[dict]:
    """Merge ALL annual rows for the ticker's most-recent
    period_end across both sources into one snapshot.

    For each field we take the first non-null across source rows;
    this lets the XBRL row contribute its 6 financial fields and
    the AR row contribute its 3 operational fields onto a single
    latest_annual dict.
    """
    with conn.cursor() as cur:
        # Find the latest annual period_end the ticker has any row for.
        cur.execute(
            """
            SELECT MAX(period_end)
              FROM bank_operational_kpis
             WHERE ticker = %s AND period_type = 'annual'
            """,
            (ticker,),
        )
        latest = cur.fetchone()
        if not latest or latest[0] is None:
            # Fall back to most-recent quarterly snapshot if no
            # annual row exists yet (XBRL-only path).
            cur.execute(
                """
                SELECT MAX(period_end)
                  FROM bank_operational_kpis
                 WHERE ticker = %s AND period_type = 'quarterly'
                """,
                (ticker,),
            )
            latest = cur.fetchone()
            if not latest or latest[0] is None:
                return None
            period_type = "quarterly"
        else:
            period_type = "annual"
        period_end = latest[0]

        cols = (
            ", ".join(_LATEST_ANNUAL_FIELDS) + ", source"
        )
        cur.execute(
            f"""
            SELECT {cols}
              FROM bank_operational_kpis
             WHERE ticker = %s AND period_type = %s AND period_end = %s
             ORDER BY source
            """,
            (ticker, period_type, period_end),
        )
        rows = cur.fetchall()
        if not rows:
            return None

    merged: dict[str, Any] = {f: None for f in _LATEST_ANNUAL_FIELDS}
    sources: list[str] = []
    for row in rows:
        mapping = _row_to_field_map(row, _LATEST_ANNUAL_FIELDS + ("source",))
        src = mapping.pop("source", None)
        if src and src not in sources:
            sources.append(src)
        for f, v in mapping.items():
            if merged[f] is None and v is not None:
                merged[f] = _coerce_number(v)
    merged["period_end"] = period_end.isoformat()
    merged["period_type"] = period_type
    merged["sources"] = sources
    return merged


def _query_quarterly_trend(conn, ticker: str, *, limit: int = 4) -> dict[str, list]:
    """Last `limit` quarterly values per metric, newest first.

    Per metric we collapse across sources by taking the
    first-non-null (XBRL source ordered first if present).
    """
    out: dict[str, list] = {m: [] for m in _QUARTERLY_METRICS}
    with conn.cursor() as cur:
        col_list = ", ".join(_QUARTERLY_METRICS)
        cur.execute(
            f"""
            SELECT period_end, source, {col_list}
              FROM bank_operational_kpis
             WHERE ticker = %s AND period_type = 'quarterly'
             ORDER BY period_end DESC, source
            """,
            (ticker,),
        )
        rows = cur.fetchall()

    # Group by period_end, collapse across sources.
    by_period: dict[Any, dict[str, Any]] = {}
    period_order: list[Any] = []
    for row in rows:
        period_end = row[0]
        # row[1] is source (unused for value merging); rest map to _QUARTERLY_METRICS.
        values = dict(zip(_QUARTERLY_METRICS, row[2:]))
        if period_end not in by_period:
            by_period[period_end] = {m: None for m in _QUARTERLY_METRICS}
            period_order.append(period_end)
        for m, v in values.items():
            if by_period[period_end][m] is None and v is not None:
                by_period[period_end][m] = _coerce_number(v)

    # Build per-metric trend lists, newest first, capped at `limit`.
    for m in _QUARTERLY_METRICS:
        series: list[dict] = []
        for pe in period_order:
            v = by_period[pe][m]
            if v is None:
                continue
            series.append({"period_end": pe.isoformat(), "value": v})
            if len(series) >= limit:
                break
        out[m] = series
    return out


@router.get("/{ticker}/kpis")
async def get_bank_kpis(ticker: str):
    """Return latest-annual snapshot + last-4-quarter trend for a bank.

    Always returns 200 (never 5xx on a missing-table / DB-down
    path). For non-bank tickers returns
    {is_bank: false, latest_annual: null, quarterly_trend: {...empty...}}.
    """
    if not ticker:
        raise HTTPException(status_code=400, detail="ticker required")
    bare = _bare_ticker(ticker)
    is_bank = _is_pure_bank(bare)
    if not is_bank:
        # Cheap path: don't even hit the DB.
        return _empty_payload(bare, is_bank=False)

    conn = _connect()
    if conn is None:
        return _empty_payload(bare, is_bank=True)
    try:
        latest = None
        trend: dict[str, list] = {m: [] for m in _QUARTERLY_METRICS}
        try:
            latest = _query_latest_annual(conn, bare)
        except Exception as exc:
            logger.warning("banks.kpis latest_annual(%s) failed: %s", bare, exc)
        try:
            trend = _query_quarterly_trend(conn, bare)
        except Exception as exc:
            logger.warning("banks.kpis quarterly_trend(%s) failed: %s", bare, exc)
        return {
            "ticker": bare,
            "is_bank": True,
            "latest_annual": latest,
            "quarterly_trend": trend,
        }
    finally:
        try:
            conn.close()
        except Exception:
            pass
