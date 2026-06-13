"""Backfill: re-normalise net_margin unit anomalies at rest (FIX-NET-MARGIN-UNIT).

Why
---
The unit-integrity validator (#918) surfaced a cohort of ``financials``
rows whose ``net_margin`` (pat/revenue) is confidently-wrong by 10^N —
ESSARSHPNG=440,053%, SHYAMTEL=-56,884%, JINDALPHOT=45,645%,
JPOLYINVST=44,162%. Root cause (diagnosed 2026-06-13): yfinance returns
``Total Revenue`` mis-scaled (typically ~1000x too small) for a cohort
of Indian micro-caps while ``Net Income`` arrives at the correct
magnitude — e.g. ESSARSHPNG FY2025 revenue=102.6M but net_income=6.6B
from the SAME income statement. ``_to_cr`` (÷1e7) propagates the
inconsistency: revenue_cr tiny, pat_cr normal, net_margin explodes.

The SOURCE fix (data_pipeline/sources/yfinance_supplement.py:
``_net_margin_unit_ok``) stops NEW corruption — when pat/revenue is
implausible the revenue figure is dropped to None at write time. But the
rows already at rest do not self-heal until each ticker is re-ingested.
This script re-normalises them in place using the SAME plausibility rule.

What it does (idempotent)
-------------------------
For every ``financials`` row (annual + quarterly) whose stored
``net_margin`` — or the implied pat/revenue ratio — exceeds the
plausibility band, it NULLs ``revenue`` and ``net_margin`` (the
untrustworthy revenue is the cause; pat/assets/equity are corroborated
sane and are LEFT INTACT). It then re-runs ``build_ratio_history.py`` for
the affected tickers so ratio_history reflects the corrected (NULL)
net_margin. Running twice is a no-op: once revenue/net_margin are NULL,
the ratio is no longer computable and nothing is re-flagged.

Authorization
-------------
DRY-RUN BY DEFAULT. A prod-data write needs explicit authorization, so
this script prints a full before/after report and exits WITHOUT writing
unless ``--apply`` is passed. ``--apply`` is intentionally gated behind
an operator decision; the dry-run report is the artifact for that review.

Usage
-----
    DATABASE_URL=... python scripts/backfill_net_margin_unit_anomalies.py            # dry-run (default)
    DATABASE_URL=... python scripts/backfill_net_margin_unit_anomalies.py --period-types annual
    DATABASE_URL=... python scripts/backfill_net_margin_unit_anomalies.py --tickers ESSARSHPNG,SHYAMTEL
    DATABASE_URL=... python scripts/backfill_net_margin_unit_anomalies.py --apply   # WRITES (needs authorization)
    DATABASE_URL=... python scripts/backfill_net_margin_unit_anomalies.py --apply --skip-rebuild
"""
from __future__ import annotations

import argparse
import logging
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.orm import sessionmaker  # noqa: E402

# Single source of truth for the plausibility band — imported from the
# source-fix module so the backfill and the ingest gate can never drift.
from data_pipeline.sources.yfinance_supplement import (  # noqa: E402
    NET_MARGIN_PLAUSIBLE_PCT,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("net_margin_unit_backfill")


# Candidate rows: stored net_margin OR the implied pat/revenue ratio is
# beyond the plausibility band. We test both because some legacy rows
# carry a stale stored net_margin that disagrees with pat/revenue.
SELECT_ANOMALIES = """
    SELECT id, ticker, period_end, period_type,
           revenue, pat, net_margin, ebitda, total_assets, data_source
      FROM financials
     WHERE period_type = ANY(:ptypes)
       AND (
            (net_margin IS NOT NULL AND abs(net_margin) > :band)
         OR (revenue IS NOT NULL AND revenue <> 0 AND pat IS NOT NULL
             AND abs(pat / revenue * 100.0) > :band)
       )
       {ticker_filter}
     ORDER BY abs(
        COALESCE(net_margin,
                 CASE WHEN revenue <> 0 THEN pat / revenue * 100.0 ELSE 0 END)
     ) DESC
"""


def _engine():
    url = os.environ.get("DATABASE_URL")
    if not url:
        logger.error("DATABASE_URL unset — refusing to run.")
        sys.exit(2)
    return create_engine(url, future=True)


def _fetch_anomalies(sess, ptypes, tickers):
    ticker_filter = ""
    params = {"ptypes": ptypes, "band": NET_MARGIN_PLAUSIBLE_PCT}
    if tickers:
        ticker_filter = "AND ticker = ANY(:tickers)"
        params["tickers"] = tickers
    sql = text(SELECT_ANOMALIES.format(ticker_filter=ticker_filter))
    return sess.execute(sql, params).mappings().all()


def _rebuild_ratio_history(tickers: list[str]) -> int:
    """Delegate to scripts/build_ratio_history.py for the fixed tickers.

    Mirrors scripts/rebuild_ratio_history.py — the builder owns its own
    session, so we invoke it as a subprocess rather than re-implementing
    the ratio math here.
    """
    builder = ROOT / "scripts" / "build_ratio_history.py"
    if not builder.exists():
        logger.warning("build_ratio_history.py not found — skipping rebuild")
        return 1
    cmd = [
        sys.executable, str(builder),
        "--tickers", ",".join(sorted(set(tickers))),
    ]
    logger.info("rebuilding ratio_history for %d tickers", len(set(tickers)))
    proc = subprocess.run(cmd, env=os.environ.copy())
    return proc.returncode


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--apply", action="store_true",
                    help="WRITE the fix (needs authorization). Default is dry-run.")
    ap.add_argument("--period-types", default="annual,quarterly",
                    help="comma list (default: annual,quarterly)")
    ap.add_argument("--tickers", default=None,
                    help="optional comma list to limit scope")
    ap.add_argument("--skip-rebuild", action="store_true",
                    help="with --apply, do NOT re-run build_ratio_history afterwards")
    ap.add_argument("--limit-report", type=int, default=40,
                    help="rows to print in the before/after table (default 40)")
    args = ap.parse_args()

    ptypes = [p.strip() for p in args.period_types.split(",") if p.strip()]
    tickers = (
        [t.strip().upper() for t in args.tickers.split(",") if t.strip()]
        if args.tickers else None
    )

    engine = _engine()
    Session = sessionmaker(bind=engine, future=True)

    with Session() as sess:
        rows = _fetch_anomalies(sess, ptypes, tickers)

        print("=" * 78)
        print(f"net_margin unit-anomaly backfill — plausibility band: "
              f"|net_margin| <= {NET_MARGIN_PLAUSIBLE_PCT:.0f}%")
        print(f"mode: {'APPLY (writing)' if args.apply else 'DRY-RUN (no writes)'}")
        print(f"period_types: {ptypes}   ticker filter: {tickers or 'ALL'}")
        print("=" * 78)
        print(f"candidate rows to normalise: {len(rows)}")
        if not rows:
            print("nothing to do — clean.")
            return 0

        affected_tickers = sorted({r["ticker"] for r in rows})
        print(f"distinct tickers affected: {len(affected_tickers)}")
        print()
        hdr = (f"{'ticker':<14}{'period':<12}{'type':<10}"
               f"{'revenue->NULL':>14}{'pat(kept)':>14}"
               f"{'net_margin->NULL':>18}{'src':>10}")
        print(hdr)
        print("-" * len(hdr))
        for r in rows[: args.limit_report]:
            implied = (
                float(r["pat"]) / float(r["revenue"]) * 100.0
                if r["revenue"] not in (None, 0) and r["pat"] is not None
                else None
            )
            nm = r["net_margin"] if r["net_margin"] is not None else implied
            print(
                f"{r['ticker']:<14}{str(r['period_end']):<12}{r['period_type']:<10}"
                f"{str(r['revenue']):>14}{str(r['pat']):>14}"
                f"{(f'{nm:,.0f}' if nm is not None else '—'):>18}"
                f"{str(r['data_source'] or '—'):>10}"
            )
        if len(rows) > args.limit_report:
            print(f"... and {len(rows) - args.limit_report} more rows")
        print()

        if not args.apply:
            print("DRY-RUN: no rows written. Re-run with --apply (after "
                  "authorization) to NULL the corrupt revenue/net_margin and "
                  "rebuild ratio_history for the affected tickers.")
            return 0

        # ── APPLY path (authorized writes) ──
        ids = [int(r["id"]) for r in rows]
        result = sess.execute(
            text("UPDATE financials SET revenue = NULL, net_margin = NULL "
                 "WHERE id = ANY(:ids)"),
            {"ids": ids},
        )
        sess.commit()
        logger.info("nulled revenue+net_margin on %d financials rows",
                    result.rowcount)

    if args.apply and not args.skip_rebuild:
        rc = _rebuild_ratio_history(affected_tickers)
        if rc != 0:
            logger.warning("build_ratio_history returned %d", rc)
            return rc
    print("DONE.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
