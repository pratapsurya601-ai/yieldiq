"""NSE sectoral-index constituents — canonical sector classification.

NSE publishes the constituent CSV for each Nifty sectoral index at:
    https://nsearchives.nseindia.com/content/indices/ind_<code>list.csv

These CSVs are open (no Akamai wall, no auth) and contain ~200-400
distinct tickers across the 12 sectoral indices. They are the
authoritative source for sector classification of NSE-listed stocks —
yfinance ``.info`` returns stale/Western-mapped values for Indian
listings and routinely mis-tags banks as "Financial Services /
Diversified Banks" (un-actionable for the YieldIQ scoring logic that
already special-cases NBFC vs. bank).

Module API:
    fetch_sectoral_constituents() -> dict[str, list[str]]
    upsert_to_neon(constituents, session) -> dict[str, int]

Usage from a backfill driver:

    from data_pipeline.sources import nse_sectoral_indices as nsi
    cons = nsi.fetch_sectoral_constituents()
    nsi.upsert_to_neon(cons, session)
"""
from __future__ import annotations

import csv
import io
import logging
import time
from typing import Iterable

logger = logging.getLogger(__name__)


# (Nifty index display name, archive code, canonical sector label).
# `canonical_sector` is the value written to ``stocks.sector`` so the
# scoring code sees a stable label across XBRL ingest cycles.
# Each tuple is (display_name, archive_csv_code, json_api_index_name, canonical_sector).
# - archive_csv_code is used at https://nsearchives.nseindia.com/content/indices/ind_<code>list.csv
# - json_api_index_name is used at /api/equity-stockIndices?index=<name>
# When the CSV slug returns 404 (Private Bank / Financial Services don't
# expose a CSV under any obvious slug as of 2026-04), we transparently
# fall through to the JSON API.
NIFTY_SECTORAL_INDICES: list[tuple[str, str, str, str]] = [
    ("Nifty IT",                 "niftyit",            "NIFTY IT",              "IT Services"),
    ("Nifty Bank",               "niftybank",          "NIFTY BANK",            "Banks"),
    ("Nifty Pharma",             "niftypharma",        "NIFTY PHARMA",          "Pharmaceuticals"),
    ("Nifty FMCG",               "niftyfmcg",          "NIFTY FMCG",            "FMCG"),
    ("Nifty Auto",               "niftyauto",          "NIFTY AUTO",            "Automobiles"),
    ("Nifty Metal",              "niftymetal",         "NIFTY METAL",           "Metals & Mining"),
    ("Nifty Energy",             "niftyenergy",        "NIFTY ENERGY",          "Energy"),
    ("Nifty Realty",             "niftyrealty",        "NIFTY REALTY",          "Realty"),
    ("Nifty Media",              "niftymedia",         "NIFTY MEDIA",           "Media"),
    ("Nifty PSU Bank",           "niftypsubank",       "NIFTY PSU BANK",        "Banks"),
    ("Nifty Private Bank",       "niftypvtbank",       "NIFTY PVT BANK",        "Banks"),
    ("Nifty Financial Services", "niftyfinservice",    "NIFTY FIN SERVICE",     "Financial Services"),
]

ARCHIVE_URL = "https://nsearchives.nseindia.com/content/indices/ind_{code}list.csv"
JSON_API_URL = "https://www.nseindia.com/api/equity-stockIndices?index={name}"


# ── HTTP session ─────────────────────────────────────────────────────

def _session():
    """curl_cffi Chrome-impersonate session (NSE archives are picky)."""
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        logger.error("curl_cffi required: pip install curl_cffi")
        raise
    s = cffi.Session(impersonate="chrome")
    try:
        s.get("https://www.nseindia.com/", timeout=15)
    except Exception:
        pass
    return s


# ── CSV parsing ──────────────────────────────────────────────────────

def _parse_csv(body: bytes) -> list[str]:
    """Return list of bare tickers from a constituents CSV.

    The CSV layout NSE publishes has columns:
        Company Name, Industry, Symbol, Series, ISIN Code

    We only need ``Symbol``. Some indices include a header line or a
    trailing blank line — both handled by csv.DictReader.
    """
    text = body.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    out: list[str] = []
    for row in reader:
        sym = (row.get("Symbol") or row.get("SYMBOL") or "").strip().upper()
        if sym:
            out.append(sym)
    return out


# ── Public API ───────────────────────────────────────────────────────

def _fetch_via_json_api(api_name: str, http) -> list[str]:
    """Fallback: ``/api/equity-stockIndices?index=<NAME>`` returns the
    constituent list as JSON. Used when the archive CSV 404s.
    """
    import json as _json
    import urllib.parse as _up
    url = JSON_API_URL.format(name=_up.quote(api_name))
    try:
        r = http.get(url, timeout=20)
    except Exception as e:
        logger.warning("nse_sectoral_indices JSON fetch failed %s: %s", api_name, e)
        return []
    if r.status_code != 200:
        logger.warning("nse_sectoral_indices JSON HTTP %s for %s", r.status_code, api_name)
        return []
    try:
        data = _json.loads(r.text)
    except Exception as e:
        logger.warning("nse_sectoral_indices JSON decode %s: %s", api_name, e)
        return []
    out: list[str] = []
    for entry in data.get("data") or []:
        sym = (entry.get("symbol") or "").strip().upper()
        # The first row is the index itself (symbol == index name).
        if sym and sym != api_name.upper().replace(" ", "") and sym != api_name.upper():
            out.append(sym)
    return out


def fetch_sectoral_constituents(
    indices: Iterable[tuple[str, str, str, str]] | None = None,
    sleep_s: float = 0.4,
) -> dict[str, list[str]]:
    """Returns ``{nifty_index_name: [ticker, …]}`` for ~12 indices.

    Network: one GET per index (CSV first, JSON-API fallback), ~200ms
    each, ~5-10s total. Polite sleep between calls so we don't trip
    NSE's archive rate limit.
    """
    sess = _session()
    indices = list(indices) if indices is not None else NIFTY_SECTORAL_INDICES
    out: dict[str, list[str]] = {}
    for entry in indices:
        # Tolerate the older 3-tuple signature for backwards-compat.
        if len(entry) == 3:
            name, code, _sector = entry
            api_name = name.upper()
        else:
            name, code, api_name, _sector = entry
        tickers: list[str] = []
        # 1. Archive CSV (cheapest, plain HTTP).
        url = ARCHIVE_URL.format(code=code)
        try:
            r = sess.get(url, timeout=20)
            if r.status_code == 200 and r.content:
                tickers = _parse_csv(r.content)
        except Exception as e:
            logger.warning("nse_sectoral_indices CSV fetch failed %s: %s", name, e)
        # 2. JSON-API fallback (Private Bank / Fin Services don't have a CSV).
        if not tickers:
            tickers = _fetch_via_json_api(api_name, sess)
        if not tickers:
            logger.warning("nse_sectoral_indices: no constituents for %s", name)
            continue
        out[name] = tickers
        logger.info("nse_sectoral_indices %s: %d constituents", name, len(tickers))
        time.sleep(sleep_s)
    return out


# ── Persistence ──────────────────────────────────────────────────────

_INDEX_TO_SECTOR = {entry[0]: entry[-1] for entry in NIFTY_SECTORAL_INDICES}


def upsert_to_neon(constituents: dict[str, list[str]], session) -> dict[str, int]:
    """UPSERT constituents into ``nse_sector_constituents``.

    Returns ``{nifty_index_name: rows_written}``.
    """
    from sqlalchemy import text

    upsert = text("""
        INSERT INTO nse_sector_constituents
            (ticker, nifty_index, canonical_sector, fetched_at)
        VALUES (:ticker, :nifty_index, :canonical_sector, now())
        ON CONFLICT (ticker, nifty_index) DO UPDATE SET
            canonical_sector = EXCLUDED.canonical_sector,
            fetched_at       = now()
    """)

    counts: dict[str, int] = {}
    for nifty_index, tickers in constituents.items():
        sector = _INDEX_TO_SECTOR.get(nifty_index)
        if not sector:
            logger.warning("upsert_to_neon: no canonical sector for %s — skipping",
                           nifty_index)
            continue
        n = 0
        for t in tickers:
            try:
                session.execute(upsert, {
                    "ticker": t,
                    "nifty_index": nifty_index,
                    "canonical_sector": sector,
                })
                n += 1
            except Exception as e:
                logger.debug("upsert fail %s/%s: %s", t, nifty_index, e)
        counts[nifty_index] = n
    try:
        session.commit()
    except Exception as e:
        logger.error("upsert_to_neon commit failed: %s", e)
        session.rollback()
        return {}
    return counts


def coverage_for_universe(tickers: Iterable[str], session) -> dict[str, int]:
    """Quick stats: how many of `tickers` are in nse_sector_constituents?

    Used by run_completeness_backfill to print a coverage summary before
    falling through to yfinance.
    """
    from sqlalchemy import text

    bare = sorted({t.upper().split(".")[0] for t in tickers})
    if not bare:
        return {"universe": 0, "covered": 0}
    row = session.execute(text("""
        SELECT COUNT(DISTINCT ticker) FROM nse_sector_constituents
         WHERE ticker = ANY(:tickers)
    """), {"tickers": bare}).scalar() or 0
    return {"universe": len(bare), "covered": int(row)}
