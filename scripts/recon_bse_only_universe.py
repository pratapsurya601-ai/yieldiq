"""Reconcile the BSE-only universe candidate list from today's bhavcopy.

Phase 1+2 of the BSE-only universe expansion. This script does NOT
write to the database. It produces a regenerated
``data_pipeline/data/bse_only_tickers.json`` with up to 200 candidate
tickers plus the 8 reconciled seed entries.

Pipeline
--------
1. Fetch latest available BSE equity bhavcopy via
   ``data_pipeline.sources.bse_securities_master._fetch_csv`` /
   ``_latest_available`` (raw CSV, not the wrapped dict — we need the
   full column set for volume + turnover).
2. Apply filters in order, recording per-stage counts:

       FinInstrmTp == 'STK'                          (equity only)
       SctySrs    in {'A', 'B'}                      (liquid groups)
       TtlTradgVol > 0                               (single-day volume)
       FinInstrmNm regex EXCLUDE fund/ETF patterns
       ISIN not in (SELECT isin FROM stocks WHERE isin IS NOT NULL)

3. Sort: group 'A' before 'B'; within each group, by daily turnover
   (TtlTrfVal) descending as a market-cap proxy. The bhavcopy does
   not carry shares-outstanding, so close-price * volume is the best
   liquidity-weighted proxy we have today.
4. Cap at top 200. Each entry carries
   ``pending_xbrl_verification: true`` — the Phase-3 smoke test will
   verify XBRL availability on bseindia.com before the rows are
   inserted into ``stocks``.
5. Reconcile the 8 existing seed entries in
   ``data_pipeline/data/bse_only_tickers.json``: look up each by
   scrip code; if today's bhavcopy lists a different name, treat the
   bhavcopy as truth and log the mismatch. Merge into the candidate
   list (dedup by scrip code).
6. Write a regenerated JSON with a ``_meta`` block carrying bhavcopy
   date, per-filter funnel counts, and the reconciliation log.

Phase 3+ (DO NOT run from this script):
    - Playwright XBRL pre-flight smoke test on a 5-ticker subset
    - Full backfill via scripts/backfill_bse_only_quarterly_xbrl.py
    - Verify rows landed in the quarterly tables

Usage
-----
    python scripts/recon_bse_only_universe.py
    python scripts/recon_bse_only_universe.py --date 20260515
    python scripts/recon_bse_only_universe.py --cap 200 --dry-run

Requires DATABASE_URL in env (or in repo .env.local — parsed manually
to avoid colliding with any stale ~/.env files on the operator's
machine).
"""
from __future__ import annotations

import argparse
import io
import json
import logging
import os
import re
import sys
from datetime import date, datetime
from pathlib import Path

try:
    import pandas as pd
except ImportError:
    print("pip install pandas", file=sys.stderr)
    sys.exit(2)

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from data_pipeline.sources.bse_securities_master import (  # noqa: E402
    _fetch_csv,
    _latest_available,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("recon_bse_only")

EXCLUDE_NAME_RE = re.compile(
    r"(?i)(ETF|MUTUAL|FUND|TRUST|REIT|INVIT|BEES|INDEX|GOLD|LIQUID|SILVER|NIFTY|SENSEX|GSEC|BOND)"
)

JSON_PATH = _REPO / "data_pipeline" / "data" / "bse_only_tickers.json"


def _load_database_url() -> str | None:
    """Parse repo .env.local manually for DATABASE_URL.

    We avoid python-dotenv here because operator machines sometimes
    have a stale ~/.env or process-env DATABASE_URL that points at a
    decommissioned host. The repo .env.local is the single source of
    truth for this script.
    """
    env_path = _REPO / ".env.local"
    if env_path.exists():
        for raw in env_path.read_text().splitlines():
            line = raw.strip()
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip().strip('"').strip("'")
    return os.environ.get("DATABASE_URL")


def _fetch_existing_isins() -> set[str]:
    url = _load_database_url()
    if not url:
        logger.error("DATABASE_URL not set — cannot dedup against stocks.isin")
        sys.exit(2)
    try:
        import psycopg2
    except ImportError:
        print("pip install psycopg2-binary", file=sys.stderr)
        sys.exit(2)
    conn = psycopg2.connect(url)
    try:
        cur = conn.cursor()
        cur.execute("SELECT isin FROM stocks WHERE isin IS NOT NULL")
        isins = {r[0].strip().upper() for r in cur.fetchall() if r[0]}
    finally:
        conn.close()
    logger.info("Loaded %d existing ISINs from stocks table", len(isins))
    return isins


def _load_bhavcopy(trade_date: date | None) -> tuple[pd.DataFrame, date]:
    if trade_date is None:
        body, used = _latest_available()
    else:
        body = _fetch_csv(trade_date)
        used = trade_date
    if body is None or used is None:
        logger.error("No bhavcopy available")
        sys.exit(2)
    df = pd.read_csv(io.BytesIO(body))
    logger.info("Bhavcopy %s: %d raw rows", used, len(df))
    return df, used


def _apply_filters(df: pd.DataFrame, existing_isins: set[str]) -> tuple[pd.DataFrame, dict]:
    funnel: dict[str, int] = {"raw": len(df)}

    # FinInstrmTp == STK
    df = df[df["FinInstrmTp"].astype(str).str.strip().str.upper() == "STK"].copy()
    funnel["after_stk"] = len(df)

    # SctySrs in {A, B}
    df["SctySrs"] = df["SctySrs"].astype(str).str.strip().str.upper()
    df = df[df["SctySrs"].isin({"A", "B"})].copy()
    funnel["after_group_AB"] = len(df)
    funnel["group_A"] = int((df["SctySrs"] == "A").sum())
    funnel["group_B"] = int((df["SctySrs"] == "B").sum())

    # Volume > 0
    df["TtlTradgVol"] = pd.to_numeric(df["TtlTradgVol"], errors="coerce").fillna(0)
    df = df[df["TtlTradgVol"] > 0].copy()
    funnel["after_volume_gt_0"] = len(df)

    # Name filter
    df["FinInstrmNm"] = df["FinInstrmNm"].astype(str).str.strip()
    mask_excl = df["FinInstrmNm"].str.contains(EXCLUDE_NAME_RE, na=False, regex=True)
    excluded_names = int(mask_excl.sum())
    df = df[~mask_excl].copy()
    funnel["after_name_filter"] = len(df)
    funnel["excluded_by_name_regex"] = excluded_names

    # ISIN valid + dedup
    df["ISIN"] = df["ISIN"].astype(str).str.strip().str.upper()
    df = df[df["ISIN"].str.len() == 12].copy()
    funnel["after_isin_valid"] = len(df)
    df = df[~df["ISIN"].isin(existing_isins)].copy()
    funnel["after_isin_dedup"] = len(df)

    # Turnover for ranking
    df["TtlTrfVal"] = pd.to_numeric(df["TtlTrfVal"], errors="coerce").fillna(0)
    df["ClsPric"] = pd.to_numeric(df["ClsPric"], errors="coerce").fillna(0)

    # Sort: A first, then B; within group desc by turnover
    df["_grp_rank"] = df["SctySrs"].map({"A": 0, "B": 1}).fillna(9)
    df = df.sort_values(["_grp_rank", "TtlTrfVal"], ascending=[True, False]).reset_index(drop=True)

    return df, funnel


def _to_candidate_entry(row: pd.Series) -> dict:
    return {
        "ticker": str(row["TckrSymb"]).strip().upper(),
        "bse_code": str(int(row["FinInstrmId"])) if pd.notna(row["FinInstrmId"]) else None,
        "name": str(row["FinInstrmNm"]).strip()[:200],
        "group": str(row["SctySrs"]).strip().upper(),
        "isin": str(row["ISIN"]).strip().upper(),
        "close": float(row["ClsPric"]) if pd.notna(row["ClsPric"]) else None,
        "turnover": float(row["TtlTrfVal"]) if pd.notna(row["TtlTrfVal"]) else None,
        "volume": int(row["TtlTradgVol"]) if pd.notna(row["TtlTradgVol"]) else None,
        "pending_xbrl_verification": True,
    }


def _reconcile_seeds(df_full: pd.DataFrame) -> tuple[list[dict], list[dict]]:
    """Look up the 8 existing seed tickers by scrip code in the full bhavcopy.

    Returns (reconciled_entries, reconciliation_log).
    """
    if not JSON_PATH.exists():
        logger.warning("No existing seed JSON at %s — skipping recon", JSON_PATH)
        return [], []
    seeds = json.loads(JSON_PATH.read_text())
    seed_rows = seeds.get("tickers", [])

    # Build scripcode -> row index from the *full* bhavcopy (pre-filter)
    df_full = df_full.copy()
    df_full["FinInstrmId"] = pd.to_numeric(df_full["FinInstrmId"], errors="coerce")
    df_full["SctySrs"] = df_full["SctySrs"].astype(str).str.strip().str.upper()
    df_full["TtlTradgVol"] = pd.to_numeric(df_full["TtlTradgVol"], errors="coerce").fillna(0)
    df_full["TtlTrfVal"] = pd.to_numeric(df_full["TtlTrfVal"], errors="coerce").fillna(0)
    df_full["ClsPric"] = pd.to_numeric(df_full["ClsPric"], errors="coerce").fillna(0)
    by_code: dict[int, pd.Series] = {}
    for _, r in df_full.iterrows():
        if pd.notna(r["FinInstrmId"]):
            by_code[int(r["FinInstrmId"])] = r

    log: list[dict] = []
    reconciled: list[dict] = []
    for seed in seed_rows:
        code_str = str(seed.get("bse_code", "")).strip()
        try:
            code_int = int(code_str)
        except (TypeError, ValueError):
            log.append({
                "ticker": seed.get("ticker"),
                "outcome": "invalid_bse_code",
                "seed_bse_code": code_str,
            })
            continue
        if code_int not in by_code:
            log.append({
                "ticker": seed.get("ticker"),
                "bse_code": code_str,
                "outcome": "not_in_bhavcopy",
                "seed_name": seed.get("name"),
            })
            # Keep the seed as-is so we don't lose coverage
            reconciled.append({
                **seed,
                "isin": seed.get("isin"),
                "pending_xbrl_verification": True,
                "_seed": True,
                "_recon_outcome": "not_in_bhavcopy",
            })
            continue
        bhav = by_code[code_int]
        bhav_name = str(bhav["FinInstrmNm"]).strip()
        bhav_ticker = str(bhav["TckrSymb"]).strip().upper()
        seed_name = (seed.get("name") or "").strip()
        # Loose match: case-insensitive substring either direction
        match = (
            seed_name.lower() in bhav_name.lower()
            or bhav_name.lower() in seed_name.lower()
            or seed_name.lower().split(" ")[0] == bhav_name.lower().split(" ")[0]
        )
        outcome = "match" if match else "mismatch_use_bhavcopy"
        log.append({
            "ticker": seed.get("ticker"),
            "bse_code": code_str,
            "outcome": outcome,
            "seed_name": seed_name,
            "bhav_name": bhav_name,
            "bhav_ticker": bhav_ticker,
            "bhav_group": str(bhav["SctySrs"]).strip().upper(),
        })
        reconciled.append({
            "ticker": bhav_ticker,
            "bse_code": str(int(bhav["FinInstrmId"])),
            "name": bhav_name[:200],
            "group": str(bhav["SctySrs"]).strip().upper(),
            "isin": str(bhav["ISIN"]).strip().upper(),
            "close": float(bhav["ClsPric"]) if pd.notna(bhav["ClsPric"]) else None,
            "turnover": float(bhav["TtlTrfVal"]) if pd.notna(bhav["TtlTrfVal"]) else None,
            "volume": int(bhav["TtlTradgVol"]) if pd.notna(bhav["TtlTradgVol"]) else None,
            "pending_xbrl_verification": True,
            "_seed": True,
            "_recon_outcome": outcome,
        })
    return reconciled, log


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", type=str, default=None, help="YYYYMMDD")
    ap.add_argument("--cap", type=int, default=200)
    ap.add_argument("--dry-run", action="store_true", help="Do not write JSON")
    args = ap.parse_args()

    trade_date = None
    if args.date:
        trade_date = datetime.strptime(args.date, "%Y%m%d").date()

    df_full, used_date = _load_bhavcopy(trade_date)
    existing_isins = _fetch_existing_isins()
    df_filtered, funnel = _apply_filters(df_full, existing_isins)

    # Cap
    capped = df_filtered.head(args.cap).copy()
    funnel["after_cap"] = len(capped)
    funnel["cap"] = args.cap

    candidate_entries = [_to_candidate_entry(r) for _, r in capped.iterrows()]
    candidate_codes = {e["bse_code"] for e in candidate_entries}

    # Reconcile seeds against the full bhavcopy (so we don't lose seeds
    # that got filtered out by group / volume)
    seed_entries, recon_log = _reconcile_seeds(df_full)

    # Merge: add any seed not already in candidate set
    merged: list[dict] = list(candidate_entries)
    for s in seed_entries:
        if s.get("bse_code") not in candidate_codes:
            merged.append(s)
            candidate_codes.add(s.get("bse_code"))

    out = {
        "_meta": {
            "description": (
                "BSE-only Group A/B candidate universe regenerated from "
                "bhavcopy + reconciled against existing seed list. "
                "Each candidate carries pending_xbrl_verification=true; "
                "Phase 3 smoke test verifies XBRL availability before "
                "Phase 4 backfill writes rows."
            ),
            "bhavcopy_date": used_date.isoformat(),
            "generated_at": datetime.utcnow().isoformat() + "Z",
            "generator": "scripts/recon_bse_only_universe.py",
            "filter_funnel": funnel,
            "reconciliation_log": recon_log,
            "candidate_count": len(candidate_entries),
            "seed_count": len(seed_entries),
            "merged_total": len(merged),
            "schema_version": 2,
            "ingest_path": "data_pipeline.sources.bse_quarterly_xbrl",
            "consumer": "scripts/backfill_bse_only_quarterly_xbrl.py",
            "next_steps": [
                "Phase 3: Playwright XBRL pre-flight smoke test on 5 tickers",
                "Phase 4: full backfill via scripts/backfill_bse_only_quarterly_xbrl.py",
                "Phase 5: verify rows landed in quarterly_financials / shares_outstanding",
            ],
        },
        "tickers": merged,
    }

    logger.info("Funnel: %s", funnel)
    logger.info("Reconciliation outcomes: %s", [r["outcome"] for r in recon_log])
    logger.info("Final merged entry count: %d", len(merged))

    if args.dry_run:
        print(json.dumps(out["_meta"], indent=2, default=str))
        return

    JSON_PATH.write_text(json.dumps(out, indent=2, default=str) + "\n")
    logger.info("Wrote %s", JSON_PATH)


if __name__ == "__main__":
    main()
