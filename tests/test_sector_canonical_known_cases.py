"""Pin known sector-canonicalization cases flagged by the
2026-05-16 audit so they don't regress as the alias map evolves.

Audit found 20 distinct sector labels across the cache where the
backend taxonomy only defines 13 canonical buckets. The aliases
that mattered most for ticker coverage:

  HDFCBANK / ICICIBANK / SBIN  -> sector should be "Bank" or
       "Private Bank" / "PSU Bank" depending on classification —
       NEVER the legacy yfinance-top-level "Financial Services"
       label, which lumps NBFCs/insurers/banks together.
  INFY / TCS / WIPRO          -> "IT Services", not yfinance
       "Technology".
  SUNPHARMA / DIVISLAB        -> "Pharma", not yfinance
       "Healthcare" / "Pharmaceuticals".
  DLF / GODREJPROP            -> "Real Estate", not "Realty".
  HINDUNILVR / NESTLEIND      -> "FMCG", not yfinance
       "Consumer Defensive" / "Consumer Staples".
"""
from __future__ import annotations

import pytest

from backend.services.sector_taxonomy import (
    CANONICAL_SECTORS,
    normalize_sector,
)


@pytest.mark.parametrize("raw,expected", [
    # IT family
    ("Technology", "IT Services"),
    ("Information Technology", "IT Services"),
    ("Software", "IT Services"),
    ("IT", "IT Services"),
    # Bank family — generic falls to "Bank" (canonical), not Financial Services
    ("Banks", "Bank"),
    ("Banking", "Bank"),
    # Pharma / healthcare
    ("Pharmaceuticals", "Pharma"),
    ("Healthcare", "Pharma"),
    ("Health Care", "Pharma"),
    # Real estate
    ("Realty", "Real Estate"),
    ("real estate investment", "Real Estate"),
    # FMCG
    ("Consumer Staples", "FMCG"),
    ("Fast Moving Consumer Goods", "FMCG"),
    # Auto
    ("Automobiles", "Auto"),
    ("Auto OEM", "Auto"),
    # Metal
    ("Metals", "Metal"),
    ("Mining", "Metal"),
    # Energy
    ("Oil & Gas", "Energy"),
    ("Power", "Energy"),
])
def test_alias_map_canonicalizes_known_pairs(raw, expected):
    assert normalize_sector(raw) == expected


@pytest.mark.parametrize("infy_label", ["Technology", "IT Services", "technology", "  IT Services  "])
def test_infy_lands_on_it_services(infy_label):
    assert normalize_sector(infy_label) == "IT Services"


@pytest.mark.parametrize("hdfcbank_label", ["Banks", "Bank", "banking", "BANKS"])
def test_hdfcbank_lands_on_bank_not_financial_services(hdfcbank_label):
    out = normalize_sector(hdfcbank_label)
    assert out == "Bank"
    assert out != "Financial Services"


def test_canonical_sectors_count_is_thirteen():
    """If this trips, audit assumed 13 canonical sectors and downstream
    docs/PR copy needs updating along with the taxonomy."""
    assert len(CANONICAL_SECTORS) == 13


def test_unknown_sector_falls_through_unchanged():
    """Never silently erase an NSE bucket we haven't mapped yet."""
    assert normalize_sector("Brand New Sector") == "Brand New Sector"


def test_null_inputs_return_none():
    assert normalize_sector(None) is None
    assert normalize_sector("") is None
    assert normalize_sector("   ") is None
