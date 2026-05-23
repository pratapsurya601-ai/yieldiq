"""Phase A.2.1 self-tests for the 4 new validators + DB loaders + admin endpoint.

These tests are the spec. They cover, in order:

1. CorporateActionsValidator: catches missing canary actions
2. ConsensusEstimatesValidator: catches cron-failed (zero-rows) state
3. RatioHistoryValidator: catches HDFCBANK PE outside plausibility band
4. PeerGroupsValidator: catches HDFCBANK with <3 peers (Day-111a signature)
5. db_loaders.load_*_sample: integration via fake conn_factory
6. Admin endpoint: gating, cache hit/miss, empty-state, force-refresh
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import patch

import pytest

from backend.services.data_quality import HealthCheckResult
from backend.services.data_quality.validators.consensus_estimates import (
    CANARY_TICKERS_WITH_COVERAGE,
    ConsensusEstimatesSample,
    ConsensusEstimatesValidator,
    MIN_FRESH_ROWS_24H,
)
from backend.services.data_quality.validators.corporate_actions import (
    CANARY_TICKERS_WITH_ACTIONS,
    CorporateActionsSample,
    CorporateActionsValidator,
)
from backend.services.data_quality.validators.peer_groups import (
    CANARY_MIN_PEERS,
    PeerGroupsSample,
    PeerGroupsValidator,
)
from backend.services.data_quality.validators.ratio_history import (
    HDFCBANK_BANDS,
    RatioHistorySample,
    RatioHistoryValidator,
)

_NOW = datetime(2026, 5, 23, 12, 0, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# 1. CorporateActions
# ---------------------------------------------------------------------------


def _ca_sample_healthy() -> CorporateActionsSample:
    return CorporateActionsSample(
        row_count=10_000,
        prior_row_count=9_950,
        schema_columns=[
            "ticker", "action_type", "ex_date", "adjustment_factor",
            "data_source", "data_quality_rank",
        ],
        last_update=_NOW - timedelta(days=2),
        split_or_bonus_count={t: 3 for t in CANARY_TICKERS_WITH_ACTIONS},
        adj_factor_split_bonus_null_count=10,
        adj_factor_split_bonus_sample_size=500,
        rank_null_count=50,
        rank_sample_size=10_000,
    )


def test_corporate_actions_healthy_is_green():
    v = CorporateActionsValidator(sample_loader=_ca_sample_healthy)
    res = v.run()
    assert res.overall_status == "green", [c for c in res.checks if c.status != "pass"]


def test_corporate_actions_missing_canary_action_is_red():
    sample = _ca_sample_healthy()
    sample.split_or_bonus_count["RELIANCE"] = 0  # populator regressed
    v = CorporateActionsValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"
    failed = [c for c in res.checks if c.status == "fail"]
    assert any(c.name == "canary_actions_present" for c in failed)


def test_corporate_actions_missing_columns_is_red():
    sample = _ca_sample_healthy()
    sample.schema_columns = ["ticker", "ex_date"]  # missing critical fields
    v = CorporateActionsValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


# ---------------------------------------------------------------------------
# 2. ConsensusEstimates
# ---------------------------------------------------------------------------


def _ce_sample_healthy() -> ConsensusEstimatesSample:
    return ConsensusEstimatesSample(
        schema_columns=["ticker", "source", "target_mean", "fetched_at"],
        rows_in_last_24h=MIN_FRESH_ROWS_24H + 200,
        last_fetched_at=_NOW - timedelta(hours=6),
        target_mean_null_count=50,
        target_mean_sample_size=5000,
        fresh_rows_per_canary={t: 3 for t in CANARY_TICKERS_WITH_COVERAGE},
    )


def test_consensus_estimates_healthy_is_green():
    v = ConsensusEstimatesValidator(sample_loader=_ce_sample_healthy)
    res = v.run()
    assert res.overall_status == "green", [c for c in res.checks if c.status != "pass"]


def test_consensus_estimates_zero_24h_rows_is_red():
    sample = _ce_sample_healthy()
    sample.rows_in_last_24h = 0  # cron broken
    v = ConsensusEstimatesValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"
    failed = [c for c in res.checks if c.status == "fail"]
    assert any(c.name == "fresh_rows_24h" for c in failed)


def test_consensus_estimates_low_24h_rows_warns_not_fails():
    sample = _ce_sample_healthy()
    sample.rows_in_last_24h = MIN_FRESH_ROWS_24H - 50  # below floor, above half
    v = ConsensusEstimatesValidator(sample_loader=lambda: sample)
    res = v.run()
    # warn, not fail
    assert res.overall_status == "yellow"


def test_consensus_estimates_missing_canary_is_red():
    sample = _ce_sample_healthy()
    sample.fresh_rows_per_canary["HDFCBANK"] = 0  # Day-71 key-mismatch signature
    v = ConsensusEstimatesValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"
    failed = [c for c in res.checks if c.status == "fail"]
    assert any(c.name == "canary_coverage" for c in failed)


# ---------------------------------------------------------------------------
# 3. RatioHistory
# ---------------------------------------------------------------------------


def _rh_sample_healthy() -> RatioHistorySample:
    return RatioHistorySample(
        row_count=100_000,
        prior_row_count=99_500,
        schema_columns=[
            "ticker", "period_end", "period_type", "pe_ratio", "pb_ratio",
            "roe", "de_ratio",
        ],
        last_update=_NOW - timedelta(days=5),
        pe_null_count=100,
        pe_sample_size=2000,
        de_null_count=200,
        de_sample_size=2000,
        hdfcbank_latest={"pe_ratio": 22.5, "roe": 15.0},
    )


def test_ratio_history_healthy_is_green():
    v = RatioHistoryValidator(sample_loader=_rh_sample_healthy)
    res = v.run()
    assert res.overall_status == "green", [c for c in res.checks if c.status != "pass"]


def test_ratio_history_hdfcbank_pe_out_of_band_is_red():
    sample = _rh_sample_healthy()
    sample.hdfcbank_latest["pe_ratio"] = 500.0  # unit bug or stale price
    v = RatioHistoryValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


def test_ratio_history_hdfcbank_pe_null_is_red():
    sample = _rh_sample_healthy()
    sample.hdfcbank_latest["pe_ratio"] = None
    v = RatioHistoryValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"


# ---------------------------------------------------------------------------
# 4. PeerGroups
# ---------------------------------------------------------------------------


def _pg_sample_healthy() -> PeerGroupsSample:
    return PeerGroupsSample(
        row_count=12_000,
        prior_row_count=12_000,
        schema_columns=["ticker", "peer_ticker"],
        last_update=_NOW - timedelta(days=3),
        peers_per_canary={t: n + 2 for t, n in CANARY_MIN_PEERS.items()},
    )


def test_peer_groups_healthy_is_green():
    v = PeerGroupsValidator(sample_loader=_pg_sample_healthy)
    res = v.run()
    assert res.overall_status == "green", [c for c in res.checks if c.status != "pass"]


def test_peer_groups_hdfcbank_too_few_peers_is_red():
    sample = _pg_sample_healthy()
    sample.peers_per_canary["HDFCBANK"] = 1  # Day-111a signature
    v = PeerGroupsValidator(sample_loader=lambda: sample)
    res = v.run()
    assert res.overall_status == "red"
    failed = [c for c in res.checks if c.status == "fail"]
    assert any(c.name == "canary_peer_count" for c in failed)


# ---------------------------------------------------------------------------
# 5. DB loader integration via fake conn_factory
# ---------------------------------------------------------------------------


class _FakeCursor:
    """Mimics enough of psycopg2's cursor protocol for the loaders."""
    def __init__(self, dispatch: dict):
        self._dispatch = dispatch
        self._last_sql = None
        self._last_params = None

    def execute(self, sql, params=()):
        self._last_sql = sql
        self._last_params = params

    def fetchone(self):
        return self._dispatch.pop("_next_row", (0,))

    def fetchall(self):
        return self._dispatch.pop("_next_rows", [])

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _ScriptedConn:
    """Plays back a fixed sequence of (fetchone | fetchall) results."""
    def __init__(self, queue: list):
        self._queue = list(queue)

    def cursor(self):
        outer = self

        class _C:
            def execute(self, sql, params=()):
                pass

            def fetchone(self):
                return outer._queue.pop(0)

            def fetchall(self):
                return outer._queue.pop(0)

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        return _C()

    def close(self):
        pass


def test_db_loader_returns_none_when_database_url_unset(monkeypatch):
    """Graceful skip path: no DATABASE_URL => loader returns None."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from backend.services.data_quality.db_loaders import load_daily_prices_sample
    from backend.services.data_quality.db_loaders_a2 import (
        load_consensus_estimates_sample,
        load_corporate_actions_sample,
        load_peer_groups_sample,
        load_ratio_history_sample,
    )

    assert load_daily_prices_sample() is None
    assert load_corporate_actions_sample() is None
    assert load_consensus_estimates_sample() is None
    assert load_ratio_history_sample() is None
    assert load_peer_groups_sample() is None


def test_db_loader_ratio_history_uses_settled_period_for_null_sample():
    """Regression for GH issue #546: ratio_history's pe_ratio null-rate
    sample must lock onto the latest *settled* period_end (>=80% of
    active universe covered), NOT MAX(period_end).

    Scenario: active universe is 2000 tickers. Two period_ends exist:
      - 2026-03-31: 1900 rows  (settled — past filing deadline)
      - 2026-06-30: 100 rows   (cold — only early filers have reported)

    Before the fix the loader picked 2026-06-30 and saw a ~95% null
    rate because most rows weren't built yet. After the fix it picks
    2026-03-31 (>=1600 rows = 80% of 2000) and the null rate reflects
    the real populator quality.
    """
    from backend.services.data_quality.db_loaders_a2 import (
        load_ratio_history_sample,
    )
    from backend.services.data_quality.validators.ratio_history import (
        HDFCBANK_BANDS,
    )
    from datetime import date

    queue: list[Any] = [
        # _columns_of fetchall
        [("ticker",), ("period_end",), ("period_type",),
         ("pe_ratio",), ("pb_ratio",), ("roe",), ("de_ratio",)],
        (50_000,),            # row_count
        (49_500,),            # prior_row_count
        (_NOW,),              # last_update
        (2_000,),             # active_universe (NEW)
        (date(2026, 3, 31),), # settled period (NEW)
        (1_900,),             # pe_sample_size
        (190,),               # pe_null_count -> 10% null rate
        (400,),               # de_null_count -> 21% null rate
    ]
    for _ in HDFCBANK_BANDS:
        queue.append((20.0,))  # plausible value per band

    sample = load_ratio_history_sample(conn_factory=lambda: _ScriptedConn(queue))
    assert sample is not None
    assert sample.pe_sample_size == 1900
    assert sample.pe_null_count == 190
    assert sample.de_null_count == 400
    # And the column we sampled is the settled period, not "max".
    # (We verify behaviour via the sample, since the loader doesn't
    # expose period_end; the queue ordering would explode if MAX(...)
    # had been called.)


def test_db_loader_ratio_history_falls_back_to_max_when_no_settled_period():
    """Cold-start path: when no period_end has >=80% coverage (e.g.
    a freshly seeded test DB), the loader falls back to MAX(period_end)
    so the validator still produces a result instead of crashing."""
    from backend.services.data_quality.db_loaders_a2 import (
        load_ratio_history_sample,
    )
    from backend.services.data_quality.validators.ratio_history import (
        HDFCBANK_BANDS,
    )
    from datetime import date

    queue: list[Any] = [
        [("ticker",), ("period_end",), ("period_type",),
         ("pe_ratio",), ("pb_ratio",), ("roe",), ("de_ratio",)],
        (100,),               # row_count
        (50,),                # prior_row_count
        (_NOW,),              # last_update
        (2_000,),             # active_universe -> threshold = 1600
        (None,),              # no period meets the >=1600 threshold
        (date(2026, 6, 30),), # MAX(period_end) fallback
        (50,),                # pe_sample_size
        (40,),                # pe_null_count (high — cold-start signal)
        (45,),                # de_null_count
    ]
    for _ in HDFCBANK_BANDS:
        queue.append((20.0,))

    sample = load_ratio_history_sample(conn_factory=lambda: _ScriptedConn(queue))
    assert sample is not None
    assert sample.pe_sample_size == 50
    assert sample.pe_null_count == 40


def test_db_loader_peer_groups_via_fake_conn():
    """End-to-end: scripted fake conn drives the peer_groups loader.

    Queue order matches the loader's execution order:
      1. _columns_of (fetchall)  -> column list
      2. row_count               -> (count,)
      3. last_update             -> (timestamp,)
      4..N peers_per_canary      -> (count,) per canary
    """
    from backend.services.data_quality.db_loaders_a2 import load_peer_groups_sample

    canaries = list(CANARY_MIN_PEERS.keys())
    queue: list[Any] = [
        [("ticker",), ("peer_ticker",), ("computed_at",)],  # _columns_of fetchall
        (5000,),                                            # row_count
        (_NOW,),                                            # last_update
    ]
    for _ in canaries:
        queue.append((4,))  # 4 peers each — passes the >=3 check

    sample = load_peer_groups_sample(conn_factory=lambda: _ScriptedConn(queue))
    assert sample is not None
    assert sample.row_count == 5000
    assert sample.schema_columns == ["ticker", "peer_ticker", "computed_at"]
    for t in canaries:
        assert sample.peers_per_canary[t] == 4


# ---------------------------------------------------------------------------
# 6. Admin endpoint — auth gating, cache TTL, force-refresh, empty state
# ---------------------------------------------------------------------------


def _fake_admin_user():
    return {"email": "pratapsurya601@gmail.com"}


def _fake_non_admin_user():
    return {"email": "random@example.com"}


def test_admin_endpoint_rejects_non_admin():
    from fastapi import HTTPException
    from backend.routers.admin import require_admin

    with pytest.raises(HTTPException) as exc_info:
        require_admin(user=_fake_non_admin_user())
    assert exc_info.value.status_code == 403


def test_admin_endpoint_cache_hit_returns_cached_payload(monkeypatch):
    """Two back-to-back calls inside the TTL should hit the cache.

    We patch _fetch_from_db so the cache layer is the only thing under
    test; the DB plumbing is exercised by the loader tests.
    """
    import asyncio
    from backend.routers import admin_data_quality

    admin_data_quality._reset_cache_for_tests()
    call_count = {"n": 0}

    def _fake_fetch(limit_history: int):
        call_count["n"] += 1
        return {
            "latest_per_table": [{
                "table": "stocks", "populator": "p", "overall_status": "green",
                "run_at": _NOW.isoformat(), "checks": [],
            }],
            "history": [],
            "summary": {"green": 1, "yellow": 0, "red": 0, "total_tables": 1},
        }

    monkeypatch.setattr(admin_data_quality, "_fetch_from_db", _fake_fetch)

    a = asyncio.run(admin_data_quality.get_data_quality_runs(
        limit_history=20, force_refresh=False, user=_fake_admin_user(),
    ))
    b = asyncio.run(admin_data_quality.get_data_quality_runs(
        limit_history=20, force_refresh=False, user=_fake_admin_user(),
    ))

    assert call_count["n"] == 1, "second call must hit cache, not DB"
    assert a["cached"] is False
    assert b["cached"] is True
    assert b["summary"] == a["summary"]


def test_admin_endpoint_force_refresh_bypasses_cache(monkeypatch):
    import asyncio
    from backend.routers import admin_data_quality

    admin_data_quality._reset_cache_for_tests()
    call_count = {"n": 0}

    def _fake_fetch(limit_history: int):
        call_count["n"] += 1
        return {
            "latest_per_table": [],
            "history": [],
            "summary": {"green": 0, "yellow": 0, "red": 0, "total_tables": 0},
        }

    monkeypatch.setattr(admin_data_quality, "_fetch_from_db", _fake_fetch)

    asyncio.run(admin_data_quality.get_data_quality_runs(
        limit_history=20, force_refresh=False, user=_fake_admin_user(),
    ))
    asyncio.run(admin_data_quality.get_data_quality_runs(
        limit_history=20, force_refresh=True, user=_fake_admin_user(),
    ))
    assert call_count["n"] == 2


def test_admin_endpoint_empty_state(monkeypatch):
    """Fresh DB with zero data_quality_runs returns clean empty payload."""
    import asyncio
    from backend.routers import admin_data_quality

    admin_data_quality._reset_cache_for_tests()
    monkeypatch.setattr(admin_data_quality, "_fetch_from_db", lambda lim: {
        "latest_per_table": [],
        "history": [],
        "summary": {"green": 0, "yellow": 0, "red": 0, "total_tables": 0},
    })

    out = asyncio.run(admin_data_quality.get_data_quality_runs(
        limit_history=20, force_refresh=False, user=_fake_admin_user(),
    ))
    assert out["latest_per_table"] == []
    assert out["summary"]["total_tables"] == 0


# ---------------------------------------------------------------------------
# 7. Wired A.1 validators graceful-skip path
# ---------------------------------------------------------------------------


def test_a1_daily_prices_validator_skips_when_db_url_unset(monkeypatch):
    """Day-after-A.1 wiring: DB loader returning None must surface as
    NotImplementedError so the orchestrator's skip path kicks in."""
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from backend.services.data_quality.validators.daily_prices import (
        DailyPricesValidator,
    )

    v = DailyPricesValidator()
    with pytest.raises(NotImplementedError):
        v._load_sample_from_db()


def test_a1_stocks_validator_skips_when_db_url_unset(monkeypatch):
    monkeypatch.delenv("DATABASE_URL", raising=False)
    from backend.services.data_quality.validators.stocks import StocksValidator

    v = StocksValidator()
    with pytest.raises(NotImplementedError):
        v._load_sample_from_db()
