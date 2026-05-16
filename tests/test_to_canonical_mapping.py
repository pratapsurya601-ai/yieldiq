"""Tests for backend.services.sector_taxonomy.to_canonical and the
per-ticker override fixes from the 2026-05-16 audit.

Why these tests exist
---------------------
The audit found three failure modes in `stocks.sector`:

1. Provider-mix (yfinance broad labels like "Basic Materials" /
   "Industrials" / "Consumer Cyclical" alongside NSE-style "Nifty
   Bank" alongside hand-curated "Bank") — fixed by the (sector,
   industry) rules in INDUSTRY_CANONICAL_RULES.

2. NULL raw sector on 3 active tickers — fixed by the "Unknown"
   fallback (so cohort SQL never crashes).

3. Hand-resolved mis-tags on 13 named tickers (POLICYBZR / RELIGARE
   / HDFCLIFE / ICICIGI / SBILIFE / GOCOLORS / MEDPLUS / SBICARD,
   plus follow-on insurers) — fixed by TICKER_CANONICAL_OVERRIDES.

If any of these regress, the sector aggregator silently slices the
wrong cohort and the verdict on the sector deep-dive page goes
quietly wrong. Pin them here.
"""
from __future__ import annotations

import pytest

from backend.services.sector_taxonomy import (
    CANONICAL_SECTORS,
    TICKER_CANONICAL_OVERRIDES,
    to_canonical,
)


# ── Per-ticker overrides (the audit's named mis-tags) ────────────


@pytest.mark.parametrize("ticker,expected_sector,expected_industry", [
    # Insurance aggregator was tagged Insurance Brokers - not an underwriter
    ("POLICYBZR", "Financial Services", "Insurance"),
    # Diversified holdco previously mis-tagged Insurance - Life
    ("RELIGARE",  "Financial Services", "NBFC"),
    # Life / general insurers tagged with industry "Nifty Financial Services"
    ("HDFCLIFE",  "Financial Services", "Insurance"),
    ("ICICIGI",   "Financial Services", "Insurance"),
    ("SBILIFE",   "Financial Services", "Insurance"),
    ("ICICIPRULI", "Financial Services", "Insurance"),
    ("LICI",      "Financial Services", "Insurance"),
    # Specialty retailer/services overrides
    ("GOCOLORS",  "Consumer Durables", "Apparel Retail"),
    ("MEDPLUS",   "Pharma", "Pharmaceutical Retailers"),
    # Credit cards roll into NBFC
    ("SBICARD",   "Financial Services", "NBFC"),
])
def test_ticker_overrides_win_over_raw_labels(ticker, expected_sector, expected_industry):
    # Pass deliberately mis-leading raw labels — the override must still win.
    sec, ind = to_canonical("Healthcare", "Bogus Industry", ticker)
    assert sec == expected_sector
    assert ind == expected_industry


def test_every_override_uses_a_canonical_sector():
    """TICKER_CANONICAL_OVERRIDES must only reference canonical buckets."""
    canon = set(CANONICAL_SECTORS)
    for tkr, (sec, _ind) in TICKER_CANONICAL_OVERRIDES.items():
        assert sec in canon, f"{tkr}: {sec!r} not in CANONICAL_SECTORS"


# ── Industry-aware rules for yfinance broad labels ───────────────


@pytest.mark.parametrize("raw_sector,raw_industry,expected", [
    # Consumer Cyclical fans out — confirm representative routes
    ("Consumer Cyclical", "Auto Parts", "Auto"),
    ("Consumer Cyclical", "Auto Manufacturers", "Auto"),
    ("Consumer Cyclical", "Apparel Manufacturing", "Consumer Durables"),
    ("Consumer Cyclical", "Textile Manufacturing", "Consumer Durables"),
    ("Consumer Cyclical", "Footwear & Accessories", "Consumer Durables"),
    ("Consumer Cyclical", "Lodging", "Consumer Durables"),
    # Consumer Defensive → FMCG mostly
    ("Consumer Defensive", "Packaged Foods", "FMCG"),
    ("Consumer Defensive", "Tobacco", "FMCG"),
    ("Consumer Defensive", "Beverages - Non-Alcoholic", "FMCG"),
    # Basic Materials disambiguation
    ("Basic Materials", "Steel", "Metal"),
    ("Basic Materials", "Aluminum", "Metal"),
    ("Basic Materials", "Specialty Chemicals", "Energy"),
    # Communication Services → Media
    ("Communication Services", "Telecom Services", "Media"),
    ("Communication Services", "Broadcasting", "Media"),
    ("Communication Services", "Entertainment", "Media"),
    # Utilities → Energy
    ("Utilities", "Utilities - Renewable", "Energy"),
    ("Utilities", "Utilities - Regulated Electric", "Energy"),
    # Financial Services keeps its name unless a bank hint appears
    ("Financial Services", "Credit Services", "Financial Services"),
    ("Financial Services", "Asset Management", "Financial Services"),
    ("Financial Services", "Capital Markets", "Financial Services"),
    # Already-canonical short labels pass through
    ("FMCG", "Nifty FMCG", "FMCG"),
    ("Pharma", "Nifty Pharma", "Pharma"),
    ("Bank", "Nifty Bank", "Bank"),
])
def test_industry_aware_rules(raw_sector, raw_industry, expected):
    sec, _ind = to_canonical(raw_sector, raw_industry, ticker=None)
    assert sec == expected


# ── NULL / unknown handling ──────────────────────────────────────


def test_null_sector_becomes_unknown():
    sec, ind = to_canonical(None, None, "FOO")
    assert sec == "Unknown"
    assert ind is None


def test_empty_sector_becomes_unknown():
    sec, _ = to_canonical("", "", None)
    assert sec == "Unknown"


def test_industry_preserved_when_sector_null():
    sec, ind = to_canonical(None, "Some Industry", None)
    assert sec == "Unknown"
    assert ind == "Some Industry"


def test_truly_unknown_sector_buckets_to_unknown():
    """A raw label we have no rule for AND that is not canonical
    must bucket as 'Unknown' — never leak a one-off NSE label."""
    sec, _ = to_canonical("Some Brand New Label", "Foo", None)
    assert sec == "Unknown"


def test_canonical_passthrough():
    """If the raw sector is already a canonical name, return verbatim."""
    for name in CANONICAL_SECTORS:
        sec, _ = to_canonical(name, None, None)
        assert sec == name


# ── Aggregator integration: prefers canonical_sector column ──────


def test_aggregator_prefers_canonical_sector_column():
    """sector_aggregator.build_sector_prism must match constituents
    on `canonical_sector` when present, ignoring the raw sector
    label entirely."""
    from backend.services.sector_aggregator import build_sector_prism

    # Constituent has a raw sector that would NOT match "Bank" via
    # normalize_sector() — but canonical_sector explicitly says Bank.
    # If the aggregator honours the canonical column, this lands in
    # the Bank cohort.
    constituents = [
        {
            "ticker": "FOOBANK",
            "sector": "Some Garbage Label",
            "canonical_sector": "Bank",
            "analysis": {},
        }
    ]
    out = build_sector_prism("Bank", constituents)
    assert out["constituent_count"] == 1


def test_aggregator_falls_back_to_normalize_sector_when_canonical_absent():
    """Legacy cache payloads predate canonical_sector — the
    aggregator must still slice correctly using normalize_sector
    on the raw label."""
    from backend.services.sector_aggregator import build_sector_prism

    constituents = [
        {"ticker": "INFY", "sector": "Technology", "analysis": {}},
    ]
    out = build_sector_prism("IT Services", constituents)
    assert out["constituent_count"] == 1
