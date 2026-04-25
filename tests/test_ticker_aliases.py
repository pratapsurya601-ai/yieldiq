"""Unit tests for the corporate-actions ticker alias resolver.

Covers the three ResolveResult variants (Fetch / Skip / Redirect), the
O(1)-no-file-read fast path for active tickers, get_status, and the
router-facing get_successors_payload helper. Each test writes a
temporary YAML and points YIELDIQ_TICKER_ALIASES_PATH at it so the
tests never depend on the checked-in config file.
"""
from __future__ import annotations

import os
import sys
import textwrap
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from data_pipeline import ticker_aliases as ta  # noqa: E402


# ---------------------------------------------------------------------------
# Fixture: write a YAML and repoint the loader at it.
# ---------------------------------------------------------------------------
@pytest.fixture
def alias_yaml(tmp_path, monkeypatch):
    def _write(content: str) -> Path:
        p = tmp_path / "ticker_aliases.yaml"
        p.write_text(textwrap.dedent(content), encoding="utf-8")
        monkeypatch.setenv("YIELDIQ_TICKER_ALIASES_PATH", str(p))
        ta._clear_cache()
        return p
    yield _write
    ta._clear_cache()


# ---------------------------------------------------------------------------
# Active / unknown ticker — fast path.
# ---------------------------------------------------------------------------
def test_unknown_ticker_returns_fetch_with_ns_suffix(alias_yaml):
    alias_yaml("")  # empty config
    res = ta.resolve_for_fetch("RELIANCE")
    assert isinstance(res, ta.Fetch)
    assert res.symbol == "RELIANCE.NS"
    assert res.ticker == "RELIANCE"


def test_unknown_ticker_with_no_config_file(monkeypatch):
    # Point at a non-existent path — loader must degrade to empty dict.
    monkeypatch.setenv("YIELDIQ_TICKER_ALIASES_PATH", "/does/not/exist.yaml")
    ta._clear_cache()
    res = ta.resolve_for_fetch("RELIANCE")
    assert isinstance(res, ta.Fetch)
    assert res.symbol == "RELIANCE.NS"


def test_special_symbol_preserves_ampersand(alias_yaml):
    alias_yaml("")
    res = ta.resolve_for_fetch("M&M")
    assert isinstance(res, ta.Fetch)
    assert res.symbol == "M&M.NS"


# ---------------------------------------------------------------------------
# Renamed — LTIM case.
# ---------------------------------------------------------------------------
def test_renamed_ticker_fetches_with_override(alias_yaml):
    alias_yaml("""
        LTIM:
          status: renamed
          former_symbol: MINDTREE
          effective_date: 2022-11-14
          fetch_symbol: LTIM.NS
    """)
    res = ta.resolve_for_fetch("LTIM")
    assert isinstance(res, ta.Fetch)
    assert res.symbol == "LTIM.NS"
    assert ta.get_status("LTIM") == "renamed"


# ---------------------------------------------------------------------------
# Demerged_pending — TATAMOTORS case (Q1 2026).
# ---------------------------------------------------------------------------
def test_demerged_pending_returns_skip(alias_yaml):
    alias_yaml("""
        TATAMOTORS:
          status: demerged_pending
          effective_date: 2026-03-01
          successors:
            - ticker: TMPV
              share_ratio: 1.0
              fetch_symbol: null
            - ticker: TMCV
              share_ratio: 1.0
              fetch_symbol: null
          note: pending listing
    """)
    res = ta.resolve_for_fetch("TATAMOTORS")
    assert isinstance(res, ta.Skip)
    assert res.reason == "demerged_pending"
    assert ta.get_status("TATAMOTORS") == "demerged_pending"


# ---------------------------------------------------------------------------
# Demerged with fetchable successors — returns Redirect.
# ---------------------------------------------------------------------------
def test_demerged_returns_redirect_with_successors(alias_yaml):
    alias_yaml("""
        TATAMOTORS:
          status: demerged
          effective_date: 2026-03-01
          successors:
            - ticker: TMPV
              share_ratio: 1.0
              fetch_symbol: TMPV.NS
            - ticker: TMCV
              share_ratio: 1.0
              fetch_symbol: TMCV.NS
    """)
    res = ta.resolve_for_fetch("TATAMOTORS")
    assert isinstance(res, ta.Redirect)
    assert [s.ticker for s in res.successors] == ["TMPV", "TMCV"]
    assert all(s.fetch_symbol for s in res.successors)


def test_demerged_without_fetch_symbols_skips(alias_yaml):
    # Config tags status=demerged but nobody filled in fetch_symbols yet.
    alias_yaml("""
        FOO:
          status: demerged
          successors:
            - ticker: BAR
              share_ratio: 1.0
    """)
    res = ta.resolve_for_fetch("FOO")
    assert isinstance(res, ta.Skip)
    assert res.reason == "demerged_no_fetch_symbols"


# ---------------------------------------------------------------------------
# Delisted — HDFC case.
# ---------------------------------------------------------------------------
def test_delisted_returns_skip(alias_yaml):
    alias_yaml("""
        HDFC:
          status: delisted
          effective_date: 2023-07-13
          successors:
            - ticker: HDFCBANK
              share_ratio: 1.68
              fetch_symbol: HDFCBANK.NS
    """)
    res = ta.resolve_for_fetch("HDFC")
    assert isinstance(res, ta.Skip)
    assert res.reason == "delisted"
    assert ta.get_status("HDFC") == "delisted"


# ---------------------------------------------------------------------------
# get_successors_payload shape — what the router returns.
# ---------------------------------------------------------------------------
def test_successors_payload_for_demerged_pending(alias_yaml):
    alias_yaml("""
        TATAMOTORS:
          status: demerged_pending
          effective_date: 2026-03-01
          successors:
            - ticker: TMPV
              share_ratio: 1.0
              fetch_symbol: null
          note: Q1 2026 demerger
    """)
    payload = ta.get_successors_payload("TATAMOTORS")
    assert payload is not None
    assert payload["status"] == "demerged_pending"
    assert payload["ticker"] == "TATAMOTORS"
    assert payload["effective_date"] == "2026-03-01"
    assert payload["successors"][0]["ticker"] == "TMPV"


def test_successors_payload_none_for_active(alias_yaml):
    alias_yaml("""
        VEDL:
          status: active
          fetch_symbol: VEDL.NS
    """)
    assert ta.get_successors_payload("VEDL") is None
    assert ta.get_successors_payload("RELIANCE") is None  # no entry


# ---------------------------------------------------------------------------
# Case / whitespace insensitivity on input.
# ---------------------------------------------------------------------------
def test_lookup_is_case_insensitive(alias_yaml):
    alias_yaml("""
        LTIM:
          status: renamed
          fetch_symbol: LTIM.NS
    """)
    assert ta.get_status("ltim") == "renamed"
    assert ta.get_status("  LTIM  ") == "renamed"


# ---------------------------------------------------------------------------
# Malformed YAML degrades gracefully.
# ---------------------------------------------------------------------------
def test_malformed_yaml_degrades_to_empty(alias_yaml):
    alias_yaml("this: is: not: valid: yaml: [")
    # Should not raise; treats everything as active.
    res = ta.resolve_for_fetch("TATAMOTORS")
    assert isinstance(res, ta.Fetch)


# ---------------------------------------------------------------------------
# Integration stub: router corp-action gate contract.
# ---------------------------------------------------------------------------
def test_router_payload_contract_for_demerged(alias_yaml):
    """Shape check — confirms the dict the router returns matches the
    frontend contract (status Literal tag + successors array)."""
    alias_yaml("""
        TATAMOTORS:
          status: demerged_pending
          effective_date: 2026-03-01
          successors:
            - ticker: TMPV
              share_ratio: 1.0
              fetch_symbol: null
            - ticker: TMCV
              share_ratio: 1.0
              fetch_symbol: null
          note: Q1 2026
    """)
    payload = ta.get_successors_payload("TATAMOTORS")
    # Required keys for frontend branching.
    for k in ("status", "ticker", "successors", "effective_date", "note"):
        assert k in payload
    assert payload["status"] in {"demerged", "demerged_pending", "delisted"}
    assert isinstance(payload["successors"], list)
    for s in payload["successors"]:
        assert set(s.keys()) == {"ticker", "share_ratio", "fetch_symbol"}


# ---------------------------------------------------------------------------
# Nickname status (PR #83 — colloquial-alias resolution).
# ---------------------------------------------------------------------------
def test_nickname_resolves_to_canonical_via_resolve_for_fetch(alias_yaml):
    """A `status: nickname` entry must rewrite the request to its canonical
    ticker and use the canonical's default Yahoo symbol."""
    alias_yaml("""
        HUL:
          status: nickname
          canonical: HINDUNILVR
          note: Colloquial Hindustan Unilever ticker.
    """)
    res = ta.resolve_for_fetch("HUL")
    assert isinstance(res, ta.Fetch)
    # The Fetch.ticker is the canonical name so cache keys, payloads, and
    # analytics events all attribute against the real entity.
    assert res.ticker == "HINDUNILVR"
    assert res.symbol == "HINDUNILVR.NS"


def test_nickname_helper_returns_canonical(alias_yaml):
    """resolve_nickname is the dedicated read-path helper for the router."""
    alias_yaml("""
        HUL:
          status: nickname
          canonical: HINDUNILVR
    """)
    assert ta.resolve_nickname("HUL") == "HINDUNILVR"
    # Lower-case and whitespace tolerated.
    assert ta.resolve_nickname("  hul  ") == "HINDUNILVR"
    # Non-nickname entries return None so the caller falls through.
    assert ta.resolve_nickname("RELIANCE") is None
    assert ta.resolve_nickname("") is None


def test_nickname_does_not_emit_corp_action_payload(alias_yaml):
    """get_successors_payload must return None for nicknames so the
    router does NOT short-circuit them through the corp-action redirect
    branch — they are pure routing rewrites, not corporate events."""
    alias_yaml("""
        HUL:
          status: nickname
          canonical: HINDUNILVR
    """)
    assert ta.get_successors_payload("HUL") is None


def test_nickname_status_is_reported_via_get_status(alias_yaml):
    alias_yaml("""
        HUL:
          status: nickname
          canonical: HINDUNILVR
    """)
    assert ta.get_status("HUL") == "nickname"
    # Importantly, `nickname` is NOT in the corp-action set the router
    # gates on, so it should NEVER be confused for one.
    assert "nickname" not in ta.CORPORATE_ACTION_STATUSES


def test_nickname_missing_canonical_degrades_safely(alias_yaml):
    """A misconfigured nickname (no `canonical:`) must not raise — it
    falls back to the default fetch path so a YAML typo can never 500
    a user request."""
    alias_yaml("""
        HUL:
          status: nickname
    """)
    res = ta.resolve_for_fetch("HUL")
    assert isinstance(res, ta.Fetch)
    # Falls back to default <ticker>.NS for the nickname itself.
    assert res.symbol == "HUL.NS"
    assert res.ticker == "HUL"


def test_nickname_chained_through_renamed_canonical(alias_yaml):
    """If the canonical itself is a `renamed` entry, the nickname should
    pick up the canonical's `fetch_symbol` (one hop of indirection)."""
    alias_yaml("""
        ZOMATO:
          status: nickname
          canonical: ETERNAL
        ETERNAL:
          status: renamed
          former_symbol: ZOMATO
          fetch_symbol: ETERNAL.NS
    """)
    res = ta.resolve_for_fetch("ZOMATO")
    assert isinstance(res, ta.Fetch)
    assert res.ticker == "ETERNAL"
    assert res.symbol == "ETERNAL.NS"
