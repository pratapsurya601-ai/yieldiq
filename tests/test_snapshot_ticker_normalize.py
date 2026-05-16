"""Tests for the offline-script bare-ticker normalizer.

Pins the contract that prevents the 2026-05-17 cache-poisoning
incident: every snapshot/refresh entry point funnels tickers through
``scripts._ticker_normalize.normalize_for_compute`` before handing
them to the compute path. A bare ``"MPHASIS"`` leaked into yfinance
returns ``market_cap=0`` and poisons the cache row that other
healthy callers store under ``"MPHASIS.NS"``.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

_REPO = Path(__file__).resolve().parent.parent
_SCRIPTS = _REPO / "scripts"
if str(_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS))


def _force_known_indian_bare(monkeypatch, names: set[str]) -> None:
    """Override the live `stocks` table lookup so the test is hermetic."""
    from backend.services.analysis import utils as au
    monkeypatch.setattr(au, "_KNOWN_INDIAN_BARE", frozenset(names))


def test_normalize_bare_indian_gets_ns(monkeypatch):
    _force_known_indian_bare(monkeypatch, {"MPHASIS", "COFORGE", "PERSISTENT"})
    from _ticker_normalize import normalize_for_compute
    assert normalize_for_compute("MPHASIS") == "MPHASIS.NS"
    assert normalize_for_compute("COFORGE") == "COFORGE.NS"
    assert normalize_for_compute("PERSISTENT") == "PERSISTENT.NS"


def test_normalize_already_suffixed_unchanged(monkeypatch):
    _force_known_indian_bare(monkeypatch, {"MPHASIS"})
    from _ticker_normalize import normalize_for_compute
    assert normalize_for_compute("MPHASIS.NS") == "MPHASIS.NS"
    assert normalize_for_compute("RELIANCE.NS") == "RELIANCE.NS"
    assert normalize_for_compute("RELIANCE.BO") == "RELIANCE.BO"


def test_normalize_numeric_bse_scrip_code(monkeypatch):
    _force_known_indian_bare(monkeypatch, set())
    from _ticker_normalize import normalize_for_compute
    # MPHASIS's BSE scrip code is 526299; INFY's is 500209; ITC's 500875.
    # Whatever the digits, a 6-digit all-numeric string is a BSE code.
    assert normalize_for_compute("500188") == "500188.BO"
    assert normalize_for_compute("526299") == "526299.BO"


def test_normalize_whitespace_and_case(monkeypatch):
    _force_known_indian_bare(monkeypatch, {"MPHASIS"})
    from _ticker_normalize import normalize_for_compute
    assert normalize_for_compute(" mphasis ") == "MPHASIS.NS"
    assert normalize_for_compute("mphasis.ns") == "MPHASIS.NS"


def test_normalize_empty_and_none_passthrough():
    from _ticker_normalize import normalize_for_compute
    assert normalize_for_compute("") == ""
    assert normalize_for_compute(None) == ""  # type: ignore[arg-type]
    assert normalize_for_compute("   ") == ""


def test_normalize_unknown_bare_defaults_to_ns(monkeypatch):
    """Offline-script callers only ever process Indian universes, so a
    bare alphanumeric symbol not in the known set still gets .NS
    rather than being allowed to fall through to the US path."""
    _force_known_indian_bare(monkeypatch, set())
    from _ticker_normalize import normalize_for_compute
    # Unknown bare alphanumeric — defaults to .NS (script-only convention).
    assert normalize_for_compute("NEWLISTING") == "NEWLISTING.NS"
