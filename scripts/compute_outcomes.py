#!/usr/bin/env python3
# scripts/compute_outcomes.py
# ═══════════════════════════════════════════════════════════════
# For each row in model_predictions_history compute t+30/60/90/180/365
# realised returns by reading daily_prices on the outcome_date and
# UPSERTing into prediction_outcomes.
#
# Skips windows whose outcome_date is in the future (no realised data
# yet — those rows are filled by a later run). Idempotent on
# (prediction_id, outcome_date).
#
# Usage
# -----
#   # Compute outcomes for all predictions (skips future windows).
#   python scripts/compute_outcomes.py --apply
#
#   # Restrict to predictions in a window (faster reruns).
#   python scripts/compute_outcomes.py --apply \
#       --since 2026-03-28 --until 2026-04-26
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import Sequence

_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger("yieldiq.compute_outcomes")

DEFAULT_WINDOWS: tuple[int, ...] = (30, 60, 90, 180, 365)


SELECT_PREDICTIONS_SQL = """
    SELECT id, ticker, prediction_date, current_price
      FROM model_predictions_history
     WHERE (:since IS NULL OR prediction_date >= :since)
       AND (:until IS NULL OR prediction_date <= :until)
     ORDER BY prediction_date ASC, ticker ASC
"""

LOOKUP_PRICE_SQL = """
    SELECT close_price
      FROM daily_prices
     WHERE ticker = :ticker
       AND trade_date <= :as_of
       AND trade_date >= :floor
     ORDER BY trade_date DESC
     LIMIT 1
"""

UPSERT_OUTCOME_SQL = """
    INSERT INTO prediction_outcomes
        (prediction_id, outcome_date, outcome_price, return_pct)
    VALUES
        (:prediction_id, :outcome_date, :outcome_price, :return_pct)
    ON CONFLICT (prediction_id, outcome_date) DO UPDATE
        SET outcome_price = EXCLUDED.outcome_price,
            return_pct = EXCLUDED.return_pct,
            computed_at = NOW()
"""


def _bare(t: str) -> str:
    return t.replace(".NS", "").replace(".BO", "").upper().strip()


def run(
    *,
    since: date | None,
    until: date | None,
    windows: Sequence[int] = DEFAULT_WINDOWS,
    apply: bool,
) -> dict:
    from sqlalchemy import text
    from backend.services.analysis.db import _get_pipeline_session

    session = _get_pipeline_session()
    if session is None:
        raise RuntimeError("compute_outcomes requires DB session (set DATABASE_URL)")

    today = date.today()
    stats = {"predictions": 0, "computed": 0, "skipped_future": 0,
             "missing_price": 0, "errors": 0}

    try:
        rows = session.execute(
            text(SELECT_PREDICTIONS_SQL),
            {"since": since, "until": until},
        ).fetchall()
        logger.info("Found %d prediction rows in window", len(rows))

        for r in rows:
            pred_id, ticker, pred_date, cmp_price = r[0], r[1], r[2], r[3]
            stats["predictions"] += 1
            if cmp_price is None or float(cmp_price) <= 0:
                continue
            cmp_price = float(cmp_price)
            ticker_bare = _bare(ticker)

            for w in windows:
                outcome_date = pred_date + timedelta(days=w)
                if outcome_date > today:
                    stats["skipped_future"] += 1
                    continue

                px_row = session.execute(
                    text(LOOKUP_PRICE_SQL),
                    {
                        "ticker": ticker_bare,
                        "as_of": outcome_date,
                        "floor": outcome_date - timedelta(days=7),
                    },
                ).fetchone()
                if px_row is None or px_row[0] is None:
                    stats["missing_price"] += 1
                    continue

                outcome_price = float(px_row[0])
                return_pct = round(((outcome_price - cmp_price) / cmp_price) * 100, 2)

                if apply:
                    try:
                        session.execute(
                            text(UPSERT_OUTCOME_SQL),
                            {
                                "prediction_id": pred_id,
                                "outcome_date": outcome_date,
                                "outcome_price": round(outcome_price, 2),
                                "return_pct": return_pct,
                            },
                        )
                        session.commit()
                        stats["computed"] += 1
                    except Exception as exc:
                        session.rollback()
                        logger.warning("UPSERT outcome(%s, %s) failed: %s",
                                       pred_id, outcome_date, exc)
                        stats["errors"] += 1
                else:
                    logger.debug("DRY %s @ %s (t+%d) → outcome=%.2f ret=%+.2f%%",
                                 ticker, outcome_date, w, outcome_price, return_pct)
                    stats["computed"] += 1

            if stats["predictions"] % 100 == 0:
                logger.info("progress: %s", stats)
    finally:
        try:
            session.close()
        except Exception:
            pass
    return stats


def _load_dotenv_local():
    f = _ROOT / ".env.local"
    if not f.exists():
        return
    for line in f.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--since", default=None, help="ISO date — only predictions on/after this date")
    p.add_argument("--until", default=None, help="ISO date — only predictions on/before this date")
    p.add_argument("--windows", default="30,60,90,180,365",
                   help="Comma-separated outcome windows in days")
    p.add_argument("--apply", action="store_true",
                   help="Actually write to prediction_outcomes")
    p.add_argument("--verbose", action="store_true")
    args = p.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )
    _load_dotenv_local()

    since = date.fromisoformat(args.since) if args.since else None
    until = date.fromisoformat(args.until) if args.until else None
    windows = tuple(int(w.strip()) for w in args.windows.split(",") if w.strip())

    stats = run(since=since, until=until, windows=windows, apply=args.apply)
    logger.info("DONE: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
