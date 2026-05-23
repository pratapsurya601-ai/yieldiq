"""DB loaders for Phase A.2.2 validators.

Mirrors db_loaders_a2.py's conventions: optional conn_factory for
tests, graceful None when DATABASE_URL is unset. Loaders never
compute thresholds — they only fetch the raw counts / samples the
validator needs.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Optional

from .db_loaders import _columns_of, _open_connection, _scalar

logger = logging.getLogger("yieldiq.data_quality.db_loaders_a2_2")


def load_cron_heartbeats_sample(
    conn_factory: Optional[Callable[[], Any]] = None,
) -> Optional[Any]:
    from .validators.cron_heartbeats import (
        CronHeartbeatsSample,
        EXPECTED_WORKFLOWS,
    )

    with _open_connection(conn_factory) as conn:
        if conn is None:
            return None
        with conn.cursor() as cur:
            schema_columns = _columns_of(cur, "cron_heartbeats")
            row_count = int(_scalar(cur, "SELECT COUNT(*) FROM cron_heartbeats") or 0)
            prior_row_count = row_count  # single-row-per-workflow table, no time slice
            heartbeats: dict[str, tuple[Optional[datetime], int]] = {}
            for workflow, expected_interval in EXPECTED_WORKFLOWS.items():
                cur.execute(
                    "SELECT last_success_at, expected_interval_minutes "
                    "FROM cron_heartbeats WHERE workflow_name = %s",
                    (workflow,),
                )
                row = cur.fetchone()
                if row is None:
                    continue
                last_success_at, declared = row
                heartbeats[workflow] = (last_success_at, int(declared or expected_interval))
        return CronHeartbeatsSample(
            row_count=row_count,
            prior_row_count=prior_row_count,
            schema_columns=schema_columns,
            heartbeats=heartbeats,
        )


def load_shareholding_pattern_sample(
    conn_factory: Optional[Callable[[], Any]] = None,
) -> Optional[Any]:
    from .validators.shareholding_pattern import (
        PROMOTER_PCT_BANDS,
        ShareholdingPatternSample,
        SUM_CANARY_TICKERS,
    )

    with _open_connection(conn_factory) as conn:
        if conn is None:
            return None
        with conn.cursor() as cur:
            schema_columns = _columns_of(cur, "shareholding_pattern")
            row_count = int(_scalar(cur, "SELECT COUNT(*) FROM shareholding_pattern") or 0)
            prior_row_count = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM shareholding_pattern "
                "WHERE quarter_end <= (CURRENT_DATE - INTERVAL '90 days')",
            ) or 0)
            last_update_date = _scalar(
                cur, "SELECT MAX(quarter_end) FROM shareholding_pattern"
            )
            last_update: Optional[datetime] = None
            if last_update_date is not None:
                if isinstance(last_update_date, datetime):
                    last_update = last_update_date
                else:
                    last_update = datetime(
                        last_update_date.year,
                        last_update_date.month,
                        last_update_date.day,
                    )

            latest_pcts: dict[str, dict[str, Optional[float]]] = {}
            wanted = set(SUM_CANARY_TICKERS) | set(PROMOTER_PCT_BANDS.keys())
            for ticker in wanted:
                cur.execute(
                    "SELECT promoter_pct, fii_pct, dii_pct, public_pct "
                    "FROM shareholding_pattern WHERE ticker = %s "
                    "ORDER BY quarter_end DESC LIMIT 1",
                    (ticker,),
                )
                row = cur.fetchone()
                if row is None:
                    latest_pcts[ticker] = {}
                    continue
                latest_pcts[ticker] = {
                    "promoter_pct": row[0],
                    "fii_pct": row[1],
                    "dii_pct": row[2],
                    "public_pct": row[3],
                }

        return ShareholdingPatternSample(
            row_count=row_count,
            prior_row_count=prior_row_count,
            schema_columns=schema_columns,
            last_update=last_update,
            latest_pcts=latest_pcts,
        )


def load_company_quarterly_results_sample(
    conn_factory: Optional[Callable[[], Any]] = None,
) -> Optional[Any]:
    from .validators.company_quarterly_results import (
        CANARY_TICKERS,
        CompanyQuarterlyResultsSample,
    )

    with _open_connection(conn_factory) as conn:
        if conn is None:
            return None
        with conn.cursor() as cur:
            schema_columns = _columns_of(cur, "company_quarterly_results")
            row_count = int(_scalar(cur, "SELECT COUNT(*) FROM company_quarterly_results") or 0)
            prior_row_count = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM company_quarterly_results "
                "WHERE period_end <= (CURRENT_DATE - INTERVAL '90 days')",
            ) or 0)
            last_update = _scalar(cur, "SELECT MAX(period_end) FROM company_quarterly_results")
            if last_update is not None and not isinstance(last_update, datetime):
                last_update = datetime(last_update.year, last_update.month, last_update.day)

            canary_latest_period_end: dict[str, Optional[datetime]] = {}
            revenue_null_count = 0
            revenue_sample_size = 0
            profit_null_count = 0
            profit_sample_size = 0
            for ticker in CANARY_TICKERS:
                latest = _scalar(
                    cur,
                    "SELECT MAX(period_end) FROM company_quarterly_results "
                    "WHERE ticker = %s",
                    (ticker,),
                )
                canary_latest_period_end[ticker] = latest

                cur.execute(
                    "SELECT revenue_cr, net_profit_cr FROM company_quarterly_results "
                    "WHERE ticker = %s ORDER BY period_end DESC LIMIT 4",
                    (ticker,),
                )
                for row in cur.fetchall():
                    revenue_sample_size += 1
                    profit_sample_size += 1
                    if row[0] is None:
                        revenue_null_count += 1
                    if row[1] is None:
                        profit_null_count += 1

            hdfcbank_latest_revenue_cr = _scalar(
                cur,
                "SELECT revenue_cr FROM company_quarterly_results "
                "WHERE ticker = %s ORDER BY period_end DESC LIMIT 1",
                ("HDFCBANK",),
            )
            if hdfcbank_latest_revenue_cr is not None:
                hdfcbank_latest_revenue_cr = float(hdfcbank_latest_revenue_cr)

        return CompanyQuarterlyResultsSample(
            row_count=row_count,
            prior_row_count=prior_row_count,
            schema_columns=schema_columns,
            last_update=last_update,
            canary_latest_period_end=canary_latest_period_end,
            revenue_null_count=revenue_null_count,
            revenue_sample_size=revenue_sample_size,
            profit_null_count=profit_null_count,
            profit_sample_size=profit_sample_size,
            hdfcbank_latest_revenue_cr=hdfcbank_latest_revenue_cr,
        )


__all__ = [
    "load_cron_heartbeats_sample",
    "load_shareholding_pattern_sample",
    "load_company_quarterly_results_sample",
]
