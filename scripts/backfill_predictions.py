#!/usr/bin/env python3
# scripts/backfill_predictions.py
# ═══════════════════════════════════════════════════════════════
# Backfill model_predictions_history for a (ticker × date) grid.
#
# Wires up the engine that PR #141 scaffolded:
#
#   for each (ticker, date) in grid:
#       hp = analysis_service.compute_for_date(ticker, date, session=…)
#       UPSERT INTO model_predictions_history (ticker, prediction_date, …)
#       VALUES (…)
#       ON CONFLICT (ticker, prediction_date) DO NOTHING;
#
# The UPSERT-as-DO-NOTHING is intentional: this script is *resume-safe*
# — re-running over the same window skips already-populated rows and
# only fills the gaps. Useful when an Aiven blip kills the run halfway.
#
# Methodology — see backend/services/analysis/compute_for_date.py for
# the full pragmatic-vs-strict counterfactual discussion. TL;DR: this
# uses CURRENT financials + HISTORICAL price for the 30d × 50 PoC.
#
# Examples
# --------
#   # Dry run (no DB writes), 30d × 50 canary, prints planned rows.
#   python scripts/backfill_predictions.py \
#       --start-date 2026-03-28 --end-date 2026-04-26 \
#       --tickers canary50
#
#   # Real run with throttle.
#   python scripts/backfill_predictions.py \
#       --start-date 2026-03-28 --end-date 2026-04-26 \
#       --tickers canary50 --apply --rate 4
#
#   # Custom universe from a file (one ticker per line).
#   python scripts/backfill_predictions.py \
#       --start-date 2026-03-28 --end-date 2026-04-26 \
#       --tickers ./my_tickers.txt --apply
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Iterable

# Repo root on path so backend.* imports resolve when invoked directly.
_HERE = Path(__file__).resolve().parent
_ROOT = _HERE.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

logger = logging.getLogger("yieldiq.backfill_predictions")

CANARY_FILE = _HERE / "canary_stocks_50.json"


# ─────────────────────────────────────────────────────────────────
# Universe resolution
# ─────────────────────────────────────────────────────────────────

def _load_canary50() -> list[str]:
    with open(CANARY_FILE, "r", encoding="utf-8") as f:
        data = json.load(f)
    return [f"{s['symbol']}.NS" for s in data["stocks"]]


def _load_all() -> list[str]:
    """Pull the full universe from the stocks table."""
    from backend.services.analysis.db import _get_pipeline_session
    from sqlalchemy import text
    sess = _get_pipeline_session()
    if sess is None:
        raise RuntimeError("--tickers all requires DB session")
    try:
        rows = sess.execute(
            text("SELECT ticker FROM stocks WHERE is_active = TRUE ORDER BY ticker")
        ).fetchall()
        return [f"{r[0]}.NS" for r in rows]
    finally:
        sess.close()


def resolve_universe(spec: str) -> list[str]:
    if spec == "canary50":
        return _load_canary50()
    if spec == "all":
        return _load_all()
    p = Path(spec)
    if not p.exists():
        raise FileNotFoundError(f"--tickers '{spec}' is not 'canary50', 'all', or a readable file")
    out: list[str] = []
    with open(p, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if not line.endswith(".NS") and not line.endswith(".BO"):
                line = f"{line}.NS"
            out.append(line)
    return out


# ─────────────────────────────────────────────────────────────────
# Date grid
# ─────────────────────────────────────────────────────────────────

def _is_trading_day(d: date) -> bool:
    """Coarse trading-day filter (Sat/Sun out, holidays NOT excluded)."""
    return d.weekday() < 5


def _daterange(start: date, end: date) -> Iterable[date]:
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


# ─────────────────────────────────────────────────────────────────
# Idempotent UPSERT
# ─────────────────────────────────────────────────────────────────

UPSERT_SQL = """
    INSERT INTO model_predictions_history (
        ticker, prediction_date, current_price, fair_value,
        margin_of_safety_pct, yieldiq_score, grade, verdict,
        cache_version_at_prediction
    )
    VALUES (
        :ticker, :prediction_date, :current_price, :fair_value,
        :margin_of_safety_pct, :yieldiq_score, :grade, :verdict,
        :cache_version
    )
    ON CONFLICT (ticker, prediction_date) DO NOTHING
    RETURNING id
"""


def _row_exists(session, ticker: str, prediction_date: date) -> bool:
    from sqlalchemy import text
    row = session.execute(
        text(
            "SELECT 1 FROM model_predictions_history "
            "WHERE ticker = :t AND prediction_date = :d LIMIT 1"
        ),
        {"t": ticker, "d": prediction_date},
    ).fetchone()
    return row is not None


# ─────────────────────────────────────────────────────────────────
# Main backfill loop
# ─────────────────────────────────────────────────────────────────

def run_backfill(
    *,
    start_date: date,
    end_date: date,
    tickers: list[str],
    apply: bool,
    rate_per_sec: float,
) -> dict:
    """Returns summary stats: planned/skipped/inserted/missing_price."""
    from backend.services.analysis.db import _get_pipeline_session
    from backend.services.analysis.compute_for_date import compute_for_date
    from sqlalchemy import text

    session = _get_pipeline_session() if apply else None
    if apply and session is None:
        raise RuntimeError(
            "--apply requires DB session — set DATABASE_URL via .env.local "
            "or environment before running"
        )

    stats = {
        "planned": 0,
        "skipped_existing": 0,
        "inserted": 0,
        "missing_price": 0,
        "errors": 0,
    }
    delay = 1.0 / rate_per_sec if rate_per_sec > 0 else 0.0

    grid_dates = [d for d in _daterange(start_date, end_date) if _is_trading_day(d)]
    logger.info(
        "Backfill: %d tickers × %d trading days = %d planned rows (apply=%s)",
        len(tickers), len(grid_dates), len(tickers) * len(grid_dates), apply,
    )

    for ticker in tickers:
        for d in grid_dates:
            stats["planned"] += 1

            if apply:
                # Resume-safe skip
                if _row_exists(session, ticker, d):
                    stats["skipped_existing"] += 1
                    if stats["planned"] % 100 == 0:
                        logger.info(
                            "progress: planned=%d inserted=%d skipped=%d missing=%d errors=%d",
                            stats["planned"], stats["inserted"],
                            stats["skipped_existing"], stats["missing_price"],
                            stats["errors"],
                        )
                    continue

            try:
                hp = compute_for_date(ticker, d, session=session if apply else None)
            except Exception as exc:
                logger.warning("compute_for_date(%s, %s) raised %s: %s",
                               ticker, d, type(exc).__name__, exc)
                stats["errors"] += 1
                continue

            if hp is None:
                stats["missing_price"] += 1
                continue

            if not apply:
                logger.debug("DRY %s @ %s → fv=%s mos=%s score=%s",
                             ticker, d, hp.fair_value, hp.margin_of_safety_pct,
                             hp.yieldiq_score)
            else:
                try:
                    session.execute(
                        text(UPSERT_SQL),
                        {
                            "ticker": ticker,
                            "prediction_date": d,
                            "current_price": hp.current_price,
                            "fair_value": hp.fair_value,
                            "margin_of_safety_pct": hp.margin_of_safety_pct,
                            "yieldiq_score": hp.yieldiq_score,
                            "grade": hp.grade,
                            "verdict": hp.verdict,
                            "cache_version": hp.cache_version,
                        },
                    )
                    session.commit()
                    stats["inserted"] += 1
                except Exception as exc:
                    session.rollback()
                    logger.warning("UPSERT(%s, %s) failed: %s: %s",
                                   ticker, d, type(exc).__name__, exc)
                    stats["errors"] += 1
                    continue

            if stats["planned"] % 100 == 0:
                logger.info(
                    "progress: planned=%d inserted=%d skipped=%d missing=%d errors=%d",
                    stats["planned"], stats["inserted"],
                    stats["skipped_existing"], stats["missing_price"], stats["errors"],
                )

            if delay:
                time.sleep(delay)

    if session is not None:
        try:
            session.close()
        except Exception:
            pass
    return stats


def _load_dotenv_local():
    """Best-effort .env.local loader so DATABASE_URL is picked up."""
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
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", required=True, help="ISO YYYY-MM-DD")
    parser.add_argument("--end-date", required=True, help="ISO YYYY-MM-DD")
    parser.add_argument("--tickers", default="canary50",
                        help="canary50 | all | <path-to-file>")
    parser.add_argument("--apply", action="store_true",
                        help="Actually write rows. Without this flag, dry-run.")
    parser.add_argument("--rate", type=float, default=8.0,
                        help="Max compute_for_date calls per second (DB throttle).")
    parser.add_argument("--verbose", action="store_true")
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s — %(message)s",
    )

    _load_dotenv_local()

    start = date.fromisoformat(args.start_date)
    end = date.fromisoformat(args.end_date)
    if start > end:
        parser.error("--start-date must be <= --end-date")

    tickers = resolve_universe(args.tickers)
    logger.info("Universe: %s → %d tickers", args.tickers, len(tickers))

    stats = run_backfill(
        start_date=start, end_date=end, tickers=tickers,
        apply=args.apply, rate_per_sec=args.rate,
    )
    logger.info("DONE: %s", stats)
    return 0


if __name__ == "__main__":
    sys.exit(main())
