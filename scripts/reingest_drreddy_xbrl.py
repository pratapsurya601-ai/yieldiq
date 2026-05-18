#!/usr/bin/env python3
"""One-shot operator script: re-ingest DRREDDY annual+quarterly XBRL.

Why this exists
---------------
v96's `TTM aggregator scale-sanity guard` quarantines DRREDDY.NS into
``data_limited`` status because the historical XBRL rows in `financials`
carry currency='USD' (a stale yfinance.financialCurrency leak from the
ADR filing — RDY trades on NYSE in USD) while the magnitudes are in INR
crores. The mixed tag confuses the aggregator's scale check.

The 2026-05-17 audit (`memory/MEMORY.md`, cache_service v96 note) found
6,996 scale-corrupt rows across 840 tickers. DRREDDY is one of them.

As of 2026-05-18 yfinance returns ``financialCurrency='INR'`` for
DRREDDY (verified by the pharma DCF investigation —
``docs/design/pharma-dcf-fix.md``). NSE's XBRL feed has always reported
INR. A targeted re-ingest will replace the bad rows with clean ones.

What this script does
---------------------
1. SELECT existing rows in ``financials`` for ticker='DRREDDY' where
   ``data_source LIKE '%XBRL%'`` OR ``currency='USD'``.
2. Snapshot the doomed rows to
   ``scripts/snapshots/drreddy_pre_reingest_<ts>.json`` (audit trail).
3. DELETE those rows (in the same transaction as the re-parse below).
4. Re-fetch annual + quarterly XBRL via
   ``data_pipeline.sources.nse_xbrl_fundamentals.fetch_ticker_financials``
   and re-write via the existing ``bse_xbrl.store_financials`` writer —
   same path used by ``scripts/backfill_fundamentals_nse_xbrl.py``.
5. Verify the new annual rows are scale-sane: at least one row with
   ``revenue`` in the 20,000-35,000 (Cr) range covering FY24-FY25 and
   ``currency='INR'``. If the new rows look wrong, ROLLBACK the
   transaction and exit non-zero.
6. Print a diff summary and exit.

Hard rules
~~~~~~~~~~
* Idempotent. Re-running after success is a no-op other than refreshing
  the new rows. The snapshot file gets a new timestamp suffix each run.
* Only touches ticker='DRREDDY'. Hard-coded; no CLI override.
* If NSE returns zero filings (data cache miss / 429 / blocked), the
  script fails LOUDLY and does NOT delete anything.
* If the re-parse returns rows but they fail the scale-sanity verify,
  the transaction is rolled back so the old rows survive — we'd rather
  leave DRREDDY in ``data_limited`` than silently empty the table.

Usage
-----
    $env:DATABASE_URL = "<neon uri>"
    python scripts/reingest_drreddy_xbrl.py            # full run
    python scripts/reingest_drreddy_xbrl.py --dry-run  # snapshot + plan only

Exit codes
~~~~~~~~~~
0  success (or dry-run preview)
1  re-parse returned rows but they failed the sanity check (rolled back)
2  no DATABASE_URL set
3  NSE returned zero filings — nothing changed
4  unexpected exception (rolled back)
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime
from pathlib import Path

_REPO = Path(__file__).resolve().parent.parent
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

from sqlalchemy import create_engine, text as sa_text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

from data_pipeline.sources.nse_xbrl_fundamentals import (  # noqa: E402
    fetch_ticker_financials,
    _get_session,
)
from data_pipeline.sources.bse_xbrl import store_financials  # noqa: E402


TICKER = "DRREDDY"
SNAPSHOT_DIR = _REPO / "scripts" / "snapshots"

# Sanity-check range: DRREDDY FY24 revenue was ~28,011 Cr; FY25 ~32,554 Cr.
# A row in this band on either currency='INR' confirms the re-parse landed.
SANE_REVENUE_MIN_CR = 20_000.0
SANE_REVENUE_MAX_CR = 50_000.0
SANE_PERIOD_MIN = date(2023, 1, 1)  # FY24+ year-end falls after this

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("reingest_drreddy_xbrl")


# ─────────────────────────────────────────────────────────────────────
# DB helpers
# ─────────────────────────────────────────────────────────────────────

def _engine():
    url = os.environ.get("DATABASE_URL", "")
    if not url:
        logger.error("DATABASE_URL not set")
        sys.exit(2)
    if url.startswith("postgres://"):
        url = "postgresql://" + url[len("postgres://"):]
    return create_engine(url, pool_recycle=300, pool_pre_ping=True)


SELECT_DOOMED_SQL = sa_text("""
    SELECT id, ticker, isin, period_end, period_type, filing_date,
           revenue, revenue_from_ops, ebitda, ebit, pbt, pat,
           eps_basic, eps_diluted,
           cfo, cfi, cff, capex, free_cash_flow,
           total_assets, total_equity, total_debt,
           current_liabilities, cash_and_equivalents, net_debt,
           shares_outstanding, roe, roa,
           debt_to_equity, gross_margin, operating_margin, net_margin,
           fcf_margin, revenue_growth_yoy, pat_growth_yoy, fcf_growth_yoy,
           data_source, data_quality_rank, currency
      FROM financials
     WHERE ticker = :t
       AND (data_source ILIKE '%XBRL%' OR currency = 'USD')
     ORDER BY period_end ASC, period_type ASC
""")


SELECT_ALL_DRREDDY_SQL = sa_text("""
    SELECT period_end, period_type, currency, data_source, revenue, pat
      FROM financials
     WHERE ticker = :t
     ORDER BY period_end DESC, period_type ASC
""")


DELETE_DOOMED_SQL = sa_text("""
    DELETE FROM financials
     WHERE ticker = :t
       AND (data_source ILIKE '%XBRL%' OR currency = 'USD')
""")


# ─────────────────────────────────────────────────────────────────────
# Snapshot / verify
# ─────────────────────────────────────────────────────────────────────

def _row_to_jsonable(row) -> dict:
    out = {}
    for k, v in row._mapping.items():
        if isinstance(v, (datetime, date)):
            out[k] = v.isoformat()
        else:
            out[k] = v
    return out


def _take_snapshot(rows: list) -> Path:
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.utcnow().strftime("%Y%m%dT%H%M%SZ")
    path = SNAPSHOT_DIR / f"drreddy_pre_reingest_{ts}.json"
    payload = {
        "ticker": TICKER,
        "captured_at_utc": ts,
        "row_count": len(rows),
        "rows": [_row_to_jsonable(r) for r in rows],
    }
    path.write_text(json.dumps(payload, indent=2, default=str), encoding="utf-8")
    logger.info("snapshot written: %s (%d rows)", path, len(rows))
    return path


def _verify_sane(conn) -> tuple[bool, str]:
    """Confirm the re-parsed rows have at least one recent annual revenue
    in the expected band with currency='INR'."""
    row = conn.execute(sa_text("""
        SELECT period_end, currency, revenue, data_source
          FROM financials
         WHERE ticker = :t
           AND period_type = 'annual'
           AND period_end >= :min_period
           AND currency = 'INR'
           AND revenue BETWEEN :rmin AND :rmax
         ORDER BY period_end DESC
         LIMIT 1
    """), {
        "t": TICKER,
        "min_period": SANE_PERIOD_MIN,
        "rmin": SANE_REVENUE_MIN_CR,
        "rmax": SANE_REVENUE_MAX_CR,
    }).fetchone()
    if row is None:
        return False, (
            f"no annual row in [{SANE_REVENUE_MIN_CR:.0f}, "
            f"{SANE_REVENUE_MAX_CR:.0f}] Cr with currency='INR' and "
            f"period_end >= {SANE_PERIOD_MIN}"
        )
    return True, (
        f"OK period_end={row[0]} currency={row[1]} revenue={row[2]:.1f}Cr "
        f"data_source={row[3]}"
    )


# ─────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--dry-run", action="store_true",
                    help="Snapshot and print plan; do NOT delete or re-parse.")
    ap.add_argument("--max-annual", type=int, default=15)
    ap.add_argument("--max-quarterly", type=int, default=40)
    ap.add_argument("--sleep", type=float, default=0.3,
                    help="Inter-XBRL-download sleep (NSE rate-limit guard).")
    args = ap.parse_args()

    engine = _engine()
    Session = sessionmaker(bind=engine)
    sess = Session()

    try:
        # ── Step 0: report current state ──────────────────────────────
        all_rows = sess.execute(SELECT_ALL_DRREDDY_SQL,
                                {"t": TICKER}).fetchall()
        logger.info("DRREDDY currently has %d rows in `financials`:", len(all_rows))
        for r in all_rows[:10]:
            logger.info("  %s %s currency=%s data_source=%s revenue=%s pat=%s",
                        r[0], r[1], r[2], r[3], r[4], r[5])
        if len(all_rows) > 10:
            logger.info("  ... and %d more", len(all_rows) - 10)

        # ── Step 1: select doomed rows ────────────────────────────────
        doomed = sess.execute(SELECT_DOOMED_SQL, {"t": TICKER}).fetchall()
        logger.info("doomed rows (XBRL or USD): %d", len(doomed))
        if not doomed:
            logger.info("nothing to do: no XBRL-tagged or USD-tagged rows for %s",
                        TICKER)
            # Still verify current state.
            ok, msg = _verify_sane(sess.connection())
            logger.info("post-state sanity: %s — %s",
                        "PASS" if ok else "FAIL", msg)
            return 0

        currency_summary: dict[str, int] = {}
        source_summary: dict[str, int] = {}
        for r in doomed:
            currency_summary[r.currency or "<null>"] = (
                currency_summary.get(r.currency or "<null>", 0) + 1
            )
            source_summary[r.data_source or "<null>"] = (
                source_summary.get(r.data_source or "<null>", 0) + 1
            )
        logger.info("  by currency:    %s", currency_summary)
        logger.info("  by data_source: %s", source_summary)

        # Root-cause sanity check: prompt says quarantine is from USD-tagged
        # historical rows. If we see ZERO USD rows AND every doomed row is
        # already INR with a sane data_source, the operator's hypothesis is
        # wrong and we should stop.
        usd_rows = currency_summary.get("USD", 0)
        if usd_rows == 0:
            logger.warning(
                "NO USD-tagged rows found for %s. The v96 quarantine may be "
                "from a different root cause than this script assumes. "
                "STOPPING. Investigate before deleting anything.",
                TICKER,
            )
            return 3

        # ── Step 2: snapshot ──────────────────────────────────────────
        snap_path = _take_snapshot(doomed)

        if args.dry_run:
            logger.info("[dry-run] would DELETE %d rows then re-parse NSE XBRL "
                        "for %s. Exiting without changes.", len(doomed), TICKER)
            return 0

        # ── Step 3+4: delete + re-parse in one transaction ────────────
        logger.info("fetching NSE XBRL filings for %s ...", TICKER)
        nse_sess = _get_session()
        try:
            new_rows = fetch_ticker_financials(
                TICKER,
                session=nse_sess,
                max_annual=args.max_annual,
                max_quarterly=args.max_quarterly,
                sleep=args.sleep,
            )
        except Exception as exc:
            logger.error("NSE XBRL fetch FAILED for %s: %s: %s",
                         TICKER, type(exc).__name__, exc)
            logger.error("no changes made — snapshot still at %s", snap_path)
            return 3

        logger.info("NSE returned %d filing rows", len(new_rows or []))
        if not new_rows:
            logger.error(
                "NSE returned ZERO filings for %s. Possible causes: "
                "cookie/Akamai block, NSE outage, symbol mismatch. "
                "NOT deleting existing rows. Snapshot at %s",
                TICKER, snap_path,
            )
            return 3

        # Single transaction: delete-then-insert. If anything fails the
        # rollback puts the doomed rows back.
        deleted = 0
        stored = 0
        try:
            del_result = sess.execute(DELETE_DOOMED_SQL, {"t": TICKER})
            deleted = del_result.rowcount or 0
            logger.info("deleted %d doomed rows (pending commit)", deleted)

            for r in new_rows:
                try:
                    if store_financials(
                        r, sess,
                        r["period_end"],
                        r.get("period_type", "annual"),
                    ):
                        stored += 1
                except Exception as exc:
                    logger.debug("store failed %s %s: %s",
                                 TICKER, r.get("period_end"), exc)
            logger.info("stored %d new rows (pending commit)", stored)

            # ── Step 5: verify scale-sane ─────────────────────────────
            ok, msg = _verify_sane(sess.connection())
            if not ok:
                logger.error("scale-sanity check FAILED: %s", msg)
                logger.error("ROLLBACK — old rows preserved, snapshot at %s",
                             snap_path)
                sess.rollback()
                return 1
            logger.info("scale-sanity check: %s", msg)

            sess.commit()
            logger.info("COMMITTED.")
        except Exception as exc:
            logger.error("unexpected error during write: %s: %s",
                         type(exc).__name__, exc)
            sess.rollback()
            logger.error("ROLLBACK — old rows preserved, snapshot at %s",
                         snap_path)
            return 4

        # ── Step 6: post-state summary ────────────────────────────────
        after_rows = sess.execute(SELECT_ALL_DRREDDY_SQL,
                                  {"t": TICKER}).fetchall()
        logger.info("=" * 70)
        logger.info("DONE. ticker=%s deleted=%d stored=%d", TICKER,
                    deleted, stored)
        logger.info("rows now in `financials` for %s: %d (was %d)",
                    TICKER, len(after_rows), len(all_rows))
        logger.info("snapshot: %s", snap_path)
        logger.info("recent annual rows:")
        for r in after_rows:
            if r[1] == "annual":
                logger.info("  %s currency=%s data_source=%s revenue=%s pat=%s",
                            r[0], r[2], r[3], r[4], r[5])
        return 0
    finally:
        sess.close()


if __name__ == "__main__":
    sys.exit(main())
