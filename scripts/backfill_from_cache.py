"""Backfill the `financials` table from the local XBRL cache.

Parses every gzipped XBRL file in ``data_pipeline/xbrl/raw_cache/``,
writes structured rows to Neon. No network calls. Re-runs in minutes.

Why this script exists
----------------------
The NSE XBRL-download pipeline (see ``scripts/download_xbrl_cache.py``)
is slow because it's network-bound. Every parser tweak previously
required re-hitting NSE for 3000 tickers = 6+ hours. This script
decouples parse from download: once the cache has the XBRL files,
every tag-map change re-runs in ~10 minutes.

Synthesize-annuals
------------------
Findings (2026-04-24, refined):

1. NSE's "Annual" endpoint returns what's labeled annual but is
   actually just the Q4 filing reprinted.

2. Inside every quarterly filing, Ind-AS filers write YTD-cumulative
   values under the "FourD" context (and standalone-quarter values
   under "OneD"). `_pick_value` picks max-magnitude, so we get:
     Q1 row → Q1 standalone (= Q1 YTD since 1 quarter)
     Q2 row → Q1+Q2 YTD
     Q3 row → Q1+Q2+Q3 YTD
     Q4 row → FULL FY YTD  ← this row IS the annual total

3. Therefore, for flow items, the annual is NOT sum of 4 quarters
   (which would double-count YTD values and land at ~2.37× reality —
   observed on BPCL FY22: synth 1,023k Cr vs real 432k Cr).
   The annual = Q4's already-cumulative value.

Synthesis rule:
  - Take Q4 row (period_end = 31-Mar-YYYY) as-is.
  - Rename period_type to 'annual'.
  - Mark data_source = 'NSE_XBRL_SYNTH'.
  - Re-derive free_cash_flow from Q4's cfo − |capex|.
  - No summing. No dependency on Q1-Q3 filings being present.

Quarterly rows are still written unconditionally, tagged
`period_type='quarterly'` and preserved in their YTD form. Downstream
consumers that want "standalone quarter" values can subtract
prior-quarter YTD (future work — not needed for DCF/ratios today).

Indian fiscal year mapping
--------------------------
FY = period_end.year + 1 if month >= 4 else period_end.year
- 30-Jun-2023 -> FY2024 Q1
- 30-Sep-2023 -> FY2024 Q2
- 31-Dec-2023 -> FY2024 Q3
- 31-Mar-2024 -> FY2024 Q4

Usage
-----
    DATABASE_URL=... python scripts/backfill_from_cache.py

    # Subset
    python scripts/backfill_from_cache.py --tickers BPCL,TCS,RELIANCE

    # Quarterly-only (skip synthesize-annual)
    python scripts/backfill_from_cache.py --no-synthesize
"""
from __future__ import annotations

import argparse
import gzip
import logging
import os
import re
import sys
import time
from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from sqlalchemy import create_engine, text as sa_text
from sqlalchemy.orm import sessionmaker

from data_pipeline.sources.nse_xbrl_fundamentals import parse_nse_xbrl
from data_pipeline.sources.bse_xbrl import store_financials

logging.basicConfig(
    level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("backfill_cache")

CACHE_ROOT = _REPO / "data_pipeline" / "xbrl" / "raw_cache"

# The filename format from download_xbrl_cache.py:
#   <period_end>_<period>[_<consolidation>].xml.gz
# Example: "31-Mar-2024_annual_cons.xml.gz"
FNAME_RE = re.compile(
    r"^(\d{1,2}-[A-Za-z]{3}-\d{4})_(annual|quarterly)(_cons|_std)?\.xml\.gz$",
    re.IGNORECASE,
)


def _engine():
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url, pool_recycle=300, pool_pre_ping=True)


def _parse_filename_date(fname: str) -> date | None:
    """Parse '31-Mar-2024_annual_cons.xml.gz' -> date(2024,3,31)."""
    m = FNAME_RE.match(fname)
    if not m:
        return None
    try:
        from datetime import datetime
        return datetime.strptime(m.group(1), "%d-%b-%Y").date()
    except Exception:
        return None


def _fy_for(period_end: date) -> int:
    """Indian fiscal year: Apr-Mar convention."""
    return period_end.year + 1 if period_end.month >= 4 else period_end.year


def _load_and_parse(fpath: Path, ticker: str) -> dict[str, Any] | None:
    """Ungzip + parse one XBRL cache file. Returns row dict or None."""
    # Skip tiny corrupt files
    try:
        size = fpath.stat().st_size
        if size < 500:
            return None
    except Exception:
        return None
    period_end = _parse_filename_date(fpath.name)
    if period_end is None:
        return None

    # The cache filename encodes the NSE-endpoint period_type hint,
    # but as we established, NSE's "annual" files are actually Q4.
    # Always pass "quarterly" — the parser's context-duration check
    # will promote to annual if a true 365d context is present.
    m = FNAME_RE.match(fpath.name)
    nse_period = (m.group(2) if m else "quarterly").lower()

    try:
        with gzip.open(fpath, "rb") as f:
            xml_bytes = f.read()
    except Exception as exc:
        logger.debug("gunzip failed %s: %s", fpath.name, exc)
        return None

    try:
        row = parse_nse_xbrl(xml_bytes, ticker, period_end, period_type=nse_period)
    except Exception as exc:
        logger.debug("parse failed %s: %s", fpath.name, exc)
        return None
    return row


def _load_and_parse_annual(fpath: Path, ticker: str) -> dict[str, Any] | None:
    """Like _load_and_parse but forces period_type='annual' so the parser
    uses the YTD context picker (_pick_value_ytd) for flow items.

    Only meaningful for Q4 files (period_end = March). The YTD picker
    prefers context IDs starting with 'Four' → year-to-date full-FY
    values. For Q1-Q3 files this still works but returns YTD-through-
    that-quarter (useful for TTM if we ever wire it up).
    """
    try:
        size = fpath.stat().st_size
        if size < 500:
            return None
    except Exception:
        return None
    period_end = _parse_filename_date(fpath.name)
    if period_end is None:
        return None
    try:
        with gzip.open(fpath, "rb") as f:
            xml_bytes = f.read()
    except Exception:
        return None
    try:
        return parse_nse_xbrl(xml_bytes, ticker, period_end, period_type="annual")
    except Exception:
        return None


# ── Sum-across-quarters synthesis ─────────────────────────────────

# Flow items (P&L, cash-flow) — add across quarters for full-year.
_FLOW_FIELDS = [
    "revenue", "revenue_from_ops", "ebitda", "ebit", "pbt", "pat",
    "cfo", "capex", "depreciation", "finance_cost",
    "total_income", "total_expenses",
]
# Balance-sheet items — take Q4's value (point-in-time).
_SNAPSHOT_FIELDS = [
    "total_assets", "total_equity", "total_debt",
    "cash", "cash_and_equivalents",
    "current_liabilities", "shares_outstanding",
]
# Per-share items — sum of quarterly EPS ≈ annual EPS (acceptable
# approximation given share counts rarely change intra-year).
_PER_SHARE_FIELDS = ["eps_basic", "eps_diluted"]


def _synthesize_annual(q4_row: dict) -> dict:
    """Promote Q4 YTD-cumulative values to an annual row.

    Key insight (2026-04-24 diagnostic): Ind-AS quarterly XBRL filings
    write year-to-date cumulative values under the dominant context
    (FourD) that `_pick_value` prefers by magnitude. For Q4 filings,
    this YTD value IS the full FY total — no summing needed, and
    summing all 4 quarters would massively double-count.

    Mutates nothing. Returns a new dict safe to pass to store_financials.
    """
    out = dict(q4_row)
    out["period_type"] = "annual"
    # Re-derive FCF defensively — store_financials also does this but
    # surfacing it here keeps the row self-consistent for any caller
    # that reads free_cash_flow directly.
    cfo = out.get("cfo")
    capex = out.get("capex")
    if cfo is not None and capex is not None:
        out["free_cash_flow"] = cfo - abs(capex)
    # Mark as synthesized so we can diagnose later — store_financials
    # preserves the `source` field as `data_source` in DB.
    out["source"] = "NSE_XBRL_SYNTH"
    return out


def _process_ticker(
    ticker: str,
    ticker_dir: Path,
    db_session,
    synthesize: bool,
) -> dict[str, int]:
    """Parse every cached XBRL for a ticker, write rows, synthesize annuals."""
    stats = {
        "parsed_ok": 0, "parse_empty": 0, "parse_err": 0,
        "stored_quarterly": 0, "stored_annual_synth": 0,
        "skipped_fy_incomplete": 0, "store_err": 0,
    }
    # Collect quarterly rows by FY for synthesis later.
    by_fy: dict[int, list[dict]] = defaultdict(list)
    q4_by_fy: dict[int, dict] = {}

    # Track which files are Q4 candidates (period_end = March) so we
    # can re-parse them in "annual" mode (YTD context picker).
    q4_files: dict[int, Path] = {}

    for fpath in sorted(ticker_dir.glob("*.xml.gz")):
        # First pass: parse as quarterly (standalone-quarter picker).
        # Ind-AS filings expose both OneD (Q4 standalone) and FourD (YTD)
        # contexts; for quarterly rows we want the standalone value, so
        # the default _pick_value's exact-end-date-match behaviour is fine.
        row = _load_and_parse(fpath, ticker)
        if row is None:
            stats["parse_empty"] += 1
            continue
        stats["parsed_ok"] += 1

        pe = row.get("period_end")
        if pe is None:
            continue
        # Store as quarterly regardless — NSE's "annual" endpoint serves
        # what is really a Q4 filing. True annuals come from the FourD
        # (YTD) context re-parse below.
        row["period_type"] = "quarterly"
        try:
            if store_financials(row, db_session, pe, "quarterly"):
                stats["stored_quarterly"] += 1
        except Exception as exc:
            logger.debug("store quarterly %s %s: %s", ticker, pe, exc)
            stats["store_err"] += 1

        # Remember Q4 filings for the annual re-parse
        if synthesize:
            fy = _fy_for(pe)
            by_fy[fy].append(row)
            if pe.month == 3 and pe.year == fy:
                q4_files[fy] = fpath

    # Second pass: re-parse each Q4 file with period_type="annual" so
    # the YTD context picker (_pick_value_ytd) extracts the FourD
    # (full-fiscal-year cumulative) values for revenue / CFO / capex /
    # etc. — matching reality within 2-5% on every ticker we verified.
    if synthesize:
        for fy, q4_fpath in sorted(q4_files.items()):
            q4_annual = _load_and_parse_annual(q4_fpath, ticker)
            if q4_annual is None:
                stats["skipped_fy_incomplete"] += 1
                continue
            annual = _synthesize_annual(q4_annual)
            try:
                if store_financials(annual, db_session, q4_annual["period_end"], "annual"):
                    stats["stored_annual_synth"] += 1
            except Exception as exc:
                logger.debug("store annual %s FY%d: %s", ticker, fy, exc)
                stats["store_err"] += 1
        # FYs with quarterly data but no Q4 filing — can't synthesize.
        for fy in by_fy:
            if fy not in q4_files:
                stats["skipped_fy_incomplete"] += 1

    return stats


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", type=str, default=None,
                    help="Comma-separated allowlist (default: all cached tickers)")
    ap.add_argument("--no-synthesize", action="store_true",
                    help="Skip annual synthesis — write quarterlies only")
    ap.add_argument("--progress-every", type=int, default=25)
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL not set")
        return 2

    if not CACHE_ROOT.exists():
        logger.error("cache not found at %s — run download_xbrl_cache.py first", CACHE_ROOT)
        return 2

    engine = _engine()
    Session = sessionmaker(bind=engine)

    # Resolve universe from cache
    if args.tickers:
        wanted = {
            t.strip().upper().replace(".NS", "").replace(".BO", "")
            for t in args.tickers.split(",") if t.strip()
        }
        all_dirs = [d for d in CACHE_ROOT.iterdir() if d.is_dir() and d.name.upper() in wanted]
    else:
        all_dirs = [d for d in CACHE_ROOT.iterdir() if d.is_dir()]

    all_dirs.sort(key=lambda d: d.name)
    logger.info("processing %d tickers from %s (synthesize=%s)",
                len(all_dirs), CACHE_ROOT, not args.no_synthesize)

    totals = {
        "parsed_ok": 0, "parse_empty": 0, "parse_err": 0,
        "stored_quarterly": 0, "stored_annual_synth": 0,
        "skipped_fy_incomplete": 0, "store_err": 0,
    }
    t0 = time.time()

    for i, ticker_dir in enumerate(all_dirs, start=1):
        ticker = ticker_dir.name
        db = Session()
        try:
            s = _process_ticker(ticker, ticker_dir, db, not args.no_synthesize)
        except Exception as exc:
            logger.info("ticker %s crashed: %s", ticker, exc)
            s = dict.fromkeys(totals, 0)
            s["parse_err"] = 1
        finally:
            try:
                db.close()
            except Exception:
                pass
        for k, v in s.items():
            totals[k] += v

        if i % args.progress_every == 0 or i == len(all_dirs):
            elapsed = time.time() - t0
            rate = i / max(elapsed, 1.0)
            eta = (len(all_dirs) - i) / max(rate, 0.001) / 60
            logger.info(
                "[%d/%d] %s: q_stored=%d ann_synth=%d parse_err=%d | "
                "rate=%.1f/min ETA=%.1f min | totals: q=%d ann=%d",
                i, len(all_dirs), ticker,
                s["stored_quarterly"], s["stored_annual_synth"], s["parse_err"],
                rate * 60, eta,
                totals["stored_quarterly"], totals["stored_annual_synth"],
            )

    elapsed = time.time() - t0
    logger.info("DONE in %.1f min", elapsed / 60)
    logger.info(
        "  parsed=%d empty=%d err=%d",
        totals["parsed_ok"], totals["parse_empty"], totals["parse_err"],
    )
    logger.info(
        "  stored: quarterly=%d annual_synth=%d | skipped_incomplete_fy=%d store_err=%d",
        totals["stored_quarterly"], totals["stored_annual_synth"],
        totals["skipped_fy_incomplete"], totals["store_err"],
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
