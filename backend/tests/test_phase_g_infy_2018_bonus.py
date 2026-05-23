# backend/tests/test_phase_g_infy_2018_bonus.py
# Regression test for GH issue #545: INFY's 2018-09-04 1:1 bonus was
# missing from `corporate_actions` because the yfinance fallback only
# fired when NSE returned ZERO rows. INFY has plenty of NSE dividend
# rows so the fallback never ran, even though NSE's historical feed
# was structurally missing the split.
#
# Fix (scripts/data_pipelines/fetch_corporate_actions.py): also fire
# the yfinance fallback when NSE rows exist but contain no SPLIT/BONUS
# coverage, and augment (not replace) with the yfinance split/bonus
# rows. The ON CONFLICT precedence guard prevents yfinance from
# displacing existing NSE rows, so augmenting is safe.
#
# These tests are DB-less. They drive the in-process `inner(ticker)`
# closure with stubbed bulk / historical / yfinance sources and a
# stubbed session_factory that records what was UPSERTed.

from __future__ import annotations

from datetime import date
from types import SimpleNamespace
from unittest.mock import patch


def _make_session_recorder():
    """Return (session_factory, captured_payloads) where the factory
    yields a stub Session that records every `execute(sql, payload)`
    call into the captured list."""
    captured: list[dict] = []

    class _StubSession:
        def execute(self, _sql, payload):
            captured.append(dict(payload))

        def commit(self):
            pass

        def rollback(self):
            pass

        def close(self):
            pass

    return (lambda: _StubSession()), captured


def _yf_infy_rows() -> list[dict]:
    """The shape `_from_yfinance` returns for INFY: a few dividends
    plus the 2018-09-04 1:1 bonus (factor=2.0)."""
    return [
        {
            "action_type": "BONUS",
            "ex_date": date(2018, 9, 4),
            "ratio": "factor=2",
            "remarks": "yfinance splits: 2",
            "adjustment_factor": 2.0,
            "data_source": "yfinance",
            "data_quality_rank": 50,
        },
        {
            "action_type": "DIVIDEND",
            "ex_date": date(2024, 6, 1),
            "ratio": "Rs 20.0000",
            "remarks": "yfinance dividend Rs 20.0000",
            "adjustment_factor": 1.0,
            "data_source": "yfinance",
            "data_quality_rank": 50,
        },
    ]


def _nse_infy_dividends_only() -> list[dict]:
    """Simulates NSE's per-symbol historical returning only DIVIDEND
    rows for INFY — the real-world signature behind issue #545."""
    return [
        {
            "action_type": "DIVIDEND",
            "ex_date": date(2024, 5, 30),
            "ratio": "Final Dividend Rs 20",
            "remarks": "Final Dividend",
            "adjustment_factor": 1.0,
            "data_source": "NSE_ARCHIVE",
            "data_quality_rank": 15,
        },
        {
            "action_type": "DIVIDEND",
            "ex_date": date(2023, 11, 1),
            "ratio": "Interim Dividend Rs 18",
            "remarks": "Interim Dividend",
            "adjustment_factor": 1.0,
            "data_source": "NSE_ARCHIVE",
            "data_quality_rank": 15,
        },
    ]


def test_infy_2018_bonus_lands_when_nse_returns_only_dividends():
    """The regression: NSE returns 2 dividend rows for INFY, no bonus.
    Before fix #545, yfinance never ran because `rows` was non-empty.
    After fix, yfinance runs and we UPSERT the 2018-09-04 BONUS."""
    from scripts.data_pipelines import fetch_corporate_actions as fca

    session_factory, captured = _make_session_recorder()

    # Pre-seed the in-process bulk cache so `_ensure_bulk_loaded`
    # short-circuits (the real impl hits the network). INFY absent from
    # bulk means rows starts empty until historical fills it.
    with patch.object(fca, "_BULK_BY_TICKER", {}), \
         patch.object(fca, "_session", lambda: SimpleNamespace()), \
         patch.object(
             fca, "_from_nse_per_symbol",
             lambda symbol, http: _nse_infy_dividends_only(),
         ), \
         patch.object(
             fca, "_from_yfinance",
             lambda yf_sym: _yf_infy_rows(),
         ):
        inner = fca._fetch_one(session_factory)
        result = inner("INFY")

    assert result["status"] == "ok", result
    # The fix manifests in the source label: when NSE returned rows
    # but yfinance contributed the SPLIT/BONUS coverage, source
    # ends in "+yfinance_splits".
    assert "yfinance_splits" in result["source"], result

    # The 2018 bonus must be in the UPSERT payloads.
    bonus_rows = [
        p for p in captured
        if p.get("ticker") == "INFY"
        and p.get("ex_date") == date(2018, 9, 4)
        and (p.get("action_type") or "").upper() == "BONUS"
    ]
    assert len(bonus_rows) == 1, (
        f"expected exactly one INFY 2018-09-04 BONUS upsert, "
        f"got {len(bonus_rows)}; all captured={captured}"
    )
    assert bonus_rows[0]["adjustment_factor"] == 2.0
    assert bonus_rows[0]["data_source"] == "yfinance"


def test_yfinance_dividends_are_not_duplicated_when_nse_has_dividends():
    """Augmentation must skip yfinance DIVIDEND rows when NSE already
    provided dividends — otherwise every ticker doubles its dividend
    row count on every cron tick. Only SPLIT/BONUS rows are carried
    forward from yfinance into the augment path."""
    from scripts.data_pipelines import fetch_corporate_actions as fca

    session_factory, captured = _make_session_recorder()

    with patch.object(fca, "_BULK_BY_TICKER", {}), \
         patch.object(fca, "_session", lambda: SimpleNamespace()), \
         patch.object(
             fca, "_from_nse_per_symbol",
             lambda symbol, http: _nse_infy_dividends_only(),
         ), \
         patch.object(
             fca, "_from_yfinance",
             lambda yf_sym: _yf_infy_rows(),
         ):
        inner = fca._fetch_one(session_factory)
        inner("INFY")

    yf_dividend_rows = [
        p for p in captured
        if p.get("data_source") == "yfinance"
        and (p.get("action_type") or "").upper() == "DIVIDEND"
    ]
    assert yf_dividend_rows == [], (
        "yfinance DIVIDEND rows must not be upserted when NSE already "
        "covers dividends; got " + str(yf_dividend_rows)
    )


def test_yfinance_skipped_when_nse_already_has_split_or_bonus():
    """Negative: if NSE historical returned a BONUS row, the yfinance
    fallback must not fire at all — we don't want a low-rank yfinance
    fetch to add noise when NSE has already covered split/bonus."""
    from scripts.data_pipelines import fetch_corporate_actions as fca

    session_factory, captured = _make_session_recorder()

    nse_with_bonus = _nse_infy_dividends_only() + [
        {
            "action_type": "BONUS",
            "ex_date": date(2018, 9, 4),
            "ratio": "1:1 Bonus",
            "remarks": "Bonus 1:1",
            "adjustment_factor": 2.0,
            "data_source": "NSE_ARCHIVE",
            "data_quality_rank": 15,
        },
    ]

    yf_calls: list[str] = []

    def _yf_spy(sym):
        yf_calls.append(sym)
        return _yf_infy_rows()

    with patch.object(fca, "_BULK_BY_TICKER", {}), \
         patch.object(fca, "_session", lambda: SimpleNamespace()), \
         patch.object(
             fca, "_from_nse_per_symbol",
             lambda symbol, http: nse_with_bonus,
         ), \
         patch.object(fca, "_from_yfinance", _yf_spy):
        inner = fca._fetch_one(session_factory)
        result = inner("INFY")

    assert result["status"] == "ok"
    assert yf_calls == [], (
        "yfinance must not be called when NSE already returned a "
        "SPLIT/BONUS row; got calls=" + str(yf_calls)
    )
    # And the upserts should only carry NSE-sourced rows.
    sources = {p.get("data_source") for p in captured}
    assert sources == {"NSE_ARCHIVE"}, sources
