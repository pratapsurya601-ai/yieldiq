"""AMFI Total Expense Ratio (TER) ingest.

Source — a single official AMFI JSON API (no per-AMC scraping):

    1. Months list (which disclosure months are published for an FY):
       GET https://www.amfiindia.com/api/populate-ter-month?year=YYYY-YYYY
         -> [{"MonthYear":"June-2026","MonthNumber":"06-2026"}, ...]
       The FY is in YYYY-YYYY form (e.g. 2026-2027 for Jun-2026). We use
       the latest MonthNumber returned.

    2. TER data for one AMC + month:
       GET https://www.amfiindia.com/api/populate-te-rdata-revised
           ?MF_ID={id}&Month={MM-YYYY}&strCat=&strType=&page=1&pageSize=5000
         -> { data:[...], meta:{page,pageSize,total,pageCount} }
       strCat / strType are ignored server-side — pass empty. Paginate
       when meta.pageCount > 1.

       Each data row carries (fields we use):
         Scheme_Name     base name, NO plan/option suffix
                         (e.g. "Parag Parikh Flexi Cap Fund")
         NSDLSchemeCode  AMFI/NSDL scheme key (e.g. "PPFA/O/E/FCF/13/04/0001")
         SchemeCat_Desc  SEBI category description
         TER_Date        ISO timestamp of the disclosure DAY
         D_TER           Direct-plan TER, string percent e.g. "1.6400"
         R_TER           Regular-plan TER, string percent e.g. "2.4400"
         MF_ID, Month    echo of the request params

    No auth, no Cloudflare — a plain requests.get with a browser
    User-Agent works (mirrors amfi_nav.fetch_navall_text). We throttle
    ~800ms between AMCs to be polite to the portal.

Granularity (IMPORTANT): the feed returns ONE ROW PER SCHEME PER
DISCLOSURE DAY — a scheme appears once for every day of the month it has
disclosed so far. We collapse to the row with the MAX TER_Date per
NSDLSchemeCode (latest_per_scheme) so each scheme contributes exactly
one current TER pair.

MF_ID discovery: MF_IDs (AMFI mutual-fund-house ids) are SPARSE — most
of 1..120 are empty. A discovery sweep records which IDs return data and
caches the live set + a MF_ID->AMC label map under
data_pipeline/data/amfi_mf_id_amc_map.json so normal runs skip the
sweep. The TER rows themselves carry NO AMC field, so the AMC used for
join-scoping comes from that committed map (curated; see its _README).

────────────────────────────────────────────────────────────────────────
UNITS DECISION (deliberate — differs from the equity convention):

  TER is stored in PERCENT (e.g. 1.6400), NOT as a decimal fraction.

  The fund detail page's CostPanel feeds metrics.ter_direct / ter_regular
  straight into fmtPct, which renders `v.toFixed(2) + "%"` with NO ×100
  (unlike schemeReturnPct, which multiplies the *return* fractions by
  100). So a stored 1.64 renders "1.64%" — correct — whereas a stored
  0.0164 would render "0.02%". fund_returns_cache.ter_direct/ter_regular
  are NUMERIC(6,4), which holds 1.6400 fine.

  This INTENTIONALLY diverges from migration 075's table-level note that
  "Decimal columns store fractions (0.12 = 12 percent) per the equity-
  side convention" — that note governs the returns/risk columns, not the
  two TER columns, which the factsheet/TER ingest owns and writes in
  percent to match the frontend formatter.
────────────────────────────────────────────────────────────────────────

Target table & run-order (CONFIRMED):

  We write ONLY fund_returns_cache.ter_direct / ter_regular (+ computed_at)
  via UPSERT. We do NOT touch the funds table.

  backend/services/funds/recompute.py's UPSERT (the daily returns/risk/
  score compute) lists every column EXCEPT ter_direct / ter_regular, so
  the two jobs never clobber each other — recompute leaves the TER
  columns untouched, this job leaves all the compute columns untouched.
  RUN-ORDER NOTE: order between the two is irrelevant for the TER columns
  precisely because of that disjoint column set; either may run first.
  (recompute reads TER as a *score input* only when it has already been
  written — until then it passes ter=None, see recompute.py pass 2.)

CLI:
    fetch_months(fy=None)              -> list[{"MonthYear","MonthNumber"}]
    fetch_ter_for_amc(mf_id, month)    -> list[dict]   (all pages, raw rows)
    latest_per_scheme(rows)            -> list[dict]   (max TER_Date / NSDL)
    normalize_base_name(name)          -> str          (shared w/ scheme_master regexes)
    match_and_upsert(conn, ter_rows, mf_id_amc, *, apply) -> ReconSummary
    main()                             -> int

    --dry-run   (default) fetch + parse + (if DATABASE_URL) match + print
                reconciliation counts, NO writes.
    --apply     commit the UPSERTs.
    --month MM-YYYY   override the disclosure month.
    --mf-id N         scope to a single AMC (proof run).

Discipline notes:
    * No CACHE_VERSION bump — TER is an ingested input, not derived data.
    * import psycopg2 locally so --help works without it installed.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import re
import sys
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Optional

# Reuse the plan/option-stripping regexes from the scheme-master parser
# rather than duplicating them. normalize_base_name() below wraps these.
from data_pipeline.sources.amfi_scheme_master import (
    _DIRECT_RE,
    _REGULAR_RE,
    _IDCW_REINVEST_RE,
    _IDCW_RE,
)

logger = logging.getLogger(__name__)

# ── Endpoints ────────────────────────────────────────────────────────

TER_MONTH_URL = "https://www.amfiindia.com/api/populate-ter-month"
TER_DATA_URL = "https://www.amfiindia.com/api/populate-te-rdata-revised"

# Browser UA — AMFI's API rejects the default python-requests UA on some
# edges. Mirror the approach amfi_nav uses for the portal.
_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)
_HEADERS = {"User-Agent": _UA, "Accept": "application/json, text/plain, */*"}

# Politeness throttle between AMC fetches (the brief specifies ~800ms).
THROTTLE_SEC = 0.8

# Range to sweep when discovering live MF_IDs. IDs are sparse; 1..120
# comfortably covers the current AMFI roster (47 live as of 2026-06).
MF_ID_SWEEP_RANGE = range(1, 121)

# Committed MF_ID -> AMC map (curated). See its _README key.
_AMC_MAP_PATH = (
    Path(__file__).resolve().parent.parent / "data" / "amfi_mf_id_amc_map.json"
)


# ── HTTP fetch ───────────────────────────────────────────────────────


def _current_fy() -> str:
    """AMFI FY string YYYY-YYYY for *today*. Indian FY starts in April."""
    today = datetime.now(timezone.utc).date()
    start_year = today.year if today.month >= 4 else today.year - 1
    return f"{start_year}-{start_year + 1}"


def fetch_months(fy: Optional[str] = None, *, timeout: int = 30) -> list[dict]:
    """Return the published disclosure months for a financial year.

    fy defaults to the current Indian FY (YYYY-YYYY). The response is
    newest-month-first; the caller typically takes [0]["MonthNumber"].
    """
    import requests

    fy = fy or _current_fy()
    r = requests.get(
        TER_MONTH_URL, params={"year": fy}, headers=_HEADERS, timeout=timeout
    )
    r.raise_for_status()
    data = r.json()
    if not isinstance(data, list):
        return []
    return data


def latest_month_number(months: list[dict]) -> Optional[str]:
    """Pick the most recent MonthNumber (MM-YYYY) from a months list.

    The API returns newest-first, but we sort defensively on (YYYY, MM)
    so a reordering upstream can't pick a stale month.
    """
    best: Optional[str] = None
    best_key: tuple[int, int] = (-1, -1)
    for m in months:
        mn = (m or {}).get("MonthNumber")
        if not mn or "-" not in mn:
            continue
        try:
            mm, yyyy = mn.split("-")
            key = (int(yyyy), int(mm))
        except ValueError:
            continue
        if key > best_key:
            best_key, best = key, mn
    return best


def resolve_latest_month(*, timeout: int = 30) -> Optional[str]:
    """Resolve the latest disclosure MonthNumber, spanning the FY rollover.

    In April the current-FY months list can be empty/short, so we also
    consult the prior FY and take the max across both.
    """
    months: list[dict] = []
    for fy in (_current_fy(), _prior_fy()):
        try:
            months.extend(fetch_months(fy, timeout=timeout))
        except Exception as exc:  # noqa: BLE001 - best-effort across FYs
            logger.warning("fetch_months(%s) failed: %s", fy, exc)
    return latest_month_number(months)


def _prior_fy() -> str:
    cur = _current_fy()
    start = int(cur.split("-")[0]) - 1
    return f"{start}-{start + 1}"


def fetch_ter_for_amc(
    mf_id: int, month: str, *, page_size: int = 5000, timeout: int = 60
) -> list[dict]:
    """Fetch ALL TER rows for one AMC (MF_ID) and disclosure month.

    Paginates when meta.pageCount > 1. Returns the raw row dicts exactly
    as the API delivers them (string TER values, ISO TER_Date). Returns
    [] for an empty/dead MF_ID.
    """
    import requests

    rows: list[dict] = []
    page = 1
    while True:
        params = {
            "MF_ID": mf_id,
            "Month": month,
            "strCat": "",
            "strType": "",
            "page": page,
            "pageSize": page_size,
        }
        r = requests.get(
            TER_DATA_URL, params=params, headers=_HEADERS, timeout=timeout
        )
        r.raise_for_status()
        try:
            payload = r.json()
        except ValueError:
            logger.warning("mf_id=%s month=%s page=%s: non-JSON body", mf_id, month, page)
            break
        batch = payload.get("data") or []
        rows.extend(batch)
        meta = payload.get("meta") or {}
        page_count = int(meta.get("pageCount") or 1)
        if page >= page_count:
            break
        page += 1
    return rows


# ── Parsing / collapse ───────────────────────────────────────────────


def _parse_pct(s) -> Optional[float]:
    """Parse a TER string percent ("1.6400" -> 1.64, "0.0000" -> 0.0).

    Stays in PERCENT (no /100) — see the module UNITS DECISION block.
    Returns None for blanks / non-numeric / negative (never legitimate).
    """
    if s is None:
        return None
    s = str(s).strip()
    if not s or s.upper() in ("N.A.", "N/A", "NA", "-", "--"):
        return None
    try:
        v = float(s)
    except ValueError:
        return None
    if v < 0:
        return None
    return v


def _parse_ter_date(s) -> Optional[datetime]:
    """Parse the ISO TER_Date ("2026-06-14T00:00:00.000Z"). None if bad."""
    if not s:
        return None
    s = str(s).strip()
    # Normalise the trailing Z (Python <3.11 fromisoformat rejects it).
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        # Fall back to a date-only prefix.
        try:
            return datetime.strptime(s[:10], "%Y-%m-%d")
        except ValueError:
            return None


def latest_per_scheme(rows: Iterable[dict]) -> list[dict]:
    """Collapse day-granular TER rows to one row (max TER_Date) per scheme.

    Keyed on NSDLSchemeCode. The feed publishes one row per scheme per
    disclosure DAY; we keep only the most recent day so each scheme
    contributes its current TER. Rows missing a usable NSDLSchemeCode or
    a parseable TER_Date are dropped (logged at debug).

    Returns the surviving raw rows (unmodified) so downstream code can
    still read Scheme_Name / D_TER / R_TER / SchemeCat_Desc etc.
    """
    best: dict[str, dict] = {}
    best_dt: dict[str, datetime] = {}
    for row in rows:
        code = (row.get("NSDLSchemeCode") or "").strip()
        if not code:
            continue
        dt = _parse_ter_date(row.get("TER_Date"))
        if dt is None:
            continue
        if code not in best_dt or dt > best_dt[code]:
            best_dt[code] = dt
            best[code] = row
    return list(best.values())


# ── Name normalisation (shared with scheme_master regexes) ───────────

# Connector words / tokens left behind after the plan/option regexes run.
_PLAN_WORD_RE = re.compile(r"\b(plan|option)\b", re.IGNORECASE)
_GROWTH_RE = re.compile(r"\bgrowth\b", re.IGNORECASE)
# Keep alphanumerics and hyphens (mid-cap); turn everything else to space.
_PUNCT_RE = re.compile(r"[^a-z0-9\- ]+")
# A SEPARATOR hyphen — one NOT sitting directly between two alphanumerics —
# is noise left behind after plan/option stripping ("Fund - - "). Collapse
# it to a space. An intra-word hyphen ("mid-cap") is flanked by word chars
# and survives.
_SEP_HYPHEN_RE = re.compile(r"(?<![a-z0-9])-+|-+(?![a-z0-9])")
_WS_RE = re.compile(r"\s+")
# Boilerplate AMC-house suffixes stripped by normalize_amc.
_AMC_SUFFIX_RE = re.compile(
    r"\b(mutual\s+fund|asset\s+management(\s+company)?|amc|"
    r"investment\s+manager(s)?|trustee|limited|ltd|pvt|private|co)\b",
    re.IGNORECASE,
)


def normalize_base_name(name: str) -> str:
    """Normalise a scheme name to a comparable BASE form.

    Strips plan (Direct/Regular) and option (Growth/IDCW/IDCW-Reinvest)
    tokens using the SAME regexes amfi_scheme_master uses to classify
    them, then canonicalises punctuation/whitespace/"&" so the TER feed's
    base Scheme_Name and a funds-table per-plan scheme_name reduce to the
    same key.

    Examples:
        "HDFC Mid-Cap Opportunities Fund - Direct Plan - Growth"
            -> "hdfc mid-cap opportunities fund"
        "Parag Parikh Flexi Cap Fund - Regular Plan (IDCW)"
            -> "parag parikh flexi cap fund"
        "ICICI Pru Bluechip Fund & Co - Direct - IDCW Reinvestment"
            -> "icici pru bluechip fund and co"
    """
    if not name:
        return ""
    s = str(name)
    # Drop plan/option tokens (reinvest before plain IDCW — IDCW is a
    # subset of the reinvest pattern, mirroring parse_plan_option order).
    for rx in (_IDCW_REINVEST_RE, _IDCW_RE, _DIRECT_RE, _REGULAR_RE):
        s = rx.sub(" ", s)
    s = s.lower()
    # "&" and "and" must compare equal (AMC names: "ICICI & Co" vs "and").
    s = s.replace("&", " and ")
    # Drop the now-orphaned "plan"/"option" connector words and the
    # standalone "growth" option token (the option regexes above only
    # cover IDCW variants; Growth is the implicit default and appears as
    # a bare word that must not survive into the base key).
    s = _PLAN_WORD_RE.sub(" ", s)
    s = _GROWTH_RE.sub(" ", s)
    # Strip bracketed leftovers like "( )" and stray separators, collapse
    # all non-alphanumeric runs (except inner hyphens in "mid-cap") to a
    # single space, then drop separator hyphens orphaned by the strips.
    s = _PUNCT_RE.sub(" ", s)
    s = _SEP_HYPHEN_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


def normalize_amc(amc: str) -> str:
    """Canonicalise an AMC name for matching (TER map value vs funds.amc).

    Lowercase, "&"->"and", collapse whitespace, and drop the boilerplate
    house suffixes ("mutual fund", "amc", "asset management (company)
    (limited)") so "Mirae Asset Mutual Fund" == "Mirae Asset Mutual Fund
    Ltd" == "mirae asset".
    """
    if not amc:
        return ""
    s = str(amc).lower().replace("&", " and ")
    s = _AMC_SUFFIX_RE.sub(" ", s)
    s = _PUNCT_RE.sub(" ", s)
    s = _WS_RE.sub(" ", s).strip()
    return s


# ── MF_ID -> AMC map (committed cache) ───────────────────────────────


def load_amc_map() -> dict[str, str]:
    """Load the committed MF_ID->AMC map. Returns {} if absent."""
    try:
        with open(_AMC_MAP_PATH, "r", encoding="utf-8") as f:
            raw = json.load(f)
    except (OSError, ValueError) as exc:
        logger.warning("amc map load failed (%s): %s", _AMC_MAP_PATH, exc)
        return {}
    # Drop the _README sentinel and any non-string ids.
    return {k: v for k, v in raw.items() if k.isdigit() and isinstance(v, str)}


def _guess_amc_from_rows(rows: list[dict]) -> Optional[str]:
    """Best-effort AMC guess from a live MF_ID's scheme names.

    Longest common leading token run, trimmed of trailing fund-type
    words. Only used for MF_IDs absent from the committed map — logged so
    the operator can curate them in. Deliberately conservative.
    """
    names = [r.get("Scheme_Name") or "" for r in rows]
    toks = [n.split() for n in names if n]
    if not toks:
        return None
    common: list[str] = []
    for i in range(min(len(t) for t in toks)):
        col = {t[i] for t in toks}
        if len(col) != 1:
            break
        common.append(toks[0][i])
    while common and common[-1].lower().strip("-(),") in _FUND_TYPE_STOPWORDS:
        common.pop()
    name = " ".join(common).strip(" -(),")
    return name or None


_FUND_TYPE_STOPWORDS = {
    "aggressive", "hybrid", "fund", "equity", "arbitrage", "active",
    "momentum", "etf", "gold", "silver", "index", "bond", "liquid", "debt",
    "overnight", "balanced", "advantage", "flexi", "flexicap", "cap",
    "large", "mid", "small", "multi", "multicap", "value", "focused",
    "dynamic", "asset", "allocation", "nifty", "sensex", "banking",
    "financial", "services", "diversified", "all", "fof", "of", "year",
    "conservative", "elss", "tax", "saver", "scheme",
}


def discover_live_mf_ids(
    month: str, *, sweep: Iterable[int] = MF_ID_SWEEP_RANGE,
    throttle: float = THROTTLE_SEC,
) -> dict[int, dict]:
    """Sweep a MF_ID range; return {mf_id: {"count","amc_guess"}} for live ones.

    "Live" = the TER endpoint returned ≥1 data row for that month. Used
    to refresh the committed map and to find MF_IDs absent from it.
    """
    found: dict[int, dict] = {}
    for mf_id in sweep:
        try:
            rows = fetch_ter_for_amc(mf_id, month)
        except Exception as exc:  # noqa: BLE001 - one dead id can't abort the sweep
            logger.debug("sweep mf_id=%s failed: %s", mf_id, exc)
            rows = []
        if rows:
            found[mf_id] = {
                "count": len(rows),
                "amc_guess": _guess_amc_from_rows(rows),
            }
        time.sleep(throttle)
    return found


# ── Match + upsert ───────────────────────────────────────────────────


_UPSERT_SQL = """
INSERT INTO fund_returns_cache (scheme_code, ter_direct, ter_regular, computed_at)
VALUES (%(scheme_code)s, %(ter_direct)s, %(ter_regular)s, now())
ON CONFLICT (scheme_code) DO UPDATE SET
    ter_direct  = EXCLUDED.ter_direct,
    ter_regular = EXCLUDED.ter_regular,
    computed_at = now()
"""

# scheme_code is a FK into funds and the PK of fund_returns_cache, so a
# row may not yet exist for a freshly-discovered fund. The UPSERT inserts
# a partial row (TER columns only; every compute column stays NULL) which
# the next recompute pass fills in — the disjoint column set means the two
# never collide. This matches the brief: write BOTH ter_direct & ter_regular
# on every matched scheme_code regardless of which plan it represents.


class ReconSummary:
    """Reconciliation counters for a match_and_upsert run."""

    def __init__(self) -> None:
        self.ter_rows_total = 0
        self.ter_rows_matched = 0
        self.ter_rows_unmatched = 0
        self.funds_rows_updated = 0
        self.unmatched_samples: list[str] = []

    def as_dict(self) -> dict:
        return {
            "ter_rows_total": self.ter_rows_total,
            "ter_rows_matched": self.ter_rows_matched,
            "ter_rows_unmatched": self.ter_rows_unmatched,
            "funds_rows_updated": self.funds_rows_updated,
            "unmatched_sample_count": len(self.unmatched_samples),
        }


def _build_funds_index(funds_rows: Iterable[dict]) -> dict[str, list[str]]:
    """Index funds rows by normalized base name -> [scheme_code].

    funds_rows are dicts with at least scheme_code, scheme_name. A single
    base name maps to MANY scheme_codes (one per plan/option), which is
    exactly the one-to-many fan-out the TER join needs.

    The key is the base name ALONE (not (base, amc)): normalize_base_name
    deliberately keeps the AMC prefix (it strips only plan/option/Growth),
    so the base name already encodes the fund house — "parag parikh flexi
    cap fund" can only be PPFAS. Keying on AMC too made the join depend on
    the MF_ID->AMC map label matching funds.amc's wording exactly, which it
    does NOT (map "Parag Parikh Mutual Fund" vs funds.amc "PPFAS") -> zero
    matches. Base-name-only is correct (AMC is in the name) AND robust to
    AMC-label drift.
    """
    idx: dict[str, list[str]] = defaultdict(list)
    for f in funds_rows:
        base = normalize_base_name(f.get("scheme_name") or "")
        if not base:
            continue
        idx[base].append(str(f.get("scheme_code")))
    return idx


def match_ter_rows(
    ter_rows: list[dict],
    funds_rows: list[dict],
    mf_id_amc: dict[str, str],
) -> tuple[list[dict], ReconSummary]:
    """Match collapsed TER rows to funds scheme_codes; return upsert params.

    For each TER row:
      1. normalize its Scheme_Name -> base.
      2. find every funds scheme_code with the same base name (the base
         already encodes the AMC house; see _build_funds_index).
      3. emit one upsert param dict per matched scheme_code, writing BOTH
         D_TER (ter_direct) and R_TER (ter_regular).

    mf_id_amc is retained for the caller's feed iteration + logging; it is
    no longer part of the join key (see _build_funds_index for why).

    Returns (upsert_params, recon_summary). Pure — no DB, no network —
    so it is unit-testable against fixture lists.
    """
    idx = _build_funds_index(funds_rows)
    recon = ReconSummary()
    params: list[dict] = []
    for row in ter_rows:
        recon.ter_rows_total += 1
        base = normalize_base_name(row.get("Scheme_Name") or "")
        codes = idx.get(base, [])
        if not codes:
            recon.ter_rows_unmatched += 1
            if len(recon.unmatched_samples) < 40:
                recon.unmatched_samples.append(
                    f"{row.get('Scheme_Name')}  [{row.get('SchemeCat_Desc')}]"
                )
            continue
        recon.ter_rows_matched += 1
        d_ter = _parse_pct(row.get("D_TER"))
        r_ter = _parse_pct(row.get("R_TER"))
        for sc in codes:
            params.append(
                {"scheme_code": sc, "ter_direct": d_ter, "ter_regular": r_ter}
            )
    recon.funds_rows_updated = len(params)
    return params, recon


def _fetch_all_active_funds(conn) -> list[dict]:
    """Load (scheme_code, scheme_name, amc) for ALL active funds.

    The TER join keys on the base scheme-name alone (which encodes the
    AMC), so we index the whole active table rather than pre-filtering by
    AMC label — the previous AMC-label filter dropped every PPFAS-style
    row whose funds.amc wording differed from the MF_ID->AMC map. ~14k
    rows, one query, indexed in memory.
    """
    out: list[dict] = []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT scheme_code, scheme_name, amc FROM funds WHERE is_active = TRUE"
        )
        for sc, name, amc in cur.fetchall():
            out.append({"scheme_code": sc, "scheme_name": name, "amc": amc})
    return out


def match_and_upsert(
    conn,
    ter_rows: list[dict],
    mf_id_amc: dict[str, str],
    *,
    apply: bool,
) -> ReconSummary:
    """Match TER rows against the funds table and (optionally) UPSERT.

    Loads all active funds, runs the pure (base-name) matcher, then
    UPSERTs the TER columns when apply=True. When apply=False it computes
    the recon counts without writing.
    """
    funds_rows = _fetch_all_active_funds(conn)
    logger.info("loaded %d active funds rows for matching", len(funds_rows))
    params, recon = match_ter_rows(ter_rows, funds_rows, mf_id_amc)

    if apply and params:
        with conn.cursor() as cur:
            cur.executemany(_UPSERT_SQL, params)
        conn.commit()
        logger.info("committed %d TER upserts", len(params))
    elif not apply:
        logger.info("dry-run: would upsert %d rows (no writes)", len(params))
    return recon


def log_reconciliation(recon: ReconSummary) -> None:
    """Emit the reconciliation summary (counts + a sample of misses)."""
    logger.info(
        "RECON ter_rows=%d matched=%d unmatched=%d funds_updated=%d",
        recon.ter_rows_total,
        recon.ter_rows_matched,
        recon.ter_rows_unmatched,
        recon.funds_rows_updated,
    )
    if recon.unmatched_samples:
        logger.info(
            "unmatched TER base-names (sample, likely ETFs/FoFs): %s",
            "; ".join(recon.unmatched_samples[:15]),
        )


# ── CLI ──────────────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    # NOTE: description is plain ASCII on purpose — the module docstring
    # has box-drawing chars that crash argparse's --help on a Windows
    # cp1252 console (UnicodeEncodeError). The docstring stays the source
    # of truth; --help just gets a short summary.
    p = argparse.ArgumentParser(
        description="AMFI TER ingest -> fund_returns_cache.ter_direct/ter_regular. "
                    "Dry-run by default; pass --apply to commit. See the module "
                    "docstring (data_pipeline/sources/amfi_ter.py) for full detail."
    )
    # --dry-run is the implicit default; --apply flips it. Not a mutually-
    # exclusive group (a default=True store_true inside one makes --apply
    # alone trip the 'not allowed with' check on some argparse versions).
    p.add_argument("--dry-run", action="store_true",
                   help="Fetch+parse+match, print recon, NO writes (default).")
    p.add_argument("--apply", action="store_true",
                   help="Commit the TER UPSERTs to fund_returns_cache.")
    p.add_argument("--month", default=None,
                   help="Disclosure month MM-YYYY (default: latest published).")
    p.add_argument("--mf-id", type=int, default=None,
                   help="Scope to a single AMC's MF_ID (proof run).")
    p.add_argument("--discover", action="store_true",
                   help="Run the MF_ID discovery sweep and print live ids + AMC guesses.")
    args = p.parse_args(argv)

    apply = bool(args.apply)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    month = args.month or resolve_latest_month()
    if not month:
        logger.error("could not resolve a disclosure month")
        return 2
    logger.info("amfi_ter: month=%s apply=%s mf_id=%s", month, apply, args.mf_id)

    amc_map = load_amc_map()

    if args.discover:
        live = discover_live_mf_ids(month)
        logger.info("discovery: %d live MF_IDs for %s", len(live), month)
        for mf_id, info in sorted(live.items()):
            curated = amc_map.get(str(mf_id))
            tag = "" if curated else "  <-- NOT in committed map; curate"
            logger.info(
                "  MF_ID=%-4d rows=%-5d curated=%r guess=%r%s",
                mf_id, info["count"], curated, info["amc_guess"], tag,
            )
        return 0

    # Determine which MF_IDs to fetch.
    if args.mf_id is not None:
        mf_ids = [args.mf_id]
        if str(args.mf_id) not in amc_map:
            logger.warning(
                "MF_ID %s not in committed AMC map — AMC-scoping will be "
                "empty for it; match-rate will be 0 until curated.",
                args.mf_id,
            )
    else:
        mf_ids = sorted(int(k) for k in amc_map)
        if not mf_ids:
            logger.error("committed AMC map empty — run --discover first")
            return 2

    # Fetch + collapse per AMC.
    all_ter: list[dict] = []
    for i, mf_id in enumerate(mf_ids):
        try:
            raw = fetch_ter_for_amc(mf_id, month)
        except Exception as exc:  # noqa: BLE001 - one AMC must not abort the run
            logger.warning("fetch MF_ID=%s failed: %s", mf_id, exc)
            raw = []
        collapsed = latest_per_scheme(raw)
        logger.info("MF_ID=%-4d raw_rows=%-5d collapsed=%-5d", mf_id, len(raw), len(collapsed))
        all_ter.extend(collapsed)
        if i < len(mf_ids) - 1:
            time.sleep(THROTTLE_SEC)

    logger.info("amfi_ter: %d collapsed TER rows across %d AMCs", len(all_ter), len(mf_ids))

    db_url = os.environ.get("DATABASE_URL")
    if not db_url:
        logger.info(
            "DATABASE_URL not set — parse-only. Parsed %d TER rows; "
            "skipping match + upsert.", len(all_ter)
        )
        return 0
    if db_url.startswith("postgres://"):
        db_url = "postgresql://" + db_url[len("postgres://"):]

    import psycopg2

    conn = psycopg2.connect(db_url)
    try:
        recon = match_and_upsert(conn, all_ter, amc_map, apply=apply)
        log_reconciliation(recon)
    finally:
        conn.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
