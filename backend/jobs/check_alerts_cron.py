"""check_alerts_cron.py — task #131 MoS-band alert evaluator.

Schedule
────────
Every 15 minutes via .github/workflows/check-alerts.yml.

What it does
────────────
1. List every ticker with at least one active MoS-band subscription.
2. For each ticker, resolve the current MoS:
     a. Read the latest cached `fair_value` from analysis_cache (or
        fair_value_history as fallback — the same source the analysis
        page hero reads).
     b. Read the latest live quote price (live_quotes → daily_prices).
     c. Compute mos_pct = (fair_value - price) / fair_value * 100.
3. Call mos_band_alerts_service.check_and_fire_alerts(ticker, mos_pct)
   which fires PWA pushes for any (user, threshold, direction) whose
   condition is met AND whose 24h cooldown has expired.
4. Log a per-ticker summary line + an overall summary so the GH
   Actions log is grep-able.

Usage
─────
    python -m backend.jobs.check_alerts_cron
    python -m backend.jobs.check_alerts_cron --dry-run
    python -m backend.jobs.check_alerts_cron --only RELIANCE,TCS

Safety
──────
* Never raises into GH Actions — exits non-zero only on a
  truly catastrophic failure (e.g. service module import error),
  so a single bad ticker doesn't fail the entire scheduled sweep.
* Reads only; the only writes are inside check_and_fire_alerts which
  stamps last_fired_at on rows that fired.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
import time
from pathlib import Path
from typing import Optional

_REPO = Path(__file__).resolve().parents[2]
if str(_REPO) not in sys.path:
    sys.path.insert(0, str(_REPO))

logger = logging.getLogger("yieldiq.check_alerts_cron")


def _setup_logging() -> None:
    logging.basicConfig(
        level=os.environ.get("LOG_LEVEL", "INFO"),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )


# ── Snapshot resolver ──────────────────────────────────────────
def _resolve_mos_for_ticker(ticker: str) -> Optional[float]:
    """Best-effort MoS resolver. Returns None if either FV or price is
    unavailable — caller logs the skip."""
    try:
        from data_pipeline.db import Session as _S
        from data_pipeline.models import FairValueHistory
    except Exception as e:
        logger.warning("cron: pipeline DB unavailable: %s", e)
        return None
    if _S is None:
        logger.warning("cron: DATABASE_URL not set — cannot resolve MoS")
        return None
    session = _S()
    try:
        row = (
            session.query(FairValueHistory)
            .filter(FairValueHistory.ticker == ticker.upper())
            .order_by(FairValueHistory.date.desc())
            .first()
        )
        if row is None:
            return None
        # Prefer the row's mos_pct if set — it's the value the UI shows.
        if row.mos_pct is not None:
            try:
                return float(row.mos_pct)
            except (TypeError, ValueError):
                pass
        fv = float(row.fair_value) if row.fair_value is not None else None
        px = float(row.price) if row.price is not None else None
        if fv is None or px is None or fv <= 0:
            return None
        return (fv - px) / fv * 100.0
    except Exception as e:
        logger.warning("cron: MoS resolve failed for %s: %s", ticker, e)
        return None
    finally:
        try:
            session.close()
        except Exception:
            pass


# ── Main run ───────────────────────────────────────────────────
def run(dry_run: bool = False, only: Optional[list[str]] = None) -> dict:
    """Returns a summary dict — handy for tests and the operator email."""
    from backend.services import mos_band_alerts_service as mbas

    started = time.monotonic()
    if only:
        tickers = sorted({t.strip().upper() for t in only if t.strip()})
    else:
        tickers = mbas.list_distinct_tickers()

    logger.info("cron: evaluating %d ticker(s) (dry_run=%s)",
                len(tickers), dry_run)

    summary = {
        "tickers_checked": 0,
        "tickers_no_data": 0,
        "fired_count": 0,
        "fired": [],
    }
    for t in tickers:
        summary["tickers_checked"] += 1
        mos = _resolve_mos_for_ticker(t)
        if mos is None:
            summary["tickers_no_data"] += 1
            logger.info("cron: %s — no MoS available, skip", t)
            continue
        logger.info("cron: %s — current MoS = %+.1f%%", t, mos)
        if dry_run:
            # Show which subs WOULD fire without mutating state.
            for sub in mbas.list_subscriptions_for_ticker(t):
                if mbas._condition_met(sub, mos) and not mbas._in_cooldown(
                    sub.last_fired_at
                ):
                    summary["fired_count"] += 1
                    summary["fired"].append({
                        "ticker": t,
                        "user_id": sub.user_id,
                        "threshold_pct": sub.threshold_pct,
                        "direction": sub.direction,
                        "dry_run": True,
                    })
            continue
        fired = mbas.check_and_fire_alerts(t, mos)
        for sub in fired:
            summary["fired_count"] += 1
            summary["fired"].append({
                "ticker": t,
                "user_id": sub.user_id,
                "threshold_pct": sub.threshold_pct,
                "direction": sub.direction,
            })
    summary["elapsed_s"] = round(time.monotonic() - started, 2)
    logger.info("cron: summary=%s", json.dumps(summary))
    return summary


def main(argv: Optional[list[str]] = None) -> int:
    _setup_logging()
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dry-run", action="store_true",
                   help="Do not send pushes or stamp last_fired_at")
    p.add_argument("--only", default="",
                   help="Comma-separated list of tickers to limit the sweep")
    args = p.parse_args(argv)
    only = [s for s in (args.only or "").split(",") if s.strip()]
    try:
        run(dry_run=args.dry_run, only=only or None)
        return 0
    except Exception:
        logger.exception("cron: catastrophic failure")
        return 1


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
