"""ingest_pledges.py — backfill promoter pledge disclosures.

Daily cron driver. Iterates active tickers, fetches BSE then NSE
(BSE preferred per task brief), idempotently UPSERTs into
``promoter_pledges``, throttles 1 req/sec per exchange.

Usage
-----
  # Offline fixture (no network):
  python scripts/ingest_pledges.py --source fixture --dry-run

  # Real BSE pull for a small list (live HTTP):
  python scripts/ingest_pledges.py --source bse --tickers RCOM,JINDALSTEL

  # Daily cron — BSE first, NSE bulk fallback, all watchlist+universe tickers:
  python scripts/ingest_pledges.py --apply

  # Initial backfill for known historical-collapse names:
  python scripts/ingest_pledges.py --source bse --tickers-from backfill_list

Idempotency
-----------
The UNIQUE(ticker, as_of_date) constraint on ``promoter_pledges`` lets
us re-run any day without duplicating rows. We use ON CONFLICT DO
UPDATE so a re-fetch refreshes ``fetched_at``.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Iterable, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("yieldiq.ingest.pledges")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


FIXTURE_PATH = ROOT / "tests" / "fixtures" / "sample_pledges.json"

# Known historical-collapse and high-pledge names — used for the initial
# proof-of-concept backfill. Curated from the task brief; these are
# precisely the tickers for which a populated pledge history is most
# instructive on the analysis page.
BACKFILL_LIST: List[str] = [
    "RCOM", "ZEEL", "JINDALSTEL", "ADANIENT", "ADANIPORTS",
    "GMRINFRA", "SUZLON", "JPASSOCIAT", "SREINFRA", "RELCAPITAL",
    "DHFL", "FRETAIL", "VIDEOCON", "ADANIGREEN", "ADANIPOWER",
    "RPOWER", "RNAVAL", "INFIBEAM", "MANAPPURAM", "MUTHOOTFIN",
    "BAJAJHIND", "CGPOWER", "DBCORP", "DCMSHRIRAM", "DEEPAKNTR",
    "DISHTV", "EVEREADY", "FORTIS", "GAYAPROJ", "GMDCLTD",
    "GMR", "HCC", "IDBI", "IL&FS", "INDIACEM",
    "INOXLEISUR", "JET", "JISLJALEQS", "KESORAMIND", "LUPIN",
    "M&MFIN", "MAHINDCIE", "NCC", "OPTOCIRCUI", "ORIENTBANK",
    "PCJEWELLER", "POWERGRID", "PUNJLLOYD", "QUESS", "RELINFRA",
]


# ── Retry / backoff envelope ───────────────────────────────────


def _with_retry(fn, *, max_attempts: int = 3, base_delay: float = 1.5):
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except NotImplementedError:
            raise
        except Exception as exc:
            last_exc = exc
            sleep_for = base_delay * (2 ** (attempt - 1))
            logger.warning(
                "attempt %d/%d failed: %s — sleeping %.1fs",
                attempt, max_attempts, exc, sleep_for,
            )
            time.sleep(sleep_for)
    assert last_exc is not None
    raise last_exc


# ── Sources ────────────────────────────────────────────────────


def _load_fixture() -> list[dict]:
    with open(FIXTURE_PATH, "r", encoding="utf-8") as fh:
        return json.load(fh)


def _row_to_dict(r) -> dict:
    """Normalize PledgeRow → dict suitable for UPSERT."""
    if hasattr(r, "to_dict"):
        return r.to_dict()
    return dict(r)


def _fetch_bse(tickers: Iterable[str], *, throttle_sec: float = 1.0) -> list[dict]:
    """Per-ticker BSE pull with throttle. Logs per-ticker outcome."""
    from backend.services.promoter_pledge_service import fetch_from_bse
    out: list[dict] = []
    for t in tickers:
        try:
            rows = _with_retry(lambda t=t: fetch_from_bse(t))
        except Exception as exc:
            logger.warning("bse fetch_error %s: %s", t, exc)
            continue
        if not rows:
            logger.info("bse no_data %s", t)
        else:
            logger.info("bse ok %s rows=%d", t, len(rows))
            out.extend(_row_to_dict(r) for r in rows)
        time.sleep(throttle_sec)
    return out


def _fetch_nse_bulk(filter_tickers: List[str] | None = None) -> list[dict]:
    """One bulk NSE pull, optionally filtered to a list of tickers."""
    from backend.services.promoter_pledge_service import fetch_from_nse_bulk
    by_sym = fetch_from_nse_bulk()
    if not by_sym:
        logger.info("nse no_data (empty bulk payload)")
        return []
    filt = {t.upper() for t in filter_tickers} if filter_tickers else None
    out: list[dict] = []
    for sym, rows in by_sym.items():
        if filt and sym not in filt:
            continue
        logger.info("nse ok %s rows=%d", sym, len(rows))
        out.extend(_row_to_dict(r) for r in rows)
    return out


# ── Alert hook ────────────────────────────────────────────────


def _maybe_emit_alerts() -> int:
    """After ingest, scan watchlists for pledge jumps > 5pp and queue
    notifications. Returns count fired. Best-effort — never raises."""
    try:
        from backend.services.promoter_pledge_service import detect_pledge_jumps
        fired = detect_pledge_jumps()
        return len(fired)
    except Exception as exc:
        logger.warning("alert emit failed: %s", exc)
        return 0


# ── Idempotent UPSERT ─────────────────────────────────────────


_UPSERT_SQL = """
INSERT INTO promoter_pledges
    (ticker, as_of_date, promoter_group_pct, pledged_pct,
     pledged_shares, source_url, fetched_at)
VALUES
    (%(ticker)s, %(as_of_date)s, %(promoter_group_pct)s, %(pledged_pct)s,
     %(pledged_shares)s, %(source_url)s, NOW())
ON CONFLICT (ticker, as_of_date) DO UPDATE SET
    promoter_group_pct = EXCLUDED.promoter_group_pct,
    pledged_pct        = EXCLUDED.pledged_pct,
    pledged_shares     = EXCLUDED.pledged_shares,
    source_url         = EXCLUDED.source_url,
    fetched_at         = NOW();
"""


def upsert_rows(rows: list[dict], *, dry_run: bool = False) -> int:
    if not rows:
        logger.info("no rows to upsert")
        return 0
    if dry_run:
        for r in rows[:5]:
            logger.info("DRY-RUN would upsert: %s", r)
        if len(rows) > 5:
            logger.info("DRY-RUN ... and %d more", len(rows) - 5)
        return len(rows)

    try:
        from data_pipeline.db import engine
    except Exception as exc:
        logger.error("DB engine import failed: %s", exc)
        return 0
    if engine is None:
        logger.error("DATABASE_URL not configured — aborting")
        return 0

    conn = engine.raw_connection()
    try:
        cur = conn.cursor()
        cur.executemany(_UPSERT_SQL, rows)
        conn.commit()
        cur.close()
    finally:
        conn.close()
    logger.info("upserted %d row(s)", len(rows))
    return len(rows)


def _active_tickers(limit: int | None = None) -> list[str]:
    """All tickers from the ``stocks`` table; bounded by ``limit`` for
    initial cron runs to keep total request budget sane."""
    try:
        from data_pipeline.db import engine
    except Exception:
        return []
    if engine is None:
        return []
    conn = engine.raw_connection()
    try:
        cur = conn.cursor()
        if limit:
            cur.execute("SELECT ticker FROM stocks ORDER BY ticker LIMIT %s", (limit,))
        else:
            cur.execute("SELECT ticker FROM stocks ORDER BY ticker")
        out = [r[0] for r in cur.fetchall()]
        cur.close()
        return out
    finally:
        conn.close()


# ── CLI ───────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill promoter_pledges.")
    p.add_argument(
        "--source", choices=["fixture", "bse", "nse"], default=None,
        help="Which source to pull from. Default: BSE-then-NSE pipeline (when --apply set).",
    )
    p.add_argument(
        "--tickers", default="",
        help="Comma-separated tickers. Ignored for --source=fixture.",
    )
    p.add_argument(
        "--tickers-from", default="",
        choices=["", "backfill_list", "stocks_table"],
        help="Source the ticker list from a known set instead of --tickers.",
    )
    p.add_argument("--all", action="store_true", help="Pull all known tickers (NSE batch).")
    p.add_argument("--dry-run", action="store_true", help="Don't write to DB.")
    p.add_argument("--apply", action="store_true",
                   help="Daily cron mode: BSE per-ticker (throttled) + NSE bulk + emit alerts.")
    p.add_argument("--limit", type=int, default=200,
                   help="Cap ticker count in --apply mode (default 200).")
    args = p.parse_args(argv)

    # Resolve ticker list.
    tickers: list[str] = []
    if args.tickers:
        tickers = [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
    elif args.tickers_from == "backfill_list":
        tickers = list(BACKFILL_LIST)

    rows: list[dict] = []

    if args.apply:
        # Daily cron path: BSE first (throttled per ticker), NSE bulk fallback,
        # then emit pledge-jump alerts.
        if not tickers:
            tickers = _active_tickers(limit=args.limit) or list(BACKFILL_LIST)
        logger.info("apply: %d tickers (BSE then NSE bulk)", len(tickers))
        rows.extend(_fetch_bse(tickers))
        rows.extend(_fetch_nse_bulk(filter_tickers=tickers))
    elif args.source == "fixture" or args.source is None:
        rows = _load_fixture()
    elif args.source == "bse":
        if not tickers:
            p.error("--source=bse requires --tickers or --tickers-from")
        rows = _fetch_bse(tickers)
    elif args.source == "nse":
        if not tickers and not args.all:
            p.error("--source=nse requires --tickers or --all")
        rows = _fetch_nse_bulk(filter_tickers=tickers if tickers else None)

    n = upsert_rows(rows, dry_run=args.dry_run)
    logger.info("done — %d row(s) %s", n, "would be written" if args.dry_run else "written")

    if args.apply and not args.dry_run:
        fired = _maybe_emit_alerts()
        logger.info("alerts fired: %d", fired)

    return 0


if __name__ == "__main__":
    sys.exit(main())
