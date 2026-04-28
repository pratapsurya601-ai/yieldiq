#!/usr/bin/env python3
"""Surgical rebuild of `ratio_history` rows for audit-flagged tickers.

This is the corrective companion to ``audit_ratio_history.py``. The
audit flags rows with NULL pe_ratio, sub-1 P/E (a pre-PR-#126
``_normalize_pct`` artifact), >100% ROE/ROCE, or stale period_end.
This script rebuilds the affected rows by re-running the canonical
``scripts/build_ratio_history.py`` pipeline for the flagged tickers
only — never the full universe.

Why a separate script
---------------------
``build_ratio_history.py`` is the ground-truth builder, but it's
designed for full-universe runs (5000+ tickers, hours of work).
For a fix-the-outliers operation we want:

  - Idempotency (UPSERT, safe to re-run)
  - --dry-run by default (operator must opt-in to --apply)
  - --ticker T for one-shot manual checks
  - --all-flagged that pulls from audit_ratio_history.py output
  - Source-of-truth handoff: pre-flight audit → curated ticker list
    → bounded rebuild → post-flight verify

Source of truth for ratios
--------------------------
``financials`` table (XBRL + yfinance backfill), recomputed via the
corrected ``_normalize_pct`` (PR #126). yfinance live values are
NOT used here — the goal is to repair stored history, not snapshot
today.

Usage
-----
    # Self-test, no DB writes
    DATABASE_URL=postgres://... python scripts/rebuild_ratio_history.py \
        --ticker JUSTDIAL --dry-run

    # Apply for one ticker
    DATABASE_URL=postgres://... python scripts/rebuild_ratio_history.py \
        --ticker JUSTDIAL --apply

    # Rebuild every ticker in the audit CSV
    DATABASE_URL=postgres://... python scripts/rebuild_ratio_history.py \
        --all-flagged --audit-csv ratio_history_audit.csv --apply

Discipline
----------
- ``--dry-run`` is the default; ``--apply`` is required for writes.
- CACHE_VERSION is NEVER touched by this script (per CLAUDE.md rule 2).
- Idempotent — UPSERT on (ticker, period_end, period_type).
- Logs every UPSERT to stdout so the operator has a paper trail.

Exit codes
----------
    0  — all tickers rebuilt (or dry-run completed) cleanly.
    1  — at least one ticker failed; see log for details.
    2  — invalid arguments.
"""
from __future__ import annotations

import argparse
import csv
import logging
import os
import subprocess
import sys
from pathlib import Path

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("rebuild_ratio_history")


def _resolve_dsn() -> str:
    dsn = os.environ.get("DATABASE_URL")
    if not dsn:
        raise SystemExit(
            "ERROR: DATABASE_URL not set. Export the Neon DSN before running."
        )
    return dsn


def load_flagged_from_csv(path: Path) -> list[str]:
    """Read tickers from an audit CSV — only rows with non-empty `flag`."""
    if not path.exists():
        raise SystemExit(f"ERROR: audit CSV not found: {path}")
    out: list[str] = []
    with path.open("r", encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            flag = (row.get("flag") or "").strip()
            ticker = (row.get("ticker") or "").strip().upper()
            if flag and ticker:
                out.append(ticker)
    # de-dupe preserving order
    seen: set[str] = set()
    deduped: list[str] = []
    for t in out:
        if t not in seen:
            deduped.append(t)
            seen.add(t)
    return deduped


def rebuild_one(
    ticker: str, dsn: str, *, dry_run: bool, repo_root: Path,
) -> int:
    """Invoke build_ratio_history.py for a single ticker.

    Returns exit code from the subprocess. We shell out (rather than
    import) deliberately:

      1. build_ratio_history.py opens its own SQLAlchemy session and
         runs SIGINT-aware loops; importing it would entangle that
         lifecycle with this driver script.
      2. Subprocess isolation — a crash on one ticker doesn't take
         out the whole run.
    """
    builder = repo_root / "scripts" / "build_ratio_history.py"
    if not builder.exists():
        logger.error("builder script missing: %s", builder)
        return 1

    cmd = [
        sys.executable,
        str(builder),
        "--tickers", ticker,
    ]
    env = os.environ.copy()
    env["DATABASE_URL"] = dsn

    if dry_run:
        logger.info("[dry-run] would run: %s", " ".join(cmd))
        return 0

    logger.info("rebuilding %s …", ticker)
    proc = subprocess.run(cmd, env=env)
    if proc.returncode != 0:
        logger.error("rebuild failed for %s (exit=%d)", ticker, proc.returncode)
    else:
        logger.info("rebuild OK: %s", ticker)
    return proc.returncode


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    g = p.add_mutually_exclusive_group(required=True)
    g.add_argument("--ticker", help="Rebuild a single ticker.")
    g.add_argument(
        "--all-flagged", action="store_true",
        help="Rebuild every ticker flagged in the audit CSV.",
    )
    p.add_argument(
        "--audit-csv", default="ratio_history_audit.csv",
        help="Audit CSV path (used with --all-flagged).",
    )
    p.add_argument(
        "--apply", action="store_true",
        help="Actually run the rebuild. Without this, runs in dry-run mode.",
    )
    p.add_argument(
        "--dry-run", action="store_true",
        help="(Default) print what would run without invoking the builder.",
    )
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    dry_run = not args.apply  # default behaviour: dry-run unless --apply
    if args.dry_run and args.apply:
        logger.error("--dry-run and --apply are mutually exclusive")
        return 2

    repo_root = Path(__file__).resolve().parent.parent

    if args.ticker:
        tickers = [args.ticker.strip().upper()]
    else:
        tickers = load_flagged_from_csv(Path(args.audit_csv))

    if not tickers:
        logger.error("no tickers to rebuild")
        return 2

    try:
        dsn = _resolve_dsn() if not dry_run else "postgres://dry-run/none"
    except SystemExit as exc:
        # Dry-run still prints the cmd skeleton even without DSN.
        if not dry_run:
            raise
        dsn = "postgres://dry-run/none"

    logger.info(
        "%s rebuild for %d ticker(s)%s",
        "DRY-RUN" if dry_run else "APPLY",
        len(tickers),
        "" if dry_run else " — writes are committed",
    )

    failures: list[str] = []
    for t in tickers:
        rc = rebuild_one(t, dsn, dry_run=dry_run, repo_root=repo_root)
        if rc != 0:
            failures.append(t)

    if failures:
        logger.error("FAILURES: %s", ",".join(failures))
        return 1
    logger.info("all tickers processed cleanly")
    return 0


if __name__ == "__main__":
    sys.exit(main())
