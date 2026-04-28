"""ingest_pledges.py — backfill promoter pledge disclosures.

SCAFFOLDING ONLY. The actual BSE/NSE scrapers are stubbed; this script
exists so the rest of the pipeline (DB schema, idempotent UPSERT,
retry/backoff envelope, logging) can be exercised end-to-end against
the JSON fixture in `tests/fixtures/sample_pledges.json`.

Usage
-----
  # Dry-run from the bundled fixture (no network):
  python scripts/ingest_pledges.py --source fixture --dry-run

  # Real backfill (NOT YET IMPLEMENTED — will raise NotImplementedError):
  python scripts/ingest_pledges.py --source bse --tickers RCOM,JINDALSTEL
  python scripts/ingest_pledges.py --source nse --all

Idempotency
-----------
The UNIQUE(ticker, as_of_date) constraint on `promoter_pledges` lets us
re-run any day without duplicating rows. We use ON CONFLICT DO UPDATE
so a re-fetch refreshes `fetched_at` and any corrected values.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

logger = logging.getLogger("yieldiq.ingest.pledges")
if not logger.handlers:
    _h = logging.StreamHandler()
    _h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    logger.addHandler(_h)
    logger.setLevel(logging.INFO)


FIXTURE_PATH = ROOT / "tests" / "fixtures" / "sample_pledges.json"


# ── Retry / backoff envelope ───────────────────────────────────


def _with_retry(fn, *, max_attempts: int = 3, base_delay: float = 1.5):
    """Call `fn()` with exponential backoff. Re-raises after max_attempts."""
    last_exc: Exception | None = None
    for attempt in range(1, max_attempts + 1):
        try:
            return fn()
        except NotImplementedError:
            # Don't retry stubs — fail fast so the operator notices.
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


def _fetch_bse(tickers: Iterable[str]) -> list[dict]:
    """Stub — will call backend.services.promoter_pledge_service.fetch_from_bse."""
    # TODO: wire to fetch_from_bse once scraper lands.
    from backend.services.promoter_pledge_service import fetch_from_bse
    rows: list[dict] = []
    for t in tickers:
        rows.extend(_with_retry(lambda: fetch_from_bse(t)))
    return rows


def _fetch_nse(tickers: Iterable[str]) -> list[dict]:
    """Stub — will call backend.services.promoter_pledge_service.fetch_from_nse."""
    # TODO: NSE returns all symbols in one payload — refactor to single
    # batch call rather than per-ticker iteration once the scraper lands.
    from backend.services.promoter_pledge_service import fetch_from_nse
    rows: list[dict] = []
    for t in tickers:
        rows.extend(_with_retry(lambda: fetch_from_nse(t)))
    return rows


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
    """Idempotently UPSERT pledge rows. Returns count written (or simulated)."""
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


# ── CLI ───────────────────────────────────────────────────────


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Backfill promoter_pledges (scaffolding).")
    p.add_argument(
        "--source", choices=["fixture", "bse", "nse"], default="fixture",
        help="Which source to pull from. 'fixture' = bundled JSON (offline).",
    )
    p.add_argument(
        "--tickers", default="",
        help="Comma-separated tickers. Ignored for --source=fixture.",
    )
    p.add_argument("--all", action="store_true", help="Pull all known tickers (NSE batch).")
    p.add_argument("--dry-run", action="store_true", help="Don't write to DB.")
    args = p.parse_args(argv)

    if args.source == "fixture":
        rows = _load_fixture()
    elif args.source == "bse":
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
        if not tickers:
            p.error("--source=bse requires --tickers")
        rows = _fetch_bse(tickers)
    elif args.source == "nse":
        tickers = [t.strip() for t in args.tickers.split(",") if t.strip()]
        if not tickers and not args.all:
            p.error("--source=nse requires --tickers or --all")
        rows = _fetch_nse(tickers)
    else:  # pragma: no cover
        raise AssertionError(f"unknown source {args.source!r}")

    n = upsert_rows(rows, dry_run=args.dry_run)
    logger.info("done — %d row(s) %s", n, "would be written" if args.dry_run else "written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
