"""Ingest BSE-only equities (not on NSE) into the `stocks` table.

Phase A of the Screener-parity push. Fetches BSE's daily equity
bhavcopy, dedupes against our existing stocks.isin, and inserts
BSE-only tickers we don't already track.

Data source (verified 2026-04-20):
    https://www.bseindia.com/download/BhavCopy/Equity/
        BhavCopy_BSE_CM_0_0_0_YYYYMMDD_F_0000.CSV

Columns (verbatim, T+0 ISO-date format):
    TradDt, BizDt, Sgmt, Src, FinInstrmTp, FinInstrmId, ISIN,
    TckrSymb, SctySrs, XpryDt, ..., ClsPric, ...

  FinInstrmId   -> BSE scrip code (e.g. 500002)
  ISIN          -> 12-char ISIN (e.g. INE117A01022)
  TckrSymb      -> BSE ticker symbol (e.g. ABB)
  FinInstrmNm   -> company name
  SctySrs       -> group code (A/B/T/X/Z/M)

We filter to liquid groups (A, B, X) and skip T/Z/M (trade-to-trade,
suspended, illiquid trust units) for initial Phase A load.

BSE-only dedup: LEFT JOIN vs stocks.isin — any ISIN already in our DB
is either NSE-listed (we track it) or dual-listed (NSE symbol is
preferred anyway).

Ticker convention: BSE-only rows get ticker = TckrSymb with `bse_code`
populated. If a BSE-only ticker collides with an existing NSE ticker
symbol (different ISINs), we suffix with `.BO` per yfinance convention.

Usage
-----
    python scripts/ingest_bse_only_universe.py                # today's bhavcopy
    python scripts/ingest_bse_only_universe.py --date 20260417
    python scripts/ingest_bse_only_universe.py --dry-run      # report only
    python scripts/ingest_bse_only_universe.py --groups A,B   # subset of groups

Requires DATABASE_URL env var.
"""
from __future__ import annotations

import argparse
import io
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path

try:
    import pandas as pd
    import requests
except ImportError:
    print("pip install pandas requests", file=sys.stderr)
    sys.exit(2)

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))


logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")
logger = logging.getLogger("ingest_bse_only")


BSE_BHAV_URL = (
    "https://www.bseindia.com/download/BhavCopy/Equity/"
    "BhavCopy_BSE_CM_0_0_0_{yyyymmdd}_F_0000.CSV"
)

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept": "text/csv,application/octet-stream,*/*",
    "Referer": "https://www.bseindia.com/",
}

DEFAULT_GROUPS = ("A", "B", "X")  # liquid groups only; skip T/Z/M


def _fetch_bhav(trade_date: date) -> "pd.DataFrame | None":
    url = BSE_BHAV_URL.format(yyyymmdd=trade_date.strftime("%Y%m%d"))
    logger.info("fetching %s", url)
    try:
        r = requests.get(url, headers=HEADERS, timeout=30)
    except Exception as exc:
        logger.warning("fetch error: %s", exc)
        return None
    if r.status_code == 404:
        logger.info("  404 — non-trading day or not yet posted")
        return None
    if r.status_code != 200:
        logger.warning("  HTTP %d", r.status_code)
        return None
    try:
        df = pd.read_csv(io.BytesIO(r.content))
    except Exception as exc:
        logger.error("  csv parse failed: %s", exc)
        return None
    logger.info("  got %d rows", len(df))
    return df


def _latest_available_bhav(max_lookback: int = 5) -> "tuple[pd.DataFrame, date] | None":
    """Try today, then walk back up to ``max_lookback`` days."""
    for back in range(max_lookback + 1):
        d = date.today() - timedelta(days=back)
        if d.weekday() >= 5:
            continue  # weekend
        df = _fetch_bhav(d)
        if df is not None:
            return df, d
    return None


def _filter_equity(df: pd.DataFrame, groups: tuple[str, ...]) -> pd.DataFrame:
    # Keep only equity rows (some files mix in other instrument types)
    if "FinInstrmTp" in df.columns:
        df = df[df["FinInstrmTp"].astype(str).str.strip().str.upper() == "STK"].copy()
    if "SctySrs" in df.columns:
        df["SctySrs"] = df["SctySrs"].astype(str).str.strip().str.upper()
        df = df[df["SctySrs"].isin(groups)].copy()
    return df


def _load_existing_isins(engine) -> set[str]:
    from sqlalchemy import text as _t
    with engine.connect() as conn:
        rows = conn.execute(_t(
            "SELECT isin FROM stocks WHERE isin IS NOT NULL AND isin != ''"
        )).fetchall()
    return {str(r[0]).strip().upper() for r in rows if r[0]}


def _load_existing_tickers(engine) -> set[str]:
    from sqlalchemy import text as _t
    with engine.connect() as conn:
        rows = conn.execute(_t("SELECT ticker FROM stocks")).fetchall()
    return {str(r[0]).strip().upper() for r in rows if r[0]}


def _insert_stocks(engine, new_rows: list[dict], batch_size: int = 500) -> int:
    """Insert new stocks rows. Uses INSERT ... ON CONFLICT DO NOTHING on ticker."""
    if not new_rows:
        return 0
    from sqlalchemy import text as _t
    inserted = 0
    with engine.begin() as conn:
        for i in range(0, len(new_rows), batch_size):
            chunk = new_rows[i:i + batch_size]
            result = conn.execute(_t("""
                INSERT INTO stocks (
                    ticker, company_name, isin, series, sector, bse_code, is_active
                ) VALUES (
                    :ticker, :company_name, :isin, :series, NULL, :bse_code, TRUE
                )
                ON CONFLICT (ticker) DO NOTHING
            """), chunk)
            inserted += result.rowcount or 0
    return inserted


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", default=None,
                    help="Bhavcopy date YYYYMMDD (default: most-recent available)")
    ap.add_argument("--groups", default=",".join(DEFAULT_GROUPS),
                    help="Comma-separated group codes to keep (default A,B,X)")
    ap.add_argument("--dry-run", action="store_true",
                    help="Report counts only; don't write to DB")
    args = ap.parse_args()

    if not os.environ.get("DATABASE_URL"):
        logger.error("DATABASE_URL not set")
        return 2

    groups = tuple(g.strip().upper() for g in args.groups.split(",") if g.strip())

    if args.date:
        d = date.fromisoformat(
            f"{args.date[:4]}-{args.date[4:6]}-{args.date[6:8]}"
        )
        df = _fetch_bhav(d)
        if df is None:
            logger.error("bhavcopy for %s not available", d)
            return 1
        bhav_date = d
    else:
        r = _latest_available_bhav()
        if r is None:
            logger.error("no bhavcopy available in last 6 days")
            return 1
        df, bhav_date = r
    logger.info("using bhavcopy for trade_date=%s", bhav_date)

    df = _filter_equity(df, groups)
    logger.info("after equity+group filter: %d rows (groups=%s)", len(df), groups)

    # Normalise fields
    df["ISIN"] = df["ISIN"].astype(str).str.strip().str.upper()
    df["FinInstrmId"] = df["FinInstrmId"].astype(str).str.strip()
    df["TckrSymb"] = df["TckrSymb"].astype(str).str.strip().str.upper()
    df["FinInstrmNm"] = df["FinInstrmNm"].astype(str).str.strip()
    df = df[df["ISIN"].str.len() == 12].copy()
    logger.info("after ISIN validity: %d rows", len(df))

    # DB dedup
    from sqlalchemy import create_engine
    url = os.environ["DATABASE_URL"]
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    engine = create_engine(url, pool_pre_ping=True)

    existing_isins = _load_existing_isins(engine)
    existing_tickers = _load_existing_tickers(engine)
    logger.info("DB has %d ISINs and %d tickers already", len(existing_isins), len(existing_tickers))

    # Keep rows whose ISIN is NOT already in DB
    df_new = df[~df["ISIN"].isin(existing_isins)].copy()
    logger.info("BSE-only candidates (ISIN not in DB): %d", len(df_new))

    # Build insert rows with collision-safe tickers
    new_rows: list[dict] = []
    seen_tickers: set[str] = set()
    collisions = 0
    for _, row in df_new.iterrows():
        base_ticker = row["TckrSymb"]
        # Collision handling: if TckrSymb already exists, suffix .BO
        ticker = base_ticker
        if ticker in existing_tickers or ticker in seen_tickers:
            ticker = f"{base_ticker}.BO"
            collisions += 1
        if ticker in existing_tickers or ticker in seen_tickers:
            # Still colliding (rare): suffix scrip code
            ticker = f"{base_ticker}.{row['FinInstrmId']}"
        seen_tickers.add(ticker)

        new_rows.append({
            "ticker": ticker,
            "company_name": row["FinInstrmNm"][:500] if row["FinInstrmNm"] else None,
            "isin": row["ISIN"],
            "series": row["SctySrs"],
            "bse_code": row["FinInstrmId"],
        })

    logger.info(
        "ready to insert %d new BSE-only stocks (%d ticker collisions got .BO suffix)",
        len(new_rows), collisions,
    )

    if args.dry_run:
        logger.info("--dry-run — not writing. Sample rows:")
        for r in new_rows[:5]:
            logger.info("  %s", r)
        return 0

    inserted = _insert_stocks(engine, new_rows)
    logger.info("INSERT complete — %d rows added", inserted)

    # Final count
    from sqlalchemy import text as _t
    with engine.connect() as conn:
        total = conn.execute(_t("SELECT COUNT(*) FROM stocks WHERE is_active")).scalar()
        bse_only = conn.execute(_t(
            "SELECT COUNT(*) FROM stocks WHERE bse_code IS NOT NULL AND is_active"
        )).scalar()
    logger.info("stocks (active): %d total, %d have bse_code", total, bse_only)
    return 0


if __name__ == "__main__":
    sys.exit(main())
