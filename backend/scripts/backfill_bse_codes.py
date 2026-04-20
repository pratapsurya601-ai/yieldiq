"""
backfill_bse_codes.py — populate stocks.bse_code for every NSE ticker.

Fetches the BSE equity master (preferred: JSON API; fallback: CSV scrip
list) and UPSERTs the `bse_code` column in the `stocks` table. Joins
on ISIN first (most reliable), then falls back to normalised company
name matching with a small Levenshtein tolerance.

Runs once from GitHub Actions (.github/workflows/bse_backfill.yml) and
on a monthly cron thereafter to pick up new listings.

Idempotent — safe to re-run. Applies the
`ALTER TABLE stocks ADD COLUMN IF NOT EXISTS bse_code TEXT` migration
itself on startup so production always has the column even if nobody
ran the raw SQL.

No investment advice. Pure reference-data plumbing.
"""

from __future__ import annotations

import logging
import os
import re
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

import requests


logger = logging.getLogger("yieldiq.bse_backfill")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


# ---------------------------------------------------------------------------
# Path bootstrap so `data_pipeline.db` imports regardless of cwd.
# ---------------------------------------------------------------------------

def _bootstrap_paths() -> None:
    here = Path(__file__).resolve()
    repo_root = here.parent.parent.parent  # backend/scripts/ -> backend -> repo
    for p in (repo_root, repo_root / "backend"):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------

_UA = "Mozilla/5.0 (compatible; YieldIQ/1.0)"
_BSE_JSON_URL = "https://api.bseindia.com/BseIndiaAPI/api/ListOfScripCode/w"
_BSE_CSV_URL = "https://www.bseindia.com/corporates/List_Scrips.aspx"
# Per-ticker fallback — BSE bulk master started 301'ing to error_Bse.html
# in April 2026. PeerSmartSearch accepts an ISIN (exact hit) or ticker
# (fuzzy) and returns an HTML snippet containing the scrip code.
_BSE_SMART_SEARCH_URL = (
    "https://api.bseindia.com/BseIndiaAPI/api/PeerSmartSearch/w"
    "?Type=SS&text={query}"
)


def _session() -> requests.Session:
    s = requests.Session()
    s.headers.update({
        "User-Agent": _UA,
        "Accept": "application/json, text/plain, */*",
        "Accept-Language": "en-US,en;q=0.9",
        "Referer": "https://www.bseindia.com/",
        "Origin": "https://www.bseindia.com",
    })
    return s


def _fetch_bse_master_json(sess: requests.Session) -> List[Dict[str, Any]]:
    """Try the JSON endpoint. Returns [] on failure."""
    for attempt in range(2):
        try:
            resp = sess.get(_BSE_JSON_URL, timeout=60)
            if resp.status_code == 200:
                try:
                    data = resp.json()
                except ValueError:
                    logger.warning("BSE JSON: non-JSON body, len=%d", len(resp.content or b""))
                    return []
                # BSE wraps payloads in either a top-level list or {"Table": [...]}.
                if isinstance(data, list):
                    return data
                if isinstance(data, dict):
                    for key in ("Table", "data", "result"):
                        if key in data and isinstance(data[key], list):
                            return data[key]
                logger.warning("BSE JSON: unexpected shape (%s)", type(data).__name__)
                return []
            if resp.status_code in (403, 429, 503) or 500 <= resp.status_code < 600:
                logger.info("BSE JSON HTTP %s — retrying", resp.status_code)
                time.sleep(2.0 * (attempt + 1))
                continue
            logger.warning("BSE JSON HTTP %s — giving up", resp.status_code)
            return []
        except Exception as exc:
            logger.info("BSE JSON attempt %d failed: %s", attempt + 1, exc)
            time.sleep(2.0 * (attempt + 1))
    return []


# Pattern: ng-click="liclick('500325','RELIANCE INDUSTRIES LTD')"
# Second best match in the response string carries the ticker/ISIN.
_SMART_RE = re.compile(r"liclick\('(\d+)',")


def _lookup_bse_code_by_query(sess: requests.Session, query: str) -> Optional[str]:
    """Use PeerSmartSearch to resolve an ISIN or ticker to a BSE scrip code.

    Returns the first scrip code in the result list, or None if no match.
    The endpoint returns a JSON-string wrapping HTML `<li>` snippets.
    """
    if not query:
        return None
    url = _BSE_SMART_SEARCH_URL.format(query=query.strip())
    try:
        resp = sess.get(url, timeout=15)
        if resp.status_code != 200:
            return None
        body = resp.text or ""
        m = _SMART_RE.search(body)
        if not m:
            return None
        return m.group(1)
    except Exception:
        return None


def backfill_per_ticker(
    sess: requests.Session,
    stocks: List[Dict[str, Any]],
    sleep: float = 0.3,
    progress_every: int = 100,
) -> Dict[str, str]:
    """Fallback path for when BSE bulk master is unavailable.

    For each stock with no bse_code, look up by ISIN first (deterministic),
    then by ticker symbol as secondary. Returns mapping ticker -> bse_code.
    """
    mapping: Dict[str, str] = {}
    need = [s for s in stocks if not s.get("bse_code")]
    logger.info("per-ticker lookup: %d stocks need a bse_code", len(need))

    for i, s in enumerate(need, 1):
        code: Optional[str] = None
        if s.get("isin"):
            code = _lookup_bse_code_by_query(sess, s["isin"])
        if not code and s.get("ticker"):
            # Fallback: search by ticker symbol (NSE symbol — usually matches BSE)
            code = _lookup_bse_code_by_query(sess, s["ticker"])
        if code:
            mapping[s["ticker"]] = code

        if i % progress_every == 0:
            logger.info(
                "  per-ticker progress: %d/%d  matched=%d",
                i, len(need), len(mapping),
            )
        time.sleep(sleep)

    logger.info("per-ticker lookup done: matched %d / %d", len(mapping), len(need))
    return mapping


# ---------------------------------------------------------------------------
# Name normalisation + fuzzy match
# ---------------------------------------------------------------------------

_SUFFIXES = (
    " limited", " ltd.", " ltd", " pvt ltd", " private limited",
    " corporation", " corp.", " corp",
    " company", " co.", " co",
    " india", " (india)",
)


def _norm_name(raw: Optional[str]) -> str:
    if not raw:
        return ""
    s = raw.strip().lower()
    # Strip common legal suffixes (longest first so " limited" wins over " ltd")
    for suf in sorted(_SUFFIXES, key=len, reverse=True):
        if s.endswith(suf):
            s = s[: -len(suf)]
            s = s.strip(" ,.-")
    # Remove all non-alphanumeric
    s = re.sub(r"[^a-z0-9]+", "", s)
    return s


def _levenshtein(a: str, b: str, max_dist: int = 2) -> int:
    """Small bounded Levenshtein. Returns max_dist+1 if exceeded.

    Uses rapidfuzz if available (faster), else a pure-python fallback."""
    if a == b:
        return 0
    if abs(len(a) - len(b)) > max_dist:
        return max_dist + 1
    try:
        from rapidfuzz.distance import Levenshtein  # type: ignore
        d = Levenshtein.distance(a, b, score_cutoff=max_dist)
        # rapidfuzz returns max_dist+1 for cutoff exceeded already
        return d
    except Exception:
        pass
    # Pure-python Wagner-Fischer — small strings so cheap.
    la, lb = len(a), len(b)
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i, ca in enumerate(a, 1):
        curr = [i] + [0] * lb
        row_min = curr[0]
        for j, cb in enumerate(b, 1):
            cost = 0 if ca == cb else 1
            curr[j] = min(
                curr[j - 1] + 1,
                prev[j] + 1,
                prev[j - 1] + cost,
            )
            if curr[j] < row_min:
                row_min = curr[j]
        if row_min > max_dist:
            return max_dist + 1
        prev = curr
    return prev[lb]


# ---------------------------------------------------------------------------
# DB helpers
# ---------------------------------------------------------------------------

_MIGRATION_SQL = (
    "ALTER TABLE stocks ADD COLUMN IF NOT EXISTS bse_code TEXT",
    "CREATE INDEX IF NOT EXISTS idx_stocks_bse_code "
    "ON stocks (bse_code) WHERE bse_code IS NOT NULL",
)


def _ensure_column(Session) -> None:
    from sqlalchemy import text as _t
    sess = Session()
    try:
        for stmt in _MIGRATION_SQL:
            sess.execute(_t(stmt))
        sess.commit()
        logger.info("bse_code column ensured on stocks table")
    except Exception as exc:
        logger.warning("ensure bse_code column failed: %s", exc)
        sess.rollback()
    finally:
        sess.close()


def _load_stocks(Session) -> List[Dict[str, Any]]:
    from sqlalchemy import text as _t
    sess = Session()
    try:
        rows = sess.execute(_t(
            "SELECT ticker, company_name, isin, bse_code FROM stocks "
            "WHERE is_active = TRUE"
        )).fetchall()
        return [
            {
                "ticker": r[0],
                "company_name": r[1],
                "isin": (r[2] or "").strip().upper() or None,
                "bse_code": (r[3] or "").strip() or None,
            }
            for r in rows
        ]
    finally:
        sess.close()


def _upsert_bse_codes(Session, mapping: Dict[str, str]) -> int:
    """mapping: ticker -> bse_code. Returns rows updated."""
    if not mapping:
        return 0
    from sqlalchemy import text as _t
    sess = Session()
    n = 0
    try:
        for ticker, code in mapping.items():
            try:
                sess.execute(
                    _t("UPDATE stocks SET bse_code = :c WHERE ticker = :t"),
                    {"c": code, "t": ticker},
                )
                n += 1
            except Exception as exc:
                logger.warning("update failed for %s: %s", ticker, exc)
                sess.rollback()
        sess.commit()
    finally:
        sess.close()
    return n


# ---------------------------------------------------------------------------
# Core matching
# ---------------------------------------------------------------------------

def _extract_bse_row(row: Dict[str, Any]) -> Optional[Tuple[str, str, str]]:
    """Pull (scrip_code, isin, issuer_name) from one BSE master row.
    Handles the various column-name variants BSE uses in the JSON feed."""
    code = None
    for k in ("SCRIP_CD", "Scrip_Cd", "scrip_cd", "SCRIP_CODE", "scrip_code"):
        if row.get(k) not in (None, ""):
            code = str(row[k]).strip()
            break
    if not code:
        return None

    isin = None
    for k in ("ISIN_NUMBER", "ISIN", "isin", "ISIN_Number"):
        if row.get(k) not in (None, ""):
            isin = str(row[k]).strip().upper()
            break

    name = None
    for k in ("ISSUER_NAME", "Issuer_Name", "SCRIP_NAME", "Scrip_Name", "scrip_name", "CompName"):
        if row.get(k) not in (None, ""):
            name = str(row[k]).strip()
            break

    return code, (isin or ""), (name or "")


def match_bse_codes(
    bse_rows: Iterable[Dict[str, Any]],
    stocks: List[Dict[str, Any]],
) -> Tuple[Dict[str, str], Dict[str, str], List[str]]:
    """Returns (ticker_to_code, diagnostics_counts, ambiguous_tickers).

    diagnostics is a dict of reason -> ticker label for logging."""
    # Build BSE indices
    by_isin: Dict[str, str] = {}
    by_norm_name: Dict[str, List[str]] = {}
    all_norm_names: List[Tuple[str, str]] = []  # (norm_name, code)

    for row in bse_rows:
        parsed = _extract_bse_row(row)
        if not parsed:
            continue
        code, isin, name = parsed
        if isin and isin not in by_isin:
            by_isin[isin] = code
        nn = _norm_name(name)
        if nn:
            by_norm_name.setdefault(nn, []).append(code)
            all_norm_names.append((nn, code))

    matched: Dict[str, str] = {}
    ambiguous: List[str] = []
    counts = {"isin": 0, "name_exact": 0, "name_fuzzy": 0,
              "unmatched": 0, "ambiguous": 0, "already": 0}

    for s in stocks:
        ticker = s["ticker"]
        if s.get("bse_code"):
            # Re-confirm existing codes — don't overwrite.
            counts["already"] += 1
            continue

        # 1. ISIN exact
        if s.get("isin") and s["isin"] in by_isin:
            matched[ticker] = by_isin[s["isin"]]
            counts["isin"] += 1
            continue

        # 2. Name exact
        nn = _norm_name(s.get("company_name"))
        if not nn:
            counts["unmatched"] += 1
            continue
        exact = by_norm_name.get(nn)
        if exact:
            if len(set(exact)) == 1:
                matched[ticker] = exact[0]
                counts["name_exact"] += 1
                continue
            ambiguous.append(ticker)
            counts["ambiguous"] += 1
            continue

        # 3. Fuzzy (Levenshtein ≤ 2 on normalised names)
        hits: List[str] = []
        for bname, code in all_norm_names:
            if abs(len(bname) - len(nn)) > 2:
                continue
            if _levenshtein(nn, bname, max_dist=2) <= 2:
                hits.append(code)
                if len(set(hits)) > 1:
                    break
        unique = list(set(hits))
        if len(unique) == 1:
            matched[ticker] = unique[0]
            counts["name_fuzzy"] += 1
        elif len(unique) > 1:
            ambiguous.append(ticker)
            counts["ambiguous"] += 1
        else:
            counts["unmatched"] += 1

    return matched, counts, ambiguous


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    _bootstrap_paths()

    if not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL not set — aborting.")
        return 2

    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:
        logger.error("could not import data_pipeline.db.Session: %s", exc)
        return 2
    if Session is None:
        logger.error("Session is None (no DATABASE_URL?)")
        return 2

    _ensure_column(Session)

    stocks = _load_stocks(Session)
    logger.info("loaded %d active stocks from DB", len(stocks))
    if not stocks:
        logger.warning("no active stocks found; nothing to do")
        return 0

    sess = _session()
    bse_rows = _fetch_bse_master_json(sess)
    logger.info("fetched %d rows from BSE equity master", len(bse_rows))

    if bse_rows:
        # Happy path — bulk master worked.
        mapping, counts, ambiguous = match_bse_codes(bse_rows, stocks)
        logger.info(
            "match results: isin=%d name_exact=%d name_fuzzy=%d "
            "ambiguous=%d unmatched=%d already=%d",
            counts["isin"], counts["name_exact"], counts["name_fuzzy"],
            counts["ambiguous"], counts["unmatched"], counts["already"],
        )
        if ambiguous:
            logger.info("ambiguous tickers (first 20): %s", ambiguous[:20])
    else:
        # Fallback path — BSE bulk master returns a 301 to error_Bse.html
        # as of April 2026. Switch to per-ticker PeerSmartSearch lookup.
        logger.warning(
            "BSE bulk master unavailable — falling back to per-ticker lookup "
            "(~10 min for 3,000 stocks at 0.15s sleep)"
        )
        # BSE PeerSmartSearch tolerates ~5 req/s per recon; 0.15s sleep is
        # well within budget and halves the wall-clock vs the 0.3s default.
        mapping = backfill_per_ticker(sess, stocks, sleep=0.15)

    updated = _upsert_bse_codes(Session, mapping)
    logger.info("UPDATE complete — %d rows written", updated)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
