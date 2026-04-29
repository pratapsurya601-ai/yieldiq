"""NSE official industry classification — master CSVs + per-ticker quote API.

Two-tier source for the canonical NSE industry label of every active
NSE-listed equity:

1. **Index master CSVs** (bulk, fast). Each NSE index publishes a
   constituents CSV with an ``Industry`` column that is the SEBI-filed
   canonical industry. Together these five CSVs cover ~750 unique
   tickers across the entire market-cap spectrum:

       https://nsearchives.nseindia.com/content/indices/ind_nifty500list.csv
       https://nsearchives.nseindia.com/content/indices/ind_nifty100list.csv
       https://nsearchives.nseindia.com/content/indices/ind_niftylargemidcap250list.csv
       https://nsearchives.nseindia.com/content/indices/ind_niftysmallcap250list.csv
       https://nsearchives.nseindia.com/content/indices/ind_niftymicrocap250_list.csv
       https://nsearchives.nseindia.com/content/indices/ind_niftytotalmarket_list.csv

2. **Per-ticker quote API** (slow, per-symbol). For tickers outside
   any index — typically SME-board / very-thinly-traded micro-caps —
   NSE's ``/api/quote-equity?symbol=<TICKER>`` returns a JSON payload
   with an ``industryInfo`` block containing macro/sector/industry/
   basicIndustry, plus a ``metadata.industry`` field. We rate-limit to
   ~5 req/sec and retry transient errors.

This module is the long-tail companion to ``nse_sectoral_indices`` —
the latter classifies by Nifty *sectoral* index (~191 large/mid-cap
tickers across 12 indices), this one fills the remaining ~2,500
micro-caps using the same SEBI-canonical industry strings.

Module API:
    fetch_index_master_classifications() -> dict[ticker, dict]
    fetch_quote_api_classification(ticker) -> dict | None
    upsert_to_neon(rows, session, *, force=False) -> int
"""
from __future__ import annotations

import csv
import io
import json
import logging
import time
from typing import Iterable, Iterator

logger = logging.getLogger(__name__)

# (slug, label) — slug goes into the archive URL, label is for log lines.
INDEX_MASTERS: list[tuple[str, str]] = [
    ("ind_niftytotalmarket_list",     "Nifty Total Market"),
    ("ind_nifty500list",              "Nifty 500"),
    ("ind_nifty100list",              "Nifty 100"),
    ("ind_niftylargemidcap250list",   "Nifty LargeMidcap 250"),
    ("ind_niftysmallcap250list",      "Nifty Smallcap 250"),
    ("ind_niftymicrocap250_list",     "Nifty Microcap 250"),
]

ARCHIVE_URL = "https://nsearchives.nseindia.com/content/indices/{slug}.csv"
QUOTE_API_URL = "https://www.nseindia.com/api/quote-equity?symbol={sym}"


# ── HTTP session ─────────────────────────────────────────────────────

def _session():
    """curl_cffi Chrome-impersonate session — NSE archives reject bare
    requests/urllib UAs.
    """
    try:
        from curl_cffi import requests as cffi
    except ImportError:
        logger.error("curl_cffi required: pip install curl_cffi")
        raise
    s = cffi.Session(impersonate="chrome")
    # Warm cookies — NSE sets a session cookie on first GET /, then will
    # serve archive CSVs and the quote API for the lifetime of the cookie.
    try:
        s.get("https://www.nseindia.com/", timeout=15)
        s.get("https://www.nseindia.com/get-quotes/equity?symbol=INFY", timeout=15)
    except Exception:
        pass
    return s


# ── CSV index masters ────────────────────────────────────────────────

def _parse_master_csv(body: bytes) -> Iterator[dict[str, str]]:
    """Yield ``{ticker, industry, company_name}`` per row. Industry is the
    canonical NSE label (e.g. "Pharmaceuticals", "IT - Software").
    """
    text = body.decode("utf-8-sig", errors="replace")
    reader = csv.DictReader(io.StringIO(text))
    for row in reader:
        sym = (row.get("Symbol") or row.get("SYMBOL") or "").strip().upper()
        ind = (row.get("Industry") or row.get("INDUSTRY") or "").strip()
        name = (row.get("Company Name") or row.get("COMPANY NAME") or "").strip()
        if sym and ind:
            yield {"ticker": sym, "industry": ind, "company_name": name}


def fetch_index_master_classifications(
    indices: Iterable[tuple[str, str]] | None = None,
    sleep_s: float = 0.4,
) -> dict[str, dict]:
    """Fetch every NSE index master CSV, dedup by ticker.

    First-seen wins (Total Market is fetched first → most-canonical).
    Returns ``{TICKER: {"industry": str, "company_name": str, "source": str}}``.
    """
    sess = _session()
    indices = list(indices) if indices is not None else INDEX_MASTERS
    out: dict[str, dict] = {}
    for slug, label in indices:
        url = ARCHIVE_URL.format(slug=slug)
        try:
            r = sess.get(url, timeout=20)
        except Exception as e:
            logger.warning("nse_industry_master CSV %s failed: %s", label, e)
            continue
        if r.status_code != 200 or not r.content:
            logger.warning("nse_industry_master CSV %s HTTP %s", label, r.status_code)
            continue
        n_new = 0
        for row in _parse_master_csv(r.content):
            if row["ticker"] in out:
                continue
            out[row["ticker"]] = {
                "industry": row["industry"],
                "company_name": row["company_name"],
                "source": label,
            }
            n_new += 1
        logger.info("nse_industry_master %s: +%d new (cum %d)", label, n_new, len(out))
        time.sleep(sleep_s)
    return out


# ── Per-ticker quote API ─────────────────────────────────────────────

def fetch_quote_api_classification(ticker: str, http=None) -> dict | None:
    """Single ``/api/quote-equity`` call. Returns
    ``{"industry","sector","macro","basic_industry"}`` or None.
    Caller is responsible for rate-limiting and shared session reuse.
    """
    sess = http or _session()
    sym = ticker.upper().split(".")[0]
    url = QUOTE_API_URL.format(sym=sym)
    try:
        r = sess.get(url, timeout=30)
    except Exception as e:
        logger.debug("quote-api %s network: %s", sym, e)
        return None
    if r.status_code == 429:
        # Bubble up so caller can back off.
        raise RuntimeError("429 from NSE quote-api")
    if r.status_code != 200:
        logger.debug("quote-api %s HTTP %s", sym, r.status_code)
        return None
    try:
        data = json.loads(r.text)
    except Exception as e:
        logger.debug("quote-api %s decode: %s", sym, e)
        return None
    info = data.get("industryInfo") or {}
    md = data.get("metadata") or {}
    industry = (info.get("industry") or "").strip()
    sector = (info.get("sector") or "").strip()
    macro = (info.get("macro") or "").strip()
    basic = (info.get("basicIndustry") or md.get("industry") or "").strip()
    if not (industry or basic):
        return None
    return {
        "industry": industry or basic,
        "sector": sector or macro or None,
        "macro": macro or None,
        "basic_industry": basic or None,
    }


def fetch_quote_api_bulk(
    tickers: Iterable[str],
    *,
    rate_per_sec: float = 5.0,
    progress_every: int = 50,
    on_progress=None,
) -> dict[str, dict]:
    """Loop ``fetch_quote_api_classification`` with throttle + 429 backoff.

    Returns ``{TICKER: {industry, sector, macro, basic_industry}}`` for
    every ticker that returned a usable industryInfo. Tickers without
    a classification are silently skipped — caller can diff input vs
    keys to find the still-missing.
    """
    sess = _session()
    out: dict[str, dict] = {}
    delay = 1.0 / max(0.5, rate_per_sec)
    backoff = 0.0
    seen = 0
    for t in tickers:
        seen += 1
        if backoff:
            time.sleep(backoff)
            backoff = 0.0
        time.sleep(delay)
        for attempt in range(3):
            try:
                res = fetch_quote_api_classification(t, http=sess)
                break
            except RuntimeError as e:
                logger.warning("quote-api 429 on %s, backoff %ds (attempt %d)",
                               t, 5 * (attempt + 1), attempt + 1)
                time.sleep(5 * (attempt + 1))
                res = None
            except Exception as e:
                logger.debug("quote-api unexpected on %s: %s", t, e)
                res = None
                break
        else:
            res = None
        if res:
            out[t.upper().split(".")[0]] = res
        if on_progress and seen % progress_every == 0:
            on_progress(seen, len(out))
    return out


# ── Persistence ──────────────────────────────────────────────────────

# When the quote-API "sector" comes back empty (older listings), we
# fall back to mapping the canonical industry string to the YieldIQ
# sector buckets used elsewhere in scoring code. Keep this short — it's
# a safety net, not a classification system.
_INDUSTRY_TO_SECTOR_FALLBACK = {
    "Banks": "Banks",
    "Financial Services": "Financial Services",
    "Insurance": "Financial Services",
    "Pharmaceuticals": "Pharmaceuticals",
    "Healthcare": "Pharmaceuticals",
    "IT - Software": "IT Services",
    "IT - Services": "IT Services",
    "FMCG": "FMCG",
    "Automobile and Auto Components": "Automobiles",
    "Metals & Mining": "Metals & Mining",
    "Power": "Energy",
    "Oil Gas & Consumable Fuels": "Energy",
    "Realty": "Realty",
    "Media": "Media",
    "Telecom": "Telecom",
    "Chemicals": "Chemicals",
    "Capital Goods": "Capital Goods",
    "Construction Materials": "Construction Materials",
    "Construction": "Construction",
    "Consumer Durables": "Consumer Durables",
    "Consumer Services": "Consumer Services",
    "Textiles": "Textiles",
    "Diversified": "Diversified",
}


def upsert_to_neon(
    rows: dict[str, dict],
    session,
    *,
    force: bool = False,
) -> dict[str, int]:
    """UPSERT industry/sector into ``stocks``.

    ``rows`` is ``{TICKER: {industry, sector?, source}}``.
    Without ``force``, only fills tickers where industry is currently
    NULL or empty string. Returns ``{"updated": n, "skipped": n}``.
    """
    from sqlalchemy import text

    if force:
        stmt = text("""
            UPDATE stocks
               SET industry   = :industry,
                   sector     = COALESCE(:sector, sector),
                   updated_at = now()
             WHERE ticker = :ticker
        """)
    else:
        stmt = text("""
            UPDATE stocks
               SET industry   = :industry,
                   sector     = COALESCE(sector, :sector),
                   updated_at = now()
             WHERE ticker = :ticker
               AND (industry IS NULL OR industry = '')
        """)

    updated = 0
    skipped = 0
    for ticker, payload in rows.items():
        industry = payload.get("industry") or ""
        if not industry:
            skipped += 1
            continue
        sector = payload.get("sector") or _INDUSTRY_TO_SECTOR_FALLBACK.get(industry)
        try:
            res = session.execute(stmt, {
                "ticker":   ticker,
                "industry": industry,
                "sector":   sector,
            })
            if (res.rowcount or 0) > 0:
                updated += 1
            else:
                skipped += 1
        except Exception as e:
            logger.debug("upsert fail %s: %s", ticker, e)
            skipped += 1
    try:
        session.commit()
    except Exception as e:
        logger.error("upsert_to_neon commit failed: %s", e)
        session.rollback()
        return {"updated": 0, "skipped": len(rows)}
    return {"updated": updated, "skipped": skipped}


def coverage_breakdown(session) -> dict[str, int]:
    """Return ``{total, with_industry, missing_industry}``."""
    from sqlalchemy import text

    row = session.execute(text("""
        SELECT
            COUNT(*) AS total,
            COUNT(*) FILTER (WHERE industry IS NOT NULL AND industry <> '') AS filled,
            COUNT(*) FILTER (WHERE industry IS NULL OR industry = '')       AS missing
          FROM stocks
    """)).one()
    return {"total": int(row[0]), "with_industry": int(row[1]),
            "missing_industry": int(row[2])}
