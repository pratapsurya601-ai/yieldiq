# backend/tests/test_shareholding_yfcache_precedence.py
# DB-less unit tests for the source-precedence + write-guard pattern
# applied to `shareholding_pattern` and `yfinance_info_cache` (mirrors
# PR #208's pattern for `financials`).
#
# Three things proven:
#   1. shareholding writer: NSE_SHAREHOLDING (rank 10) outranks
#      BSE_SHAREHOLDING (rank 30) → BSE cannot displace NSE.
#   2. yfinance_info_cache: write guard rejects financialCurrency='USD'
#      on an Indian-primary ticker (the 2026-04-29 INFY ADR mistag).
#   3. yfinance_info_cache: write guard rejects trailingPE > 1000.

from __future__ import annotations

from unittest.mock import patch


# ── Test 1: shareholding NSE > BSE precedence ─────────────────────────


def test_nse_shareholding_outranks_bse():
    from data_pipeline.sources.nse_shareholding import (
        _rank_for, _should_overwrite, _RANK_BY_SOURCE,
    )

    assert _RANK_BY_SOURCE["NSE_SHAREHOLDING"] == 10
    assert _RANK_BY_SOURCE["BSE_SHAREHOLDING"] == 30
    assert _rank_for("NSE_SHAREHOLDING") < _rank_for("BSE_SHAREHOLDING")
    assert _rank_for("yfinance") == 50
    assert _rank_for(None) == 60  # unknown / default

    nse_rank = _rank_for("NSE_SHAREHOLDING")
    bse_rank = _rank_for("BSE_SHAREHOLDING")

    # NSE can overwrite an existing BSE row.
    assert _should_overwrite(existing_rank=bse_rank, incoming_rank=nse_rank) is True
    # BSE cannot overwrite an existing NSE row.
    assert _should_overwrite(existing_rank=nse_rank, incoming_rank=bse_rank) is False
    # NSE re-running is idempotent (equal rank wins).
    assert _should_overwrite(existing_rank=nse_rank, incoming_rank=nse_rank) is True
    # NULL existing rank is treated as worst-default (60); any concrete
    # rank can fill it.
    assert _should_overwrite(existing_rank=None, incoming_rank=bse_rank) is True
    assert _should_overwrite(existing_rank=None, incoming_rank=60) is True


# ── Test 2: yfinance_info_cache rejects ADR USD mistag ────────────────


def test_yfcache_write_guard_rejects_usd_on_indian_primary():
    from data_pipeline.sources import yf_info_cache

    # Force the Indian-primary check to return True without touching DB.
    with patch.object(yf_info_cache, "_is_indian_primary_ticker", return_value=True):
        info = {
            "shortName": "Infosys Ltd",
            "regularMarketPrice": 1500.0,
            "financialCurrency": "USD",   # the mistag
            "marketCap": 7e12,
            "trailingPE": 28.0,
        }
        ok, reason = yf_info_cache._validate_info_for_write("INFY", info)
        assert ok is False
        assert reason is not None
        assert "USD" in reason
        assert "INFY" in reason


def test_yfcache_write_guard_allows_usd_on_us_primary_adr():
    from data_pipeline.sources import yf_info_cache

    # WIT (Wipro ADR) is US-primary — USD is correct, must not be flagged.
    with patch.object(yf_info_cache, "_is_indian_primary_ticker", return_value=False):
        info = {
            "shortName": "Wipro Ltd ADR",
            "regularMarketPrice": 2.85,
            "financialCurrency": "USD",
            "marketCap": 30e9,
            "trailingPE": 22.0,
        }
        ok, reason = yf_info_cache._validate_info_for_write("WIT", info)
        assert ok is True, f"Should not reject US-primary ADR; got: {reason}"


# ── Test 3: yfinance_info_cache rejects PE > 1000 ─────────────────────


def test_yfcache_write_guard_rejects_pe_over_1000():
    from data_pipeline.sources import yf_info_cache

    with patch.object(yf_info_cache, "_is_indian_primary_ticker", return_value=True):
        info = {
            "shortName": "Bogus Co",
            "regularMarketPrice": 100.0,
            "financialCurrency": "INR",
            "marketCap": 5e10,
            "trailingPE": 9999.0,   # unit bug
        }
        ok, reason = yf_info_cache._validate_info_for_write("BOGUS", info)
        assert ok is False
        assert reason is not None
        assert "trailingPE" in reason


def test_yfcache_write_guard_rejects_marketcap_overflow():
    from data_pipeline.sources import yf_info_cache

    with patch.object(yf_info_cache, "_is_indian_primary_ticker", return_value=True):
        info = {
            "shortName": "Overflow Co",
            "regularMarketPrice": 100.0,
            "financialCurrency": "INR",
            "marketCap": 5e16,   # > 1e15 cap
            "trailingPE": 25.0,
        }
        ok, reason = yf_info_cache._validate_info_for_write("OVRFLW", info)
        assert ok is False
        assert "marketCap" in reason


def test_yfcache_write_guard_passes_valid_indian_row():
    from data_pipeline.sources import yf_info_cache

    with patch.object(yf_info_cache, "_is_indian_primary_ticker", return_value=True):
        info = {
            "shortName": "Reliance Industries",
            "regularMarketPrice": 2900.0,
            "financialCurrency": "INR",
            "marketCap": 19e12,
            "trailingPE": 28.5,
        }
        ok, reason = yf_info_cache._validate_info_for_write("RELIANCE", info)
        assert ok is True, f"Should accept valid INR row; got: {reason}"
        assert reason is None
