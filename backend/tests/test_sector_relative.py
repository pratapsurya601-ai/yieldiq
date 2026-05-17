"""Tests for screener.sector_relative peer lookup helpers.

Regression for the empty-peers bug: callers pass bare tickers
(``RELIANCE``) but DIRECT_PEERS stores NSE tickers (``RELIANCE.NS``),
so peer comparison returned [] across the entire universe.
"""
from __future__ import annotations

from screener.sector_relative import get_peers_for_ticker


def test_get_peers_for_ticker_bare_symbol_returns_oil_gas_peers():
    peers = get_peers_for_ticker("RELIANCE")
    # Expect ONGC / IOC / BPCL from the oil_gas group, .NS-suffixed
    assert peers, "bare symbol RELIANCE should resolve to a non-empty peer set"
    assert "ONGC.NS" in peers
    assert "IOC.NS" in peers
    assert "BPCL.NS" in peers
    # The ticker itself must not appear in its own peer list (under any suffix).
    assert "RELIANCE.NS" not in peers
    assert "RELIANCE" not in peers


def test_get_peers_for_ticker_ns_suffix_is_idempotent():
    bare = get_peers_for_ticker("RELIANCE")
    suffixed = get_peers_for_ticker("RELIANCE.NS")
    assert bare == suffixed, (
        "suffix normalization must be idempotent: bare and .NS forms "
        "should resolve to the same peer set"
    )


def test_get_peers_for_ticker_unknown_returns_empty():
    assert get_peers_for_ticker("NONEXISTENT") == []
    assert get_peers_for_ticker("") == []
    assert get_peers_for_ticker(None) == []  # type: ignore[arg-type]


def test_get_peers_for_ticker_no_false_match_on_partial_string():
    # Ensure we are matching whole tickers, not substrings.
    # "TCS" should resolve via .NS suffix to TCS.NS (it_services group).
    peers = get_peers_for_ticker("TCS")
    assert "INFY.NS" in peers
    assert "TCS.NS" not in peers  # self must be excluded
