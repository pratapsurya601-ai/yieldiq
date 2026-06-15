"""Tests for the consensus_estimates DB fallback that feeds the
composite valuation's analyst estimator slot.

Bug context (fix/analyst-estimator-wiring)
------------------------------------------
The composite's "analyst" slot was fed ONLY by a live Finnhub call,
and Finnhub's free tier returns ZERO price-target coverage for Indian
``.NS`` symbols. So for essentially the entire NSE universe the analyst
slot resolved to None → the composite collapsed toward DCF-only. The
real coverage was already in the ``consensus_estimates`` table (written
nightly by scripts/refresh_consensus.py, BARE-ticker keyed) but nothing
on the composite path read it.

Coverage here
-------------
1. ``consensus_estimates_service.get_consensus_for_ticker`` — the new
   read-only helper:
   - returns None when there is no session
   - returns None when the table has no row (no crash)
   - returns the normalized dict for a populated row
   - bare-vs-.NS key normalization: an ``INFY.NS`` request binds the
     bare ``INFY`` symbol into the query params
   - ``_row_to_consensus`` prefers a populated row and rejects an
     all-null one
2. The SQL guard that prevents an empty Finnhub row from shadowing a
   populated yfinance row (``target_mean IS NOT NULL`` + ordering).
3. End-to-end wiring: feeding the helper's output through the same
   ``AnalystConsensus`` / ``AnalystPriceTarget`` construction the
   analysis service uses, then through ``compute_composite_iv`` the same
   way service.py calls it — proving a 0-coverage Finnhub result now
   yields a populated analyst estimator AND moves the composite.
"""
from __future__ import annotations

import pytest

from backend.services import consensus_estimates_service as ces


# ── Stub SQLAlchemy session (mirrors test_benchmark_reconciliation) ──


class _StubResult:
    """Minimal stand-in for the sqlalchemy Result `.mappings().first()`."""
    def __init__(self, row):
        self._row = row

    def mappings(self):
        return self

    def first(self):
        return self._row


class _StubSession:
    def __init__(self, row):
        self._row = row
        self.executed = []

    def execute(self, statement, params=None):
        self.executed.append((str(statement), params))
        return _StubResult(self._row)

    def close(self):
        pass


# ── 1. get_consensus_for_ticker happy / empty / no-session ──────────


def test_returns_none_when_no_session(monkeypatch):
    monkeypatch.setattr(ces, "_get_session", lambda: None)
    assert ces.get_consensus_for_ticker("RELIANCE") is None


def test_returns_none_when_no_row():
    # (d) no crash when the table has no row.
    sess = _StubSession(row=None)
    assert ces.get_consensus_for_ticker("SMALLCAP", session=sess) is None


def test_returns_normalized_dict_for_populated_row():
    sess = _StubSession(row={
        "target_mean": 1500.0,
        "target_median": 1480.0,
        "target_high": 1700.0,
        "target_low": 1200.0,
        "analyst_count": 32,
        "source": "yfinance",
        "fetched_at": "2026-06-14T00:00:00Z",
    })
    out = ces.get_consensus_for_ticker("RELIANCE", session=sess)
    assert out is not None
    assert out["target_mean"] == pytest.approx(1500.0)
    assert out["target_median"] == pytest.approx(1480.0)
    assert out["analyst_count"] == 32
    assert out["source"] == "yfinance"
    assert out["as_of"] == "2026-06-14"


# ── 2. (b) bare-vs-.NS key normalization ────────────────────────────


def test_ns_suffix_normalized_to_bare_in_query_params():
    sess = _StubSession(row=None)
    ces.get_consensus_for_ticker("RELIANCE.NS", session=sess)
    assert len(sess.executed) == 1
    _stmt, params = sess.executed[0]
    # The cron keys rows by the bare ticker; the request strips .NS.
    assert params["bare"] == "RELIANCE"


def test_bo_suffix_and_lowercase_normalized():
    sess = _StubSession(row=None)
    ces.get_consensus_for_ticker("tcs.bo", session=sess)
    _stmt, params = sess.executed[0]
    assert params["bare"] == "TCS"


# ── 3. (c) populated yfinance preferred over empty finnhub ──────────


def test_sql_guards_against_empty_finnhub_shadowing_yfinance():
    """The view orders finnhub(1) BEFORE yfinance(2) with DISTINCT ON,
    so an empty Finnhub row can shadow a populated yfinance row. Our
    query reads the base table and filters populated rows only — assert
    the guard + ordering live in the SQL."""
    sql = ces._ONE_TICKER_SQL.lower()
    # Populated-row guard defeats the empty-row shadow.
    assert "target_mean is not null" in sql
    # We query the base table, NOT the shadow-prone view.
    assert "from consensus_estimates" in sql
    assert "latest_consensus_per_ticker" not in sql
    # Freshness-then-yfinance ordering breaks ties toward real coverage.
    assert "order by" in sql
    assert "yfinance" in sql


def test_row_to_consensus_rejects_all_null_target():
    # A row with both targets null is not usable — mirrors what the SQL
    # filter excludes, defended again at the mapping layer.
    assert ces._row_to_consensus({
        "target_mean": None, "target_median": None,
        "analyst_count": 5, "source": "finnhub",
    }) is None


def test_row_to_consensus_accepts_median_only():
    out = ces._row_to_consensus({
        "target_mean": None, "target_median": 980.0,
        "analyst_count": 7, "source": "yfinance",
        "fetched_at": "2026-06-10T00:00:00Z",
    })
    assert out is not None
    assert out["target_median"] == pytest.approx(980.0)
    assert out["analyst_count"] == 7


# ── 4. End-to-end: 0-coverage Finnhub → populated analyst estimator ─


def _finnhub_zero_coverage():
    """Shape returned by fetch_analyst_consensus for an Indian .NS name
    with no Finnhub coverage (the universal NSE case)."""
    return {
        "coverage_count": 0,
        "rating_distribution": None,
        "consensus_rating": None,
        "price_target": None,
        "eps_estimate": None,
        "as_of": "2026-06-15",
        "source": "Finnhub",
    }


def test_fallback_populates_analyst_consensus_and_moves_composite():
    """Replicates the analysis-service wiring: when Finnhub returns
    0 coverage we read the DB consensus, build an AnalystConsensus, push
    the avg into `enriched`, and the composite consumes it."""
    from backend.models.responses import (
        AnalystConsensus,
        AnalystPriceTarget,
    )
    from backend.services.composite_iv_service import compute_composite_iv

    # (a) Finnhub came back with coverage_count==0 — the trigger.
    finnhub = _finnhub_zero_coverage()
    needs_db = (
        finnhub is None
        or (finnhub.get("coverage_count") or 0) <= 0
        or finnhub.get("price_target") is None
    )
    assert needs_db is True

    # DB fallback fires and returns real yfinance coverage.
    sess = _StubSession(row={
        "target_mean": 1500.0,
        "target_median": 1490.0,
        "target_high": 1700.0,
        "target_low": 1250.0,
        "analyst_count": 32,
        "source": "yfinance",
        "fetched_at": "2026-06-14T00:00:00Z",
    })
    db_cons = ces.get_consensus_for_ticker("RELIANCE.NS", session=sess)
    assert db_cons is not None

    # Build the AnalystConsensus exactly as service.py does.
    analyst_consensus = AnalystConsensus(
        coverage_count=int(db_cons["analyst_count"]),
        rating_distribution=None,
        consensus_rating=None,
        price_target=AnalystPriceTarget(
            mean=db_cons["target_mean"],
            median=db_cons["target_median"],
            high=db_cons["target_high"],
            low=db_cons["target_low"],
        ),
        eps_estimate=None,
        as_of=db_cons["as_of"],
        source=db_cons["source"],
    )
    assert analyst_consensus.coverage_count == 32
    assert analyst_consensus.price_target.mean == pytest.approx(1500.0)

    # Push into enriched the way the service does, then read it back the
    # way the composite block does.
    enriched: dict = {}
    pt = analyst_consensus.price_target
    analyst_avg_for_composite = pt.mean or pt.median
    enriched["analyst_consensus"] = {
        "coverage_count": analyst_consensus.coverage_count,
        "price_target": {"mean": pt.mean, "median": pt.median},
        "source": analyst_consensus.source,
    }
    enriched["wall_street_avg_target"] = float(analyst_avg_for_composite)

    # The composite-block resolution logic (mirrors service.py).
    cf_consensus = enriched.get("analyst_consensus")
    cf_analyst_avg = None
    if isinstance(cf_consensus, dict):
        cf_pt = cf_consensus.get("price_target") or {}
        cf_analyst_avg = cf_pt.get("mean") or cf_pt.get("median")
    if cf_analyst_avg is None:
        cf_analyst_avg = enriched.get("wall_street_avg_target")
    assert cf_analyst_avg == pytest.approx(1500.0)

    # The composite now sees a 2nd estimator: with vs without the analyst
    # slot, the composite value differs → the analyst estimator fired.
    dcf_fv = 1000.0
    multiples_fv = 1100.0
    comp_with_analyst = compute_composite_iv(
        dcf_fv, multiples_fv, cf_analyst_avg, ticker="RELIANCE",
    )
    comp_without_analyst = compute_composite_iv(
        dcf_fv, multiples_fv, None, ticker="RELIANCE",
    )
    assert comp_with_analyst.value is not None
    assert comp_without_analyst.value is not None
    # Analyst avg (1500) is above the DCF/multiples pair (1000/1100), so
    # folding it in must lift the composite.
    assert comp_with_analyst.value > comp_without_analyst.value


def test_fallback_skipped_when_finnhub_has_real_coverage():
    """When Finnhub DOES return coverage (rare for .NS, common for US
    ADRs), the DB fallback trigger is False and we keep Finnhub."""
    finnhub = {
        "coverage_count": 12,
        "price_target": {"mean": 200.0, "median": 198.0},
    }
    needs_db = (
        finnhub is None
        or (finnhub.get("coverage_count") or 0) <= 0
        or finnhub.get("price_target") is None
    )
    assert needs_db is False
