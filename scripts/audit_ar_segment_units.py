"""
audit_ar_segment_units.py
═══════════════════════════════════════════════════════════════
Backfill audit for the AR segment-unit validator (ROOT CAUSE #9).

Walks the top-50 tickers' existing ar_signals rows, runs the
validator over each segment_data list, and emits a CSV-style
report of every row that the validator flagged.

Idempotent + READ-ONLY by default. The default mode emits a
diagnostic report to stdout — no DB writes. Pass --apply to
update the persisted segment_data with the unit_validated stamps
(this is useful for backfilling the production table so the read
path doesn't recompute the stamps every request).

Why read-only by default
────────────────────────
The brief is explicit: "Don't auto-rewrite — just mark them and
add a note for manual re-extraction." This script's default is
that contract. The router stamps rows on the fly at read time so
the panel hides anomalies whether or not this audit ran. The
--apply mode is a one-shot operator convenience for the prod
table.

Exit code
─────────
0 — audit completed (per-ticker errors are tolerated and logged).
1 — DB unreachable, ticker universe empty.

Usage
─────
    python scripts/audit_ar_segment_units.py
    python scripts/audit_ar_segment_units.py --top 50
    python scripts/audit_ar_segment_units.py --apply
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

logging.basicConfig(
    level=os.environ.get("AUDIT_LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s %(message)s",
)
log = logging.getLogger("audit_ar_segment_units")


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


def _load_top_tickers(sess, n: int) -> list[str]:
    from sqlalchemy import text
    try:
        rows = sess.execute(
            text(
                """
                SELECT ticker FROM (
                    SELECT DISTINCT ON (ticker) ticker, market_cap_cr
                    FROM market_metrics
                    WHERE market_cap_cr IS NOT NULL AND market_cap_cr > 0
                    ORDER BY ticker, trade_date DESC
                ) t
                ORDER BY market_cap_cr DESC
                LIMIT :lim
                """
            ),
            {"lim": n},
        ).fetchall()
    except Exception as exc:
        log.error("load_top_tickers failed: %s", exc)
        return []
    out = []
    for r in rows:
        t = (r[0] or "").strip()
        if not t:
            continue
        if t.endswith(".NS") or t.endswith(".BO"):
            t = t.rsplit(".", 1)[0]
        out.append(t)
    return out


def _fetch_segments_for_ticker(sess, bare_ticker: str
                               ) -> list[tuple[int, int, str, list]]:
    """Return [(ar_signals_id, annual_report_id, fy, segment_data_list), ...]
    """
    from sqlalchemy import text
    try:
        rows = sess.execute(
            text(
                """
                SELECT s.id, s.annual_report_id, car.fiscal_year,
                       s.segment_data
                FROM ar_signals s
                JOIN company_annual_reports car
                  ON car.id = s.annual_report_id
                WHERE car.ticker IN (:bare, :ns, :bo)
                ORDER BY car.fiscal_year DESC, s.extracted_at DESC
                """
            ),
            {
                "bare": bare_ticker,
                "ns": f"{bare_ticker}.NS",
                "bo": f"{bare_ticker}.BO",
            },
        ).fetchall()
    except Exception as exc:
        log.debug("fetch failed for %s: %s", bare_ticker, exc)
        return []
    out = []
    for r in rows:
        sid, ar_id, fy, raw = r
        segs: list
        if raw is None:
            segs = []
        elif isinstance(raw, (list, dict)):
            segs = raw if isinstance(raw, list) else []
        else:
            try:
                parsed = json.loads(raw)
                segs = parsed if isinstance(parsed, list) else []
            except Exception:
                segs = []
        out.append((int(sid), int(ar_id), str(fy or ""), segs))
    return out


def _apply_stamps_to_db(sess, signals_id: int, stamped: list[dict]) -> bool:
    from sqlalchemy import text
    try:
        sess.execute(
            text(
                "UPDATE ar_signals SET segment_data = :sd "
                "WHERE id = :id"
            ),
            {"sd": json.dumps(stamped), "id": signals_id},
        )
        sess.commit()
        return True
    except Exception as exc:
        log.warning("apply stamps failed for id=%s: %s", signals_id, exc)
        try:
            sess.rollback()
        except Exception:
            pass
        return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit AR segment units.")
    parser.add_argument(
        "--top", type=int, default=50,
        help="How many top tickers by market cap to audit (default 50).",
    )
    parser.add_argument(
        "--apply", action="store_true",
        help="WRITE stamps back to ar_signals.segment_data "
             "(default: dry-run report only).",
    )
    args = parser.parse_args()

    from backend.services.ar_segment_validator import (  # noqa: E402
        VALIDATED_KEY,
        validate_segment_rows,
    )

    sess = _get_session()
    if sess is None:
        log.error("DB unreachable — aborting.")
        return 1

    try:
        tickers = _load_top_tickers(sess, args.top)
    finally:
        try:
            sess.close()
        except Exception:
            pass
    if not tickers:
        log.error("zero tickers loaded — aborting.")
        return 1

    log.info(
        "Auditing top-%d tickers for AR segment unit anomalies "
        "(apply=%s)", len(tickers), args.apply,
    )
    print("ticker,ar_signals_id,fy,row_index,segment_name,"
          "revenue_cr,ebit_cr,reason")
    total_flagged = 0
    total_rows = 0
    for tk in tickers:
        sess = _get_session()
        if sess is None:
            continue
        try:
            ar_rows = _fetch_segments_for_ticker(sess, tk)
            for sid, _ar_id, fy, segs in ar_rows:
                stamped = validate_segment_rows(segs)
                total_rows += len(stamped)
                bad = [r for r in stamped if r.get(VALIDATED_KEY) is False]
                for i, r in enumerate(stamped):
                    if r.get(VALIDATED_KEY) is True:
                        continue
                    label = (
                        r.get("segment") or r.get("name") or f"row{i}"
                    )
                    rev = r.get("revenue_cr")
                    ebit = r.get("ebit_cr")
                    reason = (r.get("validation_reason") or "").replace(
                        ",", ";",
                    )
                    print(f"{tk},{sid},{fy},{i},{label},{rev},{ebit},{reason}")
                    total_flagged += 1
                if bad and args.apply:
                    _apply_stamps_to_db(sess, sid, stamped)
        finally:
            try:
                sess.close()
            except Exception:
                pass

    log.info(
        "Audit done. %d rows scanned, %d flagged "
        "(apply=%s).",
        total_rows, total_flagged, args.apply,
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
