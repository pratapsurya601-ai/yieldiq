# backend/tests/test_corporate_actions_precedence.py
# Unit tests for the per-row source-precedence guard introduced in
# migration db/migrations/010_corporate_actions_quality_rank.sql.
#
# Mirrors backend/tests/test_data_quality_rank.py (PR #208, financials)
# for the corporate_actions table.
#
# These tests are deliberately DB-less — backend/tests has no shared
# Postgres fixture and the existing tests in this directory follow
# the same pattern. They prove three things:
#
#   1. The Python rank lookup table maps the data_source labels we
#      emit (NSE_CORP_ANN, NSE_ARCHIVE, BSE_CORP_FILE, finnhub,
#      yfinance) to the canonical ranks expected by the migration.
#
#   2. The UPSERT_SQL string in fetch_corporate_actions.py contains
#      the precedence-guard CASE expression for every column it
#      updates — i.e. a yfinance row (rank 50) cannot displace an
#      existing NSE_CORP_ANN row (rank 10) for the same
#      (ticker, ex_date, action_type).
#
#   3. The yfinance backfill (scripts/backfill_corporate_actions_yf.py)
#      carries the same guard and uses LEAST() so a row's rank can
#      only ever decrease.
#
# A live integration test against the real Neon DB lives in the
# canary-diff harness and is out of scope here.

from __future__ import annotations

import re


def test_rank_for_helper_maps_known_sources():
    """fetch_corporate_actions._rank_for must return canonical ranks
    matching db/migrations/010_corporate_actions_quality_rank.sql."""
    from scripts.data_pipelines.fetch_corporate_actions import _rank_for

    assert _rank_for("NSE_CORP_ANN") == 10
    assert _rank_for("NSE_ARCHIVE") == 15
    assert _rank_for("BSE_CORP_FILE") == 30
    assert _rank_for("finnhub") == 40
    assert _rank_for("yfinance") == 50
    # Unknown / None → safe default 60 (worse than any explicit rank).
    assert _rank_for("UNKNOWN_SOURCE") == 60
    assert _rank_for(None) == 60
    assert _rank_for("") == 60


def test_nse_corp_ann_outranks_yfinance():
    """The whole point: a fresh yfinance row (rank 50) must not be
    able to displace an existing NSE_CORP_ANN row (rank 10) for the
    same (ticker, ex_date, action_type)."""
    from scripts.data_pipelines.fetch_corporate_actions import _rank_for

    nse_rank = _rank_for("NSE_CORP_ANN")
    yf_rank = _rank_for("yfinance")
    # Lower rank = higher priority. NSE_CORP_ANN must win.
    assert nse_rank < yf_rank, "NSE_CORP_ANN must outrank yfinance"
    # Precedence guard predicate (EXCLUDED.rank <= existing.rank) is
    # FALSE when a new yfinance row arrives over an NSE_CORP_ANN row:
    assert (yf_rank <= nse_rank) is False
    # Conversely, an NSE_CORP_ANN row CAN overwrite an existing
    # yfinance row:
    assert (nse_rank <= yf_rank) is True
    # And NSE_ARCHIVE (15) still beats yfinance (50):
    assert _rank_for("NSE_ARCHIVE") < yf_rank


def test_upsert_sql_has_precedence_guard_for_every_updated_column():
    """Every column the UPSERT updates must be wrapped in the
    `CASE WHEN EXCLUDED.data_quality_rank <= corporate_actions.data_quality_rank ...`
    guard. A regression here would re-open the hole this PR closes."""
    from scripts.data_pipelines.fetch_corporate_actions import INSERT_SQL

    sql = str(INSERT_SQL)

    guarded_columns = [
        "ratio", "remarks", "adjustment_factor", "data_source",
    ]
    for col in guarded_columns:
        pat = re.compile(
            rf"\b{col}\s*=\s*CASE\s+WHEN\s+EXCLUDED\.data_quality_rank\s*<=\s*corporate_actions\.data_quality_rank",
            re.IGNORECASE | re.DOTALL,
        )
        assert pat.search(sql), (
            f"INSERT_SQL missing precedence guard for column `{col}`"
        )

    # data_quality_rank itself must use LEAST() so a row's rank can
    # only ever decrease (improve) — never regress.
    least_pat = re.compile(
        r"data_quality_rank\s*=\s*LEAST\s*\(\s*EXCLUDED\.data_quality_rank\s*,\s*corporate_actions\.data_quality_rank",
        re.IGNORECASE | re.DOTALL,
    )
    assert least_pat.search(sql), (
        "INSERT_SQL must monotonically improve data_quality_rank via LEAST()"
    )

    # The INSERT column list must include data_source + data_quality_rank
    # and bind them.
    assert "data_source" in sql
    assert ":data_source" in sql
    assert "data_quality_rank" in sql
    assert ":data_quality_rank" in sql

    # The ON CONFLICT target is the natural key from migration 010.
    on_conflict = re.compile(
        r"ON\s+CONFLICT\s*\(\s*ticker\s*,\s*ex_date\s*,\s*action_type\s*\)\s*DO\s+UPDATE",
        re.IGNORECASE | re.DOTALL,
    )
    assert on_conflict.search(sql), (
        "INSERT_SQL must ON CONFLICT on (ticker, ex_date, action_type)"
    )


def test_yfinance_backfill_has_precedence_guard():
    """scripts/backfill_corporate_actions_yf.py must carry the same
    precedence-guard pattern so a re-run of the yfinance backfill
    cannot demote an existing NSE_CORP_ANN row.
    """
    import importlib

    mod = importlib.import_module("scripts.backfill_corporate_actions_yf")
    sql = str(mod.UPSERT_SQL)

    # The headline columns must be CASE-guarded.
    for col in ("ratio", "remarks", "adjustment_factor", "data_source"):
        guard = re.compile(
            rf"{col}\s*=\s*CASE\s+WHEN\s+EXCLUDED\.data_quality_rank\s*<=\s*corporate_actions\.data_quality_rank",
            re.IGNORECASE | re.DOTALL,
        )
        assert guard.search(sql), (
            f"backfill_corporate_actions_yf.UPSERT_SQL missing guard for `{col}`"
        )
    assert "LEAST(EXCLUDED.data_quality_rank" in sql, (
        "backfill_corporate_actions_yf must use LEAST() so rank can only improve"
    )
    # And it must declare yfinance as rank 50 in its lookup table.
    assert mod._rank_for("yfinance") == 50
    assert mod._rank_for("NSE_CORP_ANN") == 10
