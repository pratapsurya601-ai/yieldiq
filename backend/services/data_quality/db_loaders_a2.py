"""DB loaders for Phase A.2.1 validators.

Kept separate from db_loaders.py so the A.1 reference loaders stay
untouched and easy to review. Same conventions: optional conn_factory
for tests, gracefully return None when DATABASE_URL is unset.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any, Callable, Optional

from .db_loaders import _columns_of, _open_connection, _scalar

logger = logging.getLogger("yieldiq.data_quality.db_loaders_a2")


def load_corporate_actions_sample(conn_factory: Optional[Callable[[], Any]] = None) -> Optional[Any]:
    from .validators.corporate_actions import (
        CANARY_TICKERS_WITH_ACTIONS,
        CorporateActionsSample,
    )

    with _open_connection(conn_factory) as conn:
        if conn is None:
            return None
        with conn.cursor() as cur:
            schema_columns = _columns_of(cur, "corporate_actions")
            row_count = int(_scalar(cur, "SELECT COUNT(*) FROM corporate_actions") or 0)
            prior_row_count = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM corporate_actions "
                "WHERE ex_date <= (CURRENT_DATE - INTERVAL '1 day')",
            ) or 0)
            last_update: Optional[datetime] = _scalar(
                cur,
                "SELECT MAX(ex_date)::timestamp FROM corporate_actions",
            )

            split_or_bonus_count: dict[str, int] = {}
            for ticker in CANARY_TICKERS_WITH_ACTIONS:
                split_or_bonus_count[ticker] = int(_scalar(
                    cur,
                    "SELECT COUNT(*) FROM corporate_actions "
                    "WHERE ticker = %s "
                    "AND (UPPER(action_type) LIKE %s OR UPPER(action_type) LIKE %s)",
                    (ticker, "%SPLIT%", "%BONUS%"),
                ) or 0)

            adj_factor_split_bonus_sample_size = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM corporate_actions "
                "WHERE (UPPER(action_type) LIKE %s OR UPPER(action_type) LIKE %s)",
                ("%SPLIT%", "%BONUS%"),
            ) or 0)
            adj_factor_split_bonus_null_count = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM corporate_actions "
                "WHERE (UPPER(action_type) LIKE %s OR UPPER(action_type) LIKE %s) "
                "AND adjustment_factor IS NULL",
                ("%SPLIT%", "%BONUS%"),
            ) or 0)

            rank_sample_size = row_count
            rank_null_count = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM corporate_actions WHERE data_quality_rank IS NULL",
            ) or 0)

        return CorporateActionsSample(
            row_count=row_count,
            prior_row_count=prior_row_count,
            schema_columns=schema_columns,
            last_update=last_update,
            split_or_bonus_count=split_or_bonus_count,
            adj_factor_split_bonus_null_count=adj_factor_split_bonus_null_count,
            adj_factor_split_bonus_sample_size=adj_factor_split_bonus_sample_size,
            rank_null_count=rank_null_count,
            rank_sample_size=rank_sample_size,
        )


def load_consensus_estimates_sample(conn_factory: Optional[Callable[[], Any]] = None) -> Optional[Any]:
    from .validators.consensus_estimates import (
        CANARY_TICKERS_WITH_COVERAGE,
        ConsensusEstimatesSample,
    )

    with _open_connection(conn_factory) as conn:
        if conn is None:
            return None
        with conn.cursor() as cur:
            schema_columns = _columns_of(cur, "consensus_estimates")
            rows_in_last_24h = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM consensus_estimates "
                "WHERE fetched_at >= (now() - INTERVAL '24 hours')",
            ) or 0)
            last_fetched_at: Optional[datetime] = _scalar(
                cur,
                "SELECT MAX(fetched_at) FROM consensus_estimates",
            )
            # Sample target_mean nulls over the latest 5k rows
            target_mean_sample_size = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM ("
                "  SELECT 1 FROM consensus_estimates ORDER BY fetched_at DESC LIMIT 5000"
                ") s",
            ) or 0)
            target_mean_null_count = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM ("
                "  SELECT target_mean FROM consensus_estimates ORDER BY fetched_at DESC LIMIT 5000"
                ") s WHERE target_mean IS NULL",
            ) or 0)

            fresh_rows_per_canary: dict[str, int] = {}
            for ticker in CANARY_TICKERS_WITH_COVERAGE:
                fresh_rows_per_canary[ticker] = int(_scalar(
                    cur,
                    "SELECT COUNT(*) FROM consensus_estimates "
                    "WHERE ticker = %s AND fetched_at >= (now() - INTERVAL '7 days')",
                    (ticker,),
                ) or 0)

        return ConsensusEstimatesSample(
            schema_columns=schema_columns,
            rows_in_last_24h=rows_in_last_24h,
            last_fetched_at=last_fetched_at,
            target_mean_null_count=target_mean_null_count,
            target_mean_sample_size=target_mean_sample_size,
            fresh_rows_per_canary=fresh_rows_per_canary,
        )


def load_ratio_history_sample(conn_factory: Optional[Callable[[], Any]] = None) -> Optional[Any]:
    from .validators.ratio_history import HDFCBANK_BANDS, RatioHistorySample

    # Real schema (migration 005): ratio_history is keyed by
    # (ticker, period_end, period_type). No `snapshot_date`. We use
    # `computed_at` as the "last update" proxy (always populated, NOT NULL).
    with _open_connection(conn_factory) as conn:
        if conn is None:
            return None
        with conn.cursor() as cur:
            schema_columns = _columns_of(cur, "ratio_history")
            row_count = int(_scalar(cur, "SELECT COUNT(*) FROM ratio_history") or 0)
            # "prior" = rows whose period_end is at least a quarter old.
            # The most recent quarter's rows are what changes day-to-day
            # as new financials land.
            prior_row_count = int(_scalar(
                cur,
                "SELECT COUNT(*) FROM ratio_history "
                "WHERE period_end <= (CURRENT_DATE - INTERVAL '90 days')",
            ) or 0)
            last_update: Optional[datetime] = _scalar(
                cur,
                "SELECT MAX(computed_at) FROM ratio_history",
            )

            # Null counts over the LATEST period_end only — that's the
            # row the percentile engine actually reads for "current"
            # ratios. Catches a per-period populator regression even if
            # older periods are full.
            latest_period: Optional[Any] = _scalar(
                cur, "SELECT MAX(period_end) FROM ratio_history",
            )
            if latest_period is None:
                pe_null_count = pe_sample_size = de_null_count = de_sample_size = 0
            else:
                pe_sample_size = int(_scalar(
                    cur,
                    "SELECT COUNT(*) FROM ratio_history WHERE period_end = %s",
                    (latest_period,),
                ) or 0)
                pe_null_count = int(_scalar(
                    cur,
                    "SELECT COUNT(*) FROM ratio_history WHERE period_end = %s AND pe_ratio IS NULL",
                    (latest_period,),
                ) or 0)
                de_sample_size = pe_sample_size
                de_null_count = int(_scalar(
                    cur,
                    "SELECT COUNT(*) FROM ratio_history WHERE period_end = %s AND de_ratio IS NULL",
                    (latest_period,),
                ) or 0)

            hdfcbank_latest: dict[str, Optional[float]] = {}
            for col in HDFCBANK_BANDS:
                # Column name is a literal from HDFCBANK_BANDS (validator
                # source code), never user input — safe to interpolate.
                hdfcbank_latest[col] = _scalar(
                    cur,
                    f"SELECT {col} FROM ratio_history "
                    "WHERE ticker = %s ORDER BY period_end DESC LIMIT 1",
                    ("HDFCBANK",),
                )

        return RatioHistorySample(
            row_count=row_count,
            prior_row_count=prior_row_count,
            schema_columns=schema_columns,
            last_update=last_update,
            pe_null_count=pe_null_count,
            pe_sample_size=pe_sample_size,
            de_null_count=de_null_count,
            de_sample_size=de_sample_size,
            hdfcbank_latest=hdfcbank_latest,
        )


def load_peer_groups_sample(conn_factory: Optional[Callable[[], Any]] = None) -> Optional[Any]:
    from .validators.peer_groups import CANARY_MIN_PEERS, PeerGroupsSample

    with _open_connection(conn_factory) as conn:
        if conn is None:
            return None
        with conn.cursor() as cur:
            schema_columns = _columns_of(cur, "peer_groups")
            row_count = int(_scalar(cur, "SELECT COUNT(*) FROM peer_groups") or 0)
            # No timestamp column on peer_groups; use a no-op prior so
            # row_count_stability passes informationally and recency is
            # answered via the proxy below.
            prior_row_count = row_count
            # Schema (migration 005): peer_groups.computed_at NOT NULL.
            last_update: Optional[datetime] = _scalar(
                cur,
                "SELECT MAX(computed_at) FROM peer_groups",
            )
            peers_per_canary: dict[str, int] = {}
            for ticker in CANARY_MIN_PEERS:
                peers_per_canary[ticker] = int(_scalar(
                    cur,
                    "SELECT COUNT(*) FROM peer_groups WHERE ticker = %s",
                    (ticker,),
                ) or 0)

        return PeerGroupsSample(
            row_count=row_count,
            prior_row_count=prior_row_count,
            schema_columns=schema_columns,
            last_update=last_update,
            peers_per_canary=peers_per_canary,
        )


__all__ = [
    "load_corporate_actions_sample",
    "load_consensus_estimates_sample",
    "load_ratio_history_sample",
    "load_peer_groups_sample",
]
