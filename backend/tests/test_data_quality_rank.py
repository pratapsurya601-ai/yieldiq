# backend/tests/test_data_quality_rank.py
# Unit tests for the per-row source-precedence guard introduced in
# migration db/migrations/006_data_quality_rank.sql.
#
# These tests are deliberately DB-less — backend/tests has no shared
# Postgres fixture and the existing tests in this directory follow
# the same pattern (see test_data_quality.py with db_session=None).
# They prove three things:
#
#   1. The Python rank lookup table maps the data_source labels we
#      emit (NSE_XBRL, yfinance, BSE_*, finnhub) to the canonical
#      ranks expected by the migration.
#
#   2. The UPSERT_SQL string in fetch_annual_financials.py contains
#      the precedence-guard CASE expression for every column it
#      updates — i.e. a yfinance row (rank 60) cannot displace an
#      existing NSE_XBRL row (rank 10) for the same period.
#
#   3. The bse_xbrl.store_financials UPSERT carries the same guard
#      and uses LEAST() so a row's rank can only ever decrease.
#
# A live integration test against the real Neon DB lives in
# scripts/test_dcf.py / canary_diff.py and is out of scope here.

from __future__ import annotations

import re


def test_rank_for_helper_maps_known_sources():
    """fetch_annual_financials._rank_for must return canonical ranks
    matching db/migrations/006_data_quality_rank.sql."""
    from scripts.data_pipelines.fetch_annual_financials import _rank_for

    assert _rank_for("NSE_XBRL") == 10
    assert _rank_for("NSE_XBRL_STANDALONE") == 15
    assert _rank_for("NSE_XBRL_SYNTH") == 20
    assert _rank_for("BSE_PEERCOMP") == 30
    assert _rank_for("BSE_API") == 40
    assert _rank_for("finnhub") == 50
    assert _rank_for("yfinance") == 60
    # Unknown / None → safe default 70 (worse than any explicit rank).
    assert _rank_for("UNKNOWN_SOURCE") == 70
    assert _rank_for(None) == 70
    assert _rank_for("") == 70


def test_nse_xbrl_outranks_yfinance():
    """The whole point: a fresh yfinance row (rank 60) must not be
    able to displace an existing NSE_XBRL row (rank 10)."""
    from scripts.data_pipelines.fetch_annual_financials import _rank_for

    nse_rank = _rank_for("NSE_XBRL")
    yf_rank = _rank_for("yfinance")
    # Lower rank = higher priority. NSE_XBRL must win.
    assert nse_rank < yf_rank, "NSE_XBRL must outrank yfinance"
    # And the precedence guard predicate (EXCLUDED.rank <= existing.rank)
    # is FALSE when the new yfinance row arrives over an NSE_XBRL row:
    assert (yf_rank <= nse_rank) is False
    # Conversely, an NSE_XBRL row CAN overwrite an existing yfinance row:
    assert (nse_rank <= yf_rank) is True


def test_upsert_sql_has_precedence_guard_for_every_updated_column():
    """Every column the UPSERT updates must be wrapped in the
    `CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank ...`
    guard. A regression here (e.g. someone re-introduces a bare
    `col = EXCLUDED.col`) would re-open the v74 hole."""
    from scripts.data_pipelines.fetch_annual_financials import UPSERT_SQL

    sql = str(UPSERT_SQL)

    # Every column listed in the ON CONFLICT DO UPDATE SET must use
    # the precedence-guard CASE pattern.
    guarded_columns = [
        "revenue", "pat", "ebit", "cfo", "capex", "free_cash_flow",
        "eps_diluted", "total_debt", "cash_and_equivalents",
        "total_equity", "total_assets", "roe", "data_source",
    ]
    for col in guarded_columns:
        # The pattern looks like:
        #     col = CASE WHEN EXCLUDED.data_quality_rank <= financials.data_quality_rank
        # Allow flexible whitespace.
        pat = re.compile(
            rf"\b{col}\s*=\s*CASE\s+WHEN\s+EXCLUDED\.data_quality_rank\s*<=\s*financials\.data_quality_rank",
            re.IGNORECASE | re.DOTALL,
        )
        assert pat.search(sql), f"UPSERT_SQL missing precedence guard for column `{col}`"

    # data_quality_rank itself must use LEAST() so a row's rank can
    # only ever decrease (improve) — not regress.
    least_pat = re.compile(
        r"data_quality_rank\s*=\s*LEAST\s*\(\s*EXCLUDED\.data_quality_rank\s*,\s*financials\.data_quality_rank",
        re.IGNORECASE | re.DOTALL,
    )
    assert least_pat.search(sql), "UPSERT_SQL must monotonically improve data_quality_rank via LEAST()"

    # And the INSERT column list must include data_quality_rank and
    # bind it to :data_quality_rank.
    assert "data_quality_rank" in sql
    assert ":data_quality_rank" in sql


def test_bse_xbrl_store_financials_has_precedence_guard():
    """data_pipeline/sources/bse_xbrl.py::store_financials must carry
    the same precedence-guard pattern so a re-run of the BSE backfill
    cannot demote an existing NSE_XBRL row."""
    import inspect

    from data_pipeline.sources.bse_xbrl import store_financials

    src = inspect.getsource(store_financials)
    # Spot-check a representative subset (full re-checking the SQL
    # text would be brittle; the structural invariant is what matters).
    assert "data_quality_rank" in src, "bse_xbrl.store_financials must reference data_quality_rank"
    assert "LEAST(EXCLUDED.data_quality_rank" in src, \
        "bse_xbrl.store_financials must use LEAST() so rank can only improve"
    # The CASE-guard pattern must appear for the headline columns
    # that BSE_PEERCOMP / BSE_API populate.
    for col in ("revenue", "pat", "cfo", "capex", "total_equity"):
        guard = re.compile(
            rf"{col}\s*=\s*CASE\s+WHEN\s+EXCLUDED\.data_quality_rank\s*<=\s*financials\.data_quality_rank",
            re.IGNORECASE | re.DOTALL,
        )
        assert guard.search(src), f"bse_xbrl.store_financials missing guard for `{col}`"
