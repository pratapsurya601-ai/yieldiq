"""
pulse_daily.py — CLI entry point for the Pulse axis daily refresh.

Invoked by .github/workflows/pulse_daily.yml. Loads the top-N tickers
by market cap, runs every configured Pulse source, and upserts
hex_pulse_inputs in Aiven Postgres.

Usage:
    python backend/scripts/pulse_daily.py [--limit 500] [--log-level INFO]

Not intended for Railway — this is a GH Actions cron job.
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path


def _bootstrap_paths() -> None:
    """Make `backend.services.*` and `data_pipeline.*` importable no matter
    which cwd the script is launched from."""
    here = Path(__file__).resolve()
    repo_root = here.parent.parent.parent  # backend/scripts/ -> backend -> repo
    for p in (repo_root, repo_root / "backend"):
        s = str(p)
        if s not in sys.path:
            sys.path.insert(0, s)


def main(argv: list[str] | None = None) -> int:
    _bootstrap_paths()

    parser = argparse.ArgumentParser(description="YieldIQ Pulse axis daily refresh")
    parser.add_argument(
        "--limit", type=int, default=int(os.environ.get("PULSE_LIMIT", "500")),
        help="Number of top-by-market-cap tickers to refresh (default 500).",
    )
    parser.add_argument(
        "--log-level", default=os.environ.get("PULSE_LOG_LEVEL", "INFO"),
        help="Logging level (default INFO).",
    )
    args = parser.parse_args(argv)

    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    log = logging.getLogger("yieldiq.pulse.cli")

    if not os.environ.get("DATABASE_URL"):
        log.error("DATABASE_URL is not set — cannot run Pulse refresh.")
        return 2

    # Import after path bootstrap.
    try:
        from backend.services.pulse_data_service import run_pulse_refresh
    except ImportError:
        from services.pulse_data_service import run_pulse_refresh  # type: ignore

    summary = run_pulse_refresh(limit=args.limit)
    log.info("PULSE CLI summary: %s", summary)

    # Exit non-zero only if literally nothing got updated AND we had tickers
    # — otherwise partial success (some sources down) still counts as green.
    if summary.get("tickers", 0) > 0 and summary.get("updated", 0) == 0:
        log.error("Pulse refresh produced zero upserts — treating as failure.")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
