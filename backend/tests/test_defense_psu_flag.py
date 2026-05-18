# backend/tests/test_defense_psu_flag.py
# Unit tests for the defense-PSU "analyst opinion required" NO-FIX
# flag — see docs/design/defense-psu-dcf-fix.md.
#
# These tests exercise the pure-classifier helper
# (constants.is_defense_psu) which is the single source of truth for
# the downstream service.py wiring (data_issues caveat, 0.7x
# confidence-score downgrade, analyst_opinion_required=True on
# ValuationOutput). The classifier strips .NS / .BO suffixes and
# matches a curated ticker allow-list.
from __future__ import annotations

import pytest

from backend.services.analysis.constants import (
    DEFENSE_PSU_TICKERS,
    is_defense_psu,
)


# ── Positive: defense PSUs MUST be flagged ───────────────────────


@pytest.mark.parametrize(
    "ticker",
    [
        "HAL.NS", "BEL.NS", "BDL.NS", "MAZAGON.NS",
        "GRSE.NS", "BEML.NS", "COCHINSHIP.NS", "MIDHANI.NS",
        "SOLARINDS.NS", "IDEAFORGE.NS", "ZENTEC.NS",
        "ASTRA-MICRO.NS", "DATAPATTERNS.NS", "MTAR.NS",
        "PARAS-DEFENCE.NS",
    ],
)
def test_defense_psu_listed_tickers_flagged(ticker):
    assert is_defense_psu(ticker) is True


def test_defense_psu_bo_suffix_also_flagged():
    # BSE-suffix variants should resolve the same way as .NS.
    assert is_defense_psu("HAL.BO") is True
    assert is_defense_psu("BEL.BO") is True


def test_defense_psu_bare_symbol_flagged():
    # No suffix is fine — bare uppercase symbol resolves.
    assert is_defense_psu("HAL") is True
    assert is_defense_psu("bdl") is True  # case-insensitive


def test_defense_psu_curated_set_covers_spec_tickers():
    # Spec lists 15 tickers (8 listed PSU + 7 private). Lock the set
    # so future edits to the curated allow-list are surfaced by a
    # diff in this test.
    spec_tickers = {
        "HAL", "BEL", "BDL", "MAZAGON", "GRSE", "BEML",
        "COCHINSHIP", "MIDHANI",
        "SOLARINDS", "IDEAFORGE", "ZENTEC", "ASTRA-MICRO",
        "DATAPATTERNS", "MTAR", "PARAS-DEFENCE",
    }
    assert spec_tickers <= DEFENSE_PSU_TICKERS


# ── Negative: non-defense names MUST NOT be flagged ──────────────


@pytest.mark.parametrize(
    "ticker",
    [
        "TCS.NS",          # IT services
        "RELIANCE.NS",     # Oil & Gas / conglomerate
        "HDFCBANK.NS",     # Banking
        "INFY.NS",         # IT
        "ITC.NS",          # FMCG
        "TATASTEEL.NS",    # Metals
        "MARUTI.NS",       # Auto
        "NTPC.NS",         # Utility (regulated, not defense)
    ],
)
def test_non_defense_tickers_not_flagged(ticker):
    assert is_defense_psu(ticker) is False


def test_empty_or_none_ticker_not_flagged():
    assert is_defense_psu(None) is False
    assert is_defense_psu("") is False


def test_sector_industry_args_accepted_but_optional():
    # Sector / industry are accepted (signature parity with sibling
    # classifiers) but should never flip a non-listed ticker to True
    # via keyword leakage — the curated set is the source of truth.
    assert is_defense_psu("TCS.NS", sector="Aerospace & Defense") is False
    assert is_defense_psu(
        "RELIANCE.NS", sector="Oil & Gas", industry="Defense",
    ) is False
    # And a real defense ticker stays True regardless of sector text.
    assert is_defense_psu("HAL.NS", sector="Industrials") is True
