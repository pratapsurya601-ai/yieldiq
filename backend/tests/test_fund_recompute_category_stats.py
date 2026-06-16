"""Pass-3 category-stats aggregation — backend/services/funds/recompute.py.

`recompute_category_stats` groups the already-computed per-scheme metrics
(held in memory by pass-1/2) by funds.sub_category, computes median/avg via
numpy, and UPSERTs one row per sub_category into fund_category_stats. It must:

  * skip schemes flagged ``skip`` or with no sub_category,
  * compute median/avg only over non-null metric values,
  * leave avg_ter NULL (TER is not in the compute objects — never faked),
  * count n_funds = schemes contributing >=1 non-null metric,
  * SOFT-FAIL (log + swallow) when fund_category_stats isn't migrated.

These run against an in-memory SQLite DB — same isolation pattern as
test_funds_router.py — with the per_scheme map built from tiny stubs so we
don't need real NAV series.
"""
from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend.services.funds import recompute as recompute_mod  # noqa: E402


def _returns(ret_1y=None, cagr_3y=None, cagr_5y=None):
    # recompute_category_stats only reads ret_1y / cagr_3y / cagr_5y here.
    return SimpleNamespace(ret_1y=ret_1y, cagr_3y=cagr_3y, cagr_5y=cagr_5y)


def _risk(sharpe_3y=None, stdev_3y=None, max_dd_3y=None):
    return SimpleNamespace(sharpe_3y=sharpe_3y, stdev_3y=stdev_3y, max_dd_3y=max_dd_3y)


def _scheme(sub_category, *, skip=False, **kw):
    if skip:
        return {"skip": True, "reason": "stub"}
    return {
        "skip": False,
        "sub_category": sub_category,
        "returns": _returns(**{k: v for k, v in kw.items() if k.startswith(("ret", "cagr"))}),
        "risk": _risk(**{k: v for k, v in kw.items() if k.startswith(("sharpe", "stdev", "max"))}),
    }


@pytest.fixture()
def session():
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    with engine.begin() as conn:
        conn.execute(text(
            """
            CREATE TABLE fund_category_stats (
                sub_category TEXT PRIMARY KEY,
                updated_at TEXT,
                cache_version TEXT,
                median_cagr_1y REAL, median_cagr_3y REAL, median_cagr_5y REAL,
                avg_cagr_1y REAL, avg_cagr_3y REAL, avg_cagr_5y REAL,
                avg_ter REAL, avg_sharpe_3y REAL, avg_stdev_3y REAL,
                avg_max_drawdown_3y REAL, n_funds INTEGER
            )
            """
        ))
    SessionLocal = sessionmaker(bind=engine, future=True)
    s = SessionLocal()
    yield s
    s.close()


def test_aggregates_median_and_avg_by_sub_category(session) -> None:
    per_scheme = {
        # Large Cap cohort: cagr_3y 0.10 / 0.20 / 0.30 → median 0.20, avg 0.20.
        "A": _scheme("Large Cap", ret_1y=0.05, cagr_3y=0.10, sharpe_3y=0.8, stdev_3y=0.14, max_dd_3y=-0.20),
        "B": _scheme("Large Cap", ret_1y=0.07, cagr_3y=0.20, sharpe_3y=1.0, stdev_3y=0.16, max_dd_3y=-0.25),
        "C": _scheme("Large Cap", ret_1y=0.09, cagr_3y=0.30, sharpe_3y=1.2, stdev_3y=0.18, max_dd_3y=-0.30),
        # Small Cap cohort: single fund.
        "D": _scheme("Small Cap", ret_1y=0.12, cagr_3y=0.40, sharpe_3y=0.7),
        # Skipped + no-sub_category rows must not contribute.
        "E": _scheme("Large Cap", skip=True),
        "F": _scheme(None, ret_1y=0.99, cagr_3y=0.99),
    }

    result = recompute_category_stats_helper(session, per_scheme)
    assert result["written"] == 2
    assert result["skipped"] == 0

    rows = {
        r[0]: r
        for r in session.execute(text(
            "SELECT sub_category, median_cagr_3y, avg_cagr_3y, avg_sharpe_3y, "
            "avg_stdev_3y, avg_max_drawdown_3y, avg_ter, n_funds, median_cagr_1y "
            "FROM fund_category_stats"
        )).fetchall()
    }
    lc = rows["Large Cap"]
    assert lc[1] == pytest.approx(0.20)   # median_cagr_3y
    assert lc[2] == pytest.approx(0.20)   # avg_cagr_3y
    assert lc[3] == pytest.approx(1.0)    # avg_sharpe_3y
    assert lc[6] is None                  # avg_ter — never fabricated
    assert lc[7] == 3                     # n_funds
    # median_cagr_1y uses ret_1y (0.05/0.07/0.09) → 0.07.
    assert lc[8] == pytest.approx(0.07)

    sc = rows["Small Cap"]
    assert sc[7] == 1                     # n_funds
    assert sc[1] == pytest.approx(0.40)   # single-fund median == its value


def test_nulls_excluded_from_aggregates(session) -> None:
    per_scheme = {
        "A": _scheme("Flexi", cagr_3y=0.10),          # only cagr_3y
        "B": _scheme("Flexi", cagr_3y=None, sharpe_3y=1.5),  # cagr_3y null, sharpe present
    }
    recompute_category_stats_helper(session, per_scheme)
    row = session.execute(text(
        "SELECT avg_cagr_3y, avg_sharpe_3y, n_funds FROM fund_category_stats "
        "WHERE sub_category = 'Flexi'"
    )).fetchone()
    # avg over the single non-null cagr_3y (0.10), sharpe over the single 1.5.
    assert row[0] == pytest.approx(0.10)
    assert row[1] == pytest.approx(1.5)
    assert row[2] == 2  # both schemes contributed >=1 non-null metric


def test_soft_fails_when_table_absent() -> None:
    """No fund_category_stats table → pass-3 logs + swallows, no raise."""
    engine = create_engine(
        "sqlite:///:memory:",
        future=True,
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    SessionLocal = sessionmaker(bind=engine, future=True)
    s = SessionLocal()
    try:
        per_scheme = {"A": _scheme("Large Cap", cagr_3y=0.1)}
        # Must not raise; every UPSERT soft-fails to "skipped".
        result = recompute_category_stats_helper(s, per_scheme)
        assert result["written"] == 0
        assert result["skipped"] >= 1
    finally:
        s.close()


def recompute_category_stats_helper(session, per_scheme):
    return recompute_mod.recompute_category_stats(
        session, per_scheme, cache_version="v_test_cat_stats"
    )
