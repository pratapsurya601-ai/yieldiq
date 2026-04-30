# backend/services/sector_benchmarks.py
# ═══════════════════════════════════════════════════════════════
# Sector → benchmark index mapping for the public Performance
# Retrospective.
#
# Why this exists
# ---------------
# Saying "our IT picks beat Nifty 500" is meaningless if Nifty IT
# itself outperformed Nifty 500 by a wider margin. The honest
# comparison for a sector-concentrated pick is the sector index:
# IT picks vs Nifty IT, banks vs Nifty Bank, pharma vs Nifty Pharma.
#
# This module owns the mapping. It is intentionally a flat dict —
# no DB lookup, no service object — so callers can resolve a sector
# to a benchmark ticker without a session.
#
# See also
# --------
#   docs/sector_benchmarks_design.md   (rationale, open questions)
#   backend/services/retrospective_service.py  (consumer)
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import logging
from typing import Optional

logger = logging.getLogger("yieldiq.sector_benchmarks")


# Canonical sector → Yahoo Finance ticker for the corresponding
# Nifty sector index. Keys are the canonical strings produced by
# our ingest pipeline (see `stocks.sector` column). Aliases for
# common variants are wired through SECTOR_ALIASES below.
#
# Tickers verified against yfinance / NSE indices listing as of
# 2026-04. If NSE renames an index, only this map needs to change.
SECTOR_BENCHMARK_MAP: dict[str, str] = {
    "IT Services":    "^CNXIT",        # Nifty IT
    "Banks":          "^NSEBANK",      # Nifty Bank
    "Pharma":         "^CNXPHARMA",    # Nifty Pharma
    "FMCG":           "^CNXFMCG",      # Nifty FMCG
    "Auto":           "^CNXAUTO",      # Nifty Auto
    "Metals":         "^CNXMETAL",     # Nifty Metal
    "Energy":         "^CNXENERGY",    # Nifty Energy
    "Realty":         "^CNXREALTY",    # Nifty Realty
    "Media":          "^CNXMEDIA",     # Nifty Media
    "PSU Bank":       "^CNXPSUBANK",   # Nifty PSU Bank
    "Financial Services": "^CNXFIN",   # Nifty Financial Services
    "Consumer Durables":  "^CNXCONSUM",# Nifty Consumer Durables (best fit)
    # Default fallback for unmapped sectors — keeps backward compat
    # with the legacy single-benchmark behaviour.
    "_default":       "NIFTY500.NS",
}


# Alias map: variant strings observed in the `stocks.sector` column
# (or older labels) → canonical key in SECTOR_BENCHMARK_MAP.
#
# Keep keys lowercase for case-insensitive matching in resolve().
SECTOR_ALIASES: dict[str, str] = {
    # IT
    "information technology":            "IT Services",
    "it":                                "IT Services",
    "software":                          "IT Services",
    "technology":                        "IT Services",
    # Banks
    "bank":                              "Banks",
    "banking":                           "Banks",
    "private bank":                      "Banks",
    "private sector bank":               "Banks",
    "public sector bank":                "PSU Bank",
    "psu banks":                         "PSU Bank",
    # Pharma
    "pharmaceuticals":                   "Pharma",
    "healthcare":                        "Pharma",
    "pharma & healthcare":               "Pharma",
    # FMCG
    "consumer staples":                  "FMCG",
    "consumer defensive":                "FMCG",   # yfinance top-level
    "fmcg & consumer":                   "FMCG",
    # Auto
    "automobile":                        "Auto",
    "automobiles":                       "Auto",
    "auto & ancillaries":                "Auto",
    # Metals
    "metal":                             "Metals",
    "metals & mining":                   "Metals",
    "mining":                            "Metals",
    "basic materials":                   "Metals",  # yfinance top-level
    # Energy
    "oil & gas":                         "Energy",
    "oil and gas":                       "Energy",
    "power":                             "Energy",
    "utilities":                         "Energy",
    # Realty
    "real estate":                       "Realty",
    "realty & construction":             "Realty",
    # Communication Services (yfinance lumps telecom + media + internet
    # together; map to Media for the benchmark, but the percentile
    # cohort rule handles the carve-out separately).
    "communication services":            "Media",
    # Media
    "media & entertainment":             "Media",
    "entertainment":                     "Media",
    # Financial Services (NBFCs, insurance, AMCs)
    "nbfc":                              "Financial Services",
    "financials":                        "Financial Services",
    "insurance":                         "Financial Services",
    # Consumer Durables
    "consumer durable":                  "Consumer Durables",
    "consumer goods":                    "Consumer Durables",
}


# Reverse-friendly: fully qualified Yahoo tickers that the
# index_snapshots / daily_prices tables may store under the bare
# symbol (no caret). The retrospective benchmark fetcher strips
# ".NS"/".BO" already; this map is for callers that want the bare
# form for SQL lookups.
# Per-canonical cohort filter rules.
#
# Why this exists
# ---------------
# `SECTOR_BENCHMARK_MAP` keys are *canonical* labels we coined
# (e.g. "IT Services", "Pharma", "FMCG"). The `stocks.sector`
# column, however, holds yfinance top-level sectors like
# "Technology", "Healthcare", "Consumer Defensive". Filtering
# `WHERE s.sector = 'IT Services'` therefore returns zero rows
# for every IT ticker — the cohort builder falls through to
# `data_limited` and the percentile band collapses to "Insufficient
# peer data". This was the root cause of the post-PR-#180 regression
# where INFY/TCS/NESTLEIND/etc. all rendered without a Value band.
#
# Each rule lists the stored `stocks.sector` strings that belong to
# the canonical cohort, plus an optional `industry_like` SQL pattern
# applied with ILIKE. The pattern lets us split coarse yfinance
# buckets — e.g. "Financial Services" stored sector contains both
# regional banks (canonical: Banks) and NBFCs/insurers/AMCs
# (canonical: Financial Services).
#
# Rules are intentionally inclusive: a missing canonical here means
# `_canonical_sector` will resolve the alias but the SQL will fall
# back to an exact-match on the canonical string (legacy behaviour),
# which yields an empty cohort. Adding a sector here is the single
# action that makes its tickers leave `data_limited`.
SECTOR_COHORT_RULES: dict[str, dict] = {
    "IT Services": {
        # yfinance lumps Indian IT services under "Technology"
        # (Information Technology Services / Software industries).
        # Post-PR #196 NSE-canonical labels: "IT Services",
        # "Information Technology".
        "sectors": [
            "Technology",                # yfinance legacy
            "IT Services",               # NSE canonical (post-PR #196)
            "Information Technology",    # alt NSE variant
        ],
        "industry_like": None,
    },
    "Banks": {
        # yfinance stores banks under "Financial Services" with
        # industry "Banks - Regional"/"Banks - Diversified". Post-PR
        # #196, NSE-canonical "Banks" lands directly in stocks.sector.
        "sectors": [
            "Financial Services",        # yfinance legacy (filtered by industry_like)
            "Banks",                     # NSE canonical (post-PR #196)
        ],
        # Banks - Regional / Banks - Diversified / etc.
        "industry_like": "Banks%",
    },
    "PSU Bank": {
        # yfinance does not split PSU vs private — fall back to all
        # banks. Callers that want a tighter cohort should pre-filter.
        "sectors": [
            "Financial Services",        # yfinance legacy
            "Banks",                     # NSE canonical (post-PR #196)
        ],
        "industry_like": "Banks%",
    },
    "Financial Services": {
        "sectors": ["Financial Services"],
        # Everything in Financial Services that isn't a bank.
        # Bank exclusion is applied as a separate NOT ILIKE clause
        # in sector_percentile._build_cohort_query.
        "industry_like": None,
    },
    "Pharma": {
        "sectors": [
            "Healthcare",                # yfinance legacy
            "Pharmaceuticals",           # NSE canonical (post-PR #196)
        ],
        "industry_like": None,
    },
    "FMCG": {
        "sectors": [
            "Consumer Defensive",            # yfinance legacy
            "FMCG",                          # NSE canonical (post-PR #196)
            "Fast Moving Consumer Goods",    # alt NSE variant
        ],
        "industry_like": None,
    },
    "Auto": {
        "sectors": [
            "Consumer Cyclical",                 # yfinance legacy (filtered by industry_like)
            "Automobiles",                       # NSE canonical (post-PR #196)
            "Automobile and Auto Components",    # alt NSE variant
        ],
        # Auto Manufacturers, Auto Parts, Auto & Truck Dealerships.
        "industry_like": "Auto%",
    },
    "Metals": {
        "sectors": [
            "Basic Materials",           # yfinance legacy
            "Metals & Mining",           # NSE canonical (post-PR #196)
        ],
        "industry_like": None,
    },
    "Energy": {
        # No NSE-canonical change needed — both yfinance "Energy" and
        # NSE "Energy" land on the same string. "Utilities" kept for
        # the power-gen subset (RELIANCE/POWERGRID/NTPC).
        "sectors": ["Energy", "Utilities"],
        "industry_like": None,
    },
    "Realty": {
        "sectors": [
            "Real Estate",               # yfinance legacy
            "Realty",                    # NSE canonical (post-PR #196)
        ],
        "industry_like": None,
    },
    "Media": {
        "sectors": [
            "Communication Services",                    # yfinance legacy
            "Media",                                     # NSE canonical (post-PR #196)
            "Media Entertainment & Publication",         # alt NSE variant
        ],
        "industry_like": None,
    },
    "Consumer Durables": {
        "sectors": ["Consumer Cyclical"],
        "industry_like": None,
    },
    "Infrastructure": {
        # yfinance stores L&T-style conglomerates / capital-goods names
        # under "Industrials". Post-PR #196, NSE-canonical labels
        # "Capital Goods" / "Construction" land in stocks.sector.
        "sectors": [
            "Industrials",               # yfinance legacy
            "Capital Goods",             # NSE canonical (post-PR #196)
            "Construction",              # alt NSE variant
        ],
        "industry_like": None,
    },
    "Chemicals": {
        # Specialty chemicals overlap with Basic Materials in yfinance.
        # NSE-canonical "Chemicals" lands directly in stocks.sector.
        "sectors": [
            "Basic Materials",           # yfinance legacy overlap
            "Chemicals",                 # NSE canonical (post-PR #196)
        ],
        "industry_like": None,
    },
    "Textiles": {
        # Textiles roll up under Consumer Cyclical in yfinance.
        # NSE-canonical "Textiles" lands directly in stocks.sector.
        "sectors": [
            "Consumer Cyclical",         # yfinance legacy overlap
            "Textiles",                  # NSE canonical (post-PR #196)
        ],
        "industry_like": None,
    },
}


# Industries we *exclude* from the "Financial Services" canonical
# cohort because they live in their own (Banks) bucket. Used by
# sector_percentile when SECTOR_COHORT_RULES['Financial Services']
# is selected.
FINANCIAL_SERVICES_BANK_EXCLUDE_LIKE: str = "Banks%"


def to_bare_symbol(ticker: str) -> str:
    """Strip exchange suffixes for daily_prices lookups."""
    return ticker.replace(".NS", "").replace(".BO", "").lstrip("^").upper().strip()


def resolve(sector: Optional[str]) -> str:
    """Return the benchmark ticker for the given sector string.

    - Exact match against SECTOR_BENCHMARK_MAP wins.
    - Then case-insensitive alias lookup.
    - Falls back to SECTOR_BENCHMARK_MAP['_default'].

    Never raises — an unknown sector gets the default benchmark and
    a debug log line. The retrospective service treats a missing
    benchmark price as a logged warning, not a 500.
    """
    if not sector:
        return SECTOR_BENCHMARK_MAP["_default"]

    s = str(sector).strip()
    if s in SECTOR_BENCHMARK_MAP:
        return SECTOR_BENCHMARK_MAP[s]

    canonical = SECTOR_ALIASES.get(s.lower())
    if canonical and canonical in SECTOR_BENCHMARK_MAP:
        return SECTOR_BENCHMARK_MAP[canonical]

    logger.debug("sector_benchmarks.resolve: no mapping for %r — using default", sector)
    return SECTOR_BENCHMARK_MAP["_default"]


def all_benchmark_tickers() -> list[str]:
    """All distinct benchmark tickers (incl. default) for ingest jobs."""
    seen: list[str] = []
    for v in SECTOR_BENCHMARK_MAP.values():
        if v not in seen:
            seen.append(v)
    return seen


def mapped_sectors() -> list[str]:
    """Real sectors with a dedicated benchmark (excludes _default)."""
    return [k for k in SECTOR_BENCHMARK_MAP.keys() if k != "_default"]
