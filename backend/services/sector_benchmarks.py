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
    "fmcg & consumer":                   "FMCG",
    # Auto
    "automobile":                        "Auto",
    "automobiles":                       "Auto",
    "auto & ancillaries":                "Auto",
    # Metals
    "metal":                             "Metals",
    "metals & mining":                   "Metals",
    "mining":                            "Metals",
    # Energy
    "oil & gas":                         "Energy",
    "oil and gas":                       "Energy",
    "power":                             "Energy",
    "utilities":                         "Energy",
    # Realty
    "real estate":                       "Realty",
    "realty & construction":             "Realty",
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
