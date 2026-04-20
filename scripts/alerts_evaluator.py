#!/usr/bin/env python
# scripts/alerts_evaluator.py
# ═══════════════════════════════════════════════════════════════
# Hourly alerts evaluator. Entry point for the GH Actions workflow
# .github/workflows/alerts_evaluator_hourly.yml.
#
# Usage:
#   python scripts/alerts_evaluator.py            # live: sends emails
#   python scripts/alerts_evaluator.py --dry-run  # print-only, no writes
#
# Env:
#   DATABASE_URL     — required (Aiven Postgres)
#   SENDGRID_API_KEY — required for live mode; dry-run ignores it
#
# Exit codes:
#   0  — success (including "nothing to do")
#   1  — fatal error (bad env, DB unreachable, etc.)
# ═══════════════════════════════════════════════════════════════
from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path

# Ensure project root is importable regardless of invocation cwd.
_ROOT = Path(__file__).resolve().parent.parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))
_DASHBOARD = _ROOT / "dashboard"
if str(_DASHBOARD) not in sys.path:
    sys.path.insert(0, str(_DASHBOARD))

# Load .env for local runs; GH Actions injects env directly.
try:
    from dotenv import load_dotenv
    load_dotenv(_ROOT / ".env")
except Exception:
    pass


def _setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="YieldIQ alerts evaluator")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Evaluate conditions and print what would fire, but don't "
             "send emails or persist any DB writes.",
    )
    args = parser.parse_args()
    _setup_logging()
    log = logging.getLogger("alerts_evaluator")

    if not os.environ.get("DATABASE_URL"):
        log.error("DATABASE_URL not set — cannot evaluate alerts")
        return 1

    # Import AFTER env is loaded so data_pipeline.db picks up DATABASE_URL.
    try:
        from data_pipeline.db import Session as DbSession
        from data_pipeline.models import Base as PipelineBase
        from backend.models.alerts import UserAlert  # noqa: F401 — register mapper
        from backend.services.alerts_service import evaluate_alerts
    except Exception as e:
        log.exception("import failed: %s", e)
        return 1

    if DbSession is None:
        log.error("pipeline Session is None — DATABASE_URL likely malformed")
        return 1

    # Ensure the user_alerts table exists. In prod this is applied by
    # backend.main._ensure_pipeline_tables on API boot; the evaluator
    # runs out-of-band on GH Actions where the API may not have booted
    # since the migration landed. create_all is idempotent.
    try:
        from data_pipeline.db import engine as _eng
        if _eng is not None:
            PipelineBase.metadata.create_all(_eng)
    except Exception as e:
        log.warning("create_all skipped: %s", e)

    db = DbSession()
    try:
        results = evaluate_alerts(db, dry_run=args.dry_run)
    except Exception as e:
        log.exception("evaluate_alerts crashed: %s", e)
        db.rollback()
        return 1
    finally:
        db.close()

    fired = [r for r in results if r.fired]
    cooldown = [r for r in results if r.reason == "cooldown"]
    no_data = [r for r in results if r.reason == "no_data"]
    condition_not_met = [r for r in results if r.reason == "condition_not_met"]
    no_email = [r for r in results if r.reason == "no_email"]

    if args.dry_run:
        log.info("DRY-RUN: would fire %d alerts", len(fired))
    else:
        log.info("Fired %d alerts", len(fired))
    log.info(
        "Breakdown: fired=%d cooldown=%d no_data=%d "
        "condition_not_met=%d no_email=%d (total=%d)",
        len(fired), len(cooldown), len(no_data),
        len(condition_not_met), len(no_email), len(results),
    )
    for r in fired:
        log.info(
            "  -> alert id=%s user=%s %s %s threshold=%s",
            r.alert_id, r.user_id, r.ticker, r.kind, r.threshold,
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
