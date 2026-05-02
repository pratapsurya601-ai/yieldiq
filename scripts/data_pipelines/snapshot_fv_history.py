"""
snapshot_fv_history.py
═══════════════════════════════════════════════════════════════

Nightly snapshot job for the *backtested fair-value accuracy* dataset.

What it does
────────────
For every row in ``analysis_cache`` written in the last 24 hours, copy
the (ticker, fair_value, current_price, mos_pct, verdict, cache_version)
tuple into ``fair_value_history`` keyed on (ticker, date).

Why
───
The backtest dashboard at ``/methodology/accuracy`` answers:

    "Our base-case fair value for Stock X in month-T was ₹Y.
     Actual price 12 months later: ₹Z. Hit rate across N stocks: P %."

For that, we need *one snapshot row per ticker per day*. The live
analysis path (``store_today_fair_value`` in
``data_pipeline.sources.fv_history``) already writes one such row when
a user opens a ticker page. This script closes the gap for tickers
nobody opened on a given day by replaying the last 24h of the
``analysis_cache`` table — which is where bulk warmers and pulse jobs
have already deposited fresh FVs.

Idempotent: ``ON CONFLICT (ticker, date) DO UPDATE``. Safe to re-run.

Never run at request time on Railway. Invoked by
``.github/workflows/snapshot_fv_history_nightly.yml`` (nightly cron +
manual dispatch).

Usage
─────
    python scripts/data_pipelines/snapshot_fv_history.py
    python scripts/data_pipelines/snapshot_fv_history.py --hours 48
    python scripts/data_pipelines/snapshot_fv_history.py --dry-run

Exit 0 on success. Exit 1 only if DB unreachable.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import date, datetime, timezone
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=os.environ.get("SNAPSHOT_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("snapshot_fv_history")


def _get_session():
    try:
        from data_pipeline.db import Session  # type: ignore
    except Exception as exc:
        log.error("cannot import data_pipeline.db: %s", exc)
        return None
    if Session is None:
        return None
    try:
        return Session()
    except Exception as exc:
        log.error("cannot open session: %s", exc)
        return None


def _bare(t: str) -> str:
    """Normalize ticker to bare form for fair_value_history (matches
    the convention of backfill_fair_value_history_monthly.py)."""
    if not t:
        return t
    if t.endswith(".NS") or t.endswith(".BO"):
        return t.rsplit(".", 1)[0]
    return t


def _verdict_from_mos(mos_pct: float | None) -> str | None:
    if mos_pct is None:
        return None
    if mos_pct > 10:
        return "undervalued"
    if mos_pct > -10:
        return "fairly_valued"
    return "overvalued"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=("Snapshot recent analysis_cache rows into "
                     "fair_value_history for the backtest dataset.")
    )
    parser.add_argument("--hours", type=int, default=24,
                        help="Lookback window in hours (default 24).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Read + summarize but do not write.")
    args = parser.parse_args()

    sess = _get_session()
    if sess is None:
        log.error("DB session unavailable — aborting.")
        return 1

    from sqlalchemy import text

    try:
        rows = sess.execute(
            text(
                """
                SELECT ticker, computed_at, payload
                FROM analysis_cache
                WHERE computed_at > NOW() - (:hrs || ' hours')::interval
                """
            ),
            {"hrs": str(int(args.hours))},
        ).fetchall()
    except Exception as exc:
        log.error("read from analysis_cache failed: %s", exc)
        try:
            sess.close()
        except Exception:
            pass
        return 1

    log.info("Found %d analysis_cache rows in last %dh", len(rows), args.hours)

    written = 0
    skipped_no_fv = 0
    errored = 0
    today = date.today()

    for ticker, computed_at, payload in rows:
        bare = _bare((ticker or "").strip())
        if not bare:
            continue

        # payload may be dict (JSONB) or text/bytes.
        if isinstance(payload, (bytes, bytearray)):
            try:
                payload = payload.decode("utf-8")
            except Exception:
                skipped_no_fv += 1
                continue
        if isinstance(payload, str):
            try:
                payload = json.loads(payload)
            except Exception:
                skipped_no_fv += 1
                continue
        if not isinstance(payload, dict):
            skipped_no_fv += 1
            continue

        val = payload.get("valuation") or {}
        if not isinstance(val, dict):
            skipped_no_fv += 1
            continue

        try:
            fv = val.get("fair_value")
            fv_f = float(fv) if fv is not None else None
        except (TypeError, ValueError):
            fv_f = None
        if not fv_f or fv_f <= 0:
            skipped_no_fv += 1
            continue

        try:
            cp = val.get("current_price")
            cp_f = float(cp) if cp is not None else None
        except (TypeError, ValueError):
            cp_f = None
        try:
            mos = val.get("mos_pct")
            mos_f = float(mos) if mos is not None else None
        except (TypeError, ValueError):
            mos_f = None
        if mos_f is None and cp_f and cp_f > 0:
            mos_f = round((fv_f - cp_f) / cp_f * 100.0, 2)

        verdict = val.get("verdict") or _verdict_from_mos(mos_f)
        cache_version = payload.get("cache_version")

        # Snapshot date = computed_at's date if recent, else today.
        if isinstance(computed_at, datetime):
            snap_date = computed_at.date()
        else:
            snap_date = today

        if args.dry_run:
            written += 1
            continue

        try:
            sess.execute(
                text(
                    """
                    INSERT INTO fair_value_history
                        (ticker, date, fair_value, price, mos_pct,
                         verdict, wacc, confidence, updated_at)
                    VALUES
                        (:ticker, :d, :fv, :price, :mos,
                         :verdict, NULL, :conf, now())
                    ON CONFLICT (ticker, date) DO UPDATE SET
                        fair_value = EXCLUDED.fair_value,
                        price      = EXCLUDED.price,
                        mos_pct    = EXCLUDED.mos_pct,
                        verdict    = COALESCE(EXCLUDED.verdict,
                                              fair_value_history.verdict),
                        updated_at = now()
                    """
                ),
                {
                    "ticker": bare,
                    "d": snap_date,
                    "fv": round(fv_f, 4),
                    "price": round(cp_f, 4) if cp_f else None,
                    "mos": round(mos_f, 4) if mos_f is not None else None,
                    "verdict": verdict,
                    # cache_version recorded as confidence==80 sentinel
                    # (live snapshot, vs 40 for synthesized monthly).
                    "conf": 80,
                },
            )
            written += 1
        except Exception as exc:
            errored += 1
            log.debug("upsert failed %s @ %s: %s", bare, snap_date, exc)
            try:
                sess.rollback()
            except Exception:
                pass

        # Commit in batches of 200 to keep transactions short on Neon.
        if written and written % 200 == 0:
            try:
                sess.commit()
            except Exception:
                try:
                    sess.rollback()
                except Exception:
                    pass

    if not args.dry_run:
        try:
            sess.commit()
        except Exception:
            try:
                sess.rollback()
            except Exception:
                pass

    try:
        sess.close()
    except Exception:
        pass

    log.info(
        "DONE — written=%d skipped_no_fv=%d errored=%d (dry_run=%s)",
        written, skipped_no_fv, errored, args.dry_run,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
