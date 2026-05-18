# backend/tests/test_yieldiq50_db_fallback_ticker_form.py
# =============================================================================
# Regression test for the 2026-05-18 Discover "warming up" placeholders bug.
#
# Root cause:
#   `_build_yieldiq50` (backend/routers/analysis.py) falls back to a SQL query
#   against `fair_value_history` JOIN `analysis_cache` whenever the in-process
#   cache and `data/screener_results.csv` are both empty (i.e. every Railway
#   cold-start). The fallback's EXISTS clause filtered out stale rows whose
#   live `analysis_cache.payload->valuation->verdict` had flipped to a "bad"
#   bucket.
#
#   Before this fix the EXISTS join was
#       ac.ticker = fv.ticker_bare
#   but `analysis_cache.ticker` is stored in CANONICAL form (e.g. RELIANCE.NS)
#   per `analysis_cache_service._canonical_cache_key`, while `fv.ticker_bare`
#   is the bare symbol (RELIANCE). The join never matched for Indian tickers,
#   so the EXISTS clause rejected every row from the DB fallback. Result:
#   `_build_yieldiq50` returned an empty list, the Discover frontend saw
#   `yiq50.results.length === 0` and rendered "YieldIQ 50 is warming up"
#   indefinitely after each deploy/restart — even though 2,300+ tickers had
#   freshly recomputed in `analysis_cache`.
#
# The fix matches both bare and `.NS`/`.BO`-suffixed forms via `IN (...)`,
# preserving the index seek (no functional CASE on the ac.ticker side).
#
# This test pins the SQL string so any future edit that drops the
# multi-form match will fail loudly in CI before reaching prod.
# =============================================================================

from __future__ import annotations

import inspect

from backend.routers import analysis as analysis_router


def _builder_source() -> str:
    return inspect.getsource(analysis_router._build_yieldiq50)


def test_exists_clause_matches_canonical_and_bare_ticker_forms():
    """The EXISTS join against analysis_cache must tolerate both forms.

    analysis_cache stores canonical tickers (FOO.NS); fair_value_history
    is mixed-form and our CTE normalises to bare (FOO). The EXISTS check
    must therefore match `fv.ticker_bare` OR `fv.ticker_bare || '.NS'`
    (and `.BO` for completeness) — otherwise every Indian ticker is
    filtered out and Discover renders "warming up" on cold-start.
    """
    src = _builder_source()

    # Must reference analysis_cache in an EXISTS subquery
    assert "FROM analysis_cache ac" in src, (
        "DB-fallback should still join against analysis_cache to drop stale "
        "fair_value_history rows whose live verdict has flipped."
    )

    # The buggy "ac.ticker = fv.ticker_bare" equality alone (without the
    # multi-form IN) must NOT be present as executable SQL. We strip the
    # historical-fix commentary so the test only inspects the actual SQL
    # body, not the explanatory comments referencing the original bug.
    sql_only = "\n".join(
        line for line in src.splitlines()
        if "--" not in line and "# " not in line
    )
    assert "ac.ticker = fv.ticker_bare" not in sql_only, (
        "Single-form join reintroduced. analysis_cache stores canonical "
        "(.NS) tickers, fv.ticker_bare is bare — this never matches for "
        "Indian tickers and empties the YieldIQ 50."
    )

    # Multi-form IN (...) match must be present so canonical and bare
    # both resolve the same security.
    # We check the three pieces independently so re-indents don't break us.
    assert "ac.ticker IN (" in src, (
        "Expected `ac.ticker IN (...)` multi-form match in EXISTS clause."
    )
    assert "fv.ticker_bare || '.NS'" in src, (
        "Expected `.NS`-suffixed form in the multi-form match (writers "
        "that canonicalise to NSE)."
    )
    assert "fv.ticker_bare || '.BO'" in src, (
        "Expected `.BO`-suffixed form in the multi-form match (BSE-only "
        "tickers written by the BSE backfill path)."
    )


def test_db_fallback_still_filters_bad_verdicts():
    """Lock the verdict-filtering intent: the EXISTS clause must still
    reject rows whose live cached verdict is in the bad-bucket list.

    Regression guard against a future "just drop the EXISTS clause to
    fix the empty-list problem" shortcut — which would re-surface stale
    YESBANK-shape rows on Discover.
    """
    src = _builder_source()
    for verdict in ("avoid", "under_review", "data_limited", "overvalued"):
        assert f"'{verdict}'" in src, (
            f"Bad verdict {verdict!r} no longer filtered in DB fallback SQL."
        )
